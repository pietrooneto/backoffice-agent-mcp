"""Avvia l'interfaccia web per uno scenario di test, con un database nuovo e la configurazione dello scenario.

Uso:  python tests/scenarios/avvia_scenario.py N --fase prima|dopo --porta 8101 [--prompt base]

Crea logs/scenari/<fase>/SNN/ con una copia nuova del database sintetico (stesso seed di sempre) e la cartella
dei log JSON Lines della sessione. Poi serve l'interfaccia web finche' non viene fermato.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Impostazioni particolari di alcuni scenari (le altre usano la configurazione normale).
ENV_SCENARIO = {
    14: {"SIMULA_GUASTO": "dettaglio_evento"},  # guasto simulato del database
    15: {"MAX_ITERATIONS": "2"},  # limite di iterazioni volutamente basso
}
SIMULATI = {16, 17, 18}  # modello a risposte preparate (comportamenti dell'harness non provocabili in modo ripetibile)


def provider_simulato(n: int):
    from harness.llm.fake import ProviderScriptato, risposta

    if n == 16:  # il modello chiede un tool che non esiste
        return ProviderScriptato([
            risposta(tool=[("cancella_tutto", {})], token_ingresso=900, token_uscita=20),
            risposta("Non posso eseguire questa operazione: il tool richiesto non esiste.", token_ingresso=960, token_uscita=18),
        ])
    if n == 17:  # il modello chiede un tool di scrittura con un parametro non valido
        return ProviderScriptato([
            risposta(tool=[("chiudi_vendite_evento", {"evento_id": 0})], token_ingresso=900, token_uscita=25),
            risposta("L'id indicato non è valido, quindi non ho modificato nulla.", token_ingresso=980, token_uscita=20),
        ])
    if n == 18:  # il modello risponde a vuoto la prima volta
        return ProviderScriptato([
            risposta("", token_ingresso=900, token_uscita=1),
            risposta("Sono attivo e pronto ad aiutarti con eventi, ordini e clienti.", token_ingresso=900, token_uscita=16),
        ])
    raise ValueError(n)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("numero", type=int)
    parser.add_argument("--fase", choices=["prima", "dopo", "controlli"], required=True)
    parser.add_argument("--porta", type=int, default=8100)
    parser.add_argument("--prompt", default="base")
    parser.add_argument("--senza-controlli", action="store_true",
                        help="disattiva anteprima e controllo degli id (comportamento dei primi due giri)")
    args = parser.parse_args()

    cartella = ROOT / "logs" / "scenari" / args.fase / f"S{args.numero:02d}"
    cartella.mkdir(parents=True, exist_ok=False)  # un'esecuzione = una cartella: mai sovrascrivere risultati
    db = cartella / "ticketing.db"
    subprocess.run([sys.executable, str(ROOT / "backend" / "seed.py"), str(db)], check=True, capture_output=True, cwd=ROOT)

    os.environ.update({
        "DB_PATH": str(db), "LOG_DIR": str(cartella / "log"), "VARIANTE_PROMPT": args.prompt,
        "CONTROLLI_HARNESS": "0" if args.senza_controlli else "1",
        **ENV_SCENARIO.get(args.numero, {}),
    })
    (cartella / "pid.txt").write_text(str(os.getpid()), encoding="utf-8")

    import uvicorn

    from harness.config import Configurazione
    from harness.web import crea_app

    provider = provider_simulato(args.numero) if args.numero in SIMULATI else None
    app = crea_app(Configurazione.da_ambiente(), provider)
    print(f"Scenario {args.numero} ({args.fase}, prompt {args.prompt}) su http://127.0.0.1:{args.porta}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.porta, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
