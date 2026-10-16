"""Tool di lettura: ricerca degli eventi per titolo e/o stato."""
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "cerca_eventi"
DESCRIZIONE = (
    "Cerca eventi per titolo (anche parziale) e/o stato. Restituisce id, titolo, luogo, data e stato. "
    "Piu' eventi possono avere lo stesso titolo: se ne trovi piu' di uno, chiedi quale intende l'operatore."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class EventoSintesi(BaseModel):
    id: int
    titolo: str
    luogo: str
    data_evento: str
    stato: Literal["bozza", "in_vendita", "vendite_chiuse", "annullato"]


class RisultatoRicerca(BaseModel):
    totale: int
    eventi: list[EventoSintesi]


@tool_sicuro(NOME)
def esegui(
    titolo: Annotated[str | None, Field(description="Parte del titolo, senza distinguere maiuscole")] = None,
    stato: Annotated[
        Literal["bozza", "in_vendita", "vendite_chiuse", "annullato"] | None,
        Field(description="Filtra per stato dell'evento"),
    ] = None,
) -> RisultatoRicerca:
    eventi = repository.cerca_eventi(contesto.conn, titolo=titolo, stato=stato)
    return RisultatoRicerca(totale=len(eventi), eventi=eventi)
