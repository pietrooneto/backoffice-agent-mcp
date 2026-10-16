"""Tool di lettura: stato e dettaglio di un ordine."""
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "stato_ordine"
DESCRIZIONE = (
    "Stato e dettaglio di un ordine: cliente, evento, settore, quantita', totale in centesimi, "
    "biglietti ed eventuali rimborsi. Richiede l'id dell'ordine."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class RimborsoRegistrato(BaseModel):
    importo_centesimi: int
    motivo: str
    creato_il: str


class DettaglioOrdine(BaseModel):
    ordine_id: int
    stato: Literal["pagato", "rimborsato", "annullato"]
    quantita: int
    totale_centesimi: int
    creato_il: str
    cliente_id: int
    cliente_nome: str
    cliente_cognome: str
    evento_id: int
    evento_titolo: str
    data_evento: str
    evento_stato: Literal["bozza", "in_vendita", "vendite_chiuse", "annullato"]
    settore: str
    biglietti: dict[str, int] = Field(description="Numero di biglietti per stato (valido, rimborsato)")
    rimborsi: list[RimborsoRegistrato]


@tool_sicuro(NOME)
def esegui(
    ordine_id: Annotated[int, Field(ge=1, description="Id dell'ordine")],
) -> DettaglioOrdine:
    return DettaglioOrdine(**repository.stato_ordine(contesto.conn, ordine_id))
