"""Tool di lettura: dettaglio di un evento con capienza, venduti e disponibili."""
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "dettaglio_evento"
DESCRIZIONE = (
    "Dettaglio di un evento: stato, capienza, biglietti venduti e disponibili, per settore e in totale. "
    "I prezzi sono in centesimi di euro. Richiede l'id dell'evento (usa cerca_eventi per trovarlo)."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class Settore(BaseModel):
    settore_id: int
    nome: str
    capienza: int
    prezzo_centesimi: int
    venduti: int
    disponibili: int


class DettaglioEvento(BaseModel):
    id: int
    titolo: str
    luogo: str
    data_evento: str
    stato: Literal["bozza", "in_vendita", "vendite_chiuse", "annullato"]
    settori: list[Settore]
    capienza_totale: int
    venduti_totali: int
    disponibili_totali: int


@tool_sicuro(NOME)
def esegui(
    evento_id: Annotated[int, Field(ge=1, description="Id dell'evento")],
) -> DettaglioEvento:
    return DettaglioEvento(**repository.dettaglio_evento(contesto.conn, evento_id))
