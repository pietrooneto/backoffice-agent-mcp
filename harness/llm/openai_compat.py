"""Provider per qualunque server con API compatibile OpenAI (/chat/completions).

Ollama la espone su /v1; la usano anche LM Studio, llama.cpp e altri server locali.
Basta cambiare l'indirizzo in configurazione.
"""
import json
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


class OpenAICompatProvider(LLMProvider):
    nome = "openai_compat"

    def __init__(
        self,
        modello: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "",
        timeout: float = 600,
        temperatura: float = 0.0,
        seed: int = 42,
    ) -> None:
        self.modello = modello
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.temperatura = temperatura
        self.seed = seed

    @staticmethod
    def _messaggio(m: Messaggio) -> dict:
        if m.ruolo == "assistant" and m.chiamate_tool:
            return {
                "role": "assistant",
                "content": m.contenuto or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        # In questo formato gli argomenti viaggiano come stringa JSON.
                        "function": {"name": c.nome, "arguments": json.dumps(c.argomenti, ensure_ascii=False)},
                    }
                    for c in m.chiamate_tool
                ],
            }
        if m.ruolo == "tool":
            return {"role": "tool", "tool_call_id": m.id_chiamata, "content": m.contenuto}
        return {"role": m.ruolo, "content": m.contenuto}

    def chat(self, messaggi: list[Messaggio], strumenti: list[SpecTool]) -> RispostaModello:
        corpo = {
            "model": self.modello,
            "messages": [self._messaggio(m) for m in messaggi],
            "temperature": self.temperatura,
            "seed": self.seed,
        }
        if strumenti:
            corpo["tools"] = [
                {"type": "function", "function": {"name": t.nome, "description": t.descrizione, "parameters": t.parametri}}
                for t in strumenti
            ]
        intestazioni = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        inizio = time.monotonic()
        risposta = post_json(f"{self.base_url}/chat/completions", corpo, self.timeout, intestazioni)
        durata_ms = int((time.monotonic() - inizio) * 1000)

        try:
            messaggio = risposta["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as errore:
            raise ErroreModello(f"Risposta senza scelte utilizzabili: {str(risposta)[:200]}") from errore

        chiamate = []
        for i, c in enumerate(messaggio.get("tool_calls") or []):
            funzione = c.get("function", {})
            nome = funzione.get("name", "")
            argomenti, errore = leggi_argomenti(funzione.get("arguments"), nome)
            chiamate.append(ChiamataTool(id=c.get("id") or f"call_{i}", nome=nome, argomenti=argomenti, errore_argomenti=errore))

        uso = risposta.get("usage") or {}
        return RispostaModello(
            testo=messaggio.get("content") or "",
            chiamate_tool=chiamate,
            token_ingresso=int(uso.get("prompt_tokens") or 0),
            token_uscita=int(uso.get("completion_tokens") or 0),
            durata_ms=durata_ms,
            modello=self.modello,
        )
