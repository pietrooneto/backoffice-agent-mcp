"""Tool di scrittura (basso rischio): chiude le vendite di un evento."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "chiudi_vendite_evento"
DESCRIZIONE = (
    "SCRITTURA. Chiude le vendite di un evento in vendita: nessun nuovo acquisto, gli ordini esistenti "
    "restano validi e non viene rimborsato nulla. NON annulla l'evento (per quello esiste annulla_evento). "
    "Funziona solo su eventi in stato 'in_vendita'."
)
# Scrittura (readOnlyHint=False) ma non distruttiva: i dati esistenti non vengono persi.
ANNOTAZIONI = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


class EsitoChiusura(BaseModel):
    evento_id: int
    titolo: str
    stato_precedente: str
    stato_nuovo: str


@tool_sicuro(NOME)
def esegui(
    evento_id: Annotated[int, Field(ge=1, description="Id dell'evento di cui chiudere le vendite")],
) -> EsitoChiusura:
    return EsitoChiusura(**repository.chiudi_vendite_evento(contesto.conn, evento_id, contesto.adesso()))
