"""Test del server MCP: schemi, validazione, errori, effetti sui dati, e prova end-to-end via stdio."""
import asyncio
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.contesto import contesto
from mcp_server.server import crea_server
from mcp_server.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
LETTURE = {"cerca_eventi", "dettaglio_evento", "storico_acquisti_cliente", "stato_ordine"}
SCRITTURE = {"chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine"}
SERVIZIO = {"anteprima_azione"}  # usato solo dall'harness, nascosto al modello


@pytest.fixture
def server(conn, adesso):
    """Server con il database di test e l'ora di riferimento del seed."""
    contesto.configura(conn=conn, adesso=adesso)
    yield crea_server()
    contesto.configura(conn=None, adesso=None)


def chiama(server, tool, /, **argomenti):
    return asyncio.run(server.call_tool(tool, argomenti))


def dati(risultato):
    """Contenuto strutturato di una chiamata riuscita."""
    assert not risultato.is_error
    return risultato.structured_content


# ---------- catalogo dei tool ----------

def test_sette_tool_per_il_modello_piu_uno_di_servizio(server):
    nomi = {t.name for t in asyncio.run(server.list_tools())}
    assert nomi == LETTURE | SCRITTURE | SERVIZIO


def test_metadati_di_scrittura_per_la_conferma_umana(server):
    """L'harness decide se chiedere conferma leggendo readOnlyHint."""
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    for nome in LETTURE:
        assert tools[nome].annotations.read_only_hint is True
    for nome in SCRITTURE:
        assert tools[nome].annotations.read_only_hint is False
    assert tools["annulla_evento"].annotations.destructive_hint is True
    assert tools["chiudi_vendite_evento"].annotations.destructive_hint is False


def test_ogni_tool_ha_descrizione_e_schemi(server):
    for t in asyncio.run(server.list_tools()):
        assert len(t.description) > 40
        assert t.input_schema["type"] == "object"
        assert t.output_schema is not None
        for nome, proprieta in t.input_schema["properties"].items():
            assert proprieta.get("description"), f"{t.name}.{nome} senza descrizione"


def test_moduli_e_registro_coerenti():
    assert [m.NOME for m in TOOLS] == [
        "cerca_eventi", "dettaglio_evento", "storico_acquisti_cliente", "stato_ordine",
        "chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine",
    ]


# ---------- letture ----------

def test_cerca_eventi_omonimi(server):
    risultato = dati(chiama(server, "cerca_eventi", titolo="notte elettrica"))
    assert risultato["totale"] == 2
    assert {e["luogo"] for e in risultato["eventi"]} == {"Milano, Arena Nord", "Roma, Palasport Sud"}


def test_dettaglio_evento(server):
    risultato = dati(chiama(server, "dettaglio_evento", evento_id=9))
    assert risultato["capienza_totale"] == 60
    assert risultato["venduti_totali"] + risultato["disponibili_totali"] == 60


def test_storico_per_nome_univoco(server, conn):
    univoco = conn.execute(
        """SELECT c.nome, c.cognome FROM clienti c JOIN ordini o ON o.cliente_id = c.id
           GROUP BY c.id HAVING (SELECT COUNT(*) FROM clienti x WHERE x.nome = c.nome AND x.cognome = c.cognome) = 1
           ORDER BY COUNT(*) DESC LIMIT 1"""
    ).fetchone()
    risultato = dati(chiama(server, "storico_acquisti_cliente", nome=univoco["nome"], cognome=univoco["cognome"]))
    assert risultato["cliente"]["cognome"] == univoco["cognome"]
    assert len(risultato["ultimi_ordini"]) <= 10


def test_storico_omonimi_chiede_chiarimento(server):
    with pytest.raises(ToolError, match="id 1.*id 2.*cliente_id"):
        chiama(server, "storico_acquisti_cliente", nome="Marco", cognome="Rossi")


def test_storico_omonimi_risolto_con_cliente_id(server):
    risultato = dati(chiama(server, "storico_acquisti_cliente", cliente_id=2))
    assert risultato["cliente"]["email"] == "marco.rossi2@example.com"


def test_storico_cliente_inesistente(server):
    with pytest.raises(ToolError, match="Nessun cliente"):
        chiama(server, "storico_acquisti_cliente", nome="Zzz", cognome="Inesistente")


def test_storico_senza_criteri(server):
    with pytest.raises(ToolError, match="nome e cognome"):
        chiama(server, "storico_acquisti_cliente")


# ---------- parametri non validi ----------

@pytest.mark.parametrize(
    "nome, argomenti",
    [
        ("dettaglio_evento", {"evento_id": 0}),
        ("dettaglio_evento", {"evento_id": "abc"}),
        ("dettaglio_evento", {}),
        ("cerca_eventi", {"stato": "chiuso"}),
        ("rimborsa_ordine", {"ordine_id": 1, "motivo": ""}),
    ],
)
def test_parametri_non_validi_sono_errori_del_tool(server, nome, argomenti):
    with pytest.raises(ToolError):
        chiama(server, nome, **argomenti)


def test_tool_inesistente(server):
    with pytest.raises(ToolError):
        chiama(server, "cancella_tutto")


# ---------- scritture ----------

def test_chiudi_vendite_modifica_i_dati(server, conn):
    risultato = dati(chiama(server, "chiudi_vendite_evento", evento_id=12))
    assert risultato["stato_nuovo"] == "vendite_chiuse"
    assert conn.execute("SELECT stato FROM eventi WHERE id = 12").fetchone()["stato"] == "vendite_chiuse"


def test_chiudi_vendite_evento_gia_chiuso_e_errore_leggibile(server):
    with pytest.raises(ToolError, match="gia' le vendite chiuse"):
        chiama(server, "chiudi_vendite_evento", evento_id=5)


def test_annulla_evento_gia_annullato(server):
    with pytest.raises(ToolError, match="gia' annullato"):
        chiama(server, "annulla_evento", evento_id=8)


def test_rimborso_fuori_termine(server, conn):
    ordine = conn.execute(
        """SELECT o.id FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 7 AND o.stato = 'pagato' LIMIT 1"""
    ).fetchone()["id"]
    with pytest.raises(ToolError, match="48 ore"):
        chiama(server, "rimborsa_ordine", ordine_id=ordine)


def test_rimborso_con_motivo_predefinito(server, conn):
    ordine = conn.execute(
        """SELECT o.id FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 1 AND o.stato = 'pagato' LIMIT 1"""
    ).fetchone()["id"]
    risultato = dati(chiama(server, "rimborsa_ordine", ordine_id=ordine))
    assert risultato["motivo"] == "richiesta del cliente"
    assert risultato["stato_ordine"] == "rimborsato"


# ---------- anteprima (tool di servizio) ----------

def test_anteprima_ammessa_e_vietata_sono_risultati_non_errori(server):
    ok = dati(chiama(server, "anteprima_azione", tool="annulla_evento", parametri={"evento_id": 12}))
    assert ok["ammessa"] is True and "26 ordini pagati" in ok["riepilogo"] and ok["motivo"] is None

    vietata = dati(chiama(server, "anteprima_azione", tool="annulla_evento", parametri={"evento_id": 8}))
    assert vietata["ammessa"] is False and "gia' annullato" in vietata["motivo"]


def test_anteprima_non_modifica_i_dati(server, conn):
    chiama(server, "anteprima_azione", tool="chiudi_vendite_evento", parametri={"evento_id": 12})
    assert conn.execute("SELECT stato FROM eventi WHERE id = 12").fetchone()["stato"] == "in_vendita"
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_anteprima_solo_per_i_tool_di_scrittura(server):
    with pytest.raises(ToolError):
        chiama(server, "anteprima_azione", tool="cerca_eventi", parametri={})


# ---------- guasti simulati ----------

def test_guasto_simulato_su_un_tool(server, monkeypatch):
    monkeypatch.setenv("SIMULA_GUASTO", "dettaglio_evento")
    with pytest.raises(ToolError, match="Errore temporaneo del database"):
        chiama(server, "dettaglio_evento", evento_id=1)
    # gli altri tool continuano a funzionare
    assert dati(chiama(server, "cerca_eventi"))["totale"] == 12


def test_guasto_simulato_su_scrittura_non_modifica_i_dati(server, conn, monkeypatch):
    monkeypatch.setenv("SIMULA_GUASTO", "chiudi_vendite_evento")
    with pytest.raises(ToolError, match="NON e' stata eseguita"):
        chiama(server, "chiudi_vendite_evento", evento_id=12)
    assert conn.execute("SELECT stato FROM eventi WHERE id = 12").fetchone()["stato"] == "in_vendita"


# ---------- end-to-end via stdio (come fara' l'harness) ----------

def test_end_to_end_via_stdio(db_modello, tmp_path):
    """Avvia il server come processo figlio e lo usa con un vero client MCP."""
    import shutil

    copia = tmp_path / "e2e.db"
    shutil.copy(db_modello, copia)
    parametri = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        cwd=str(ROOT),
        env={"DB_PATH": str(copia), "SIMULA_GUASTO": "stato_ordine", "PYTHONPATH": str(ROOT)},
    )

    async def scenario():
        async with stdio_client(parametri) as (lettura, scrittura):
            async with ClientSession(lettura, scrittura) as sessione:
                await sessione.initialize()
                elenco = await sessione.list_tools()
                nomi = {t.name for t in elenco.tools}

                ok = await sessione.call_tool("cerca_eventi", {"titolo": "cabaret"})
                parametri_errati = await sessione.call_tool("dettaglio_evento", {"evento_id": 0})
                guasto = await sessione.call_tool("stato_ordine", {"ordine_id": 1})
                return elenco, nomi, ok, parametri_errati, guasto

    elenco, nomi, ok, parametri_errati, guasto = asyncio.run(scenario())

    assert nomi == LETTURE | SCRITTURE | SERVIZIO
    scritture = {t.name for t in elenco.tools if t.annotations.read_only_hint is False}
    assert scritture == SCRITTURE

    assert not ok.is_error
    assert ok.structured_content["eventi"][0]["titolo"] == "Serata Cabaret"
    assert parametri_errati.is_error
    assert guasto.is_error
    assert "Errore temporaneo del database" in guasto.content[0].text
