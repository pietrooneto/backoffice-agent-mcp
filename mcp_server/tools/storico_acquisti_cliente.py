"""Tool di lettura: storico degli acquisti di un cliente, con gestione degli omonimi."""
from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend import repository
from backend.repository import NonTrovato, ParametroNonValido, RichiestaAmbigua

from ..contesto import contesto
from ..errori import tool_sicuro

NOME = "storico_acquisti_cliente"
DESCRIZIONE = (
    "Storico acquisti di un cliente: riepilogo (ordini, eventi acquistati, biglietti validi, spesa in "
    "centesimi) e ultimi ordini. Cerca per nome e cognome oppure, se noto, per cliente_id. "
    "Se esistono clienti omonimi risponde con un errore che li elenca: chiedi all'operatore quale intende."
)
ANNOTAZIONI = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class Cliente(BaseModel):
    id: int
    nome: str
    cognome: str
    email: str


class Riepilogo(BaseModel):
    ordini_totali: int
    ordini_pagati: int
    eventi_acquistati: int
    biglietti_validi: int
    speso_centesimi: int


class OrdineSintesi(BaseModel):
    ordine_id: int
    evento_id: int
    evento_titolo: str
    data_evento: str
    settore: str
    quantita: int
    totale_centesimi: int
    stato: Literal["pagato", "rimborsato", "annullato"]
    creato_il: str


class StoricoCliente(BaseModel):
    cliente: Cliente
    riepilogo: Riepilogo
    ultimi_ordini: list[OrdineSintesi]
    ordini_mostrati: int


@tool_sicuro(NOME)
def esegui(
    nome: Annotated[str | None, Field(description="Nome del cliente")] = None,
    cognome: Annotated[str | None, Field(description="Cognome del cliente")] = None,
    cliente_id: Annotated[
        int | None, Field(ge=1, description="Id del cliente, se gia' noto (ha la precedenza su nome e cognome)")
    ] = None,
) -> StoricoCliente:
    conn = contesto.conn
    if cliente_id is None:
        if not (nome or "").strip() and not (cognome or "").strip():
            raise ParametroNonValido("Indica nome e cognome del cliente, oppure il suo cliente_id.")
        trovati = repository.trova_clienti(conn, nome=nome, cognome=cognome)
        if not trovati:
            raise NonTrovato(f"Nessun cliente trovato con nome '{nome or ''}' e cognome '{cognome or ''}'.")
        if len(trovati) > 1:
            elenco = "; ".join(f"id {c['id']}: {c['nome']} {c['cognome']} ({c['email']})" for c in trovati)
            raise RichiestaAmbigua(
                f"Trovati {len(trovati)} clienti corrispondenti: {elenco}. "
                "Chiedi all'operatore quale intende, poi richiama il tool con cliente_id."
            )
        cliente_id = trovati[0]["id"]
    return StoricoCliente(**repository.storico_cliente(conn, cliente_id))
