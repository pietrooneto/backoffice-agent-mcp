"""Generazione del database con dati interamente sintetici e riproducibili.

Uso:  python backend/seed.py [percorso_db]
Il percorso predefinito e' la variabile DB_PATH oppure backend/ticketing.db.
Il database viene ricreato da zero a ogni esecuzione.
"""
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
# Data di riferimento fissa: gli scenari di test non dipendono dalla data odierna.
ADESSO = datetime(2026, 11, 1, 12, 0)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = Path(__file__).resolve().parent / "schema.sql"

NOMI = [
    "Luca", "Giulia", "Marco", "Sara", "Andrea", "Chiara", "Matteo", "Elena",
    "Davide", "Francesca", "Simone", "Martina", "Paolo", "Alessia", "Stefano",
    "Valentina", "Giorgio", "Federica", "Nicola", "Laura", "Fabio", "Silvia",
    "Roberto", "Elisa", "Daniele", "Irene", "Claudio", "Monica", "Enrico", "Anna",
]
COGNOMI = [
    "Rossi", "Bianchi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci",
    "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Giordano",
    "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Fontana", "Santoro",
    "Mariani", "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini", "Leone", "Longo",
]

# (titolo, luogo, data, stato, [(settore, capienza, prezzo_centesimi)], riempimento)
# Il riempimento e' la frazione di capienza venduta (None = nessuna vendita).
EVENTI = [
    ("Notte Elettrica Festival", "Milano, Arena Nord", "2026-12-12 21:00", "in_vendita",
     [("Parterre", 300, 4500), ("Tribuna", 200, 6500)], 0.55),
    ("Notte Elettrica Festival", "Roma, Palasport Sud", "2027-01-23 21:00", "in_vendita",
     [("Parterre", 250, 4800), ("Tribuna", 150, 7000)], 0.30),
    ("Concerto di Capodanno", "Torino, Teatro Civico", "2026-12-31 20:30", "in_vendita",
     [("Platea", 180, 5500), ("Galleria", 120, 3500)], 0.70),
    ("Il Misantropo", "Napoli, Teatro del Porto", "2026-11-20 20:45", "in_vendita",
     [("Platea", 100, 3000), ("Palchi", 40, 4000)], 0.60),
    ("Coppa dei Borghi - Finale", "Bologna, Stadio Comunale", "2026-11-28 15:00", "vendite_chiuse",
     [("Curva", 400, 1500), ("Tribuna", 200, 3500)], 0.90),
    ("Recital di Primavera", "Firenze, Sala dei Giardini", "2027-03-14 18:00", "bozza",
     [("Unico", 150, 2500)], None),
    ("Stand-up Night", "Genova, Teatro Piccolo", "2026-11-02 21:00", "in_vendita",
     [("Platea", 80, 2200), ("Balconata", 40, 1800)], 0.75),
    ("Jazz sotto le Stelle", "Palermo, Arena Aperta", "2026-09-20 21:00", "annullato",
     [("Prato", 200, 2000), ("Poltrone", 80, 3500)], 0.50),
    ("Rassegna Rock Club", "Bari, Rock Club", "2026-12-05 22:00", "in_vendita",
     [("Platea", 40, 2800), ("Gradinata", 20, 2000)], 0.97),
    ("Balletto del Lago", "Como, Teatro Lariano", "2027-02-10 20:30", "in_vendita",
     [("Platea", 120, 4200), ("Galleria", 60, 2800)], 0.20),
    ("Festival della Birra Artigianale", "Padova, Fiera Vecchia", "2026-11-14 12:00", "annullato",
     [("Ingresso", 500, 1200), ("Ingresso VIP", 50, 4500)], 0.40),
    ("Serata Cabaret", "Cagliari, Teatro Mediterraneo", "2026-11-25 21:00", "in_vendita",
     [("Platea", 90, 2600), ("Balconata", 50, 2000)], 0.45),
]


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def crea_clienti(rng: random.Random):
    clienti = []
    # Due omonimi voluti (stesso nome e cognome, email diverse): caso di test.
    clienti.append(("Marco", "Rossi", "marco.rossi@example.com"))
    clienti.append(("Marco", "Rossi", "marco.rossi2@example.com"))
    combinazioni = [(n, c) for n in NOMI for c in COGNOMI if (n, c) != ("Marco", "Rossi")]
    rng.shuffle(combinazioni)
    for nome, cognome in combinazioni[:58]:
        email = f"{nome}.{cognome}".lower().replace(" ", "") + "@example.com"
        clienti.append((nome, cognome, email))
    return clienti


def popola(conn: sqlite3.Connection) -> None:
    rng = random.Random(SEED)
    cur = conn.cursor()

    clienti = crea_clienti(rng)
    for nome, cognome, email in clienti:
        creato = ADESSO - timedelta(days=rng.randint(60, 700))
        cur.execute(
            "INSERT INTO clienti (nome, cognome, email, creato_il) VALUES (?,?,?,?)",
            (nome, cognome, email, fmt(creato)),
        )
    n_clienti = len(clienti)
    # L'ultimo cliente non ha mai acquistato: caso di test "nessun ordine".
    ids_attivi = list(range(1, n_clienti))
    # Pesi: pochi clienti molto attivi, molti occasionali.
    pesi = [rng.choice([1, 1, 1, 2, 3, 6]) for _ in ids_attivi]

    contatore_biglietti = 0
    for titolo, luogo, data, stato, settori, riempimento in EVENTI:
        data_evento = datetime.strptime(data, "%Y-%m-%d %H:%M")
        creato = min(data_evento, ADESSO) - timedelta(days=rng.randint(90, 150))
        cur.execute(
            "INSERT INTO eventi (titolo, luogo, data_evento, stato, creato_il) VALUES (?,?,?,?,?)",
            (titolo, luogo, fmt(data_evento), stato, fmt(creato)),
        )
        evento_id = cur.lastrowid
        n_rimborsi_evento = 0

        for nome_settore, capienza, prezzo in settori:
            cur.execute(
                "INSERT INTO settori (evento_id, nome, capienza, prezzo_centesimi) VALUES (?,?,?,?)",
                (evento_id, nome_settore, capienza, prezzo),
            )
            settore_id = cur.lastrowid
            if riempimento is None:
                continue

            da_vendere = round(capienza * riempimento)
            venduti = 0
            while venduti < da_vendere:
                quantita = min(rng.randint(1, 4), da_vendere - venduti)
                cliente_id = rng.choices(ids_attivi, weights=pesi)[0]
                totale = quantita * prezzo
                quando = min(ADESSO, data_evento) - timedelta(
                    days=rng.randint(1, 60), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
                )
                if stato == "annullato":
                    stato_ordine = "rimborsato"
                elif rng.random() < 0.05:
                    stato_ordine = "rimborsato"  # rimborso richiesto dal cliente
                else:
                    stato_ordine = "pagato"
                cur.execute(
                    "INSERT INTO ordini (cliente_id, settore_id, quantita, totale_centesimi, stato, creato_il)"
                    " VALUES (?,?,?,?,?,?)",
                    (cliente_id, settore_id, quantita, totale, stato_ordine, fmt(quando)),
                )
                ordine_id = cur.lastrowid
                stato_biglietto = "valido" if stato_ordine == "pagato" else "rimborsato"
                for _ in range(quantita):
                    contatore_biglietti += 1
                    cur.execute(
                        "INSERT INTO biglietti (ordine_id, codice, stato) VALUES (?,?,?)",
                        (ordine_id, f"TKT-{contatore_biglietti:06d}", stato_biglietto),
                    )
                if stato_ordine == "rimborsato":
                    n_rimborsi_evento += 1
                    if stato == "annullato":
                        motivo = "evento annullato"
                        # Annullamento 3 giorni prima di "adesso" (o dell'evento); i rimborsi si susseguono
                        # di minuto in minuto, ma mai prima dell'acquisto.
                        base = min(ADESSO, data_evento) - timedelta(days=3)
                        rimborsato_il = max(base + timedelta(minutes=n_rimborsi_evento), quando + timedelta(minutes=5))
                    else:
                        motivo = "richiesta del cliente"
                        rimborsato_il = quando + timedelta(hours=2 + (ordine_id * 7) % 70)
                    # Calcolo deterministico (nessun numero casuale in piu': i dati restano gli stessi) e mai
                    # nell'ultima ora prima di "adesso", che resta libera per le azioni fatte dall'agente.
                    rimborsato_il = min(rimborsato_il, ADESSO - timedelta(hours=1))
                    cur.execute(
                        "INSERT INTO rimborsi (ordine_id, importo_centesimi, motivo, creato_il)"
                        " VALUES (?,?,?,?)",
                        (ordine_id, totale, motivo, fmt(rimborsato_il)),
                    )
                venduti += quantita
    conn.commit()


def verifica(conn: sqlite3.Connection) -> None:
    errori = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert not errori, f"violazioni di chiave esterna: {errori}"

    sforati = conn.execute(
        """SELECT s.id FROM settori s
           JOIN ordini o ON o.settore_id = s.id AND o.stato = 'pagato'
           GROUP BY s.id HAVING SUM(o.quantita) > s.capienza"""
    ).fetchall()
    assert not sforati, f"capienza superata nei settori: {sforati}"

    incoerenti = conn.execute(
        """SELECT o.id FROM ordini o
           JOIN biglietti b ON b.ordine_id = o.id
           GROUP BY o.id HAVING COUNT(b.id) != o.quantita"""
    ).fetchall()
    assert not incoerenti, f"ordini con numero biglietti errato: {incoerenti}"


def main() -> None:
    destinazione = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "backend/ticketing.db")
    percorso = Path(destinazione)
    if not percorso.is_absolute():
        percorso = ROOT / percorso
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()

    conn = sqlite3.connect(percorso)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    popola(conn)
    verifica(conn)

    print(f"Database creato: {percorso}")
    for tabella in ("clienti", "eventi", "settori", "ordini", "biglietti", "rimborsi", "audit_log"):
        n = conn.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
        print(f"  {tabella:<10} {n}")
    conn.close()


if __name__ == "__main__":
    main()
