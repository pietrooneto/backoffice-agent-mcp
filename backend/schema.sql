-- Schema della piattaforma di ticketing (dati interamente sintetici).
-- Importi in centesimi (interi) per evitare errori di arrotondamento.
-- Date/ore in formato ISO 8601 (testo).

PRAGMA foreign_keys = ON;

CREATE TABLE clienti (
    id        INTEGER PRIMARY KEY,
    nome      TEXT NOT NULL,
    cognome   TEXT NOT NULL,
    email     TEXT NOT NULL UNIQUE,
    creato_il TEXT NOT NULL
);
CREATE INDEX idx_clienti_cognome_nome ON clienti (cognome, nome);

CREATE TABLE eventi (
    id          INTEGER PRIMARY KEY,
    titolo      TEXT NOT NULL,
    luogo       TEXT NOT NULL,
    data_evento TEXT NOT NULL,
    stato       TEXT NOT NULL
                CHECK (stato IN ('bozza', 'in_vendita', 'vendite_chiuse', 'annullato')),
    creato_il   TEXT NOT NULL
);
CREATE INDEX idx_eventi_titolo ON eventi (titolo);

CREATE TABLE settori (
    id               INTEGER PRIMARY KEY,
    evento_id        INTEGER NOT NULL REFERENCES eventi (id),
    nome             TEXT NOT NULL,
    capienza         INTEGER NOT NULL CHECK (capienza > 0),
    prezzo_centesimi INTEGER NOT NULL CHECK (prezzo_centesimi >= 0),
    UNIQUE (evento_id, nome)
);

-- Semplificazione: un ordine riguarda un solo settore di un solo evento.
CREATE TABLE ordini (
    id               INTEGER PRIMARY KEY,
    cliente_id       INTEGER NOT NULL REFERENCES clienti (id),
    settore_id       INTEGER NOT NULL REFERENCES settori (id),
    quantita         INTEGER NOT NULL CHECK (quantita BETWEEN 1 AND 10),
    totale_centesimi INTEGER NOT NULL CHECK (totale_centesimi >= 0),
    stato            TEXT NOT NULL
                     CHECK (stato IN ('pagato', 'rimborsato', 'annullato')),
    creato_il        TEXT NOT NULL
);
CREATE INDEX idx_ordini_cliente ON ordini (cliente_id);
CREATE INDEX idx_ordini_settore ON ordini (settore_id);

CREATE TABLE biglietti (
    id        INTEGER PRIMARY KEY,
    ordine_id INTEGER NOT NULL REFERENCES ordini (id),
    codice    TEXT NOT NULL UNIQUE,
    stato     TEXT NOT NULL CHECK (stato IN ('valido', 'rimborsato'))
);
CREATE INDEX idx_biglietti_ordine ON biglietti (ordine_id);

-- Il pagamento e' solo simulato: nessuna integrazione con circuiti reali.
CREATE TABLE rimborsi (
    id                INTEGER PRIMARY KEY,
    ordine_id         INTEGER NOT NULL REFERENCES ordini (id),
    importo_centesimi INTEGER NOT NULL CHECK (importo_centesimi > 0),
    motivo            TEXT NOT NULL,
    creato_il         TEXT NOT NULL
);
CREATE INDEX idx_rimborsi_ordine ON rimborsi (ordine_id);

-- Traccia lato server delle operazioni di scrittura eseguite dai tool.
CREATE TABLE audit_log (
    id             INTEGER PRIMARY KEY,
    quando         TEXT NOT NULL,
    ruolo          TEXT,
    tool           TEXT NOT NULL,
    parametri_json TEXT NOT NULL,
    esito          TEXT NOT NULL
);
