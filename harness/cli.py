"""Interfaccia minimale a riga di comando: chat con l'agente nel terminale.

Uso:  python -m harness.cli
"""
import asyncio
import json
import sys

from .agent_loop import Agente
from .conferma import ConfermaDaTerminale
from .config import Configurazione
from .llm import crea_provider
from .mcp_client import ClientMcp
from .registro import Registro


def mostra(evento: dict) -> None:
    """Stampa sul terminale un riassunto di ogni passo (il log completo e' nel file JSONL)."""
    tipo = evento["tipo"]
    if tipo == "chiamata_modello":
        if evento["esito"] == "errore":
            print(f"  [modello] ERRORE: {evento['errore']}")
        else:
            print(f"  [modello] passo {evento['iterazione']}: {evento['token_ingresso']} token in, "
                  f"{evento['token_uscita']} out, {evento['durata_ms'] / 1000:.1f}s ({evento['esito']})")
    elif tipo == "nuovo_tentativo":
        print(f"  [modello] {evento['motivo']}: riprovo")
    elif tipo == "tool":
        parametri = json.dumps(evento["parametri"], ensure_ascii=False)
        print(f"  [tool] {evento['tool']}({parametri}) -> {evento['esito']}")


async def principale() -> None:
    config = Configurazione.da_ambiente()
    provider = crea_provider(config)
    registro = Registro(config.log_dir)
    registro.aggiungi_ascoltatore(mostra)

    print(f"Modello: {provider.nome}/{provider.modello}. Scrivi una richiesta (vuoto o 'esci' per uscire).")
    async with ClientMcp() as mcp:
        agente = Agente(provider, mcp, ConfermaDaTerminale(), registro,
                        max_iterazioni=config.max_iterazioni,
                        tentativi_extra_risposta_vuota=config.tentativi_extra_risposta_vuota,
                        timeout_tool=config.timeout_tool)
        while True:
            try:
                richiesta = await asyncio.to_thread(input, "\nOperatore> ")
            except (EOFError, KeyboardInterrupt):
                break
            if richiesta.strip().lower() in {"", "esci", "exit"}:
                break
            esito = await agente.esegui(richiesta)
            print(f"\nAgente> {esito.risposta}")
            print(f"  ({esito.motivo.value}; {esito.iterazioni} iterazioni; "
                  f"{esito.token_ingresso + esito.token_uscita} token; {esito.durata_ms / 1000:.1f}s)")
    if registro.percorso:
        print(f"\nLog: {registro.percorso}")


def main() -> None:
    # Console di Windows e output rediretto: forza UTF-8 per non rovinare gli accenti.
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(principale())


if __name__ == "__main__":
    main()
