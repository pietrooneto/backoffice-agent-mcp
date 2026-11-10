# backoffice-agent-mcp

Agente AI di **back-office** per un'ipotetica piattaforma di ticketing online, realizzato come Project Work (traccia n. 26, CdS Informatica per le Aziende Digitali L-31, Università Pegaso): un **server MCP** espone le funzioni del sistema informativo come tool, e un **harness agentico** scritto a mano governa il ciclo del modello linguistico.

> Tutti i dati sono **sintetici**. Il sistema è generico e non riproduce schemi, API o regole di sistemi aziendali reali.

## Componenti

- `backend/`: base dati SQLite (`schema.sql`), generatore di dati sintetici (`seed.py`) e funzioni di accesso ai dati (`repository/`)
- `mcp_server/`: server MCP con otto tool per il modello (quattro di lettura, quattro di scrittura) e un nono tool di servizio, `anteprima_azione`, usato solo dall'harness e nascosto al modello; un file per tool in `tools/`
- `harness/`: ciclo agentico (`agent_loop.py`), astrazione del modello (`llm/`, interfaccia `LLMProvider` con Ollama e API compatibile OpenAI), conferma umana sulle scritture (`conferma.py`), log JSON Lines (`registro.py`), client MCP, interfaccia web (`web/`) e CLI
- `tests/`: test automatici (modello finto, server MCP vero)

## Requisiti

- Python 3.13 (verificato con 3.13.3)
- [Ollama](https://ollama.com) con un modello che supporti la chiamata di tool (provato: `qwen2.5:7b`)

Versioni delle dipendenze con cui il progetto e la suite sono stati verificati (Windows 11, Python 3.13.3): `mcp 2.3.0`, `mcp-types 2.3.0`, `pydantic 2.14.1`, `jsonschema 4.26.0`, `starlette 1.8.0`, `uvicorn 0.54.0`, `sse-starlette 3.5.0`, `anyio 4.15.1`, `pytest 9.1.1`. L'elenco completo è in [requirements-verificato.txt](requirements-verificato.txt); `requirements.txt` indica solo i limiti minimi, quindi per riprodurre esattamente l'ambiente verificato si usa `pip install -r requirements-verificato.txt`.

## Installazione

Windows (PowerShell):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
ollama pull qwen2.5:7b
python backend/seed.py
```

macOS e Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
ollama pull qwen2.5:7b
python backend/seed.py
```

Il progetto è stato provato solo su Windows 11: il codice non usa funzioni specifiche di Windows (il server MCP viene avviato con lo stesso interprete Python), ma su macOS e Linux non è stato eseguito.

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

Ogni sessione scrive un log strutturato in `logs/*.jsonl`.

## Come si usa

L'assistente è per gli operatori dell'assistenza e si scrive in italiano, come a un collega (la stessa guida compare nella pagina quando la chat è vuota).

- **Cosa sa fare:** cercare eventi, mostrare capienza e biglietti venduti, consultare lo storico di un cliente, vedere un ordine (letture, senza conferma). Può anche chiudere le vendite di un evento, riaprirle (solo per eventi a vendite chiuse e non ancora svolti), annullare un evento (rimborsa tutti gli ordini pagati) e rimborsare un ordine (scritture, sempre con conferma).
- **Come indicare l'evento o l'ordine nelle modifiche:** con il numero («chiudi le vendite dell'evento 12», «rimborsa l'ordine 596», «l'id dell'evento è 12», o solo «12» se rispondi a una domanda sull'evento) oppure con il titolo, aggiungendo città o data se più eventi hanno lo stesso titolo. Un numero senza la parola «id» («12 biglietti», «il 12 dicembre») o un messaggio che cita insieme evento e ordine non vanno bene, e in quel caso l'agente deve cercare l'id con i tool di lettura.
- **Conferma:** prima di ogni modifica compare la scheda «Serve la tua conferma» con tool, parametri e ciò che succederebbe (nomi, numeri, importi). Senza Conferma non cambia nulla; se premi Rifiuta la stessa azione non viene riproposta nella stessa richiesta.
- **Cosa non può fare:** riaprire un evento annullato o già svolto, rimettere in vendita una bozza, modificare dati dei clienti, rispondere a domande fuori dall'ambito (eventi, ordini, clienti).
- **Limiti:** il modello locale è piccolo e può sbagliare, scegliere l'azione sbagliata (per esempio chiudere invece di aprire) o fare domande poco chiare. Controlla sempre la scheda di conferma e il pannello dei dati. Se più eventi hanno lo stesso titolo, o la richiesta è ambigua («chiudi l'evento»: chiudere le vendite o annullare?), l'agente deve chiedere un chiarimento.
- **Tempi:** senza scheda grafica ogni passo richiede da 10 a 30 secondi, e il primo anche un minuto per caricare il modello.

Esempi: «quanti posti restano per la Rassegna Rock Club?», «quanti eventi ha comprato Daniele Esposito?», «chiudi le vendite dell'evento 12», «riapri le vendite dell'evento 5», «rimborsa l'ordine 596».

Il server MCP si può avviare anche da solo, per usarlo con altri client MCP:

```bash
python -m mcp_server
```

## Configurazione

Tutto in `.env` (vedi `.env.example`). Per cambiare modello basta `OLLAMA_MODEL`; per usare un altro server compatibile OpenAI, `LLM_PROVIDER=openai_compat` e `OPENAI_BASE_URL`. Il codice non cambia.

## Controlli dell'harness sulle scritture

Prima di chiedere la conferma per un tool di scrittura l'harness (1) verifica che gli id usati compaiano nei risultati dei tool oppure siano scritti dall'operatore in modo chiaro: accanto alla parola dell'entità («evento 12», «ordine 596», «cliente 7»), dopo la parola «id» («id: 1», «l'id è 12») o come solo numero in risposta a una domanda, purché nel messaggio (o nella domanda) compaia una sola entità tra evento, ordine e cliente. Se il messaggio non nomina nessuna entità, «il suo id è 12» vale per qualunque tipo di id: il tipo lo decide il tool che il modello chiama, e la scheda di conferma mostra il nome dell'evento o del cliente. «12 biglietti», «il 12 dicembre» o un messaggio con più entità non valgono come id, e un id di un tipo non vale per un altro (un numero d'ordine non è un id evento); e (2) chiede al server un'anteprima dell'azione: se le regole la vietano l'operatore non viene disturbato, altrimenti la scheda di conferma mostra che cosa succederà (nomi, numeri, importi). Il controllo sugli id verifica solo la provenienza del numero, non che l'entità sia quella voluta: la conferma dell'operatore resta necessaria. Anteprima ed esecuzione condividono le stesse regole, ma dati e orario possono cambiare durante l'attesa della conferma, quindi l'esecuzione ricontrolla le condizioni dentro la transazione. Si possono disattivare i controlli con `CONTROLLI_HARNESS=0`. L'anteprima usa il tool di servizio `anteprima_azione` del server MCP, che l'harness non mostra al modello.

Se l'operatore rifiuta un'azione, la stessa azione (stesso tool e stessi parametri) non viene riproposta nella stessa richiesta, anche se il modello insiste: il modello riceve «già rifiutata» e il turno termina con motivo `conferma_negata`. Una nuova richiesta dell'operatore può chiederla di nuovo.

## Log

Ogni sessione scrive `logs/*.jsonl`. La prima riga (`configurazione`) riporta variante del prompt, controlli attivi, modello, provider e limiti (mai chiavi API). Le righe `tool` conservano il risultato **integrale**; al modello va una versione abbreviata oltre 6.000 caratteri (campi `troncato_per_il_modello` e `caratteri_risultato`), e la pagina web ne mostra al più 2.000.

## Test

```bash
python -m pytest
```

I test non richiedono Ollama: usano un modello finto con risposte preparate e il vero server MCP su una copia del database.

## Stato

Completo per il Project Work (traccia n. 26): base dati, server MCP con otto tool per il modello e uno di servizio, harness agentico con interfaccia web e CLI e 170 test automatici. Il limite noto è quello del modello locale usato, piccolo e lento senza scheda grafica.

## Licenza

MIT, vedi [LICENSE](LICENSE).
