"""Ciclo agentico scritto a mano (nessun framework agentico).

Per ogni richiesta dell'operatore:
  1. si chiede al modello cosa fare (con la conversazione e l'elenco dei tool);
  2. se il modello risponde con testo semplice, e' la risposta finale: si ferma;
  3. se chiede dei tool, l'harness li controlla, ne chiede conferma se scrivono dati,
     li esegue sul server MCP e rimanda i risultati al modello;
  4. si torna al punto 1, fino a un numero massimo di iterazioni.

Tutto cio' che va storto (tool inesistente, parametri non validi, errore del tool, conferma
negata, timeout) torna al modello come risultato: l'harness non si ferma per questo.
"""
import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum

from jsonschema import Draft202012Validator

from .conferma import Conferma, RichiestaConferma
from .llm.base import ChiamataTool, ErroreModello, LLMProvider, Messaggio, RispostaModello, SpecTool
from .mcp_client import NOME_ANTEPRIMA, ClientMcp, InfoTool
from .prompt import PROMPT_SISTEMA
from .registro import Registro

LIMITE_RISULTATO = 6000  # caratteri di risultato tool rimandati al modello


class MotivoArresto(str, Enum):
    """Condizioni di arresto esplicite del ciclo."""

    RISPOSTA_FINALE = "risposta_finale"  # il modello ha risposto con testo, senza chiedere tool
    CONFERMA_NEGATA = "conferma_negata"  # come sopra, ma dopo che l'operatore ha rifiutato una scrittura
    LIMITE_ITERAZIONI = "limite_iterazioni"  # raggiunto il numero massimo di iterazioni
    ERRORE_MODELLO = "errore_modello"  # modello non raggiungibile o risposta vuota anche dopo il nuovo tentativo
    ERRORE_MCP = "errore_mcp"  # il server MCP non risponde piu' (guasto di trasporto)


@dataclass
class EsitoTurno:
    """Riepilogo di una richiesta dell'operatore."""

    motivo: MotivoArresto
    risposta: str
    iterazioni: int = 0
    chiamate_modello: int = 0
    chiamate_tool: int = 0
    conferme_negate: int = 0
    token_ingresso: int = 0
    token_uscita: int = 0
    durata_ms: int = 0


@dataclass
class _EsitoTool:
    testo: str
    esito: str
    fatale: bool = False
    attesa_conferma_ms: int = 0  # tempo che l'operatore ha impiegato a rispondere, escluso dalla durata del tool


@dataclass
class _Turno:
    numero: int
    iterazione: int = 0
    stato: EsitoTurno = field(default_factory=lambda: EsitoTurno(MotivoArresto.RISPOSTA_FINALE, ""))
    rifiutate: set[str] = field(default_factory=set)  # azioni rifiutate dall'operatore in questa richiesta


def _chiave_azione(nome: str, argomenti: dict) -> str:
    return nome + json.dumps(argomenti, sort_keys=True, ensure_ascii=False)


def pulisci_schema(schema):
    """Toglie dallo schema dei parametri cio' che non serve al modello (e costa token).

    Rimuove i 'title' generati dall'SDK e semplifica 'anyOf: [X, null]' in 'X'.
    """
    if isinstance(schema, list):
        return [pulisci_schema(voce) for voce in schema]
    if not isinstance(schema, dict):
        return schema
    pulito = {}
    for chiave, valore in schema.items():
        if chiave == "title" and isinstance(valore, str):
            continue
        if chiave == "default" and valore is None:
            continue
        if chiave == "properties" and isinstance(valore, dict):
            pulito[chiave] = {nome: pulisci_schema(s) for nome, s in valore.items()}
        else:
            pulito[chiave] = pulisci_schema(valore)
    varianti = pulito.get("anyOf")
    if isinstance(varianti, list):
        non_nulle = [v for v in varianti if v.get("type") != "null"]
        if len(non_nulle) == 1 and len(varianti) == 2:
            del pulito["anyOf"]
            pulito = {**non_nulle[0], **pulito}
    return pulito


# Riferimenti espliciti a un'entita' nel testo dell'operatore: "evento 12", "ordine n. 596", "cliente id 7".
# Un numero senza una di queste parole davanti ("12 biglietti", "il 12 dicembre") non e' un id.
_RIFERIMENTO = re.compile(r"\b(evento|ordine|cliente)\s+(?:(?:n\.?|n°|numero|id)\s*)?#?(\d+)\b", re.IGNORECASE)
_PARAMETRO_PER_ENTITA = {"evento": "evento_id", "ordine": "ordine_id", "cliente": "cliente_id"}
ID_QUALSIASI_TIPO = "*"  # chiave degli id scritti con «id N» in un messaggio che non nomina nessuna entita'


# Forme meno rigide: "id: 1", "l'id dell'evento e' 12" (parola "id" seguita da un numero) e il solo numero come
# risposta a una domanda ("12"). Valgono solo se dal testo, o dalla domanda a cui si risponde, si capisce di quale
# tipo di entita' si parla: una sola tra evento, ordine, cliente.
_ID_GENERICO = re.compile(r"\bid\b[^\d\n]{0,25}?#?(\d+)\b", re.IGNORECASE)
_SOLO_NUMERO = re.compile(r"^\s*(?:id\s*)?#?(\d+)\s*[.!]?\s*$", re.IGNORECASE)
_PAROLE_ENTITA = {
    "evento": re.compile(r"\bevent[oi]\b", re.IGNORECASE),
    "ordine": re.compile(r"\bordin[ei]\b", re.IGNORECASE),
    "cliente": re.compile(r"\bclient[ei]\b", re.IGNORECASE),
}


def _entita_citate(testo: str) -> set[str]:
    return {entita for entita, parola in _PAROLE_ENTITA.items() if parola.search(testo)}


def id_espliciti(testo: str, domanda: str = "") -> dict[str, set[int]]:
    """Id scritti dall'operatore, per nome di parametro (evento_id, ordine_id, cliente_id).

    Si accetta un numero se e' scritto accanto alla parola dell'entita' («evento 12», «ordine n. 596»), oppure
    dopo la parola «id» («id: 1») o da solo, purche' nel messaggio, o nella domanda a cui risponde, compaia una
    sola entita' tra evento, ordine e cliente. Quantita' e date («12 biglietti», «il 12 dicembre») non sono id, e
    con piu' entita' nello stesso messaggio il numero e' ambiguo e non si accetta.

    Se il messaggio non nomina nessuna entita' (e nemmeno la domanda a cui risponde), un numero dopo la parola
    «id» («il suo id e' 12») vale per qualunque tipo di id, con la chiave ID_QUALSIASI_TIPO: il tipo lo
    stabilisce il tool che il modello chiama, e la scheda di conferma mostra comunque il nome dell'evento o del
    cliente. Un numero senza la parola «id» («12 biglietti») non e' mai un id in questo caso.

    Controllo volutamente semplice: dice da dove viene il numero, non che l'entita' sia quella che
    l'operatore intendeva. La conferma resta necessaria.
    """
    trovati: dict[str, set[int]] = {}
    for entita, numero in _RIFERIMENTO.findall(testo):
        trovati.setdefault(_PARAMETRO_PER_ENTITA[entita.lower()], set()).add(int(numero))

    citate = _entita_citate(testo)
    if not citate:  # nessuna entita' nel messaggio: si guarda la domanda a cui l'operatore sta rispondendo
        citate = _entita_citate(domanda)
        if not citate:  # nessuna entita' nemmeno li': «il suo id e' 12» vale per qualunque tipo di id
            for numero in _ID_GENERICO.findall(testo):
                trovati.setdefault(ID_QUALSIASI_TIPO, set()).add(int(numero))
    if len(citate) == 1:
        parametro = _PARAMETRO_PER_ENTITA[next(iter(citate))]
        for numero in [*_ID_GENERICO.findall(testo), *_SOLO_NUMERO.findall(testo)]:
            trovati.setdefault(parametro, set()).add(int(numero))
    return trovati


def raccogli_id(valore, noti: dict[str, set[int]]) -> None:
    """Annota gli id che compaiono in un risultato dei tool, per nome di parametro (evento_id, ordine_id...).

    Un oggetto con "id" e "titolo" e' un evento, uno con "id" e "cognome" e' un cliente.
    """
    if isinstance(valore, list):
        for voce in valore:
            raccogli_id(voce, noti)
    elif isinstance(valore, dict):
        if isinstance(valore.get("id"), int) and not isinstance(valore["id"], bool):
            if "titolo" in valore:
                noti.setdefault("evento_id", set()).add(valore["id"])
            elif "cognome" in valore:
                noti.setdefault("cliente_id", set()).add(valore["id"])
        for chiave, voce in valore.items():
            if chiave.endswith("_id") and isinstance(voce, int) and not isinstance(voce, bool):
                noti.setdefault(chiave, set()).add(voce)
            raccogli_id(voce, noti)


class Agente:
    """Un agente di back-office: tiene la conversazione e gestisce una richiesta alla volta."""

    def __init__(
        self,
        provider: LLMProvider,
        mcp: ClientMcp,
        conferma: Conferma,
        registro: Registro,
        max_iterazioni: int = 10,
        tentativi_extra_risposta_vuota: int = 1,
        timeout_tool: float = 60,
        prompt_sistema: str = PROMPT_SISTEMA,
        controlli: bool = True,
        info_config: dict | None = None,
    ) -> None:
        self.provider = provider
        self.mcp = mcp
        self.conferma = conferma
        self.registro = registro
        self.max_iterazioni = max_iterazioni
        self.tentativi_extra = tentativi_extra_risposta_vuota
        self.timeout_tool = timeout_tool
        self.prompt_sistema = prompt_sistema
        self.controlli = controlli  # anteprima delle scritture e controllo degli id

        self.info_config = dict(info_config or {})  # variante del prompt, modello ecc., per il log (mai chiavi API)
        self._config_registrata = False

        # Id che il modello puo' usare nelle scritture, per tipo di entita' (evento_id, ordine_id, cliente_id):
        # scritti dall'operatore con l'entita' esplicita, oppure letti nei risultati dei tool.
        self._id_operatore: dict[str, set[int]] = {}
        self._id_letti: dict[str, set[int]] = {}

        self._info: dict[str, InfoTool] = {t.nome: t for t in mcp.strumenti}
        self.strumenti = [SpecTool(t.nome, t.descrizione, pulisci_schema(t.schema)) for t in mcp.strumenti]
        self.storia: list[Messaggio] = []
        self._turni = 0
        self._gia_registrati = 0  # quanti messaggi della storia sono gia' finiti nel log

    def reset(self) -> None:
        """Dimentica la conversazione (nuova chat)."""
        self.storia.clear()
        self._gia_registrati = 0
        self._id_operatore.clear()
        self._id_letti.clear()
        self._config_registrata = False  # la nuova chat ha un nuovo log, che deve ripartire dalla configurazione

    def _registra_configurazione(self) -> None:
        """Una riga all'inizio di ogni log con cio' che serve a interpretare le prove (nessun segreto)."""
        self.registro.scrivi(
            "configurazione",
            **self.info_config,
            provider=self.provider.nome, modello=self.provider.modello,
            max_iterazioni=self.max_iterazioni, tentativi_extra_risposta_vuota=self.tentativi_extra,
            timeout_tool_s=self.timeout_tool, controlli=self.controlli,
            limite_risultato_al_modello=LIMITE_RISULTATO, tool_disponibili=len(self.strumenti),
            prompt_caratteri=len(self.prompt_sistema),
            prompt_sha256=hashlib.sha256(self.prompt_sistema.encode("utf-8")).hexdigest()[:12],
        )
        self._config_registrata = True

    # ------------------------------------------------------------------ ciclo

    async def esegui(self, richiesta: str) -> EsitoTurno:
        """Gestisce una richiesta dell'operatore e restituisce come e' finita."""
        self._turni += 1
        turno = _Turno(self._turni)
        inizio = time.monotonic()
        if not self._config_registrata:
            self._registra_configurazione()
        self.registro.scrivi(
            "richiesta_utente", turno=turno.numero, testo=richiesta,
            modello=self.provider.modello, provider=self.provider.nome, max_iterazioni=self.max_iterazioni,
        )
        self.storia.append(Messaggio("user", richiesta))
        ultima_domanda = next((m.contenuto for m in reversed(self.storia[:-1]) if m.ruolo == "assistant" and m.contenuto), "")
        for parametro, numeri in id_espliciti(richiesta, ultima_domanda).items():
            self._id_operatore.setdefault(parametro, set()).update(numeri)

        for iterazione in range(1, self.max_iterazioni + 1):
            turno.iterazione = iterazione
            turno.stato.iterazioni = iterazione

            try:
                risposta = await self._chiedi_al_modello(turno)
            except ErroreModello as errore:
                return self._chiudi(turno, inizio, MotivoArresto.ERRORE_MODELLO,
                                    f"Non riesco a ottenere una risposta dal modello: {errore}")

            self.storia.append(Messaggio("assistant", risposta.testo, risposta.chiamate_tool))

            if not risposta.chiamate_tool:
                motivo = MotivoArresto.CONFERMA_NEGATA if turno.stato.conferme_negate else MotivoArresto.RISPOSTA_FINALE
                return self._chiudi(turno, inizio, motivo, risposta.testo)

            for posizione, chiamata in enumerate(risposta.chiamate_tool):
                esito = await self._esegui_tool(chiamata, turno)
                self.storia.append(Messaggio("tool", esito.testo, id_chiamata=chiamata.id, nome_tool=chiamata.nome))
                if esito.fatale:
                    # Ogni chiamata del modello deve avere una risposta, anche se non eseguita.
                    for rimasta in risposta.chiamate_tool[posizione + 1:]:
                        self.storia.append(Messaggio("tool", "Non eseguito: server MCP non disponibile.",
                                                     id_chiamata=rimasta.id, nome_tool=rimasta.nome))
                    return self._chiudi(turno, inizio, MotivoArresto.ERRORE_MCP,
                                        "Il server dei tool non risponde piu': operazione interrotta.")

        return self._chiudi(
            turno, inizio, MotivoArresto.LIMITE_ITERAZIONI,
            f"Mi sono fermato dopo {self.max_iterazioni} iterazioni senza arrivare a una risposta. "
            "Prova a riformulare la richiesta in modo piu' preciso.",
        )

    # ----------------------------------------------------------------- modello

    async def _chiedi_al_modello(self, turno: _Turno) -> RispostaModello:
        """Chiama il modello; se risponde a vuoto riprova (di default una volta) e poi segnala l'errore."""
        tentativi = 1 + self.tentativi_extra
        for tentativo in range(1, tentativi + 1):
            conversazione = [Messaggio("system", self.prompt_sistema), *self.storia]
            nuovi = [m.a_dict() for m in self.storia[self._gia_registrati:]]
            self._gia_registrati = len(self.storia)
            inizio = time.monotonic()
            campi_comuni = dict(
                turno=turno.numero, iterazione=turno.iterazione, tentativo=tentativo,
                modello=self.provider.modello, messaggi_totali=len(conversazione),
                nuovi_messaggi=nuovi, tool_disponibili=len(self.strumenti),
            )
            try:
                risposta = await asyncio.to_thread(self.provider.chat, conversazione, self.strumenti)
            except ErroreModello as errore:
                self.registro.scrivi(
                    "chiamata_modello", **campi_comuni, esito="errore", errore=str(errore),
                    durata_ms=int((time.monotonic() - inizio) * 1000), token_ingresso=0, token_uscita=0,
                )
                raise

            turno.stato.chiamate_modello += 1
            turno.stato.token_ingresso += risposta.token_ingresso
            turno.stato.token_uscita += risposta.token_uscita
            self.registro.scrivi(
                "chiamata_modello", **campi_comuni,
                esito="vuota" if risposta.vuota else "ok",
                testo_risposta=risposta.testo,
                chiamate_tool=[{"id": c.id, "nome": c.nome, "argomenti": c.argomenti} for c in risposta.chiamate_tool],
                token_ingresso=risposta.token_ingresso, token_uscita=risposta.token_uscita,
                durata_ms=risposta.durata_ms,
            )
            if not risposta.vuota:
                return risposta
            if tentativo < tentativi:
                self.registro.scrivi("nuovo_tentativo", turno=turno.numero, iterazione=turno.iterazione,
                                     motivo="risposta vuota del modello", tentativo_successivo=tentativo + 1)
        raise ErroreModello(f"risposta vuota anche dopo {tentativi} tentativi")

    # -------------------------------------------------------------------- tool

    async def _esegui_tool(self, chiamata: ChiamataTool, turno: _Turno) -> _EsitoTool:
        """Controlla, fa confermare se scrive dati, esegue e registra una chiamata del modello."""
        inizio = time.monotonic()
        info = self._info.get(chiamata.nome)
        scrittura = info.scrittura if info else None
        turno.stato.chiamate_tool += 1

        esito = await self._decidi_ed_esegui(chiamata, info, turno)
        if esito.esito == "ok":  # gli id letti qui potranno essere usati nelle scritture successive
            try:
                raccogli_id(json.loads(esito.testo), self._id_letti)
            except json.JSONDecodeError:
                pass

        # Il log conserva il risultato integrale; al modello va una versione abbreviata se supera il limite.
        completo = esito.testo
        troncato = len(completo) > LIMITE_RISULTATO
        per_il_modello = completo[:LIMITE_RISULTATO] + " …[risultato troncato]" if troncato else completo
        self.registro.scrivi(
            "tool", turno=turno.numero, iterazione=turno.iterazione, id_chiamata=chiamata.id,
            tool=chiamata.nome, parametri=chiamata.argomenti, scrittura=scrittura,
            esito=esito.esito, risultato=completo, troncato_per_il_modello=troncato,
            caratteri_risultato=len(completo), attesa_conferma_ms=esito.attesa_conferma_ms,
            durata_ms=max(0, int((time.monotonic() - inizio) * 1000) - esito.attesa_conferma_ms),
        )
        return _EsitoTool(per_il_modello, esito.esito, esito.fatale, esito.attesa_conferma_ms)

    async def _decidi_ed_esegui(self, chiamata: ChiamataTool, info: InfoTool | None, turno: _Turno) -> _EsitoTool:
        # 1. Argomenti illeggibili.
        if chiamata.errore_argomenti:
            return _EsitoTool(f"Errore: {chiamata.errore_argomenti}. Riprova con parametri validi.", "parametri_non_validi")

        # 2. Tool inesistente.
        if info is None:
            disponibili = ", ".join(sorted(self._info))
            return _EsitoTool(f"Errore: il tool '{chiamata.nome}' non esiste. Tool disponibili: {disponibili}.", "tool_non_disponibile")

        # 3. Parametri contro lo schema: prima di disturbare l'operatore con una conferma inutile.
        problemi = sorted(Draft202012Validator(info.schema).iter_errors(chiamata.argomenti), key=lambda e: list(e.path))
        if problemi:
            dettaglio = "; ".join(f"{'.'.join(map(str, e.path)) or 'parametri'}: {e.message}" for e in problemi[:5])
            return _EsitoTool(f"Errore: parametri non validi per '{info.nome}': {dettaglio}.", "parametri_non_validi")

        # 3b. Un'azione che l'operatore ha gia' rifiutato in questa richiesta non si ripropone: lo decide
        # il codice, non la buona volonta' del modello. Una nuova richiesta dell'operatore (altro turno) puo' ripeterla.
        if info.scrittura and _chiave_azione(info.nome, chiamata.argomenti) in turno.rifiutate:
            return _EsitoTool(
                "L'operatore ha gia' RIFIUTATO questa stessa azione in questa richiesta: non e' stata eseguita e non "
                "viene riproposta. Comunica all'operatore che l'azione non e' stata eseguita.",
                "rifiuto_ripetuto",
            )

        # 4. Controlli sulle scritture, prima di disturbare l'operatore: id mai visti e anteprima delle regole.
        riepilogo = None
        if info.scrittura and self.controlli:
            problema = self._id_non_verificato(info, chiamata.argomenti)
            if problema:
                return _EsitoTool(problema, "id_non_verificato")
            if self.mcp.ha_anteprima:
                anteprima = await self._anteprima(info, chiamata, turno)
                if isinstance(anteprima, _EsitoTool):  # vietata dalle regole, o guasto dell'anteprima
                    return anteprima
                riepilogo = anteprima

        # 5. Conferma umana per i tool che modificano i dati.
        attesa_ms = 0
        if info.scrittura:
            richiesta = RichiestaConferma(info.nome, info.descrizione, chiamata.argomenti, riepilogo)
            inizio_attesa = time.monotonic()
            approvata = await self.conferma.chiedi(richiesta)
            attesa_ms = int((time.monotonic() - inizio_attesa) * 1000)
            self.registro.scrivi("conferma", turno=turno.numero, iterazione=turno.iterazione,
                                 tool=info.nome, parametri=chiamata.argomenti, riepilogo=riepilogo,
                                 decisione="approvata" if approvata else "negata", attesa_ms=attesa_ms)
            if not approvata:
                turno.stato.conferme_negate += 1
                turno.rifiutate.add(_chiave_azione(info.nome, chiamata.argomenti))
                return _EsitoTool(
                    "L'operatore ha RIFIUTATO questa azione: nessun dato e' stato modificato. "
                    "Non riprovare: comunica all'operatore che l'azione non e' stata eseguita.",
                    "rifiutato", attesa_conferma_ms=attesa_ms,
                )

        # 6. Esecuzione sul server MCP.
        try:
            risultato = await asyncio.wait_for(self.mcp.chiama(info.nome, chiamata.argomenti), self.timeout_tool)
        except asyncio.TimeoutError:
            return _EsitoTool(
                f"Errore: il tool '{info.nome}' non ha risposto entro {self.timeout_tool:g} secondi. "
                "L'esito e' incerto: se era una modifica, verifica lo stato con un tool di lettura.",
                "timeout", attesa_conferma_ms=attesa_ms,
            )
        except Exception as errore:  # guasto di trasporto: il server non e' piu' raggiungibile
            return _EsitoTool(f"Errore di comunicazione con il server dei tool: {errore}", "errore_trasporto",
                              fatale=True, attesa_conferma_ms=attesa_ms)

        if risultato.errore:
            return _EsitoTool(risultato.testo, "errore_tool", attesa_conferma_ms=attesa_ms)
        return _EsitoTool(risultato.testo, "ok", attesa_conferma_ms=attesa_ms)

    def _id_non_verificato(self, info: InfoTool, argomenti: dict) -> str | None:
        """Una scrittura puo' usare solo id scritti dall'operatore o letti nei risultati dei tool: non inventati."""
        for nome, valore in argomenti.items():
            if not nome.endswith("_id") or not isinstance(valore, int) or isinstance(valore, bool):
                continue
            scritto = self._id_operatore.get(nome, set()) | self._id_operatore.get(ID_QUALSIASI_TIPO, set())
            if valore in scritto or valore in self._id_letti.get(nome, set()):
                continue
            suggerimento = {
                "evento_id": "chiama cerca_eventi con il titolo dell'evento e usa l'id che trovi",
                "cliente_id": "chiama storico_acquisti_cliente con nome e cognome e usa l'id che trovi",
                "ordine_id": "chiedi all'operatore il numero dell'ordine",
            }.get(nome, "cercalo con i tool di lettura")
            return (
                f"Errore: l'id {nome} {valore} non e' comparso ne' nella richiesta dell'operatore come riferimento "
                f"chiaro a quell'entita' ne' nei risultati dei tool. Non inventare id: {suggerimento}."
            )
        return None

    async def _anteprima(self, info: InfoTool, chiamata: ChiamataTool, turno: _Turno) -> "str | _EsitoTool":
        """Chiede al server di verificare la scrittura senza eseguirla. Restituisce il riepilogo, o un errore."""
        inizio = time.monotonic()
        try:
            risultato = await asyncio.wait_for(
                self.mcp.chiama(NOME_ANTEPRIMA, {"tool": info.nome, "parametri": chiamata.argomenti}), self.timeout_tool
            )
        except asyncio.TimeoutError:
            return _EsitoTool(f"Errore: la verifica di '{info.nome}' non ha risposto in tempo. Nessuna modifica eseguita.", "timeout")
        except Exception as errore:
            return _EsitoTool(f"Errore di comunicazione con il server dei tool: {errore}", "errore_trasporto", fatale=True)
        if risultato.errore:
            return _EsitoTool(risultato.testo, "errore_tool")
        try:
            dati = json.loads(risultato.testo)
        except json.JSONDecodeError:
            return _EsitoTool("Errore: risposta di verifica non leggibile. Nessuna modifica eseguita.", "errore_tool")

        self.registro.scrivi(
            "anteprima", turno=turno.numero, iterazione=turno.iterazione, tool=info.nome, parametri=chiamata.argomenti,
            ammessa=dati.get("ammessa"), riepilogo=dati.get("riepilogo"), motivo=dati.get("motivo"),
            durata_ms=int((time.monotonic() - inizio) * 1000),
        )
        if not dati.get("ammessa"):
            return _EsitoTool(f"Errore: azione non eseguibile. {dati.get('motivo')}", "non_ammessa")
        return dati.get("riepilogo")

    # ------------------------------------------------------------------ chiusura

    def _chiudi(self, turno: _Turno, inizio: float, motivo: MotivoArresto, risposta: str) -> EsitoTurno:
        esito = turno.stato
        esito.motivo, esito.risposta = motivo, risposta
        esito.durata_ms = int((time.monotonic() - inizio) * 1000)
        self.registro.scrivi(
            "arresto", turno=turno.numero, motivo=motivo.value, risposta=risposta,
            iterazioni=esito.iterazioni, chiamate_modello=esito.chiamate_modello,
            chiamate_tool=esito.chiamate_tool, conferme_negate=esito.conferme_negate,
            token_ingresso=esito.token_ingresso, token_uscita=esito.token_uscita, durata_ms=esito.durata_ms,
        )
        return esito
