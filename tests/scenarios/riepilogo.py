"""Mette insieme i risultati degli scenari eseguiti in una tabella Markdown (e ne calcola i totali).

Uso:  python tests/scenarios/riepilogo.py prima [dopo]
Legge logs/scenari/<fase>/SNN/risultato.json e tests/scenarios/giudizi_<fase>.json.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOMI = {1: "Lettura semplice", 2: "Storico di un cliente", 3: "Cliente omonimo", 4: "Cliente inesistente",
        5: "Fuori ambito", 6: "Richiesta ambigua", 7: "Stesso titolo", 8: "Scrittura approvata", 9: "Conferma negata",
        10: "Annullamento a cascata", 11: "Rimborso valido", 12: "Rimborso oltre il termine", 13: "Evento gia' annullato",
        14: "Errore del database", 15: "Limite di iterazioni", 16: "Tool inesistente (simulato)",
        17: "Parametri non validi (simulato)", 18: "Risposta vuota (simulato)"}
ETICHETTA = {"riuscito": "riuscito", "parziale": "parziale", "non_riuscito": "non riuscito"}


def carica(fase):
    risultati, giudizi = {}, {}
    gf = ROOT / "tests" / "scenarios" / f"giudizi_{fase}.json"
    if gf.exists():
        giudizi = json.loads(gf.read_text(encoding="utf-8"))
    for f in sorted((ROOT / "logs" / "scenari" / fase).glob("S*/risultato.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        risultati[r["scenario"]] = r
    return risultati, giudizi


def tabella(fase):
    risultati, giudizi = carica(fase)
    righe = ["| N | Scenario | Esito | Iterazioni | Tool chiamati | Token in | Token out | Durata (s) | Arresto |",
             "|---|----------|-------|-----------:|---------------|---------:|----------:|-----------:|---------|"]
    tot_in = tot_out = tot_dur = 0
    conteggio = {}
    reali = {n: r for n, r in risultati.items() if n <= 15}
    for n in sorted(risultati):
        r = risultati[n]
        g = giudizi.get(str(n), {})
        durata = (r["durata_ms"] - r.get("attesa_conferma_ms", 0)) / 1000
        tool = ", ".join(t["nome"] for t in r["tool"]) or "nessuno"
        esito = ETICHETTA.get(g.get("esito"), "da valutare")
        righe.append(f"| {n} | {NOMI.get(n, '')} | {esito} | {r['iterazioni']} | {tool} | {r['token_ingresso']} | "
                     f"{r['token_uscita']} | {durata:.1f} | {r['motivo'].replace('_', ' ')} |")
        conteggio[esito] = conteggio.get(esito, 0) + 1
        if n in reali:
            tot_in += r["token_ingresso"]; tot_out += r["token_uscita"]; tot_dur += durata
    righe.append("")
    righe.append("Esiti: " + ", ".join(f"{k} {v}" for k, v in conteggio.items()) + ".")
    if reali:
        k = len(reali)
        righe.append(f"Scenari con modello reale ({k}): in media {tot_in / k:.0f} token in ingresso, {tot_out / k:.0f} in uscita "
                     f"e {tot_dur / k:.0f} secondi (esclusa l'attesa delle conferme); totale {tot_in + tot_out} token.")
    return "\n".join(righe)


if __name__ == "__main__":
    for fase in sys.argv[1:] or ["prima"]:
        print(f"## Fase: {fase}\n")
        print(tabella(fase))
        print()
