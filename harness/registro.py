"""Log strutturato in formato JSON Lines: una riga per ogni passo dell'agente."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable


class Registro:
    """Scrive gli eventi di una sessione su file (se c'e' una cartella) e li tiene in memoria.

    Ogni riga ha almeno: timestamp, sessione_id, tipo. Chi mostra l'andamento in tempo reale
    (per esempio l'interfaccia web) si registra con aggiungi_ascoltatore().
    """

    def __init__(self, cartella: Path | None = None, sessione_id: str | None = None) -> None:
        self.sessione_id = sessione_id or uuid.uuid4().hex[:8]
        self.cartella = cartella
        self.eventi: list[dict] = []
        self._ascoltatori: list[Callable[[dict], None]] = []
        self._file: Path | None = None

    @property
    def percorso(self) -> Path | None:
        return self._file

    def aggiungi_ascoltatore(self, funzione: Callable[[dict], None]) -> None:
        self._ascoltatori.append(funzione)

    def scrivi(self, tipo: str, **campi) -> dict:
        evento = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "sessione_id": self.sessione_id,
            "tipo": tipo,
            **campi,
        }
        self.eventi.append(evento)
        if self.cartella is not None:
            if self._file is None:
                self.cartella.mkdir(parents=True, exist_ok=True)
                marca = datetime.now().strftime("%Y%m%d-%H%M%S")
                self._file = self.cartella / f"{marca}-{self.sessione_id}.jsonl"
            with self._file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        for ascoltatore in self._ascoltatori:
            ascoltatore(evento)
        return evento
