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
import json
import time
from dataclasses import dataclass, field
from enum import Enum

from jsonschema import Draft202012Validator

from .conferma import Conferma, RichiestaConferma
from .llm.base import ChiamataTool, ErroreModello, LLMProvider, Messaggio, RispostaModello, SpecTool
from .mcp_client import ClientMcp, InfoTool
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
    ) -> None:
        self.provider = provider
        self.mcp = mcp
        self.conferma = conferma
        self.registro = registro
        self.max_iterazioni = max_iterazioni
        self.tentativi_extra = tentativi_extra_risposta_vuota
        self.timeout_tool = timeout_tool
        self.prompt_sistema = prompt_sistema

        self._info: dict[str, InfoTool] = {t.nome: t for t in mcp.strumenti}
        self.strumenti = [SpecTool(t.nome, t.descrizione, pulisci_schema(t.schema)) for t in mcp.strumenti]
        self.storia: list[Messaggio] = []
        self._turni = 0
        self._gia_registrati = 0  # quanti messaggi della storia sono gia' finiti nel log

    def reset(self) -> None:
        """Dimentica la conversazione (nuova chat)."""
        self.storia.clear()
        self._gia_registrati = 0

    # ------------------------------------------------------------------ ciclo

    async def esegui(self, richiesta: str) -> EsitoTurno:
        """Gestisce una richiesta dell'operatore e restituisce come e' finita."""
        self._turni += 1
        turno = _Turno(self._turni)
        inizio = time.monotonic()
        self.registro.scrivi(
            "richiesta_utente", turno=turno.numero, testo=richiesta,
            modello=self.provider.modello, provider=self.provider.nome, max_iterazioni=self.max_iterazioni,
        )
        self.storia.append(Messaggio("user", richiesta))

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

        testo = esito.testo
        if len(testo) > LIMITE_RISULTATO:
            testo = testo[:LIMITE_RISULTATO] + " …[risultato troncato]"
        self.registro.scrivi(
            "tool", turno=turno.numero, iterazione=turno.iterazione, id_chiamata=chiamata.id,
            tool=chiamata.nome, parametri=chiamata.argomenti, scrittura=scrittura,
            esito=esito.esito, risultato=testo, attesa_conferma_ms=esito.attesa_conferma_ms,
            durata_ms=max(0, int((time.monotonic() - inizio) * 1000) - esito.attesa_conferma_ms),
        )
        return _EsitoTool(testo, esito.esito, esito.fatale, esito.attesa_conferma_ms)

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

        # 4. Conferma umana per i tool che modificano i dati.
        attesa_ms = 0
        if info.scrittura:
            richiesta = RichiestaConferma(info.nome, info.descrizione, chiamata.argomenti)
            inizio_attesa = time.monotonic()
            approvata = await self.conferma.chiedi(richiesta)
            attesa_ms = int((time.monotonic() - inizio_attesa) * 1000)
            self.registro.scrivi("conferma", turno=turno.numero, iterazione=turno.iterazione,
                                 tool=info.nome, parametri=chiamata.argomenti,
                                 decisione="approvata" if approvata else "negata", attesa_ms=attesa_ms)
            if not approvata:
                turno.stato.conferme_negate += 1
                return _EsitoTool(
                    "L'operatore ha RIFIUTATO questa azione: nessun dato e' stato modificato. "
                    "Non riprovare: comunica all'operatore che l'azione non e' stata eseguita.",
                    "rifiutato", attesa_conferma_ms=attesa_ms,
                )

        # 5. Esecuzione sul server MCP.
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
