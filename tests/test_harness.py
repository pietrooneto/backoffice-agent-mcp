"""Test dell'harness: ciclo agentico, arresti, errori, conferma umana, log e provider.

Il modello e' finto (risposte preparate); il server MCP e' quello vero, avviato come processo
figlio su una copia del database sintetico. Nessun modello reale e' coinvolto.
"""
import asyncio
import json
import shutil
import sqlite3
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness.agent_loop import Agente, MotivoArresto, pulisci_schema
from harness.conferma import AutoApprova, AutoRifiuta, RichiestaConferma
from harness.config import Configurazione
from harness.llm import (
    ErroreModello, Messaggio, OllamaProvider, OpenAICompatProvider, SpecTool, crea_provider,
)
from harness.llm.base import ChiamataTool
from harness.llm.fake import ProviderScriptato, risposta
from harness.mcp_client import ClientMcp
from harness.registro import Registro


# ----------------------------------------------------------------------- utilita'

@pytest.fixture
def db(db_modello, tmp_path):
    """Percorso di una copia fresca del database sintetico."""
    copia = tmp_path / "harness.db"
    shutil.copy(db_modello, copia)
    return copia


def stato_evento(db, evento_id):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT stato FROM eventi WHERE id = ?", (evento_id,)).fetchone()[0]
    finally:
        conn.close()


@asynccontextmanager
async def sessione(db, copione, conferma=None, env=None, cartella_log=None, **opzioni):
    """Avvia il server MCP vero e restituisce (agente, provider, registro)."""
    provider = ProviderScriptato(copione)
    registro = Registro(cartella_log)
    async with ClientMcp({"DB_PATH": str(db), **(env or {})}) as mcp:
        agente = Agente(provider, mcp, conferma or AutoApprova(), registro, **opzioni)
        yield agente, provider, registro


def esegui(coro):
    return asyncio.run(coro)


def tipi(registro, tipo):
    return [e for e in registro.eventi if e["tipo"] == tipo]


class ConfermaRegistrata:
    """Approva o rifiuta e ricorda cosa le e' stato chiesto."""

    def __init__(self, approva: bool) -> None:
        self.approva = approva
        self.richieste: list[RichiestaConferma] = []

    async def chiedi(self, richiesta):
        self.richieste.append(richiesta)
        return self.approva


# ------------------------------------------------------------- ciclo e arresti

def test_lettura_e_risposta_finale(db, tmp_path):
    copione = [
        risposta(tool=[("cerca_eventi", {"titolo": "cabaret"})], token_ingresso=300, token_uscita=30),
        risposta("Serata Cabaret e' a Cagliari.", token_ingresso=400, token_uscita=15),
    ]

    async def prova():
        async with sessione(db, copione, cartella_log=tmp_path / "log") as (agente, provider, registro):
            return await agente.esegui("dove si tiene il cabaret?"), provider, registro

    esito, provider, registro = esegui(prova())

    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE
    assert esito.risposta == "Serata Cabaret e' a Cagliari."
    assert (esito.iterazioni, esito.chiamate_modello, esito.chiamate_tool) == (2, 2, 1)
    assert (esito.token_ingresso, esito.token_uscita) == (700, 45)

    # Il risultato del tool e' tornato al modello alla seconda chiamata.
    messaggio_tool = provider.chiamate[1][-1]
    assert messaggio_tool.ruolo == "tool" and "Serata Cabaret" in messaggio_tool.contenuto
    # Il prompt di sistema e' sempre il primo messaggio.
    assert provider.chiamate[0][0].ruolo == "system"

    # Log JSONL: ogni riga e' JSON valido con i campi comuni.
    righe = [json.loads(r) for r in registro.percorso.read_text(encoding="utf-8").splitlines()]
    assert [r["tipo"] for r in righe] == [
        "richiesta_utente", "chiamata_modello", "tool", "chiamata_modello", "arresto"]
    assert all({"timestamp", "sessione_id"} <= set(r) for r in righe)
    tool = righe[2]
    assert tool["tool"] == "cerca_eventi" and tool["parametri"] == {"titolo": "cabaret"}
    assert tool["esito"] == "ok" and tool["scrittura"] is False and "Serata Cabaret" in tool["risultato"]
    assert righe[1]["token_ingresso"] == 300 and righe[4]["token_uscita"] == 45
    assert righe[4]["motivo"] == "risposta_finale"


def test_limite_di_iterazioni(db):
    copione = [risposta(tool=[("cerca_eventi", {})])] * 3

    async def prova():
        async with sessione(db, copione, max_iterazioni=3) as (agente, _, registro):
            return await agente.esegui("continua all'infinito"), registro

    esito, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.LIMITE_ITERAZIONI
    assert esito.iterazioni == 3 and esito.chiamate_tool == 3
    assert tipi(registro, "arresto")[0]["motivo"] == "limite_iterazioni"


def test_risposta_vuota_riprova_una_volta(db):
    copione = [risposta("", token_ingresso=100, token_uscita=5), risposta("Ecco fatto.", token_ingresso=100, token_uscita=8)]

    async def prova():
        async with sessione(db, copione) as (agente, provider, registro):
            return await agente.esegui("ciao"), provider, registro

    esito, provider, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE and esito.risposta == "Ecco fatto."
    assert esito.chiamate_modello == 2 and esito.iterazioni == 1
    assert (esito.token_ingresso, esito.token_uscita) == (200, 13)  # il tentativo extra e' conteggiato
    assert len(tipi(registro, "nuovo_tentativo")) == 1
    assert [e["esito"] for e in tipi(registro, "chiamata_modello")] == ["vuota", "ok"]


def test_risposta_vuota_due_volte_e_errore_del_modello(db):
    async def prova():
        async with sessione(db, [risposta(""), risposta("")]) as (agente, _, registro):
            return await agente.esegui("ciao"), registro

    esito, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.ERRORE_MODELLO
    assert "vuota" in esito.risposta
    assert tipi(registro, "arresto")[0]["motivo"] == "errore_modello"


def test_modello_non_raggiungibile(db):
    async def prova():
        async with sessione(db, [ErroreModello("Ollama spento")]) as (agente, _, registro):
            return await agente.esegui("ciao"), registro

    esito, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.ERRORE_MODELLO and "Ollama spento" in esito.risposta
    assert tipi(registro, "chiamata_modello")[0]["esito"] == "errore"


def test_la_conversazione_continua_tra_le_richieste(db):
    async def prova():
        async with sessione(db, [risposta("Prima."), risposta("Seconda.")]) as (agente, provider, _):
            await agente.esegui("domanda uno")
            await agente.esegui("domanda due")
            return provider

    provider = esegui(prova())
    secondo_invio = [m.contenuto for m in provider.chiamate[1] if m.ruolo in ("user", "assistant")]
    assert secondo_invio == ["domanda uno", "Prima.", "domanda due"]


# ------------------------------------------------------- tool: errori e controlli

def test_tool_inesistente_torna_al_modello(db):
    copione = [risposta(tool=[("cancella_tutto", {})]), risposta("Non posso farlo.")]

    async def prova():
        async with sessione(db, copione) as (agente, provider, registro):
            return await agente.esegui("cancella tutto"), provider, registro

    esito, provider, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE
    assert tipi(registro, "tool")[0]["esito"] == "tool_non_disponibile"
    assert "non esiste" in provider.chiamate[1][-1].contenuto
    assert "cerca_eventi" in provider.chiamate[1][-1].contenuto  # elenca i tool disponibili


def test_parametri_non_validi_non_chiedono_conferma(db):
    conferma = ConfermaRegistrata(approva=True)
    copione = [risposta(tool=[("chiudi_vendite_evento", {"evento_id": 0})]), risposta("Id non valido.")]

    async def prova():
        async with sessione(db, copione, conferma=conferma) as (agente, provider, registro):
            return await agente.esegui("chiudi l'evento zero"), provider, registro

    esito, provider, registro = esegui(prova())
    assert conferma.richieste == []  # l'operatore non viene disturbato per una chiamata sbagliata
    assert tipi(registro, "tool")[0]["esito"] == "parametri_non_validi"
    assert "non validi" in provider.chiamate[1][-1].contenuto


def test_argomenti_illeggibili(db):
    chiamata_rotta = ChiamataTool(id="x", nome="cerca_eventi", argomenti={}, errore_argomenti="argomenti non in formato JSON valido")
    r = risposta()
    r.chiamate_tool = [chiamata_rotta]

    async def prova():
        async with sessione(db, [r, risposta("Riprovo piu' tardi.")]) as (agente, _, registro):
            return await agente.esegui("cerca"), registro

    esito, registro = esegui(prova())
    assert tipi(registro, "tool")[0]["esito"] == "parametri_non_validi"
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE


def test_errore_del_tool_torna_al_modello(db):
    # L'evento 5 ha gia' le vendite chiuse: il tool risponde con un errore leggibile.
    copione = [risposta(tool=[("chiudi_vendite_evento", {"evento_id": 5})]), risposta("Era gia' chiuso.")]

    async def prova():
        async with sessione(db, copione) as (agente, provider, registro):
            return await agente.esegui("chiudi le vendite della coppa"), provider, registro

    esito, provider, registro = esegui(prova())
    assert tipi(registro, "tool")[0]["esito"] == "errore_tool"
    assert "gia' le vendite chiuse" in provider.chiamate[1][-1].contenuto
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE


def test_guasto_simulato_del_database(db):
    copione = [risposta(tool=[("cerca_eventi", {})]), risposta("Il sistema ha un problema.")]

    async def prova():
        async with sessione(db, copione, env={"SIMULA_GUASTO": "cerca_eventi"}) as (agente, provider, registro):
            return await agente.esegui("elenca gli eventi"), provider, registro

    esito, provider, registro = esegui(prova())
    assert tipi(registro, "tool")[0]["esito"] == "errore_tool"
    assert "Errore temporaneo del database" in provider.chiamate[1][-1].contenuto


def test_timeout_del_tool(db):
    copione = [risposta(tool=[("cerca_eventi", {})]), risposta("Il tool e' lento.")]

    async def lento(nome, argomenti):
        await asyncio.sleep(5)

    async def prova():
        async with sessione(db, copione, timeout_tool=0.05) as (agente, provider, registro):
            agente.mcp.chiama = lento
            return await agente.esegui("elenca gli eventi"), provider, registro

    esito, provider, registro = esegui(prova())
    assert tipi(registro, "tool")[0]["esito"] == "timeout"
    assert "incerto" in provider.chiamate[1][-1].contenuto
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE


def test_guasto_di_trasporto_ferma_il_ciclo(db):
    copione = [risposta(tool=[("cerca_eventi", {}), ("cerca_eventi", {})])]

    async def rotto(nome, argomenti):
        raise RuntimeError("pipe chiusa")

    async def prova():
        async with sessione(db, copione) as (agente, _, registro):
            agente.mcp.chiama = rotto
            esito = await agente.esegui("elenca gli eventi")
            return esito, agente, registro

    esito, agente, registro = esegui(prova())
    assert esito.motivo == MotivoArresto.ERRORE_MCP
    assert tipi(registro, "tool")[0]["esito"] == "errore_trasporto"
    # Ogni chiamata del modello ha comunque una risposta nella storia (conversazione coerente).
    assert [m.ruolo for m in agente.storia] == ["user", "assistant", "tool", "tool"]


# ------------------------------------------------------------ conferma umana

def test_scrittura_approvata_modifica_i_dati(db):
    conferma = ConfermaRegistrata(approva=True)
    copione = [risposta(tool=[("chiudi_vendite_evento", {"evento_id": 12})]), risposta("Vendite chiuse.")]

    async def prova():
        async with sessione(db, copione, conferma=conferma) as (agente, _, registro):
            return await agente.esegui("chiudi le vendite del cabaret"), registro

    esito, registro = esegui(prova())
    assert stato_evento(db, 12) == "vendite_chiuse"
    assert [(r.tool, r.argomenti) for r in conferma.richieste] == [("chiudi_vendite_evento", {"evento_id": 12})]
    assert tipi(registro, "conferma")[0]["decisione"] == "approvata"
    assert tipi(registro, "tool")[0]["scrittura"] is True
    assert esito.motivo == MotivoArresto.RISPOSTA_FINALE


def test_l_attesa_della_conferma_non_conta_come_durata_del_tool(db):
    class ConfermaLenta:
        async def chiedi(self, richiesta):
            await asyncio.sleep(0.6)  # l'operatore ci pensa
            return True

    copione = [risposta(tool=[("chiudi_vendite_evento", {"evento_id": 12})]), risposta("Fatto.")]

    async def prova():
        async with sessione(db, copione, conferma=ConfermaLenta()) as (agente, _, registro):
            await agente.esegui("chiudi le vendite del cabaret")
            return registro

    registro = esegui(prova())
    tool = tipi(registro, "tool")[0]
    assert tool["attesa_conferma_ms"] >= 600
    assert tool["durata_ms"] < tool["attesa_conferma_ms"]  # durata = solo l'esecuzione del tool
    assert tipi(registro, "conferma")[0]["attesa_ms"] >= 600


def test_scrittura_negata_non_modifica_i_dati(db):
    copione = [risposta(tool=[("annulla_evento", {"evento_id": 12})]), risposta("Va bene, non annullo nulla.")]

    async def prova():
        async with sessione(db, copione, conferma=AutoRifiuta()) as (agente, provider, registro):
            return await agente.esegui("annulla il cabaret"), provider, registro

    esito, provider, registro = esegui(prova())
    assert stato_evento(db, 12) == "in_vendita"
    assert esito.motivo == MotivoArresto.CONFERMA_NEGATA and esito.conferme_negate == 1
    assert tipi(registro, "conferma")[0]["decisione"] == "negata"
    assert tipi(registro, "tool")[0]["esito"] == "rifiutato"
    # Il rifiuto e' stato restituito al modello, che ha potuto rispondere.
    assert "RIFIUTATO" in provider.chiamate[1][-1].contenuto
    assert esito.risposta == "Va bene, non annullo nulla."


def test_le_letture_non_chiedono_conferma(db):
    conferma = ConfermaRegistrata(approva=False)
    copione = [risposta(tool=[("dettaglio_evento", {"evento_id": 9})]), risposta("Restano pochi posti.")]

    async def prova():
        async with sessione(db, copione, conferma=conferma) as (agente, _, _):
            return await agente.esegui("quanti posti restano al rock club?")

    esito = esegui(prova())
    assert conferma.richieste == [] and esito.motivo == MotivoArresto.RISPOSTA_FINALE


def test_i_tre_tool_di_scrittura_sono_riconosciuti_dal_server(db):
    async def prova():
        async with ClientMcp({"DB_PATH": str(db)}) as mcp:
            return {t.nome for t in mcp.strumenti if t.scrittura}

    assert esegui(prova()) == {"chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine"}


# --------------------------------------------------------------- schema e config

def test_pulisci_schema_toglie_titoli_e_anyof_nulli():
    schema = {
        "title": "eseguiArguments",
        "type": "object",
        "properties": {
            "titolo": {"title": "Titolo", "anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "description": "d"},
            "title": {"title": "Title", "type": "string"},  # una proprieta' che si chiama "title" va conservata
        },
    }
    assert pulisci_schema(schema) == {
        "type": "object",
        "properties": {"titolo": {"type": "string", "description": "d"}, "title": {"type": "string"}},
    }


def test_le_varianti_del_prompt():
    from harness.prompt import PROMPT, PROMPT_SISTEMA, prompt_per

    assert prompt_per("base") == PROMPT_SISTEMA  # la versione di partenza resta il termine di confronto
    assert set(PROMPT) == {"base", "v2"} and prompt_per("v2") != prompt_per("base")
    with pytest.raises(ValueError, match="sconosciuta"):
        prompt_per("inesistente")


def test_crea_provider_dalla_configurazione():
    assert isinstance(crea_provider(Configurazione(provider="ollama")), OllamaProvider)
    assert isinstance(crea_provider(Configurazione(provider="openai_compat")), OpenAICompatProvider)
    with pytest.raises(ValueError, match="sconosciuto"):
        crea_provider(Configurazione(provider="inesistente"))


# ---------------------------------------------------------------- provider HTTP

class ServerFinto:
    """Server HTTP locale che registra le richieste e restituisce una risposta preparata."""

    def __init__(self, corpo, stato=200):
        self.richieste = []
        finto = self

        class Gestore(BaseHTTPRequestHandler):
            def do_POST(self):
                lunghezza = int(self.headers["Content-Length"])
                finto.richieste.append((self.path, dict(self.headers), json.loads(self.rfile.read(lunghezza))))
                dati = json.dumps(corpo).encode()
                self.send_response(stato)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dati)))
                self.end_headers()
                self.wfile.write(dati)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Gestore)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def chiudi(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server_finto():
    creati = []

    def crea(corpo, stato=200):
        s = ServerFinto(corpo, stato)
        creati.append(s)
        return s

    yield crea
    for s in creati:
        s.chiudi()


CONVERSAZIONE = [
    Messaggio("system", "sei un assistente"),
    Messaggio("user", "dove e' il cabaret?"),
    Messaggio("assistant", "", [ChiamataTool("c1", "cerca_eventi", {"titolo": "cabaret"})]),
    Messaggio("tool", '{"totale":1}', id_chiamata="c1", nome_tool="cerca_eventi"),
]
STRUMENTI = [SpecTool("cerca_eventi", "Cerca eventi", {"type": "object", "properties": {}})]


def test_ollama_provider_formato_e_risposta(server_finto):
    finto = server_finto({
        "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": "cerca_eventi", "arguments": {"titolo": "x"}}}]},
        "prompt_eval_count": 50, "eval_count": 7,
    })
    provider = OllamaProvider(modello="m", host=finto.url)
    r = provider.chat(CONVERSAZIONE, STRUMENTI)

    assert [(c.nome, c.argomenti) for c in r.chiamate_tool] == [("cerca_eventi", {"titolo": "x"})]
    assert (r.token_ingresso, r.token_uscita, r.modello) == (50, 7, "m")

    percorso, _, corpo = finto.richieste[0]
    assert percorso == "/api/chat" and corpo["stream"] is False
    assert corpo["options"]["temperature"] == 0 and corpo["tools"][0]["function"]["name"] == "cerca_eventi"
    assert corpo["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"titolo": "cabaret"}
    assert corpo["messages"][3] == {"role": "tool", "content": '{"totale":1}', "tool_name": "cerca_eventi"}


def test_openai_compat_provider_formato_e_risposta(server_finto):
    finto = server_finto({
        "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "abc", "function": {"name": "cerca_eventi", "arguments": '{"titolo": "y"}'}},
            {"id": "def", "function": {"name": "dettaglio_evento", "arguments": "{non json"}},
        ]}}],
        "usage": {"prompt_tokens": 60, "completion_tokens": 9},
    })
    provider = OpenAICompatProvider(modello="m", base_url=finto.url + "/v1", api_key="segreta")
    r = provider.chat(CONVERSAZIONE, STRUMENTI)

    assert r.chiamate_tool[0].argomenti == {"titolo": "y"} and r.chiamate_tool[0].id == "abc"
    assert r.chiamate_tool[1].errore_argomenti is not None  # argomenti illeggibili segnalati, non eccezione
    assert (r.token_ingresso, r.token_uscita) == (60, 9)

    percorso, intestazioni, corpo = finto.richieste[0]
    assert percorso == "/v1/chat/completions" and intestazioni["Authorization"] == "Bearer segreta"
    assert corpo["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"titolo": "cabaret"}'
    assert corpo["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": '{"totale":1}'}


def test_provider_errori_diventano_errore_modello(server_finto):
    errore_http = server_finto({"error": "boom"}, stato=500)
    with pytest.raises(ErroreModello, match="500"):
        OllamaProvider(host=errore_http.url).chat(CONVERSAZIONE, STRUMENTI)

    spento = server_finto({})
    spento.chiudi()
    with pytest.raises(ErroreModello, match="non raggiungibile"):
        OllamaProvider(host=spento.url, timeout=2).chat(CONVERSAZIONE, STRUMENTI)
