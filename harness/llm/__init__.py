"""Modelli linguistici disponibili. Si sceglie con LLM_PROVIDER in configurazione."""
from ..config import Configurazione
from .base import ChiamataTool, ErroreModello, LLMProvider, Messaggio, RispostaModello, SpecTool
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

__all__ = [
    "LLMProvider", "Messaggio", "ChiamataTool", "SpecTool", "RispostaModello", "ErroreModello",
    "OllamaProvider", "OpenAICompatProvider", "crea_provider",
]


def crea_provider(config: Configurazione) -> LLMProvider:
    """Costruisce il provider indicato dalla configurazione: l'unico punto che li conosce."""
    if config.provider == "ollama":
        return OllamaProvider(
            modello=config.modello, host=config.ollama_host,
            timeout=config.timeout_modello, num_ctx=config.num_ctx,
        )
    if config.provider == "openai_compat":
        return OpenAICompatProvider(
            modello=config.modello, base_url=config.openai_base_url,
            api_key=config.api_key, timeout=config.timeout_modello,
        )
    raise ValueError(f"LLM_PROVIDER '{config.provider}' sconosciuto. Valori ammessi: ollama, openai_compat.")
