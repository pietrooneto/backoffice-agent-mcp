"""Livello di accesso ai dati: funzioni che ricevono una connessione SQLite."""
from .clienti import storico_cliente, trova_clienti
from .db import connetti, connetti_sola_lettura, percorso_db
from .errors import (
    ErroreDominio,
    FuoriTermine,
    NonTrovato,
    ParametroNonValido,
    RichiestaAmbigua,
    StatoNonValido,
)
from .eventi import annulla_evento, cerca_eventi, chiudi_vendite_evento, dettaglio_evento
from .ordini import TERMINE_RIMBORSO_ORE, rimborsa_ordine, stato_ordine

__all__ = [
    "connetti", "connetti_sola_lettura", "percorso_db",
    "cerca_eventi", "dettaglio_evento", "chiudi_vendite_evento", "annulla_evento",
    "trova_clienti", "storico_cliente",
    "stato_ordine", "rimborsa_ordine", "TERMINE_RIMBORSO_ORE",
    "ErroreDominio", "NonTrovato", "StatoNonValido", "FuoriTermine", "ParametroNonValido",
    "RichiestaAmbigua",
]
