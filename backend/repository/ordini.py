"""Accesso ai dati degli ordini e rimborsi."""
import sqlite3
from datetime import datetime

from .audit import scrivi_audit
from .db import a_testo, da_testo, transazione
from .errors import FuoriTermine, NonTrovato, ParametroNonValido, StatoNonValido

# Il rimborso di un singolo ordine e' consentito fino a questo anticipo sull'evento.
TERMINE_RIMBORSO_ORE = 48


def stato_ordine(conn: sqlite3.Connection, ordine_id: int) -> dict:
    """Dettaglio di un ordine: cliente, evento, importi, biglietti e rimborsi."""
    ordine = conn.execute(
        """SELECT o.id AS ordine_id, o.stato, o.quantita, o.totale_centesimi, o.creato_il,
                  c.id AS cliente_id, c.nome AS cliente_nome, c.cognome AS cliente_cognome,
                  e.id AS evento_id, e.titolo AS evento_titolo, e.data_evento,
                  e.stato AS evento_stato, s.nome AS settore
           FROM ordini o
           JOIN clienti c ON c.id = o.cliente_id
           JOIN settori s ON s.id = o.settore_id
           JOIN eventi e ON e.id = s.evento_id
           WHERE o.id = ?""",
        (ordine_id,),
    ).fetchone()
    if ordine is None:
        raise NonTrovato(f"Nessun ordine con id {ordine_id}.")

    biglietti = conn.execute(
        "SELECT stato, COUNT(*) AS n FROM biglietti WHERE ordine_id = ? GROUP BY stato",
        (ordine_id,),
    ).fetchall()
    rimborsi = conn.execute(
        "SELECT importo_centesimi, motivo, creato_il FROM rimborsi WHERE ordine_id = ? ORDER BY id",
        (ordine_id,),
    ).fetchall()

    risultato = dict(ordine)
    risultato["biglietti"] = {r["stato"]: r["n"] for r in biglietti}
    risultato["rimborsi"] = [dict(r) for r in rimborsi]
    return risultato


def applica_rimborso(
    conn: sqlite3.Connection, ordine_id: int, importo_centesimi: int, motivo: str, adesso: datetime
) -> None:
    """Segna ordine e biglietti come rimborsati e registra il rimborso.

    Va chiamata dentro una transazione aperta dal chiamante.
    """
    conn.execute("UPDATE ordini SET stato = 'rimborsato' WHERE id = ?", (ordine_id,))
    conn.execute("UPDATE biglietti SET stato = 'rimborsato' WHERE ordine_id = ?", (ordine_id,))
    conn.execute(
        "INSERT INTO rimborsi (ordine_id, importo_centesimi, motivo, creato_il) VALUES (?,?,?,?)",
        (ordine_id, importo_centesimi, motivo, a_testo(adesso)),
    )


def rimborsa_ordine(
    conn: sqlite3.Connection, ordine_id: int, motivo: str, adesso: datetime
) -> dict:
    """Rimborso totale di un ordine pagato, entro il termine consentito.

    Il pagamento e' solo simulato: non c'e' nessuna integrazione con circuiti reali.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ParametroNonValido("Il motivo del rimborso non puo' essere vuoto.")

    with transazione(conn):
        riga = conn.execute(
            """SELECT o.stato, o.totale_centesimi, e.id AS evento_id, e.titolo, e.data_evento
               FROM ordini o
               JOIN settori s ON s.id = o.settore_id
               JOIN eventi e ON e.id = s.evento_id
               WHERE o.id = ?""",
            (ordine_id,),
        ).fetchone()
        if riga is None:
            raise NonTrovato(f"Nessun ordine con id {ordine_id}.")
        if riga["stato"] != "pagato":
            raise StatoNonValido(
                f"L'ordine {ordine_id} e' gia' nello stato '{riga['stato']}': "
                "si possono rimborsare solo ordini pagati."
            )

        ore_mancanti = (da_testo(riga["data_evento"]) - adesso).total_seconds() / 3600
        if ore_mancanti < TERMINE_RIMBORSO_ORE:
            if ore_mancanti <= 0:
                dettaglio = "l'evento si e' gia' svolto"
            else:
                dettaglio = f"all'evento mancano circa {ore_mancanti:.0f} ore"
            raise FuoriTermine(
                f"Rimborso non consentito: {dettaglio}, ma il rimborso e' possibile "
                f"solo fino a {TERMINE_RIMBORSO_ORE} ore prima dell'evento."
            )

        applica_rimborso(conn, ordine_id, riga["totale_centesimi"], motivo, adesso)
        scrivi_audit(conn, "rimborsa_ordine", {"ordine_id": ordine_id, "motivo": motivo}, adesso)

    return {
        "ordine_id": ordine_id,
        "evento_titolo": riga["titolo"],
        "importo_rimborsato_centesimi": riga["totale_centesimi"],
        "motivo": motivo,
        "stato_ordine": "rimborsato",
    }
