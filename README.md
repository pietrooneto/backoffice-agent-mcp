# backoffice-agent-mcp

Agente AI di **back-office** per un'ipotetica piattaforma di ticketing online, realizzato come Project Work (traccia n. 26, CdS Informatica per le Aziende Digitali L-31, Università Pegaso): un **server MCP** espone le funzioni del sistema informativo come tool, e un **harness agentico** scritto a mano governa il ciclo del modello linguistico.

> Tutti i dati sono **sintetici**. Il sistema è generico e non riproduce schemi, API o regole di sistemi aziendali reali.

## Componenti

- `backend/`: base dati SQLite (`schema.sql`), generatore di dati sintetici (`seed.py`) e funzioni di accesso ai dati (`repository/`)
- `mcp_server/`: server MCP con sette tool (quattro di lettura, tre di scrittura), uno per file in `tools/`
- `harness/`: ciclo agentico (`agent_loop.py`), astrazione del modello (`llm/`, interfaccia `LLMProvider` con Ollama e API compatibile OpenAI), conferma umana sulle scritture (`conferma.py`), log JSON Lines (`registro.py`), client MCP, interfaccia web (`web/`) e CLI
- `tests/`: test automatici (modello finto, server MCP vero)
- `docs/`: diagrammi e documentazione

## Requisiti

- Python 3.13
- [Ollama](https://ollama.com) con un modello che supporti la chiamata di tool (provato: `qwen2.5:7b`)

## Installazione

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
ollama pull qwen2.5:7b
python backend/seed.py
```

`seed.py` crea `backend/ticketing.db` con dati sintetici sempre identici (seme fisso).

## Esecuzione

Interfaccia web (avvia da sola il server MCP come processo figlio), poi apri http://127.0.0.1:8000 nel browser:

```bash
python -m harness.web
```

La pagina mostra in tempo reale i passi dell'agente e, accanto alla chat, un pannello di **sola lettura** con tre schede (eventi, movimenti, registro delle modifiche) per controllare i dati e vedere l'effetto di ogni modifica. Quando l'agente vuole modificare i dati compare una scheda con tool e parametri e l'esecuzione resta ferma finché non premi **Conferma** o **Rifiuta**. Il server ascolta solo su `127.0.0.1` (porta modificabile con `WEB_PORT`) e rifiuta richieste provenienti da altri siti.

In alternativa, chat nel terminale:

```bash
python -m harness.cli
```

Esempi di richieste (valgono per entrambe le interfacce): «quanti posti restano per la Rassegna Rock Club?», «quanti eventi ha comprato Daniele Esposito?», «chiudi le vendite della Serata Cabaret». Prima di ogni modifica ai dati l'agente chiede conferma e mostra tool e parametri. Ogni sessione scrive un log strutturato in `logs/*.jsonl`.

Il server MCP si può avviare anche da solo, per usarlo con altri client MCP:

```bash
python -m mcp_server
```

## Configurazione

Tutto in `.env` (vedi `.env.example`). Per cambiare modello basta `OLLAMA_MODEL`; per usare un altro server compatibile OpenAI, `LLM_PROVIDER=openai_compat` e `OPENAI_BASE_URL`. Il codice non cambia.

## Test

```bash
python -m pytest
```

I test non richiedono Ollama: usano un modello finto con risposte preparate e il vero server MCP su una copia del database.

## Stato

Work in progress.

## Licenza

MIT, vedi [LICENSE](LICENSE).
