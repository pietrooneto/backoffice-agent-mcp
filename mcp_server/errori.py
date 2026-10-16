"""Traduzione degli errori in risultati leggibili dal modello."""
import functools
import sqlite3
import sys
import threading

from mcp.server.mcpserver.exceptions import ToolError

from backend.repository import ErroreDominio

from .contesto import contesto

# Un solo tool alla volta tocca il database (un'unica connessione condivisa).
_LUCCHETTO = threading.Lock()

MESSAGGIO_GUASTO = (
    "Errore temporaneo del database: l'operazione NON e' stata eseguita. "
    "Riprova tra poco; se persiste avvisa un tecnico."
)


def tool_sicuro(nome: str):
    """Decoratore comune a tutti i tool.

    - Errori di dominio (non trovato, stato non valido, fuori termine...): il messaggio
      arriva al modello cosi' com'e', come risultato di errore (non fa crashare nulla).
    - Errori del database: messaggio generico, senza dettagli interni; il dettaglio va
      sullo stderr del server (lo stdout e' riservato al protocollo MCP).
    - Guasto simulato (SIMULA_GUASTO) per testare la gestione degli errori dell'harness.
    """

    def decoratore(funzione):
        @functools.wraps(funzione)
        def avvolta(*args, **kwargs):
            try:
                with _LUCCHETTO:
                    if contesto.guasto_simulato(nome):
                        raise sqlite3.OperationalError("guasto simulato: database is locked")
                    return funzione(*args, **kwargs)
            except ErroreDominio as errore:
                raise ToolError(str(errore)) from errore
            except sqlite3.Error as errore:
                print(f"[{nome}] errore database: {errore}", file=sys.stderr, flush=True)
                raise ToolError(MESSAGGIO_GUASTO) from errore

        return avvolta

    return decoratore
