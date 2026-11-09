"""Tool di scrittura (basso rischio): riapre le vendite di un evento a vendite chiuse."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "apri_vendite_evento"
DESCRIZIONE = (
    "SCRITTURA. Riapre le vendite di un evento che ha le vendite chiuse: l'evento torna in vendita e non viene "
    "rimborsato nulla. E' l'opposto di chiudi_vendite_evento. Funziona solo su eventi in stato 'vendite_chiuse' "
    "non ancora svolti; non serve per eventi annullati."
)
# Scrittura (readOnlyHint=False) ma non distruttiva: nessun dato esistente va perso.
ANNOTAZIONI = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


class EsitoApertura(BaseModel):
    evento_id: int
    titolo: str
    stato_precedente: str
    stato_nuovo: str


@tool_sicuro(NOME)
def esegui(
    evento_id: Annotated[int, Field(ge=1, description="Id dell'evento di cui riaprire le vendite")],
) -> EsitoApertura:
    return EsitoApertura(**repository.apri_vendite_evento(contesto.conn, evento_id, contesto.adesso()))
