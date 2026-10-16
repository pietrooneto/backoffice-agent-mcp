"""Astrazione del modello linguistico: tipi normalizzati e interfaccia LLMProvider.

Il resto dell'harness conosce solo questi tipi: per cambiare modello o fornitore basta
un'altra implementazione di LLMProvider, senza toccare il ciclo agentico.
"""
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ErroreModello(Exception):
    """Il modello non e' raggiungibile o ha risposto in modo inutilizzabile."""


@dataclass
class ChiamataTool:
    """Richiesta del modello di eseguire un tool."""

    id: str
    nome: str
    argomenti: dict
    errore_argomenti: str | None = None  # valorizzato se il modello ha prodotto argomenti illeggibili


@dataclass
class Messaggio:
    """Messaggio della conversazione. ruolo: system, user, assistant oppure tool."""

    ruolo: str
    contenuto: str = ""
    chiamate_tool: list[ChiamataTool] = field(default_factory=list)  # solo per assistant
    id_chiamata: str | None = None  # solo per tool: a quale chiamata risponde
    nome_tool: str | None = None  # solo per tool

    def a_dict(self) -> dict:
        """Forma compatta per il log."""
        d: dict = {"ruolo": self.ruolo, "contenuto": self.contenuto}
        if self.chiamate_tool:
            d["chiamate_tool"] = [{"id": c.id, "nome": c.nome, "argomenti": c.argomenti} for c in self.chiamate_tool]
        if self.id_chiamata:
            d["id_chiamata"] = self.id_chiamata
            d["nome_tool"] = self.nome_tool
        return d


@dataclass
class SpecTool:
    """Descrizione di un tool da mostrare al modello."""

    nome: str
    descrizione: str
    parametri: dict  # JSON Schema dei parametri


@dataclass
class RispostaModello:
    """Risposta normalizzata, uguale per ogni fornitore."""

    testo: str
    chiamate_tool: list[ChiamataTool]
    token_ingresso: int
    token_uscita: int
    durata_ms: int
    modello: str

    @property
    def vuota(self) -> bool:
        return not self.testo.strip() and not self.chiamate_tool


class LLMProvider(ABC):
    """Interfaccia comune a tutti i modelli."""

    nome: str = "provider"
    modello: str = ""

    @abstractmethod
    def chat(self, messaggi: list[Messaggio], strumenti: list[SpecTool]) -> RispostaModello:
        """Invia la conversazione e i tool disponibili, restituisce la risposta normalizzata.

        Solleva ErroreModello se il modello non e' raggiungibile o la risposta e' inutilizzabile.
        """


def post_json(url: str, corpo: dict, timeout: float, intestazioni: dict | None = None) -> dict:
    """POST JSON con la sola libreria standard; traduce gli errori in ErroreModello."""
    richiesta = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", **(intestazioni or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            return json.load(risposta)
    except urllib.error.HTTPError as errore:
        dettaglio = errore.read().decode("utf-8", errors="replace")[:300]
        raise ErroreModello(f"Il modello ha risposto con errore HTTP {errore.code}: {dettaglio}") from errore
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as errore:
        raise ErroreModello(f"Modello non raggiungibile ({url}): {errore}") from errore
    except json.JSONDecodeError as errore:
        raise ErroreModello("Il modello ha risposto con un JSON non valido.") from errore


def leggi_argomenti(grezzi, nome_tool: str) -> tuple[dict, str | None]:
    """Normalizza gli argomenti di una chiamata: dict, oppure stringa JSON da interpretare."""
    if grezzi in (None, "", {}):
        return {}, None
    if isinstance(grezzi, dict):
        return grezzi, None
    if isinstance(grezzi, str):
        try:
            valore = json.loads(grezzi)
        except json.JSONDecodeError:
            return {}, f"argomenti non in formato JSON valido: {grezzi[:200]!r}"
        if isinstance(valore, dict):
            return valore, None
    return {}, f"argomenti di '{nome_tool}' non sono un oggetto: {str(grezzi)[:200]!r}"
