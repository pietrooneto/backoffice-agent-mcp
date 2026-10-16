"""Registro dei tool esposti dal server MCP (uno per file)."""
from . import (
    annulla_evento,
    anteprima_azione,
    cerca_eventi,
    chiudi_vendite_evento,
    dettaglio_evento,
    rimborsa_ordine,
    stato_ordine,
    storico_acquisti_cliente,
)

# Ogni modulo definisce NOME, DESCRIZIONE, ANNOTAZIONI ed esegui().
TOOLS = [
    cerca_eventi,
    dettaglio_evento,
    storico_acquisti_cliente,
    stato_ordine,
    chiudi_vendite_evento,
    annulla_evento,
    rimborsa_ordine,
]

# Tool usati solo dall'harness: il server li espone, ma l'harness non li mostra al modello.
TOOLS_SERVIZIO = [anteprima_azione]
