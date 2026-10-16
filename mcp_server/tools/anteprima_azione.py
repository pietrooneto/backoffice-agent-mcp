"""Tool di servizio per l'harness (NON per il modello): anteprima di un'azione di scrittura.

L'harness lo usa prima di chiedere la conferma all'operatore e lo nasconde al modello. Non modifica nulla.
"""
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository
from backend.repository import ErroreDominio

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "anteprima_azione"
DESCRIZIONE = (
    "Servizio per l'harness, non per il modello. Dato un tool di scrittura e i suoi parametri, dice se le regole "
    "lo permettono e descrive l'effetto (nomi, numeri, importi) senza modificare nulla."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class EsitoAnteprima(BaseModel):
    ammessa: bool
    riepilogo: str | None = Field(default=None, description="Che cosa farebbe l'azione, se ammessa")
    motivo: str | None = Field(default=None, description="Perche' l'azione non e' ammessa, se vietata")


@tool_sicuro(NOME)
def esegui(
    tool: Annotated[Literal["chiudi_vendite_evento", "annulla_evento", "rimborsa_ordine"], Field(description="Tool di scrittura da simulare")],
    parametri: Annotated[dict[str, Any], Field(description="Parametri che il modello vorrebbe usare")],
) -> EsitoAnteprima:
    try:
        riepilogo = repository.anteprima_azione(contesto.conn, tool, parametri, contesto.adesso())
    except ErroreDominio as errore:
        # Un'azione vietata non e' un errore del tool: e' il risultato dell'anteprima.
        return EsitoAnteprima(ammessa=False, motivo=str(errore))
    return EsitoAnteprima(ammessa=True, riepilogo=riepilogo)
