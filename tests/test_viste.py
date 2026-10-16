"""Test delle viste di sola lettura del pannello informativo."""
import sqlite3

import pytest

from backend.repository import (
    chiudi_vendite_evento,
    connetti_sola_lettura,
    dettaglio_evento,
    rimborsa_ordine,
)
from backend.repository.viste import elenco_eventi, movimenti_recenti, registro_modifiche


def test_elenco_eventi_coerente_con_il_dettaglio(conn):
    eventi = elenco_eventi(conn)
    assert len(eventi) == 12
    assert [e["data_evento"] for e in eventi] == sorted(e["data_evento"] for e in eventi)
    for e in eventi:
        dettaglio = dettaglio_evento(conn, e["id"])
        assert (e["capienza"], e["venduti"]) == (dettaglio["capienza_totale"], dettaglio["venduti_totali"])
    assert next(e for e in eventi if e["id"] == 6)["venduti"] == 0  # la bozza non ha vendite


def test_movimenti_misti_e_ordinati_dal_piu_recente(conn):
    movimenti = movimenti_recenti(conn, limite=40)
    assert len(movimenti) == 40
    assert {m["tipo"] for m in movimenti} == {"acquisto", "rimborso"}
    quando = [m["quando"] for m in movimenti]
    assert quando == sorted(quando, reverse=True)
    assert movimenti_recenti(conn, limite=5).__len__() == 5


def test_un_rimborso_compare_in_cima_ai_movimenti(conn, adesso):
    ordine = conn.execute(
        """SELECT o.id FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 1 AND o.stato = 'pagato' LIMIT 1"""
    ).fetchone()["id"]
    rimborsa_ordine(conn, ordine, "richiesta del cliente", adesso)
    primo = movimenti_recenti(conn, limite=1)[0]
    assert (primo["tipo"], primo["ordine_id"], primo["nota"]) == ("rimborso", ordine, "richiesta del cliente")


def test_registro_modifiche_parte_vuoto_e_registra_le_scritture(conn, adesso):
    assert registro_modifiche(conn) == []
    chiudi_vendite_evento(conn, 12, adesso)
    voce = registro_modifiche(conn)[0]
    assert (voce["tool"], voce["parametri"], voce["esito"]) == ("chiudi_vendite_evento", {"evento_id": 12}, "ok")


def test_la_connessione_di_sola_lettura_non_puo_scrivere(db_modello):
    conn = connetti_sola_lettura(db_modello)
    try:
        assert conn.execute("SELECT COUNT(*) FROM eventi").fetchone()[0] == 12
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE eventi SET stato = 'annullato'")
    finally:
        conn.close()


def test_connessione_di_sola_lettura_con_spazi_nel_percorso(db_modello, tmp_path):
    """Il progetto sta in una cartella con spazi: il percorso va codificato correttamente."""
    import shutil

    cartella = tmp_path / "cartella con spazi"
    cartella.mkdir()
    copia = cartella / "db.sqlite"
    shutil.copy(db_modello, copia)
    conn = connetti_sola_lettura(copia)
    assert conn.execute("SELECT COUNT(*) FROM clienti").fetchone()[0] == 60
    conn.close()
