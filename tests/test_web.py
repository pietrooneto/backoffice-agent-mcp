"""Test dell'interfaccia web: server vero (uvicorn in un thread), modello finto, server MCP vero."""
import asyncio
import http.client
import json
import shutil
import socket
import sqlite3
import threading
import time

import pytest
import uvicorn

from harness.config import Configurazione
from harness.conferma import RichiestaConferma
from harness.llm.fake import ProviderScriptato, risposta
from harness.web import crea_app
from harness.web.app import Bus, ConfermaWeb


class ServerWeb:
    def __init__(self, copione, db, timeout_conferma=30):
        self.provider = ProviderScriptato(copione)
        app = crea_app(Configurazione(log_dir=None), self.provider, {"DB_PATH": str(db)}, timeout_conferma, db_path=db)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.porta = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        fine = time.time() + 30
        while not self.server.started:  # il lifespan avvia il server MCP: ci vuole qualche secondo
            assert time.time() < fine, "server web non avviato"
            time.sleep(0.05)

    def richiesta(self, metodo, percorso, corpo=None, intestazioni=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=20)
        dati = json.dumps(corpo) if corpo is not None else None
        h = {"Content-Type": "application/json"} if corpo is not None else {}
        h.update(intestazioni or {})
        conn.request(metodo, percorso, body=dati, headers=h)
        r = conn.getresponse()
        testo = r.read().decode("utf-8")
        conn.close()
        try:
            return r.status, json.loads(testo)
        except json.JSONDecodeError:
            return r.status, testo

    def eventi_fino_a(self, condizione, timeout=30):
        """Legge il flusso SSE (dall'inizio, con la cronologia) finche' la condizione e' vera."""
        conn = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=timeout)
        conn.request("GET", "/api/eventi")
        r = conn.getresponse()
        visti = []
        scadenza = time.time() + timeout  # i "ping" del server tengono sveglia la connessione: serve un limite totale
        try:
            while time.time() < scadenza:
                riga = r.readline().decode("utf-8")
                if not riga:
                    break
                if riga.startswith("data: "):
                    visti.append(json.loads(riga[6:]))
                    if condizione(visti):
                        return visti
        finally:
            conn.close()
        raise AssertionError(f"la condizione non si e' verificata entro {timeout} s; eventi visti: {[e['tipo'] for e in visti]}")

    def chiudi(self):
        self.server.should_exit = True
        self.thread.join(15)
        self.socket.close()


@pytest.fixture
def avvia(db_modello, tmp_path):
    creati = []

    def _avvia(copione, **opzioni):
        db = tmp_path / f"web{len(creati)}.db"
        shutil.copy(db_modello, db)
        s = ServerWeb(copione, db, **opzioni)
        s.db = db
        creati.append(s)
        return s

    yield _avvia
    for s in creati:
        s.chiudi()


def ha_arresto(eventi):
    return any(e["tipo"] == "arresto" for e in eventi)


def stato_evento(db, evento_id):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT stato FROM eventi WHERE id = ?", (evento_id,)).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- pagine e stato

def test_pagina_e_stato(avvia):
    s = avvia([])
    codice, html = s.richiesta("GET", "/")
    assert codice == 200 and "<title>Assistente di back-office</title>" in html
    codice, stato = s.richiesta("GET", "/api/stato")
    assert codice == 200 and stato["modello"] == "finto" and stato["occupato"] is False
    assert len(stato["tool"]) == 7 and sum(t["scrittura"] for t in stato["tool"]) == 3


def test_la_pagina_non_inserisce_testo_come_html():
    """Il testo del modello deve entrare solo come testo semplice: niente innerHTML."""
    from harness.web.app import PAGINA
    codice = PAGINA.read_text(encoding="utf-8")
    assert "innerHTML" not in codice and "insertAdjacentHTML" not in codice and "document.write" not in codice


# ------------------------------------------------------- pannello dati (sola lettura)

def test_la_pagina_ha_le_tre_schede_dei_dati():
    from harness.web.app import PAGINA
    codice = PAGINA.read_text(encoding="utf-8")
    for scheda in ("Eventi", "Movimenti", "Registro modifiche"):
        assert f">{scheda}<" in codice


def test_dati_del_pannello(avvia):
    s = avvia([])
    codice, dati = s.richiesta("GET", "/api/dati")
    assert codice == 200 and set(dati) == {"eventi", "movimenti", "registro"}
    assert len(dati["eventi"]) == 12 and dati["registro"] == []
    assert {"id", "titolo", "luogo", "data_evento", "stato", "capienza", "venduti"} <= set(dati["eventi"][0])
    assert {"tipo", "quando", "ordine_id", "cliente", "evento", "importo_centesimi", "nota"} <= set(dati["movimenti"][0])


def test_il_pannello_e_in_sola_lettura(avvia):
    s = avvia([])
    assert s.richiesta("POST", "/api/dati", {})[0] == 405
    assert s.richiesta("PUT", "/api/dati", {})[0] == 405
    assert s.richiesta("DELETE", "/api/dati")[0] == 405


def test_dopo_una_scrittura_il_pannello_mostra_l_effetto(avvia):
    s = avvia([risposta(tool=[("chiudi_vendite_evento", {"evento_id": 12})]), risposta("Vendite chiuse.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "chiudi le vendite dell'evento 12"})
    eventi = s.eventi_fino_a(lambda ev: any(e["tipo"] == "richiesta_conferma" for e in ev))
    id_conferma = next(e for e in eventi if e["tipo"] == "richiesta_conferma")["id"]

    prima = s.richiesta("GET", "/api/dati")[1]
    assert next(e for e in prima["eventi"] if e["id"] == 12)["stato"] == "in_vendita" and prima["registro"] == []

    s.richiesta("POST", "/api/conferma", {"id": id_conferma, "approva": True})
    s.eventi_fino_a(ha_arresto)
    dopo = s.richiesta("GET", "/api/dati")[1]
    assert next(e for e in dopo["eventi"] if e["id"] == 12)["stato"] == "vendite_chiuse"
    assert [(r["tool"], r["parametri"], r["esito"]) for r in dopo["registro"]] == [("chiudi_vendite_evento", {"evento_id": 12}, "ok")]


# ------------------------------------------------------------ richieste e flusso

def test_richiesta_di_lettura_arriva_alla_pagina(avvia):
    s = avvia([risposta(tool=[("cerca_eventi", {"titolo": "cabaret"})]), risposta("Si tiene a Cagliari.")])
    assert s.richiesta("POST", "/api/messaggio", {"testo": "dove e' il cabaret?"})[0] == 202

    eventi = s.eventi_fino_a(ha_arresto)
    assert [e["tipo"] for e in eventi] == ["richiesta_utente", "chiamata_modello", "tool", "chiamata_modello", "arresto"]
    assert eventi[2]["tool"] == "cerca_eventi" and eventi[2]["esito"] == "ok"
    assert "nuovi_messaggi" not in eventi[1]  # i messaggi completi restano solo nel file di log
    assert eventi[-1]["risposta"] == "Si tiene a Cagliari." and eventi[-1]["motivo"] == "risposta_finale"


def test_chi_si_collega_dopo_riceve_la_cronologia(avvia):
    s = avvia([risposta("Ciao.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "ciao"})
    s.eventi_fino_a(ha_arresto)
    # Una seconda pagina (o un ricaricamento) rivede tutto dall'inizio.
    di_nuovo = s.eventi_fino_a(ha_arresto)
    assert di_nuovo[0]["tipo"] == "richiesta_utente" and di_nuovo[-1]["risposta"] == "Ciao."


def test_richieste_non_valide(avvia):
    s = avvia([])
    assert s.richiesta("POST", "/api/messaggio", {"testo": "   "})[0] == 400
    assert s.richiesta("POST", "/api/messaggio", {"testo": "x" * 2001})[0] == 400
    assert s.richiesta("POST", "/api/messaggio", {"altro": 1})[0] == 400
    assert s.richiesta("POST", "/api/conferma", {"id": "inesistente", "approva": True})[0] == 404
    assert s.richiesta("POST", "/api/conferma", {"id": "x", "approva": "si"})[0] == 400


# ---------------------------------------------------------------- conferma umana

def test_scrittura_approvata_dalla_pagina(avvia):
    s = avvia([risposta(tool=[("chiudi_vendite_evento", {"evento_id": 12})]), risposta("Vendite chiuse.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "chiudi le vendite dell'evento 12"})

    eventi = s.eventi_fino_a(lambda ev: any(e["tipo"] == "richiesta_conferma" for e in ev))
    richiesta = next(e for e in eventi if e["tipo"] == "richiesta_conferma")
    assert richiesta["tool"] == "chiudi_vendite_evento" and richiesta["argomenti"] == {"evento_id": 12}
    assert "«Serata Cabaret»" in richiesta["riepilogo"]  # la scheda dice di quale evento si tratta, non solo l'id
    assert stato_evento(s.db, 12) == "in_vendita"  # finche' l'operatore non conferma, nulla cambia

    assert s.richiesta("POST", "/api/conferma", {"id": richiesta["id"], "approva": True})[0] == 200
    finali = s.eventi_fino_a(ha_arresto)
    assert any(e["tipo"] == "conferma_risolta" and e["approvata"] for e in finali)
    assert finali[-1]["motivo"] == "risposta_finale"
    assert stato_evento(s.db, 12) == "vendite_chiuse"


def test_scrittura_rifiutata_dalla_pagina(avvia):
    s = avvia([risposta(tool=[("annulla_evento", {"evento_id": 12})]), risposta("Non annullo nulla.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "annulla l'evento 12"})
    eventi = s.eventi_fino_a(lambda ev: any(e["tipo"] == "richiesta_conferma" for e in ev))
    id_conferma = next(e for e in eventi if e["tipo"] == "richiesta_conferma")["id"]

    s.richiesta("POST", "/api/conferma", {"id": id_conferma, "approva": False})
    finali = s.eventi_fino_a(ha_arresto)
    assert finali[-1]["motivo"] == "conferma_negata" and finali[-1]["conferme_negate"] == 1
    assert stato_evento(s.db, 12) == "in_vendita"


def test_una_sola_richiesta_alla_volta(avvia):
    s = avvia([risposta(tool=[("chiudi_vendite_evento", {"evento_id": 12})]), risposta("Fatto.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "chiudi le vendite dell'evento 12"})
    eventi = s.eventi_fino_a(lambda ev: any(e["tipo"] == "richiesta_conferma" for e in ev))

    codice, errore = s.richiesta("POST", "/api/messaggio", {"testo": "altra richiesta"})
    assert codice == 409 and "elaborando" in errore["errore"]
    assert s.richiesta("POST", "/api/nuova", {})[0] == 409
    assert s.richiesta("GET", "/api/stato")[1]["occupato"] is True

    id_conferma = next(e for e in eventi if e["tipo"] == "richiesta_conferma")["id"]
    s.richiesta("POST", "/api/conferma", {"id": id_conferma, "approva": False})
    s.eventi_fino_a(ha_arresto)


def test_nuova_chat_azzera_la_cronologia(avvia):
    s = avvia([risposta("Prima."), risposta("Dopo.")])
    s.richiesta("POST", "/api/messaggio", {"testo": "uno"})
    s.eventi_fino_a(ha_arresto)
    assert s.richiesta("POST", "/api/nuova", {})[0] == 200

    s.richiesta("POST", "/api/messaggio", {"testo": "due"})
    eventi = s.eventi_fino_a(ha_arresto)
    assert [e["tipo"] for e in eventi][0] == "nuova_chat"
    assert [e["testo"] for e in eventi if e["tipo"] == "richiesta_utente"] == ["due"]
    # La conversazione dell'agente e' ripartita da zero: il modello non ha visto "uno".
    assert all(m.contenuto != "uno" for m in s.provider.chiamate[-1])


def test_la_conferma_scaduta_e_considerata_negata():
    async def prova():
        bus = Bus()
        conferma = ConfermaWeb(bus, timeout=0.05)
        approvata = await conferma.chiedi(RichiestaConferma("annulla_evento", "x", {"evento_id": 1}))
        return approvata, bus.storico

    approvata, storico = asyncio.run(prova())
    assert approvata is False
    assert storico[-1]["tipo"] == "conferma_risolta" and storico[-1]["motivo"] == "scaduta"


# ------------------------------------------------------------------- sicurezza

def test_protezioni_contro_siti_esterni(avvia):
    s = avvia([])
    # Host non locale (DNS rebinding)
    assert s.richiesta("GET", "/api/stato", intestazioni={"Host": "evil.example"})[0] == 403
    # Origine di un altro sito (CSRF): e' quello che impedirebbe a un'altra pagina di premere Conferma
    corpo = {"id": "x", "approva": True}
    assert s.richiesta("POST", "/api/conferma", corpo, {"Origin": "https://evil.example"})[0] == 403
    # POST che non e' JSON (la forma che un form di un altro sito potrebbe inviare)
    conn = http.client.HTTPConnection("127.0.0.1", s.porta, timeout=10)
    conn.request("POST", "/api/conferma", body="id=x&approva=true",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert conn.getresponse().status == 415
    conn.close()
    # La stessa origine e' ammessa
    origine = f"http://127.0.0.1:{s.porta}"
    assert s.richiesta("POST", "/api/conferma", corpo, {"Origin": origine})[0] == 404  # arriva alla logica: nessuna conferma in attesa
