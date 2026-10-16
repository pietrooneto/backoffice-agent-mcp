"""Conferma umana (human-in-the-loop) prima dei tool che modificano i dati.

L'harness conosce solo l'interfaccia Conferma: terminale, web e test la realizzano in modo diverso.
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Protocol


@dataclass
class RichiestaConferma:
    tool: str
    descrizione: str
    argomenti: dict


class Conferma(Protocol):
    async def chiedi(self, richiesta: RichiestaConferma) -> bool:
        """True se l'operatore autorizza l'esecuzione, False se la rifiuta."""
        ...


class AutoApprova:
    """Approva sempre: solo per i test."""

    async def chiedi(self, richiesta: RichiestaConferma) -> bool:
        return True


class AutoRifiuta:
    """Rifiuta sempre: solo per i test."""

    async def chiedi(self, richiesta: RichiestaConferma) -> bool:
        return False


class ConfermaDaTerminale:
    """Mostra tool e parametri e aspetta s/n dalla tastiera."""

    async def chiedi(self, richiesta: RichiestaConferma) -> bool:
        print("\n  >>> RICHIESTA DI CONFERMA: l'agente vuole modificare i dati")
        print(f"      Tool:      {richiesta.tool}")
        print(f"      Parametri: {json.dumps(richiesta.argomenti, ensure_ascii=False)}")
        print(f"      Effetto:   {richiesta.descrizione}")
        risposta = await asyncio.to_thread(input, "      Confermi? [s/N] ")
        return risposta.strip().lower() in {"s", "si", "sì", "y", "yes"}
