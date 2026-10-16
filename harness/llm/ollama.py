"""Provider per Ollama (modello locale), tramite la sua API nativa /api/chat."""
import time

from .base import (
    ChiamataTool,
    ErroreModello,
    LLMProvider,
    Messaggio,
    RispostaModello,
    SpecTool,
    leggi_argomenti,
    post_json,
)


class OllamaProvider(LLMProvider):
    nome = "ollama"

    def __init__(
        self,
        modello: str = "qwen2.5:7b",
        host: str = "http://localhost:11434",
        timeout: float = 600,
        temperatura: float = 0.0,
        seed: int = 42,
        num_ctx: int = 8192,
        keep_alive: str = "30m",
    ) -> None:
        self.modello = modello
        self.host = host.rstrip("/")
        self.timeout = timeout
        # Temperatura 0 e seme fisso: gli scenari di test sono il piu' possibile ripetibili.
        self.opzioni = {"temperature": temperatura, "seed": seed, "num_ctx": num_ctx}
        self.keep_alive = keep_alive  # tiene il modello in memoria tra una chiamata e l'altra

    @staticmethod
    def _messaggio(m: Messaggio) -> dict:
        if m.ruolo == "assistant" and m.chiamate_tool:
            return {
                "role": "assistant",
                "content": m.contenuto,
                "tool_calls": [
                    {"function": {"name": c.nome, "arguments": c.argomenti}} for c in m.chiamate_tool
                ],
            }
        if m.ruolo == "tool":
            return {"role": "tool", "content": m.contenuto, "tool_name": m.nome_tool}
        return {"role": m.ruolo, "content": m.contenuto}

    def chat(self, messaggi: list[Messaggio], strumenti: list[SpecTool]) -> RispostaModello:
        corpo = {
            "model": self.modello,
            "stream": False,
            "messages": [self._messaggio(m) for m in messaggi],
            "options": self.opzioni,
            "keep_alive": self.keep_alive,
        }
        if strumenti:
            corpo["tools"] = [
                {"type": "function", "function": {"name": t.nome, "description": t.descrizione, "parameters": t.parametri}}
                for t in strumenti
            ]

        inizio = time.monotonic()
        risposta = post_json(f"{self.host}/api/chat", corpo, self.timeout)
        durata_ms = int((time.monotonic() - inizio) * 1000)

        if "message" not in risposta:
            raise ErroreModello(f"Risposta di Ollama senza messaggio: {str(risposta)[:200]}")
        messaggio = risposta["message"]
        chiamate = []
        for i, c in enumerate(messaggio.get("tool_calls") or []):
            funzione = c.get("function", {})
            nome = funzione.get("name", "")
            argomenti, errore = leggi_argomenti(funzione.get("arguments"), nome)
            chiamate.append(ChiamataTool(id=c.get("id") or f"call_{i}", nome=nome, argomenti=argomenti, errore_argomenti=errore))

        return RispostaModello(
            testo=messaggio.get("content") or "",
            chiamate_tool=chiamate,
            token_ingresso=int(risposta.get("prompt_eval_count") or 0),
            token_uscita=int(risposta.get("eval_count") or 0),
            durata_ms=durata_ms,
            modello=self.modello,
        )
