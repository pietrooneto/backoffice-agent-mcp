"""Stato condiviso dei tool: connessione al database, ora di riferimento, guasti simulati."""
import os
import sqlite3
from datetime import datetime

from backend.repository import connetti
from backend.repository.db import da_testo
from backend.seed import ADESSO as ORA_PREDEFINITA


class Contesto:
    """Fornisce ai tool la connessione e l'"ora attuale".

    Variabili d'ambiente (lette a ogni uso):
    - DB_PATH: percorso del database (vedi backend.repository.db).
    - RIFERIMENTO_ORA: "reale" per l'ora di sistema, oppure una data "AAAA-MM-GG HH:MM:SS".
      Se assente si usa la data fissa del seed, cosi' gli scenari sono ripetibili.
    - SIMULA_GUASTO: nomi di tool separati da virgola che devono fallire come un guasto del
      database (per gli scenari di errore).
    """

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._adesso: datetime | None = None

    def configura(self, conn: sqlite3.Connection | None = None, adesso: datetime | None = None) -> None:
        """Sostituisce connessione e/o ora (usato dai test)."""
        self._conn, self._adesso = conn, adesso

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connetti()
        return self._conn

    def adesso(self) -> datetime:
        if self._adesso is not None:
            return self._adesso
        valore = os.environ.get("RIFERIMENTO_ORA", "").strip()
        if valore.lower() == "reale":
            return datetime.now().replace(microsecond=0)
        return da_testo(valore) if valore else ORA_PREDEFINITA

    def guasto_simulato(self, tool: str) -> bool:
        elenco = os.environ.get("SIMULA_GUASTO", "")
        return tool in {voce.strip() for voce in elenco.split(",") if voce.strip()}


contesto = Contesto()
