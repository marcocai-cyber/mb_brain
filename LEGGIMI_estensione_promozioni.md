# Lettore Promozioni — estensione Chrome

Legge le promozioni dai siti che blocca l'anti-bot quando lo scraper li apre
in automatico: **Sisal, Snai, Goldbet, StarVegas, StarCasino, Admiralbet,
Betwin360, Eplay24, Quigioco**. Il principio è lo stesso già usato per le
maggiorate: l'estensione legge la pagina **mentre la apri tu, nel tuo
Chrome**, usando la tua sessione normale — non c'è nessun browser automatico
da bloccare.

Nota: Betwin360 ed Eplay24 sono lo stesso gruppo (e-Play24 ITA Ltd) — li ho
tenuti come due entry separate perché hanno domini diversi.

`scraper_promozioni.py` ora salta questi 9 book in automatico (sono marcati
`"estensione": true` in `scraper_config.json`), così non spreca tentativi né
va in cooldown inutilmente.

Gli URL delle pagine promozioni e i selettori CSS delle card sono quelli
verificati sui siti reali e usati anche in `scraper_config.json` (es. Sisal e
Snai: `/bonus/bonus-benvenuto`; Goldbet: `/bonus/tutti`; Quigioco: `/promo`;
StarVegas non ha una pagina indice, quindi si legge la home). Con il
selettore la lettura è precisa; se non trova nulla si passa all'euristica per
parole chiave. Solo per StarCasino l'URL `/promozioni` non è ancora
verificato: se l'estensione non trova nulla, correggilo da "Gestisci siti".
Se avevi già installato l'estensione, gli URL vecchi vengono aggiornati da
soli al primo riavvio di Chrome (o con "Aggiorna" in `chrome://extensions`).

## Installazione (una tantum)

1. Apri `chrome://extensions` nel tuo Chrome.
2. Attiva "Modalità sviluppatore" (interruttore in alto a destra).
3. Clicca "Carica estensione non pacchettizzata" e seleziona la cartella
   `estensione_promozioni/`.
4. Fissa l'icona dell'estensione nella barra (icona puzzle in alto a destra
   di Chrome > spillo accanto a "Lettore Promozioni").

## Uso

1. Avvia il bridge locale con doppio click su
   `Avvia_Server_Estensione_Promozioni.bat` (resta aperto in background).
2. Due modi per leggere le promo:
   - **Pagina per pagina**: vai tu su una pagina promozioni (es.
     `sisal.it/scommesse/promozioni`), apri il popup dell'estensione, clicca
     "Leggi pagina corrente".
   - **Tutte insieme**: apri il popup su una scheda qualsiasi e clicca
     "Apri e leggi tutti i siti bloccati" — apre Sisal, Snai e Goldbet in
     schede di sfondo, legge ciascuna e le chiude da sola.
3. I risultati finiscono in `promozioni.json`, nella stessa cartella dello
   script. Importali come sempre: app > tab Offerte > "Importa da file".

## Aggiungere un nuovo sito (es. un clone scoperto più avanti)

Apri il popup > "Gestisci siti / parole chiave" > inserisci nome book,
dominio (es. `pokerstars.it`) e URL della pagina promozioni > "Aggiungi
sito". Chrome chiederà il permesso per quel dominio: accettalo. Da quel
momento anche quel sito compare nel pulsante "Apri e leggi tutti".

## Limiti da sapere

- L'estrazione è euristica (stessa logica dello scraper): titoli/valori/
  scadenze vanno comunque controllati prima di scommettere, come per i dati
  letti dallo scraper.
- Il bridge deve essere avviato mentre usi l'estensione, altrimenti il
  popup segnala "bridge non raggiungibile".
- Se Sisal/Goldbet cambiano struttura pagina, l'euristica potrebbe smettere
  di trovare le card: lo stesso problema che già avete con i selettori CSS
  vuoti nello scraper.

## Riassunto delle promo e promo scadute

Sia lo scraper sia l'estensione:

- aprono anche la **pagina di dettaglio** di ogni promo, perché rollover,
  cap, quote e scadenze di solito stanno lì e non nella card della lista;
- scrivono nel campo note un **riassunto per punti** (Attivazione,
  Qualificante, Requisito giocata, Bonus, Dove spenderlo, Rollover / cap,
  Real bonus, Scadenze). Un punto compare solo se è stato trovato nel testo;
- compilano da soli scadenza, wagering (es. `35x`), valore bonus e max cap;
- **scartano le promo già scadute** (data di fine passata, o "promozione
  terminata") e non le scrivono nel file;
- usano le stesse regole dello scraper per categoria (Benvenuto / Rimborso /
  Ricorrenti) e filtri: tra i benvenuto restano solo sport e slot, e le
  promo senza importo vengono scartate.

Le promo di un book che non compaiono più quando rileggi la sua pagina con
l'estensione passano nella cartella "Scaduti" dell'app e vengono cancellate
dal file dopo 14 giorni. Una promo letta con l'estensione e non più
riconfermata per 7 giorni (perché non hai riaperto quel book) viene
anch'essa segnata come scaduta: conviene usare "Apri e leggi tutti i siti
bloccati" almeno una volta a settimana.

La logica del riassunto sta in `riassunto_promo.py`, quella di storico e
scadenze in `scraper_promozioni.py`: devono restare nella stessa cartella di
`ponte_promozioni.py`.

Una promo senza data di fine leggibile viene tenuta (meglio una promo in
più da controllare che una buona persa). Se su un book la lettura delle
pagine di dettaglio dà problemi, nello scraper puoi spegnerla con
`"enrich_terms": false` nella sua voce di `scraper_config.json`.
