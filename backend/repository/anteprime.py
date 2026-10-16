"""Anteprima delle azioni di scrittura: controlla le regole e descrive l'effetto SENZA modificare nulla.

Serve all'harness prima di chiedere la conferma all'operatore: se una regola vieta l'azione l'operatore non
viene disturbato, e se e' ammessa la conferma mostra che cosa succedera' davvero (nomi, numeri, importi) e
non soltanto un id. Le regole sono le stesse funzioni usate dalle scritture, quindi non possono divergere.
"""
import sqlite3
from datetime import datetime

from .errors import ParametroNonValido
from .eventi import _leggi_evento, dettaglio_evento, verifica_annullabile, verifica_chiudibile
from .ordini import stato_ordine, verifica_rimborsabile

AZIONI = ("chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine")


def _euro(centesimi: int) -> str:
    testo = f"{centesimi / 100:,.2f}"  # 1,402.00
    return testo.replace(",", "X").replace(".", ",").replace("X", ".") + " euro"


def _data(valore: str) -> str:
    giorno, ora = valore[:16].split(" ")
    anno, mese, g = giorno.split("-")
    return f"{g}/{mese}/{anno} {ora}"


def _intero(parametri: dict, nome: str) -> int:
    valore = parametri.get(nome)
    if isinstance(valore, bool) or not isinstance(valore, int) or valore < 1:
        raise ParametroNonValido(f"Il parametro {nome} deve essere un intero positivo.")
    return valore


def anteprima_azione(conn: sqlite3.Connection, tool: str, parametri: dict, adesso: datetime) -> str:
    """Restituisce una descrizione dell'effetto dell'azione, oppure solleva l'errore di dominio che la vieta."""
    if tool == "chiudi_vendite_evento":
        evento = _leggi_evento(conn, _intero(parametri, "evento_id"))
        verifica_chiudibile(evento)
        dettaglio = dettaglio_evento(conn, evento["id"])
        return (
            f"Chiudere le vendite dell'evento «{evento['titolo']}» ({evento['luogo']}, {_data(evento['data_evento'])}). "
            f"Venduti {dettaglio['venduti_totali']} biglietti su {dettaglio['capienza_totale']}; "
            "gli ordini esistenti restano validi e non viene rimborsato nulla."
        )

    if tool == "annulla_evento":
        evento = _leggi_evento(conn, _intero(parametri, "evento_id"))
        verifica_annullabile(evento, adesso)
        riga = conn.execute(
            """SELECT COUNT(*) AS ordini, COALESCE(SUM(o.quantita), 0) AS biglietti,
                      COALESCE(SUM(o.totale_centesimi), 0) AS totale
               FROM ordini o JOIN settori s ON s.id = o.settore_id
               WHERE s.evento_id = ? AND o.stato = 'pagato'""",
            (evento["id"],),
        ).fetchone()
        return (
            f"Annullare l'evento «{evento['titolo']}» ({evento['luogo']}, {_data(evento['data_evento'])}) e "
            f"rimborsare per intero {riga['ordini']} ordini pagati ({riga['biglietti']} biglietti), "
            f"in totale {_euro(riga['totale'])}."
        )

    if tool == "rimborsa_ordine":
        ordine_id = _intero(parametri, "ordine_id")
        ordine = stato_ordine(conn, ordine_id)
        verifica_rimborsabile(ordine_id, ordine["stato"], ordine["data_evento"], adesso)
        return (
            f"Rimborsare per intero l'ordine {ordine_id} di {ordine['cliente_nome']} {ordine['cliente_cognome']}: "
            f"{ordine['quantita']} biglietti per «{ordine['evento_titolo']}» ({_data(ordine['data_evento'])}), "
            f"{_euro(ordine['totale_centesimi'])}."
        )

    raise ParametroNonValido(f"Azione sconosciuta: {tool}. Azioni previste: {', '.join(AZIONI)}.")
