"""Errori di dominio del livello di accesso ai dati.

I messaggi sono scritti in italiano e pensati per essere letti dal modello:
dicono cosa e' andato storto e, quando serve, cosa fare.
"""


class ErroreDominio(Exception):
    """Base di tutti gli errori previsti dalle regole di business."""


class NonTrovato(ErroreDominio):
    """L'entita' richiesta (evento, ordine, cliente) non esiste."""


class StatoNonValido(ErroreDominio):
    """L'operazione non e' consentita nello stato attuale dell'entita'."""


class FuoriTermine(ErroreDominio):
    """Il rimborso e' richiesto oltre il termine consentito."""


class ParametroNonValido(ErroreDominio):
    """Un parametro ha un valore non accettabile."""
