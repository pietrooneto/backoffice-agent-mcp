"""Accesso ai dati degli eventi: ricerca, dettaglio, chiusura vendite, annullamento."""
import sqlite3
from datetime import datetime

from .audit import scrivi_audit
from .db import da_testo, transazione
from .errors import NonTrovato, ParametroNonValido, StatoNonValido
from .ordini import applica_rimborso

STATI_EVENTO = ("bozza", "in_vendita", "vendite_chiuse", "annullato")

_DESCRIZIONE_STATO = {
    "bozza": "e' ancora in bozza",
    "in_vendita": "e' in vendita",
    "vendite_chiuse": "ha gia' le vendite chiuse",
    "annullato": "e' annullato",
}


def _leggi_evento(conn: sqlite3.Connection, evento_id: int) -> sqlite3.Row:
    evento = conn.execute(
        "SELECT id, titolo, luogo, data_evento, stato FROM eventi WHERE id = ?", (evento_id,)
    ).fetchone()
    if evento is None:
        raise NonTrovato(f"Nessun evento con id {evento_id}.")
    return evento


def verifica_chiudibile(evento: sqlite3.Row) -> None:
    """Regola della chiusura vendite (condivisa da scrittura e anteprima): solo eventi in vendita."""
    if evento["stato"] != "in_vendita":
        raise StatoNonValido(
            f"L'evento {evento['id']} ('{evento['titolo']}') {_DESCRIZIONE_STATO[evento['stato']]}: "
            "si possono chiudere solo le vendite di eventi in vendita."
        )


def verifica_annullabile(evento: sqlite3.Row, adesso: datetime) -> None:
    """Regole dell'annullamento (condivise da scrittura e anteprima): non gia' annullato, non gia' svolto."""
    if evento["stato"] == "annullato":
        raise StatoNonValido(f"L'evento {evento['id']} ('{evento['titolo']}') e' gia' annullato.")
    if da_testo(evento["data_evento"]) <= adesso:
        raise StatoNonValido(
            f"L'evento {evento['id']} ('{evento['titolo']}') si e' gia' svolto: non si puo' annullare."
        )


def cerca_eventi(
    conn: sqlite3.Connection, titolo: str | None = None, stato: str | None = None
) -> list[dict]:
    """Eventi il cui titolo contiene `titolo` (senza distinguere maiuscole), filtrabili per stato."""
    condizioni, valori = [], []
    if titolo and titolo.strip():
        pezzo = titolo.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        condizioni.append("titolo LIKE ? ESCAPE '\\'")
        valori.append(f"%{pezzo}%")
    if stato:
        if stato not in STATI_EVENTO:
            raise ParametroNonValido(
                f"Stato '{stato}' non valido. Valori ammessi: {', '.join(STATI_EVENTO)}."
            )
        condizioni.append("stato = ?")
        valori.append(stato)

    where = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    righe = conn.execute(
        f"SELECT id, titolo, luogo, data_evento, stato FROM eventi {where} ORDER BY data_evento, id",
        valori,
    ).fetchall()
    return [dict(r) for r in righe]


def dettaglio_evento(conn: sqlite3.Connection, evento_id: int) -> dict:
    """Evento con capienza, venduti e disponibili, per settore e in totale.

    Contano come venduti solo i biglietti degli ordini pagati.
    """
    evento = _leggi_evento(conn, evento_id)
    settori = conn.execute(
        """SELECT s.id AS settore_id, s.nome, s.capienza, s.prezzo_centesimi,
                  COALESCE(SUM(CASE WHEN o.stato = 'pagato' THEN o.quantita END), 0) AS venduti
           FROM settori s LEFT JOIN ordini o ON o.settore_id = s.id
           WHERE s.evento_id = ?
           GROUP BY s.id ORDER BY s.id""",
        (evento_id,),
    ).fetchall()

    elenco = []
    for s in settori:
        riga = dict(s)
        riga["disponibili"] = riga["capienza"] - riga["venduti"]
        elenco.append(riga)

    risultato = dict(evento)
    risultato["settori"] = elenco
    risultato["capienza_totale"] = sum(s["capienza"] for s in elenco)
    risultato["venduti_totali"] = sum(s["venduti"] for s in elenco)
    risultato["disponibili_totali"] = risultato["capienza_totale"] - risultato["venduti_totali"]
    return risultato


def chiudi_vendite_evento(conn: sqlite3.Connection, evento_id: int, adesso: datetime) -> dict:
    """Chiude le vendite di un evento in vendita. Non rimborsa nulla ed e' reversibile."""
    with transazione(conn):
        evento = _leggi_evento(conn, evento_id)
        verifica_chiudibile(evento)
        conn.execute("UPDATE eventi SET stato = 'vendite_chiuse' WHERE id = ?", (evento_id,))
        scrivi_audit(conn, "chiudi_vendite_evento", {"evento_id": evento_id}, adesso)

    return {
        "evento_id": evento_id,
        "titolo": evento["titolo"],
        "stato_precedente": "in_vendita",
        "stato_nuovo": "vendite_chiuse",
    }


def annulla_evento(conn: sqlite3.Connection, evento_id: int, adesso: datetime) -> dict:
    """Annulla un evento e rimborsa a cascata tutti gli ordini pagati. Alto impatto.

    Non e' possibile annullare un evento gia' annullato o gia' svolto.
    """
    with transazione(conn):
        evento = _leggi_evento(conn, evento_id)
        verifica_annullabile(evento, adesso)

        ordini = conn.execute(
            """SELECT o.id, o.totale_centesimi, o.quantita
               FROM ordini o JOIN settori s ON s.id = o.settore_id
               WHERE s.evento_id = ? AND o.stato = 'pagato'
               ORDER BY o.id""",
            (evento_id,),
        ).fetchall()
        for ordine in ordini:
            applica_rimborso(conn, ordine["id"], ordine["totale_centesimi"], "evento annullato", adesso)

        conn.execute("UPDATE eventi SET stato = 'annullato' WHERE id = ?", (evento_id,))
        scrivi_audit(conn, "annulla_evento", {"evento_id": evento_id}, adesso)

    return {
        "evento_id": evento_id,
        "titolo": evento["titolo"],
        "stato_precedente": evento["stato"],
        "stato_nuovo": "annullato",
        "ordini_rimborsati": len(ordini),
        "biglietti_rimborsati": sum(o["quantita"] for o in ordini),
        "totale_rimborsato_centesimi": sum(o["totale_centesimi"] for o in ordini),
    }
