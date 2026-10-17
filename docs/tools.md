# Documentazione dei tool del server MCP

Generata da `docs/genera_tools.py` leggendo i tool veri del server e, per gli esempi, eseguendo chiamate reali sul database sintetico (una copia nuova per ogni esempio, data di riferimento 2026-11-01 12:00). Nei risultati di esempio gli elenchi lunghi sono ridotti ai primi due elementi (`…`).

Il server espone **otto tool**: sette per il modello (quattro di lettura e tre di scrittura) e uno di servizio, `anteprima_azione`, che usa solo l'harness e che non viene mai mostrato al modello. I tool di scrittura sono riconosciuti dall'harness dal metadato standard MCP `readOnlyHint = false` e richiedono sempre la conferma dell'operatore. Gli errori previsti (non trovato, stato non valido, fuori termine, parametri non validi, richiesta ambigua) tornano al modello come risultato di errore (`is_error`) con un messaggio in italiano.

## `cerca_eventi`

**Tipo:** lettura · **readOnlyHint:** True

**Descrizione:** Cerca eventi per titolo (anche parziale) e/o stato. Restituisce id, titolo, luogo, data e stato. Piu' eventi possono avere lo stesso titolo: se ne trovi piu' di uno, chiedi quale intende l'operatore.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `titolo` | string | no | Parte del titolo, senza distinguere maiuscole |
| `stato` | `bozza` / `in_vendita` / `vendite_chiuse` / `annullato` | no | Filtra per stato dell'evento |

**Risultato (campi)**

- `totale`: integer
- `eventi`: elenco di oggetto (id, titolo, luogo, data_evento, stato)

**Effetti sui dati:** Nessuno: sola lettura.

**Esempio di invocazione**

```json
{
  "tool": "cerca_eventi",
  "parametri": {
    "titolo": "cabaret"
  }
}
```

Risultato:

```json
{
  "totale": 1,
  "eventi": [
    {
      "id": 12,
      "titolo": "Serata Cabaret",
      "luogo": "Cagliari, Teatro Mediterraneo",
      "data_evento": "2026-11-25 21:00:00",
      "stato": "in_vendita"
    }
  ]
}
```

## `dettaglio_evento`

**Tipo:** lettura · **readOnlyHint:** True

**Descrizione:** Dettaglio di un evento: stato, capienza, biglietti venduti e disponibili, per settore e in totale. I prezzi sono in centesimi di euro. Richiede l'id dell'evento (usa cerca_eventi per trovarlo).

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `evento_id` | integer (min 1) | sì | Id dell'evento |

**Risultato (campi)**

- `id`: integer
- `titolo`: string
- `luogo`: string
- `data_evento`: string
- `stato`: string
- `settori`: elenco di oggetto (settore_id, nome, capienza, prezzo_centesimi, venduti, disponibili)
- `capienza_totale`: integer
- `venduti_totali`: integer
- `disponibili_totali`: integer

**Effetti sui dati:** Nessuno: sola lettura.

**Esempio di invocazione**

```json
{
  "tool": "dettaglio_evento",
  "parametri": {
    "evento_id": 12
  }
}
```

Risultato:

```json
{
  "id": 12,
  "titolo": "Serata Cabaret",
  "luogo": "Cagliari, Teatro Mediterraneo",
  "data_evento": "2026-11-25 21:00:00",
  "stato": "in_vendita",
  "settori": [
    {
      "settore_id": 22,
      "nome": "Platea",
      "capienza": 90,
      "prezzo_centesimi": 2600,
      "venduti": 37,
      "disponibili": 53
    },
    {
      "settore_id": 23,
      "nome": "Balconata",
      "capienza": 50,
      "prezzo_centesimi": 2000,
      "venduti": 22,
      "disponibili": 28
    }
  ],
  "capienza_totale": 140,
  "venduti_totali": 59,
  "disponibili_totali": 81
}
```

## `storico_acquisti_cliente`

**Tipo:** lettura · **readOnlyHint:** True

**Descrizione:** Storico acquisti di un cliente: riepilogo (ordini, eventi acquistati, biglietti validi, spesa in centesimi) e ultimi ordini. Cerca per nome e cognome oppure, se noto, per cliente_id. Se esistono clienti omonimi risponde con un errore che li elenca: chiedi all'operatore quale intende.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `nome` | string | no | Nome del cliente |
| `cognome` | string | no | Cognome del cliente |
| `cliente_id` | integer (min 1) | no | Id del cliente, se gia' noto (ha la precedenza su nome e cognome) |

**Risultato (campi)**

- `cliente`: oggetto (id, nome, cognome, email)
- `riepilogo`: oggetto (ordini_totali, ordini_pagati, eventi_acquistati, biglietti_validi, speso_centesimi)
- `ultimi_ordini`: elenco di oggetto (ordine_id, evento_id, evento_titolo, data_evento, settore, quantita, totale_centesimi, stato, creato_il)
- `ordini_mostrati`: integer

**Effetti sui dati:** Nessuno: sola lettura.

**Esempio di invocazione**

```json
{
  "tool": "storico_acquisti_cliente",
  "parametri": {
    "nome": "Daniele",
    "cognome": "Esposito"
  }
}
```

Risultato:

```json
{
  "cliente": {
    "id": 7,
    "nome": "Daniele",
    "cognome": "Esposito",
    "email": "daniele.esposito@example.com"
  },
  "riepilogo": {
    "ordini_totali": 39,
    "ordini_pagati": 26,
    "eventi_acquistati": 8,
    "biglietti_validi": 65,
    "speso_centesimi": 246800
  },
  "ultimi_ordini": [
    {
      "ordine_id": 674,
      "evento_id": 11,
      "evento_titolo": "Festival della Birra Artigianale",
      "data_evento": "2026-11-14 12:00:00",
      "settore": "Ingresso",
      "quantita": 2,
      "totale_centesimi": 2400,
      "stato": "rimborsato",
      "creato_il": "2026-10-30 17:22:00"
    },
    {
      "ordine_id": 720,
      "evento_id": 12,
      "evento_titolo": "Serata Cabaret",
      "data_evento": "2026-11-25 21:00:00",
      "settore": "Platea",
      "quantita": 1,
      "totale_centesimi": 2600,
      "stato": "pagato",
      "creato_il": "2026-10-30 05:27:00"
    },
    "…"
  ],
  "ordini_mostrati": 10
}
```

## `stato_ordine`

**Tipo:** lettura · **readOnlyHint:** True

**Descrizione:** Stato e dettaglio di un ordine: cliente, evento, settore, quantita', totale in centesimi, biglietti ed eventuali rimborsi. Richiede l'id dell'ordine.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `ordine_id` | integer (min 1) | sì | Id dell'ordine |

**Risultato (campi)**

- `ordine_id`: integer
- `stato`: string
- `quantita`: integer
- `totale_centesimi`: integer
- `creato_il`: string
- `cliente_id`: integer
- `cliente_nome`: string
- `cliente_cognome`: string
- `evento_id`: integer
- `evento_titolo`: string
- `data_evento`: string
- `evento_stato`: string
- `settore`: string
- `biglietti`: dizionario nome → numero
- `rimborsi`: elenco di oggetto (importo_centesimi, motivo, creato_il)

**Effetti sui dati:** Nessuno: sola lettura.

**Esempio di invocazione**

```json
{
  "tool": "stato_ordine",
  "parametri": {
    "ordine_id": 596
  }
}
```

Risultato:

```json
{
  "ordine_id": 596,
  "stato": "pagato",
  "quantita": 2,
  "totale_centesimi": 8400,
  "creato_il": "2026-09-19 01:27:00",
  "cliente_id": 58,
  "cliente_nome": "Davide",
  "cliente_cognome": "Greco",
  "evento_id": 10,
  "evento_titolo": "Balletto del Lago",
  "data_evento": "2027-02-10 20:30:00",
  "evento_stato": "in_vendita",
  "settore": "Platea",
  "biglietti": {
    "valido": 2
  },
  "rimborsi": []
}
```

## `chiudi_vendite_evento`

**Tipo:** scrittura · **readOnlyHint:** False · **destructiveHint:** False

**Descrizione:** SCRITTURA. Chiude le vendite di un evento in vendita: nessun nuovo acquisto, gli ordini esistenti restano validi e non viene rimborsato nulla. NON annulla l'evento (per quello esiste annulla_evento). Funziona solo su eventi in stato 'in_vendita'.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `evento_id` | integer (min 1) | sì | Id dell'evento di cui chiudere le vendite |

**Risultato (campi)**

- `evento_id`: integer
- `titolo`: string
- `stato_precedente`: string
- `stato_nuovo`: string

**Effetti sui dati:** `eventi.stato` passa da `in_vendita` a `vendite_chiuse`; una riga in `audit_log`. Gli ordini restano validi e non si rimborsa nulla. Reversibile in pratica.

**Esempio di invocazione**

```json
{
  "tool": "chiudi_vendite_evento",
  "parametri": {
    "evento_id": 12
  }
}
```

Risultato:

```json
{
  "evento_id": 12,
  "titolo": "Serata Cabaret",
  "stato_precedente": "in_vendita",
  "stato_nuovo": "vendite_chiuse"
}
```

## `annulla_evento`

**Tipo:** scrittura (alto impatto) · **readOnlyHint:** False · **destructiveHint:** True

**Descrizione:** SCRITTURA AD ALTO IMPATTO. Annulla un evento e rimborsa per intero TUTTI gli ordini pagati. Da non confondere con chiudi_vendite_evento: usalo solo se l'operatore chiede esplicitamente di annullare l'evento. Non funziona su eventi gia' annullati o gia' svolti.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `evento_id` | integer (min 1) | sì | Id dell'evento da annullare |

**Risultato (campi)**

- `evento_id`: integer
- `titolo`: string
- `stato_precedente`: string
- `stato_nuovo`: string
- `ordini_rimborsati`: integer
- `biglietti_rimborsati`: integer
- `totale_rimborsato_centesimi`: integer

**Effetti sui dati:** `eventi.stato` passa ad `annullato`; per ogni ordine pagato dell'evento `ordini.stato` e `biglietti.stato` passano a `rimborsato` e si inserisce una riga in `rimborsi` (motivo «evento annullato»); una riga in `audit_log`. Tutto in una sola transazione: o riesce per intero o non cambia nulla. Alto impatto.

**Esempio di invocazione**

```json
{
  "tool": "annulla_evento",
  "parametri": {
    "evento_id": 12
  }
}
```

Risultato:

```json
{
  "evento_id": 12,
  "titolo": "Serata Cabaret",
  "stato_precedente": "in_vendita",
  "stato_nuovo": "annullato",
  "ordini_rimborsati": 26,
  "biglietti_rimborsati": 59,
  "totale_rimborsato_centesimi": 140200
}
```

## `rimborsa_ordine`

**Tipo:** scrittura · **readOnlyHint:** False · **destructiveHint:** True

**Descrizione:** SCRITTURA. Rimborsa per intero un singolo ordine pagato (pagamento solo simulato). Consentito solo se all'evento mancano almeno 48 ore; altrimenti risponde con un errore.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `ordine_id` | integer (min 1) | sì | Id dell'ordine da rimborsare |
| `motivo` | string (lunghezza min 1, lunghezza max 200) | no | Motivo del rimborso Predefinito: `richiesta del cliente`. |

**Risultato (campi)**

- `ordine_id`: integer
- `evento_titolo`: string
- `importo_rimborsato_centesimi`: integer
- `motivo`: string
- `stato_ordine`: string

**Effetti sui dati:** `ordini.stato` e `biglietti.stato` dell'ordine passano a `rimborsato`; una riga in `rimborsi` per l'intero importo; una riga in `audit_log`. Consentito solo fino a 48 ore prima dell'evento.

**Esempio di invocazione**

```json
{
  "tool": "rimborsa_ordine",
  "parametri": {
    "ordine_id": 596,
    "motivo": "richiesta del cliente"
  }
}
```

Risultato:

```json
{
  "ordine_id": 596,
  "evento_titolo": "Balletto del Lago",
  "importo_rimborsato_centesimi": 8400,
  "motivo": "richiesta del cliente",
  "stato_ordine": "rimborsato"
}
```

## `anteprima_azione`

**Tipo:** servizio per l'harness · **readOnlyHint:** True

**Descrizione:** Servizio per l'harness, non per il modello. Dato un tool di scrittura e i suoi parametri, dice se le regole lo permettono e descrive l'effetto (nomi, numeri, importi) senza modificare nulla.

**Parametri di ingresso**

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `tool` | `chiudi_vendite_evento` / `annulla_evento` / `rimborsa_ordine` | sì | Tool di scrittura da simulare |
| `parametri` | object | sì | Parametri che il modello vorrebbe usare |

**Risultato (campi)**

- `ammessa`: boolean
- `riepilogo`: string
- `motivo`: string

**Effetti sui dati:** Nessuno: sola lettura. Tool di servizio per l'harness, nascosto al modello.

**Esempio di invocazione**

```json
{
  "tool": "anteprima_azione",
  "parametri": {
    "tool": "annulla_evento",
    "parametri": {
      "evento_id": 12
    }
  }
}
```

Risultato:

```json
{
  "ammessa": true,
  "riepilogo": "Annullare l'evento «Serata Cabaret» (Cagliari, Teatro Mediterraneo, 25/11/2026 21:00) e rimborsare per intero 26 ordini pagati (59 biglietti), in totale 1.402,00 euro.",
  "motivo": null
}
```
