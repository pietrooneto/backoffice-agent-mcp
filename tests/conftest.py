import shutil
import sqlite3

import pytest

from backend import seed
from backend.repository import connetti


@pytest.fixture(scope="session")
def db_modello(tmp_path_factory):
    """Database sintetico generato una sola volta con il seed (riproducibile)."""
    percorso = tmp_path_factory.mktemp("db") / "modello.db"
    conn = sqlite3.connect(percorso)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(seed.SCHEMA.read_text(encoding="utf-8"))
    seed.popola(conn)
    conn.close()
    return percorso


@pytest.fixture
def conn(db_modello, tmp_path):
    """Copia fresca del database per ogni test: le scritture non si influenzano."""
    copia = tmp_path / "test.db"
    shutil.copy(db_modello, copia)
    connessione = connetti(copia)
    yield connessione
    connessione.close()


@pytest.fixture
def adesso():
    """Data di riferimento del seed (2026-11-01 12:00)."""
    return seed.ADESSO
