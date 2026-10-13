# backoffice-agent-mcp

Agente AI di **back-office** per un'ipotetica piattaforma di ticketing online, realizzato come Project Work (traccia n. 26, CdS Informatica per le Aziende Digitali L-31, Università Pegaso): un **server MCP** espone le funzioni del sistema informativo come tool, e un **harness agentico** scritto a mano governa il ciclo del modello linguistico.

> Tutti i dati sono **sintetici**. Il sistema è generico e non riproduce schemi, API o regole di sistemi aziendali reali.

## Componenti

- `backend/`: base dati relazionale (SQLite) e accesso ai dati
- `mcp_server/`: server MCP con i tool (lettura e scrittura)
- `harness/`: ciclo agentico, astrazione del modello (`LLMProvider`), conferma umana sulle scritture, log strutturato JSON Lines, CLI
- `tests/`: test automatici e scenari in linguaggio naturale
- `docs/`: diagrammi UML/ER, documentazione dei tool, diario di sviluppo

## Installazione ed esecuzione

*Da completare man mano che il codice viene scritto.*

Requisiti: Python 3.13+, [Ollama](https://ollama.com) (opzionale, per il modello locale).

```bash
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env
```

## Stato

Work in progress.

## Licenza

MIT, vedi [LICENSE](LICENSE).
