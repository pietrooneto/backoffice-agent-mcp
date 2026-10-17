"""Genera docs/tools.md dal codice del server MCP.

Nomi, descrizioni, schemi dei parametri e di uscita vengono letti dai tool veri; gli esempi sono chiamate
reali eseguite sul database sintetico (una copia nuova per ogni esempio).

Uso (dalla cartella del progetto):  python docs/genera_tools.py
"""
import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import seed  # noqa: E402
from backend.repository import connetti  # noqa: E402
from mcp_server.contesto import contesto  # noqa: E402
from mcp_server.server import crea_server  # noqa: E402

ORDINE = ["cerca_eventi", "dettaglio_evento", "storico_acquisti_cliente", "stato_ordine",
          "chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine", "anteprima_azione"]

ESEMPI = {
    "cerca_eventi": {"titolo": "cabaret"},
    "dettaglio_evento": {"evento_id": 12},
    "storico_acquisti_cliente": {"nome": "Daniele", "cognome": "Esposito"},
    "stato_ordine": {"ordine_id": 596},
    "chiudi_vendite_evento": {"evento_id": 12},
    "annulla_evento": {"evento_id": 12},
    "rimborsa_ordine": {"ordine_id": 596, "motivo": "richiesta del cliente"},
    "anteprima_azione": {"tool": "annulla_evento", "parametri": {"evento_id": 12}},
}

# Effetti sui dati: scritti a mano perche' descrivono le tabelle toccate (e sono verificati dai test).
EFFETTI = {
    "cerca_eventi": "Nessuno: sola lettura.",
    "dettaglio_evento": "Nessuno: sola lettura.",
    "storico_acquisti_cliente": "Nessuno: sola lettura.",
    "stato_ordine": "Nessuno: sola lettura.",
    "chiudi_vendite_evento": "`eventi.stato` passa da `in_vendita` a `vendite_chiuse`; una riga in `audit_log`. Gli ordini restano validi e non si rimborsa nulla. Reversibile in pratica.",
    "annulla_evento": "`eventi.stato` passa ad `annullato`; per ogni ordine pagato dell'evento `ordini.stato` e `biglietti.stato` passano a `rimborsato` e si inserisce una riga in `rimborsi` (motivo «evento annullato»); una riga in `audit_log`. Tutto in una sola transazione: o riesce per intero o non cambia nulla. Alto impatto.",
    "rimborsa_ordine": "`ordini.stato` e `biglietti.stato` dell'ordine passano a `rimborsato`; una riga in `rimborsi` per l'intero importo; una riga in `audit_log`. Consentito solo fino a 48 ore prima dell'evento.",
    "anteprima_azione": "Nessuno: sola lettura. Tool di servizio per l'harness, nascosto al modello.",
}

TIPO = {
    "cerca_eventi": "lettura", "dettaglio_evento": "lettura", "storico_acquisti_cliente": "lettura",
    "stato_ordine": "lettura", "chiudi_vendite_evento": "scrittura", "annulla_evento": "scrittura (alto impatto)",
    "rimborsa_ordine": "scrittura", "anteprima_azione": "servizio per l'harness",
}


def tipo_di(proprieta: dict) -> str:
    if "enum" in proprieta:
        return " / ".join(f"`{v}`" for v in proprieta["enum"])
    if "anyOf" in proprieta:
        return " oppure ".join(tipo_di(p) for p in proprieta["anyOf"] if p.get("type") != "null")
    t = proprieta.get("type", "oggetto")
    vincoli = []
    for chiave, etichetta in (("minimum", "min"), ("maximum", "max"), ("minLength", "lunghezza min"), ("maxLength", "lunghezza max")):
        if chiave in proprieta:
            vincoli.append(f"{etichetta} {proprieta[chiave]}")
    return t + (f" ({', '.join(vincoli)})" if vincoli else "")


def tabella_parametri(schema: dict) -> str:
    props, obbligatori = schema.get("properties", {}), set(schema.get("required", []))
    righe = ["| Parametro | Tipo | Obbligatorio | Descrizione |", "|---|---|---|---|"]
    for nome, p in props.items():
        pred = f" Predefinito: `{p['default']}`." if "default" in p and p["default"] is not None else ""
        righe.append(f"| `{nome}` | {tipo_di(p)} | {'sì' if nome in obbligatori else 'no'} | {p.get('description', '')}{pred} |")
    return "\n".join(righe)


def campi_uscita(schema: dict) -> str:
    defs = schema.get("$defs", {})

    def descrivi(p: dict) -> str:
        if "$ref" in p:
            d = defs[p["$ref"].split("/")[-1]]
            return "oggetto (" + ", ".join(d.get("properties", {})) + ")"
        if p.get("type") == "array":
            return "elenco di " + descrivi(p.get("items", {}))
        if "anyOf" in p:
            return " oppure ".join(descrivi(x) for x in p["anyOf"] if x.get("type") != "null")
        if p.get("type") == "object" and "additionalProperties" in p:
            return "dizionario nome → numero"
        return p.get("type", "valore")

    return "\n".join(f"- `{n}`: {descrivi(p)}" for n, p in schema.get("properties", {}).items())


def abbrevia(valore, n=2):
    """Riduce gli elenchi lunghi ai primi n elementi, per tenere leggibili gli esempi."""
    if isinstance(valore, list):
        taglia = [abbrevia(v, n) for v in valore[:n]]
        return taglia + (["…"] if len(valore) > n else [])
    if isinstance(valore, dict):
        return {k: abbrevia(v, n) for k, v in valore.items()}
    return valore


async def esegui_esempi() -> dict:
    cartella = Path(tempfile.mkdtemp(prefix="esempi_tool_"))
    modello = cartella / "modello.db"
    conn = sqlite3.connect(modello)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(seed.SCHEMA.read_text(encoding="utf-8"))
    seed.popola(conn)
    conn.close()

    server = crea_server()
    risultati = {}
    for nome in ORDINE:
        copia = cartella / f"{nome}.db"
        shutil.copy(modello, copia)
        contesto.configura(conn=connetti(copia), adesso=seed.ADESSO)
        try:
            risposta = await server.call_tool(nome, ESEMPI[nome])
            risultati[nome] = risposta.structured_content
        finally:
            contesto.configura(conn=None, adesso=None)
    shutil.rmtree(cartella, ignore_errors=True)
    return risultati


async def principale() -> str:
    server = crea_server()
    tool = {t.name: t for t in await server.list_tools()}
    esempi = await esegui_esempi()

    parti = [
        "# Documentazione dei tool del server MCP",
        "",
        "Generata da `docs/genera_tools.py` leggendo i tool veri del server e, per gli esempi, eseguendo chiamate reali sul "
        "database sintetico (una copia nuova per ogni esempio, data di riferimento 2026-11-01 12:00). Nei risultati di esempio "
        "gli elenchi lunghi sono ridotti ai primi due elementi (`…`).",
        "",
        "Il server espone **otto tool**: sette per il modello (quattro di lettura e tre di scrittura) e uno di servizio, "
        "`anteprima_azione`, che usa solo l'harness e che non viene mai mostrato al modello. I tool di scrittura sono "
        "riconosciuti dall'harness dal metadato standard MCP `readOnlyHint = false` e richiedono sempre la conferma "
        "dell'operatore. Gli errori previsti (non trovato, stato non valido, fuori termine, parametri non validi, richiesta "
        "ambigua) tornano al modello come risultato di errore (`is_error`) con un messaggio in italiano.",
        "",
    ]
    for nome in ORDINE:
        t = tool[nome]
        a = t.annotations
        parti += [
            f"## `{nome}`",
            "",
            f"**Tipo:** {TIPO[nome]} · **readOnlyHint:** {a.read_only_hint}"
            + (f" · **destructiveHint:** {a.destructive_hint}" if a.destructive_hint is not None else ""),
            "",
            f"**Descrizione:** {t.description}",
            "",
            "**Parametri di ingresso**",
            "",
            tabella_parametri(t.input_schema),
            "",
            "**Risultato (campi)**",
            "",
            campi_uscita(t.output_schema),
            "",
            f"**Effetti sui dati:** {EFFETTI[nome]}",
            "",
            "**Esempio di invocazione**",
            "",
            "```json",
            json.dumps({"tool": nome, "parametri": ESEMPI[nome]}, ensure_ascii=False, indent=2),
            "```",
            "",
            "Risultato:",
            "",
            "```json",
            json.dumps(abbrevia(esempi[nome]), ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    return "\n".join(parti)


if __name__ == "__main__":
    testo = asyncio.run(principale())
    (ROOT / "docs" / "tools.md").write_text(testo, encoding="utf-8")
    print(f"docs/tools.md scritto: {len(testo.split())} parole")
