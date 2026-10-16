"""Modello finto, a risposte preparate: serve ai test dell'harness (nessun modello reale)."""
from .base import ChiamataTool, ErroreModello, LLMProvider, Messaggio, RispostaModello, SpecTool


def risposta(testo: str = "", tool: list[tuple[str, dict]] | None = None, token_ingresso: int = 100, token_uscita: int = 20) -> RispostaModello:
    """Costruisce una RispostaModello; `tool` e' una lista di (nome, argomenti)."""
    chiamate = [ChiamataTool(id=f"call_{i}", nome=n, argomenti=a) for i, (n, a) in enumerate(tool or [])]
    return RispostaModello(testo, chiamate, token_ingresso, token_uscita, 5, "finto")


class ProviderScriptato(LLMProvider):
    """Restituisce in ordine le risposte preparate (o solleva un'eccezione se l'elemento lo e')."""

    nome = "scriptato"
    modello = "finto"

    def __init__(self, copione: list[RispostaModello | Exception]) -> None:
        self.copione = list(copione)
        self.chiamate: list[list[Messaggio]] = []  # conversazioni ricevute, per i controlli dei test
        self.strumenti_ricevuti: list[SpecTool] = []

    def chat(self, messaggi: list[Messaggio], strumenti: list[SpecTool]) -> RispostaModello:
        self.chiamate.append(list(messaggi))
        self.strumenti_ricevuti = strumenti
        if not self.copione:
            raise ErroreModello("copione esaurito")
        prossima = self.copione.pop(0)
        if isinstance(prossima, Exception):
            raise prossima
        return prossima
