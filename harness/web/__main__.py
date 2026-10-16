"""Avvia l'interfaccia web in locale:  python -m harness.web  (poi apri l'indirizzo mostrato)."""
import os

import uvicorn

from ..config import Configurazione
from .app import crea_app


def main() -> None:
    config = Configurazione.da_ambiente()
    porta = int(os.environ.get("WEB_PORT") or 8000)
    print(f"Interfaccia web su http://127.0.0.1:{porta}  (modello: {config.provider}/{config.modello}; Ctrl+C per uscire)")
    # Solo 127.0.0.1: la pagina puo' approvare modifiche ai dati, non va esposta in rete.
    uvicorn.run(crea_app(config), host="127.0.0.1", port=porta, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
