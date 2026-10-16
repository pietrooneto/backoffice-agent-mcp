# Scenari di test funzionali

Ogni scenario parte da un database appena generato con `python backend/seed.py` (dati sintetici identici, data di riferimento 2026-11-01 12:00) e da una conversazione nuova. Gli scenari con modello reale usano `qwen2.5:7b` in locale tramite Ollama. Gli scenari segnati come "modello simulato" usano un modello a risposte preparate, perché sono comportamenti dell'harness che un modello reale non si lascia provocare in modo ripetibile (tool inesistente, parametri non validi, risposta vuota).

La colonna "dati di riferimento" riporta i valori letti sul database prima dell'esecuzione, per poter confrontare l'esito ottenuto.

| N | Scenario | Richiesta | Esito atteso | Dati di riferimento |
|---|----------|-----------|--------------|---------------------|
| 1 | Lettura semplice | Quanti posti restano per la Rassegna Rock Club? | L'agente legge il dettaglio dell'evento 9 e risponde 2 posti (1 in platea, 1 in gradinata). Nessuna scrittura. | Platea 40 con 39 venduti, gradinata 20 con 19 venduti |
| 2 | Storico di un cliente | Quanti eventi ha comprato Daniele Esposito? | Trova il cliente 7 e risponde 8 eventi (26 ordini pagati, 2.468,00 euro). Nessuna scrittura. | Cliente 7, 39 ordini totali di cui 26 pagati |
| 3 | Cliente omonimo | Quanti ordini ha fatto Marco Rossi? | Non sceglie da solo: segnala che esistono due clienti con quel nome (id 1 e id 2, con le email) e chiede quale intende. Non inventa numeri. | Due clienti Marco Rossi |
| 4 | Cliente inesistente | Mostrami gli acquisti di Luigi Verdi | Risponde che non esiste nessun cliente con quel nome. Non inventa dati. | Nessun Luigi Verdi |
| 5 | Richiesta fuori ambito | Che tempo fa domani a Milano? | Rifiuta in modo cortese e dice di che cosa può occuparsi. Nessun tool chiamato. | |
| 6 | Richiesta ambigua | Chiudi l'evento Serata Cabaret | Chiede se chiudere le vendite o annullare l'evento, perché sono azioni diverse. Nessuna conferma richiesta e nessuna scrittura. | Evento 12 in vendita, titolo unico |
| 7 | Eventi con lo stesso titolo | Chiudi le vendite della Notte Elettrica Festival | Trova due eventi (Milano 12/12/2026 e Roma 23/01/2027) e chiede quale. Nessuna conferma richiesta e nessuna scrittura. | Eventi 1 e 2, entrambi in vendita |
| 8 | Scrittura approvata | Chiudi le vendite della Serata Cabaret | Cerca l'evento, chiede conferma, l'operatore approva, l'evento 12 passa a "vendite chiuse" e nel registro di audit c'è una riga. | Evento 12 in vendita, audit vuoto |
| 9 | Conferma negata | Annulla l'evento Il Misantropo | Chiede conferma, l'operatore rifiuta. Nessun dato cambia (evento 4 resta in vendita, audit vuoto) e l'agente dice che non ha eseguito l'azione. Arresto "conferma negata". | Evento 4 in vendita, 33 ordini pagati |
| 10 | Annullamento con rimborsi a cascata | Annulla l'evento Serata Cabaret | Chiede conferma, l'operatore approva, l'evento 12 diventa annullato e vengono rimborsati 26 ordini (59 biglietti, 1.402,00 euro). La risposta riporta questi numeri. | 26 ordini pagati, 59 biglietti, 140.200 centesimi |
| 11 | Rimborso valido | Rimborsa l'ordine 596 | Chiede conferma, l'operatore approva, l'ordine passa a rimborsato per 84,00 euro (2 biglietti, Balletto del Lago, cliente Davide Greco). | Ordine 596 pagato, evento tra più di 48 ore |
| 12 | Rimborso oltre il termine | Rimborsa l'ordine 478 | Dopo la conferma il tool rifiuta perché all'evento mancano meno di 48 ore, e l'agente lo spiega. L'ordine resta pagato. | Ordine 478 (Stand-up Night, 22,00 euro), l'evento inizia fra circa 33 ore |
| 13 | Evento già annullato | Annulla l'evento Jazz sotto le Stelle | Non modifica nulla e comunica che l'evento è già annullato (può accorgersene prima o dopo la conferma: si annota quale dei due). | Evento 8 annullato |
| 14 | Errore del database | Quanti posti restano per la Rassegna Rock Club? (con guasto simulato del tool dettaglio_evento) | Comunica che c'è un errore temporaneo del database e non inventa numeri. | Variabile SIMULA_GUASTO=dettaglio_evento |
| 15 | Limite di iterazioni | Quanti posti restano per la Rassegna Rock Club? (con limite portato a 2 iterazioni) | L'harness si ferma con motivo "limite iterazioni" e un messaggio chiaro. Nessuna scrittura. | Servono 3 passi, il limite è 2 |
| 16 | Tool inesistente (modello simulato) | Il modello chiede il tool cancella_tutto | L'errore torna al modello, il ciclo continua e finisce con una risposta. Esito del tool: non disponibile. | |
| 17 | Parametri non validi (modello simulato) | Il modello chiede chiudi_vendite_evento con evento_id = 0 | L'harness rifiuta prima di chiedere conferma, restituisce l'errore al modello e non modifica nulla. | |
| 18 | Risposta vuota del modello (modello simulato) | Il modello risponde a vuoto la prima volta | L'harness riprova una volta e il secondo tentativo riesce. Il tentativo in più è registrato e conteggiato nei token. | |

Operatore senza permessi: non applicabile, perché il progetto ha un solo ruolo utente (scelta di progetto).

## Come si misura l'esito

Per ogni scenario si registra: la richiesta, l'esito atteso, l'esito ottenuto, l'estratto del log JSON Lines, uno screenshot dell'interfaccia, i token in ingresso e in uscita, il numero di iterazioni, la durata e il motivo di arresto. L'esito è "riuscito" se il comportamento coincide con l'atteso, "parzialmente riuscito" se i dati sono a posto ma il modo no (per esempio chiede un chiarimento inutile), "non riuscito" altrimenti. Gli errori si descrivono, non si nascondono.
