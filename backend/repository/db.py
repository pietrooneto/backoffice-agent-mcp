"""Connessione al database e gestione delle transazioni."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"


def percorso_db() -> Path:
    """Percorso del database: variabile DB_PATH oppure backend/ticketing.db."""
    percorso = Path(os.environ.get("DB_PATH", "backend/ticketing.db"))
    return percorso if percorso.is_absolute() else ROOT / percorso


def connetti(percorso: str | Path | None = None) -> sqlite3.Connection:
    """Apre una connessione con righe accessibili per nome e chiavi esterne attive.

    isolation_level=None: le transazioni sono gestite esplicitamente da transazione().
    check_same_thread=False: il server MCP esegue i tool in thread diversi; l'accesso e'
    comunque serializzato da un lucchetto (vedi mcp_server.errori), quindi e' sicuro.
    """
    conn = sqlite3.connect(percorso or percorso_db(), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connetti_sola_lettura(percorso: str | Path | None = None) -> sqlite3.Connection:
    """Connessione che non puo' scrivere (mode=ro), per le viste informative dell'interfaccia."""
    percorso = Path(percorso or percorso_db()).resolve()
    conn = sqlite3.connect(f"{percorso.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transazione(conn: sqlite3.Connection):
    """Transazione tutto-o-niente: BEGIN IMMEDIATE, poi COMMIT o ROLLBACK.

    BEGIN IMMEDIATE blocca subito le altre scritture, cosi' i controlli di stato
    fatti dentro la transazione restano validi fino al commit.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def da_testo(valore: str) -> datetime:
    return datetime.strptime(valore, FORMATO_DATA)


def a_testo(valore: datetime) -> str:
    return valore.strftime(FORMATO_DATA)
