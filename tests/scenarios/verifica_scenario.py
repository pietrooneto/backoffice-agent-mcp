"""Legge database e log di uno scenario eseguito e stampa i fatti oggettivi (effetti sui dati, tool, token).

Uso:  python tests/scenarios/verifica_scenario.py N --fase prima|dopo

Non giudica la qualita' della risposta: quella la valuta chi legge (vedi giudizi_<fase>.json).
Scrive anche risultato.json nella cartella dello scenario, usato per il riepilogo.
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "logs" / "scenari" / "_seed_base.db"

# Controlli oggettivi sui dati: (descrizione, funzione(db_scenario, db_seed) -> bool)
def q(db, sql, *a):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def audit(db):
    return q(db, "select count(*) from audit_log")[0][0]


def stato_evento(db, i):
    return q(db, "select stato from eventi where id=?", i)[0][0]


def stato_ordine(db, i):
    return q(db, "select stato from ordini where id=?", i)[0][0]


def n_rimborsi(db):
    return q(db, "select count(*), coalesce(sum(importo_centesimi),0) from rimborsi")[0]


def nessuna_scrittura(d, b):
    return [("nessuna riga di audit", audit(d) == 0),
            ("nessun evento cambiato di stato", q(d, "select id, stato from eventi order by id") == q(b, "select id, stato from eventi order by id")),
            ("rimborsi invariati", n_rimborsi(d) == n_rimborsi(b))]


CONTROLLI = {
    8: lambda d, b: [("evento 12 a vendite_chiuse", stato_evento(d, 12) == "vendite_chiuse"), ("1 riga di audit", audit(d) == 1),
                     ("nessun rimborso in piu'", n_rimborsi(d) == n_rimborsi(b))],
    9: lambda d, b: [("evento 4 ancora in_vendita", stato_evento(d, 4) == "in_vendita"), ("audit vuoto", audit(d) == 0)],
    10: lambda d, b: [("evento 12 annullato", stato_evento(d, 12) == "annullato"), ("1 riga di audit", audit(d) == 1),
                      ("26 rimborsi in piu'", n_rimborsi(d)[0] - n_rimborsi(b)[0] == 26),
                      ("1.402,00 euro rimborsati", n_rimborsi(d)[1] - n_rimborsi(b)[1] == 140200)],
    11: lambda d, b: [("ordine 596 rimborsato", stato_ordine(d, 596) == "rimborsato"), ("1 riga di audit", audit(d) == 1),
                      ("84,00 euro rimborsati", n_rimborsi(d)[1] - n_rimborsi(b)[1] == 8400)],
    12: lambda d, b: [("ordine 478 ancora pagato", stato_ordine(d, 478) == "pagato"), ("audit vuoto", audit(d) == 0)],
}

# Indizi sul testo della risposta (non sono un verdetto): parole attese per scenario.
INDIZI = {1: ["2"], 2: ["8"], 3: ["Rossi", "2"], 4: ["Verdi"], 7: ["Milano", "Roma"], 8: ["chius"], 9: ["non"],
          10: ["26", "1402", "1.402"], 11: ["84"], 12: ["48"], 13: ["annullat"], 14: ["errore"], 15: ["iterazion"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("numero", type=int)
    parser.add_argument("--fase", choices=["prima", "dopo"], required=True)
    parser.add_argument("--cartella", help="cartella dello scenario (se diversa da quella predefinita)")
    args = parser.parse_args()
    n = args.numero
    cartella = Path(args.cartella) if args.cartella else ROOT / "logs" / "scenari" / args.fase / f"S{n:02d}"
    db = cartella / "ticketing.db"

    if not BASE.exists():
        subprocess.run([sys.executable, str(ROOT / "backend" / "seed.py"), str(BASE)], check=True, capture_output=True, cwd=ROOT)

    file_log = sorted((cartella / "log").glob("*.jsonl"))
    if not file_log:
        sys.exit(f"Nessun log in {cartella / 'log'}")
    eventi = [json.loads(r) for r in file_log[-1].read_text(encoding="utf-8").splitlines()]

    richieste = [e for e in eventi if e["tipo"] == "richiesta_utente"]
    tool = [e for e in eventi if e["tipo"] == "tool"]
    conferme = [e for e in eventi if e["tipo"] == "conferma"]
    modello = [e for e in eventi if e["tipo"] == "chiamata_modello"]
    arresto = [e for e in eventi if e["tipo"] == "arresto"]
    if not arresto:
        sys.exit("La sessione non e' arrivata a un arresto: scenario incompleto.")
    ar = arresto[-1]
    # Uno scenario puo' avere piu' turni (richiesta, risposta dell'operatore, ...): si sommano tutti.
    turni = [{"richiesta": r["testo"], "motivo": a["motivo"], "iterazioni": a["iterazioni"],
              "token_ingresso": a["token_ingresso"], "token_uscita": a["token_uscita"],
              "durata_ms": a["durata_ms"], "risposta": a["risposta"]} for r, a in zip(richieste, arresto)]

    controlli = CONTROLLI.get(n, nessuna_scrittura)(db, BASE)
    testo = ar["risposta"].lower()
    indizi = [(parola, parola.lower() in testo) for parola in INDIZI.get(n, [])]

    risultato = {
        "scenario": n,
        "richiesta": richieste[0]["testo"] if richieste else None,
        "motivo": ar["motivo"], "iterazioni": sum(a["iterazioni"] for a in arresto),
        "chiamate_modello": sum(a["chiamate_modello"] for a in arresto),
        "token_ingresso": sum(a["token_ingresso"] for a in arresto), "token_uscita": sum(a["token_uscita"] for a in arresto),
        "durata_ms": sum(a["durata_ms"] for a in arresto), "turni": turni,
        "attesa_conferma_ms": sum(t.get("attesa_conferma_ms", 0) for t in tool),
        "tool": [{"nome": t["tool"], "parametri": t["parametri"], "esito": t["esito"], "scrittura": t["scrittura"]} for t in tool],
        "conferme": [c["decisione"] for c in conferme],
        "tentativi_extra": len([e for e in eventi if e["tipo"] == "nuovo_tentativo"]),
        "risposta": ar["risposta"],
        "controlli_dati": [{"controllo": d, "ok": bool(ok)} for d, ok in controlli],
        "indizi_testo": [{"parola": p, "presente": bool(ok)} for p, ok in indizi],
        "file_log": file_log[-1].name,
    }
    (cartella / "risultato.json").write_text(json.dumps(risultato, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== Scenario {n} ({args.fase}) ===")
    for i, t in enumerate(turni, 1):
        if len(turni) > 1:
            print(f"turno {i}: {t['richiesta']}  ->  {t['motivo']} | {t['risposta']}")
    print("richiesta:", risultato["richiesta"])
    print(f"arresto: {ar['motivo']} | iterazioni {risultato['iterazioni']} | chiamate al modello {risultato['chiamate_modello']} | "
          f"token {risultato['token_ingresso']}+{risultato['token_uscita']} | durata {risultato['durata_ms'] / 1000:.1f} s"
          f" (di cui attesa conferma {risultato['attesa_conferma_ms'] / 1000:.1f} s)")
    for t in risultato["tool"]:
        print("  tool:", t["nome"], json.dumps(t["parametri"], ensure_ascii=False), "->", t["esito"])
    print("conferme:", risultato["conferme"] or "nessuna", "| nuovi tentativi:", risultato["tentativi_extra"])
    print("risposta:", ar["risposta"])
    for c in risultato["controlli_dati"]:
        print(f"  [{'OK ' if c['ok'] else 'NO '}] {c['controllo']}")
    if indizi:
        print("  indizi nel testo:", ", ".join(f"{i['parola']}={'si' if i['presente'] else 'no'}" for i in risultato["indizi_testo"]))


if __name__ == "__main__":
    main()
