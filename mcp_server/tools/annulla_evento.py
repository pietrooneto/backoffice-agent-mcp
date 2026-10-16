"""Tool di scrittura (alto impatto): annulla un evento e rimborsa tutti gli ordini."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "annulla_evento"
DESCRIZIONE = (
    "SCRITTURA AD ALTO IMPATTO. Annulla un evento e rimborsa per intero TUTTI gli ordini pagati. "
    "Da non confondere con chiudi_vendite_evento: usalo solo se l'operatore chiede esplicitamente di "
    "annullare l'evento. Non funziona su eventi gia' annullati o gia' svolti."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class EsitoAnnullamento(BaseModel):
    evento_id: int
    titolo: str
    stato_precedente: str
    stato_nuovo: str
    ordini_rimborsati: int
    biglietti_rimborsati: int
    totale_rimborsato_centesimi: int


@tool_sicuro(NOME)
def esegui(
    evento_id: Annotated[int, Field(ge=1, description="Id dell'evento da annullare")],
) -> EsitoAnnullamento:
    return EsitoAnnullamento(**repository.annulla_evento(contesto.conn, evento_id, contesto.adesso()))
