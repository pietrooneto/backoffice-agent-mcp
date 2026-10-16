"""Test dell'anteprima delle azioni: stesse regole delle scritture, nessun effetto sui dati."""
import pytest

from backend.repository import (
    FuoriTermine,
    NonTrovato,
    ParametroNonValido,
    StatoNonValido,
    anteprima_azione,
    annulla_evento,
    chiudi_vendite_evento,
    rimborsa_ordine,
)


def stato_db(conn):
    """Fotografia dei dati che le scritture potrebbero toccare."""
    return (
        [tuple(r) for r in conn.execute("SELECT id, stato FROM eventi ORDER BY id")],
        tuple(conn.execute("SELECT COUNT(*), SUM(stato = 'pagato') FROM ordini").fetchone()),
        conn.execute("SELECT COUNT(*) FROM rimborsi").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
    )


def un_ordine_pagato(conn, evento_id):
    return conn.execute(
        """SELECT o.id FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = ? AND o.stato = 'pagato' ORDER BY o.id LIMIT 1""",
        (evento_id,),
    ).fetchone()["id"]


# ---------------------------------------------------------------- descrizioni

def test_anteprima_chiusura_descrive_l_evento(conn, adesso):
    testo = anteprima_azione(conn, "chiudi_vendite_evento", {"evento_id": 12}, adesso)
    assert "«Serata Cabaret»" in testo and "Cagliari" in testo and "25/11/2026 21:00" in testo
    assert "Venduti 59 biglietti su 140" in testo


def test_anteprima_annullamento_riporta_ordini_e_importo(conn, adesso):
    testo = anteprima_azione(conn, "annulla_evento", {"evento_id": 12}, adesso)
    assert "«Serata Cabaret»" in testo
    assert "26 ordini pagati (59 biglietti)" in testo and "1.402,00 euro" in testo


def test_anteprima_rimborso_nomina_cliente_ed_evento(conn, adesso):
    testo = anteprima_azione(conn, "rimborsa_ordine", {"ordine_id": 596}, adesso)
    assert "Davide Greco" in testo and "«Balletto del Lago»" in testo and "84,00 euro" in testo


# ------------------------------------------------- le regole sono quelle delle scritture

@pytest.mark.parametrize("evento_id, errore", [(5, StatoNonValido), (6, StatoNonValido), (8, StatoNonValido), (999, NonTrovato)])
def test_anteprima_chiusura_rifiuta_come_la_scrittura(conn, adesso, evento_id, errore):
    with pytest.raises(errore):
        anteprima_azione(conn, "chiudi_vendite_evento", {"evento_id": evento_id}, adesso)
    with pytest.raises(errore):
        chiudi_vendite_evento(conn, evento_id, adesso)


@pytest.mark.parametrize("evento_id, errore", [(8, StatoNonValido), (11, StatoNonValido), (999, NonTrovato)])
def test_anteprima_annullamento_rifiuta_come_la_scrittura(conn, adesso, evento_id, errore):
    with pytest.raises(errore):
        anteprima_azione(conn, "annulla_evento", {"evento_id": evento_id}, adesso)
    with pytest.raises(errore):
        annulla_evento(conn, evento_id, adesso)


def test_anteprima_rimborso_fuori_termine_come_la_scrittura(conn, adesso):
    ordine = un_ordine_pagato(conn, 7)  # l'evento 7 inizia fra circa 33 ore
    with pytest.raises(FuoriTermine, match="48 ore"):
        anteprima_azione(conn, "rimborsa_ordine", {"ordine_id": ordine}, adesso)
    with pytest.raises(FuoriTermine):
        rimborsa_ordine(conn, ordine, "richiesta del cliente", adesso)


def test_anteprima_rimborso_ordine_gia_rimborsato(conn, adesso):
    ordine = un_ordine_pagato(conn, 1)
    rimborsa_ordine(conn, ordine, "richiesta del cliente", adesso)
    with pytest.raises(StatoNonValido, match="rimborsato"):
        anteprima_azione(conn, "rimborsa_ordine", {"ordine_id": ordine}, adesso)


def test_anteprima_ordine_inesistente(conn, adesso):
    with pytest.raises(NonTrovato):
        anteprima_azione(conn, "rimborsa_ordine", {"ordine_id": 999999}, adesso)


@pytest.mark.parametrize("parametri", [{}, {"evento_id": 0}, {"evento_id": "12"}, {"evento_id": True}])
def test_anteprima_parametri_non_validi(conn, adesso, parametri):
    with pytest.raises(ParametroNonValido):
        anteprima_azione(conn, "chiudi_vendite_evento", parametri, adesso)


def test_anteprima_azione_sconosciuta(conn, adesso):
    with pytest.raises(ParametroNonValido, match="sconosciuta"):
        anteprima_azione(conn, "cancella_tutto", {}, adesso)


# --------------------------------------------------------------- nessun effetto

def test_l_anteprima_non_modifica_nulla(conn, adesso):
    prima = stato_db(conn)
    anteprima_azione(conn, "chiudi_vendite_evento", {"evento_id": 12}, adesso)
    anteprima_azione(conn, "annulla_evento", {"evento_id": 12}, adesso)
    anteprima_azione(conn, "rimborsa_ordine", {"ordine_id": 596}, adesso)
    assert stato_db(conn) == prima
