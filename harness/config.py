"""Configurazione dell'harness, letta da variabili d'ambiente (e dal file .env se presente)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELLO_PREDEFINITO = "qwen2.5:7b"


def carica_env(percorso: Path | None = None) -> None:
    """Legge un file .env semplice (CHIAVE=valore). Le variabili gia' impostate non vengono sovrascritte."""
    percorso = percorso or ROOT / ".env"
    if not percorso.exists():
        return
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, _, valore = riga.partition("=")
        chiave, valore = chiave.strip(), valore.strip().strip('"').strip("'")
        if valore and chiave not in os.environ:
            os.environ[chiave] = valore


@dataclass
class Configurazione:
    provider: str = "ollama"
    modello: str = MODELLO_PREDEFINITO
    ollama_host: str = "http://localhost:11434"
    openai_base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    max_iterazioni: int = 10
    tentativi_extra_risposta_vuota: int = 1
    timeout_modello: float = 600
    timeout_tool: float = 60
    num_ctx: int = 8192
    variante_prompt: str = "base"
    controlli: bool = True  # anteprima delle scritture e controllo degli id (CONTROLLI_HARNESS=0 per disattivarli)
    log_dir: Path = ROOT / "logs"

    @classmethod
    def da_ambiente(cls) -> "Configurazione":
        carica_env()
        e = os.environ
        log_dir = Path(e.get("LOG_DIR") or "logs")
        return cls(
            provider=e.get("LLM_PROVIDER") or "ollama",
            modello=e.get("OLLAMA_MODEL") or MODELLO_PREDEFINITO,
            ollama_host=e.get("OLLAMA_HOST") or "http://localhost:11434",
            openai_base_url=e.get("OPENAI_BASE_URL") or "http://localhost:11434/v1",
            api_key=e.get("LLM_API_KEY") or "",
            max_iterazioni=int(e.get("MAX_ITERATIONS") or 10),
            timeout_modello=float(e.get("TIMEOUT_MODELLO") or 600),
            timeout_tool=float(e.get("TIMEOUT_TOOL") or 60),
            num_ctx=int(e.get("NUM_CTX") or 8192),
            variante_prompt=e.get("VARIANTE_PROMPT") or "base",
            controlli=(e.get("CONTROLLI_HARNESS") or "1").strip().lower() not in {"0", "no", "false"},
            log_dir=log_dir if log_dir.is_absolute() else ROOT / log_dir,
        )
