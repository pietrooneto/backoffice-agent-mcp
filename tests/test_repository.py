"""Test del livello di accesso ai dati sul database sintetico del seed.

Gli id degli eventi sono quelli del seed: 1 e 2 omonimi, 5 vendite chiuse, 6 bozza,
7 inizia entro 48 ore, 8 e 11 annullati, 9 quasi esaurito, 12 in vendita.
"""
import json
from datetime import timedelta

import pytest

from backend.repository import (
    FuoriTermine,
    NonTrovato,
    ParametroNonValido,
    StatoNonValido,
    annulla_evento,
    cerca_eventi,
    chiudi_vendite_evento,
    dettaglio_evento,
    rimborsa_ordine,
    stato_ordine,
    storico_cliente,
    trova_clienti,
)
from backend.repository import eventi as modulo_eventi


def un_ordine_pagato(conn, evento_id):
    return conn.execute(
        """SELECT o.id FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = ? AND o.stato = 'pagato' ORDER BY o.id LIMIT 1""",
        (evento_id,),
    ).fetchone()["id"]


def ordini_pagati(conn, evento_id):
    return conn.execute(
        """SELECT COUNT(*) AS n, COALESCE(SUM(o.totale_centesimi), 0) AS tot
           FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = ? AND o.stato = 'pagato'""",
        (evento_id,),
    ).fetchone()


def righe_audit(conn):
    return conn.execute("SELECT tool, parametri_json, esito FROM audit_log").fetchall()


# ---------- eventi: letture ----------

def test_cerca_eventi_omonimi(conn):
    risultati = cerca_eventi(conn, titolo="notte elettrica")
    assert [e["id"] for e in risultati] == [1, 2]
    assert {e["luogo"] for e in risultati} == {"Milano, Arena Nord", "Roma, Palasport Sud"}


def test_cerca_eventi_per_stato(conn):
    annullati = cerca_eventi(conn, stato="annullato")
    assert [e["id"] for e in annullati] == [8, 11]  # ordinati per data


def test_cerca_eventi_stato_non_valido(conn):
    with pytest.raises(ParametroNonValido):
        cerca_eventi(conn, stato="chiuso")


def test_cerca_eventi_nessun_risultato(conn):
    assert cerca_eventi(conn, titolo="titolo inesistente") == []


def test_cerca_eventi_caratteri_speciali_non_sono_jolly(conn):
    assert cerca_eventi(conn, titolo="%") == []


def test_dettaglio_evento_quadra_con_il_database(conn):
    dettaglio = dettaglio_evento(conn, 9)
    assert dettaglio["capienza_totale"] == 60
    assert dettaglio["venduti_totali"] + dettaglio["disponibili_totali"] == 60
    assert dettaglio["disponibili_totali"] >= 0
    attesi = conn.execute(
        """SELECT SUM(o.quantita) AS n FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 9 AND o.stato = 'pagato'"""
    ).fetchone()["n"]
    assert dettaglio["venduti_totali"] == attesi
    assert len(dettaglio["settori"]) == 2


def test_dettaglio_evento_bozza_senza_vendite(conn):
    assert dettaglio_evento(conn, 6)["venduti_totali"] == 0


def test_dettaglio_evento_inesistente(conn):
    with pytest.raises(NonTrovato):
        dettaglio_evento(conn, 999)


# ---------- chiudi vendite ----------

def test_chiudi_vendite_ok(conn, adesso):
    esito = chiudi_vendite_evento(conn, 12, adesso)
    assert esito["stato_nuovo"] == "vendite_chiuse"
    assert dettaglio_evento(conn, 12)["stato"] == "vendite_chiuse"
    audit = righe_audit(conn)
    assert len(audit) == 1 and audit[0]["tool"] == "chiudi_vendite_evento"
    assert json.loads(audit[0]["parametri_json"]) == {"evento_id": 12}


def test_chiudi_vendite_non_tocca_gli_ordini(conn, adesso):
    prima = ordini_pagati(conn, 12)
    chiudi_vendite_evento(conn, 12, adesso)
    assert tuple(ordini_pagati(conn, 12)) == tuple(prima)


@pytest.mark.parametrize("evento_id", [5, 6, 8])
def test_chiudi_vendite_stato_non_valido(conn, adesso, evento_id):
    with pytest.raises(StatoNonValido):
        chiudi_vendite_evento(conn, evento_id, adesso)
    assert righe_audit(conn) == []


def test_chiudi_vendite_due_volte(conn, adesso):
    chiudi_vendite_evento(conn, 12, adesso)
    with pytest.raises(StatoNonValido, match="gia' le vendite chiuse"):
        chiudi_vendite_evento(conn, 12, adesso)


def test_chiudi_vendite_evento_inesistente(conn, adesso):
    with pytest.raises(NonTrovato):
        chiudi_vendite_evento(conn, 999, adesso)


# ---------- annulla evento ----------

def test_annulla_evento_rimborsa_a_cascata(conn, adesso):
    prima = ordini_pagati(conn, 12)
    assert prima["n"] > 0
    esito = annulla_evento(conn, 12, adesso)

    assert esito["stato_nuovo"] == "annullato"
    assert esito["ordini_rimborsati"] == prima["n"]
    assert esito["totale_rimborsato_centesimi"] == prima["tot"]
    assert ordini_pagati(conn, 12)["n"] == 0
    assert dettaglio_evento(conn, 12)["venduti_totali"] == 0

    validi = conn.execute(
        """SELECT COUNT(*) AS n FROM biglietti b
           JOIN ordini o ON o.id = b.ordine_id JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 12 AND b.stato = 'valido'"""
    ).fetchone()["n"]
    assert validi == 0
    rimborsi = conn.execute(
        """SELECT COUNT(*) AS n FROM rimborsi r
           JOIN ordini o ON o.id = r.ordine_id JOIN settori s ON s.id = o.settore_id
           WHERE s.evento_id = 12 AND r.motivo = 'evento annullato' AND r.creato_il = ?""",
        (adesso.strftime("%Y-%m-%d %H:%M:%S"),),
    ).fetchone()["n"]
    assert rimborsi == prima["n"]
    assert righe_audit(conn)[0]["tool"] == "annulla_evento"


def test_annulla_evento_gia_annullato(conn, adesso):
    with pytest.raises(StatoNonValido, match="gia' annullato"):
        annulla_evento(conn, 8, adesso)


def test_annulla_evento_gia_svolto(conn, adesso):
    conn.execute("UPDATE eventi SET data_evento = '2026-10-01 20:00:00' WHERE id = 12")
    with pytest.raises(StatoNonValido, match="gia' svolto"):
        annulla_evento(conn, 12, adesso)


def test_annulla_evento_e_atomico(conn, adesso, monkeypatch):
    """Se qualcosa fallisce a meta', non resta nessun rimborso parziale."""
    prima = ordini_pagati(conn, 12)

    def fallisce(*args, **kwargs):
        raise RuntimeError("guasto simulato")

    monkeypatch.setattr(modulo_eventi, "scrivi_audit", fallisce)
    with pytest.raises(RuntimeError):
        annulla_evento(conn, 12, adesso)

    assert tuple(ordini_pagati(conn, 12)) == tuple(prima)
    assert dettaglio_evento(conn, 12)["stato"] == "in_vendita"


# ---------- rimborso singolo ordine ----------

def test_rimborsa_ordine_ok(conn, adesso):
    ordine_id = un_ordine_pagato(conn, 1)
    esito = rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)
    assert esito["stato_ordine"] == "rimborsato"

    dettaglio = stato_ordine(conn, ordine_id)
    assert dettaglio["stato"] == "rimborsato"
    assert dettaglio["biglietti"] == {"rimborsato": dettaglio["quantita"]}
    assert dettaglio["rimborsi"][-1]["importo_centesimi"] == dettaglio["totale_centesimi"]
    assert righe_audit(conn)[0]["tool"] == "rimborsa_ordine"


def test_rimborsa_ordine_due_volte(conn, adesso):
    ordine_id = un_ordine_pagato(conn, 1)
    rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)
    with pytest.raises(StatoNonValido):
        rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)


def test_rimborsa_ordine_fuori_termine(conn, adesso):
    ordine_id = un_ordine_pagato(conn, 7)  # l'evento inizia fra circa 33 ore
    with pytest.raises(FuoriTermine, match="48 ore"):
        rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)
    assert stato_ordine(conn, ordine_id)["stato"] == "pagato"
    assert righe_audit(conn) == []


def test_rimborsa_ordine_al_limite_del_termine(conn, adesso):
    ordine_id = un_ordine_pagato(conn, 1)
    conn.execute(
        "UPDATE eventi SET data_evento = ? WHERE id = 1",
        ((adesso + timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    assert rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)["stato_ordine"] == "rimborsato"


def test_rimborsa_ordine_evento_gia_svolto(conn, adesso):
    ordine_id = un_ordine_pagato(conn, 1)
    conn.execute("UPDATE eventi SET data_evento = '2026-10-01 20:00:00' WHERE id = 1")
    with pytest.raises(FuoriTermine, match="gia' svolto"):
        rimborsa_ordine(conn, ordine_id, "richiesta del cliente", adesso)


def test_rimborsa_ordine_motivo_vuoto(conn, adesso):
    with pytest.raises(ParametroNonValido):
        rimborsa_ordine(conn, un_ordine_pagato(conn, 1), "   ", adesso)


def test_rimborsa_ordine_inesistente(conn, adesso):
    with pytest.raises(NonTrovato):
        rimborsa_ordine(conn, 999999, "richiesta del cliente", adesso)


def test_stato_ordine_inesistente(conn):
    with pytest.raises(NonTrovato):
        stato_ordine(conn, 999999)


# ---------- clienti ----------

def test_trova_clienti_omonimi(conn):
    risultati = trova_clienti(conn, nome="Marco", cognome="Rossi")
    assert [c["email"] for c in risultati] == ["marco.rossi@example.com", "marco.rossi2@example.com"]


def test_trova_clienti_senza_distinguere_maiuscole(conn):
    assert len(trova_clienti(conn, nome="marco", cognome="ROSSI")) == 2


def test_trova_clienti_inesistente(conn):
    assert trova_clienti(conn, nome="Zzz", cognome="Inesistente") == []


def test_trova_clienti_senza_criteri(conn):
    with pytest.raises(ParametroNonValido):
        trova_clienti(conn, nome="  ", cognome=None)


def test_storico_cliente_riepilogo_coerente(conn):
    cliente_id = conn.execute(
        "SELECT cliente_id FROM ordini GROUP BY cliente_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()["cliente_id"]
    storico = storico_cliente(conn, cliente_id, limite=3)

    attesi = conn.execute(
        """SELECT COUNT(*) AS n, COUNT(DISTINCT s.evento_id) AS eventi
           FROM ordini o JOIN settori s ON s.id = o.settore_id
           WHERE o.cliente_id = ? AND o.stato = 'pagato'""",
        (cliente_id,),
    ).fetchone()
    assert storico["riepilogo"]["ordini_pagati"] == attesi["n"]
    assert storico["riepilogo"]["eventi_acquistati"] == attesi["eventi"]
    assert storico["riepilogo"]["ordini_totali"] > 3
    assert len(storico["ultimi_ordini"]) == storico["ordini_mostrati"] == 3


def test_storico_cliente_senza_ordini(conn):
    ultimo = conn.execute("SELECT MAX(id) AS id FROM clienti").fetchone()["id"]
    storico = storico_cliente(conn, ultimo)
    assert storico["riepilogo"]["ordini_totali"] == 0
    assert storico["riepilogo"]["speso_centesimi"] == 0
    assert storico["ultimi_ordini"] == []


def test_storico_cliente_inesistente(conn):
    with pytest.raises(NonTrovato):
        storico_cliente(conn, 999999)
