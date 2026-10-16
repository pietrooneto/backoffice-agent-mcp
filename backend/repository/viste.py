"""Viste di sola lettura per il pannello informativo dell'interfaccia web.

Non fanno parte dei tool dell'agente: servono all'operatore per controllare i dati e vedere
l'effetto delle modifiche. Le modifiche, invece, passano solo dall'agente (tool + conferma).
"""
import json
import sqlite3


def elenco_eventi(conn: sqlite3.Connection) -> list[dict]:
    """Tutti gli eventi con biglietti venduti (ordini pagati) e capienza totale."""
    righe = conn.execute(
        """SELECT e.id, e.titolo, e.luogo, e.data_evento, e.stato,
                  (SELECT COALESCE(SUM(capienza), 0) FROM settori WHERE evento_id = e.id) AS capienza,
                  (SELECT COALESCE(SUM(o.quantita), 0)
                   FROM ordini o JOIN settori s ON s.id = o.settore_id
                   WHERE s.evento_id = e.id AND o.stato = 'pagato') AS venduti
           FROM eventi e ORDER BY e.data_evento, e.id"""
    ).fetchall()
    return [dict(r) for r in righe]


def movimenti_recenti(conn: sqlite3.Connection, limite: int = 40) -> list[dict]:
    """Acquisti e rimborsi piu' recenti, mescolati per data."""
    righe = conn.execute(
        """SELECT tipo, quando, ordine_id, cliente, evento, importo_centesimi, nota FROM (
               SELECT 'acquisto' AS tipo, o.creato_il AS quando, o.id AS ordine_id,
                      c.nome || ' ' || c.cognome AS cliente, e.titolo AS evento,
                      o.totale_centesimi AS importo_centesimi,
                      o.quantita || ' biglietti · ' || o.stato AS nota, o.id AS seq
               FROM ordini o
               JOIN clienti c ON c.id = o.cliente_id
               JOIN settori s ON s.id = o.settore_id
               JOIN eventi e ON e.id = s.evento_id
               UNION ALL
               SELECT 'rimborso', r.creato_il, r.ordine_id,
                      c.nome || ' ' || c.cognome, e.titolo, r.importo_centesimi, r.motivo, r.id
               FROM rimborsi r
               JOIN ordini o ON o.id = r.ordine_id
               JOIN clienti c ON c.id = o.cliente_id
               JOIN settori s ON s.id = o.settore_id
               JOIN eventi e ON e.id = s.evento_id
           ) ORDER BY quando DESC, seq DESC LIMIT ?""",  # a parita' di istante vince l'ultimo inserito
        (limite,),
    ).fetchall()
    return [dict(r) for r in righe]


def registro_modifiche(conn: sqlite3.Connection, limite: int = 50) -> list[dict]:
    """Le ultime scritture registrate nell'audit, dalla piu' recente."""
    righe = conn.execute(
        "SELECT id, quando, ruolo, tool, parametri_json, esito FROM audit_log ORDER BY id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    risultato = []
    for r in righe:
        voce = dict(r)
        voce["parametri"] = json.loads(voce.pop("parametri_json"))
        risultato.append(voce)
    return risultato
