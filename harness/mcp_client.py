"""Client MCP: avvia il server come processo figlio e ne usa i tool via stdio."""
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import ROOT

# Variabili d'ambiente che il server MCP deve ereditare (il resto non viene passato).
VARIABILI_SERVER = ("DB_PATH", "RIFERIMENTO_ORA", "SIMULA_GUASTO")


@dataclass
class InfoTool:
    nome: str
    descrizione: str
    schema: dict
    scrittura: bool  # True se il tool modifica i dati


@dataclass
class RisultatoTool:
    testo: str  # quello che vede il modello
    errore: bool  # il tool ha risposto con un errore (is_error)


class ClientMcp:
    """Uso:  async with ClientMcp() as mcp: ... mcp.strumenti ... await mcp.chiama(nome, argomenti)"""

    def __init__(self, env_extra: dict[str, str] | None = None) -> None:
        self._env_extra = env_extra or {}
        self._stack: AsyncExitStack | None = None
        self._sessione: ClientSession | None = None
        self.strumenti: list[InfoTool] = []

    async def __aenter__(self) -> "ClientMcp":
        env = {k: os.environ[k] for k in VARIABILI_SERVER if k in os.environ}
        env.update(self._env_extra)
        env["PYTHONPATH"] = str(ROOT)
        parametri = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], cwd=str(ROOT), env=env)

        self._stack = AsyncExitStack()
        try:
            lettura, scrittura = await self._stack.enter_async_context(stdio_client(parametri))
            self._sessione = await self._stack.enter_async_context(ClientSession(lettura, scrittura))
            await self._sessione.initialize()
            elenco = await self._sessione.list_tools()
        except BaseException:
            await self._stack.aclose()
            raise
        self.strumenti = [
            InfoTool(
                nome=t.name,
                descrizione=t.description or "",
                schema=t.input_schema,
                # Sicuro per default: e' di sola lettura solo se il server lo dichiara esplicitamente.
                scrittura=not (t.annotations is not None and t.annotations.read_only_hint is True),
            )
            for t in elenco.tools
        ]
        return self

    async def __aexit__(self, *eccezione) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def chiama(self, nome: str, argomenti: dict) -> RisultatoTool:
        """Esegue un tool. Un errore del tool torna come risultato; i guasti di trasporto sollevano eccezioni."""
        risposta = await self._sessione.call_tool(nome, argomenti)
        if risposta.is_error:
            testo = " ".join(getattr(c, "text", "") for c in risposta.content).strip() or "Errore del tool."
            return RisultatoTool(testo, True)
        if risposta.structured_content is not None:
            return RisultatoTool(json.dumps(risposta.structured_content, ensure_ascii=False, separators=(",", ":")), False)
        return RisultatoTool(" ".join(getattr(c, "text", "") for c in risposta.content).strip(), False)
