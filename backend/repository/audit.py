"""Registro di audit delle scritture, nella stessa transazione dell'operazione."""
import json
import sqlite3
from datetime import datetime

from .db import a_testo


def scrivi_audit(
    conn: sqlite3.Connection,
    tool: str,
    parametri: dict,
    adesso: datetime,
    esito: str = "ok",
    ruolo: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (quando, ruolo, tool, parametri_json, esito) VALUES (?,?,?,?,?)",
        (a_testo(adesso), ruolo, tool, json.dumps(parametri, ensure_ascii=False), esito),
    )
