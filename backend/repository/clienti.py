"""Accesso ai dati dei clienti (solo lettura)."""
import sqlite3

from .errors import NonTrovato, ParametroNonValido


def trova_clienti(
    conn: sqlite3.Connection, nome: str | None = None, cognome: str | None = None
) -> list[dict]:
    """Clienti con nome e/o cognome uguali (senza distinguere maiuscole).

    Puo' restituire piu' righe: gli omonimi vanno distinti dal chiamante.
    """
    nome = (nome or "").strip()
    cognome = (cognome or "").strip()
    if not nome and not cognome:
        raise ParametroNonValido("Indica almeno il nome o il cognome del cliente.")

    condizioni, valori = [], []
    if nome:
        condizioni.append("nome = ? COLLATE NOCASE")
        valori.append(nome)
    if cognome:
        condizioni.append("cognome = ? COLLATE NOCASE")
        valori.append(cognome)
    righe = conn.execute(
        f"SELECT id, nome, cognome, email FROM clienti WHERE {' AND '.join(condizioni)} ORDER BY id",
        valori,
    ).fetchall()
    return [dict(r) for r in righe]


def storico_cliente(conn: sqlite3.Connection, cliente_id: int, limite: int = 10) -> dict:
    """Riepilogo degli acquisti di un cliente e i suoi ultimi `limite` ordini.

    L'elenco e' limitato di proposito: ogni riga costa token al modello.
    Il riepilogo invece e' calcolato su tutti gli ordini.
    """
    cliente = conn.execute(
        "SELECT id, nome, cognome, email FROM clienti WHERE id = ?", (cliente_id,)
    ).fetchone()
    if cliente is None:
        raise NonTrovato(f"Nessun cliente con id {cliente_id}.")

    riepilogo = conn.execute(
        """SELECT COUNT(*)                                              AS ordini_totali,
                  COALESCE(SUM(o.stato = 'pagato'), 0)                  AS ordini_pagati,
                  COUNT(DISTINCT CASE WHEN o.stato = 'pagato' THEN s.evento_id END)
                                                                        AS eventi_acquistati,
                  COALESCE(SUM(CASE WHEN o.stato = 'pagato' THEN o.quantita END), 0)
                                                                        AS biglietti_validi,
                  COALESCE(SUM(CASE WHEN o.stato = 'pagato' THEN o.totale_centesimi END), 0)
                                                                        AS speso_centesimi
           FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE o.cliente_id = ?""",
        (cliente_id,),
    ).fetchone()

    ordini = conn.execute(
        """SELECT o.id AS ordine_id, e.id AS evento_id, e.titolo AS evento_titolo,
                  e.data_evento, s.nome AS settore, o.quantita, o.totale_centesimi,
                  o.stato, o.creato_il
           FROM ordini o
           JOIN settori s ON s.id = o.settore_id
           JOIN eventi e ON e.id = s.evento_id
           WHERE o.cliente_id = ?
           ORDER BY o.creato_il DESC, o.id DESC
           LIMIT ?""",
        (cliente_id, limite),
    ).fetchall()

    return {
        "cliente": dict(cliente),
        "riepilogo": dict(riepilogo),
        "ultimi_ordini": [dict(r) for r in ordini],
        "ordini_mostrati": len(ordini),
    }
