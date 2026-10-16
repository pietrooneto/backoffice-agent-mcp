"""Tool di scrittura: rimborso di un singolo ordine."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "rimborsa_ordine"
DESCRIZIONE = (
    "SCRITTURA. Rimborsa per intero un singolo ordine pagato (pagamento solo simulato). Consentito solo "
    f"se all'evento mancano almeno {repository.TERMINE_RIMBORSO_ORE} ore; altrimenti risponde con un errore."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class EsitoRimborso(BaseModel):
    ordine_id: int
    evento_titolo: str
    importo_rimborsato_centesimi: int
    motivo: str
    stato_ordine: str


@tool_sicuro(NOME)
def esegui(
    ordine_id: Annotated[int, Field(ge=1, description="Id dell'ordine da rimborsare")],
    motivo: Annotated[str, Field(min_length=1, max_length=200, description="Motivo del rimborso")] = "richiesta del cliente",
) -> EsitoRimborso:
    return EsitoRimborso(**repository.rimborsa_ordine(contesto.conn, ordine_id, motivo, contesto.adesso()))
