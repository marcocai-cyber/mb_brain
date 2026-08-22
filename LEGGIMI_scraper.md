# Pubblicare l'app online (accesso da telefono/ovunque, non solo Wi-Fi di casa)

Per usare l'app da smartphone senza doverla aprire dal PC, l'abbiamo collegata a **GitHub Pages**: un
hosting statico gratuito che pubblica `MatchBetting_Assistant.html` con un URL pubblico raggiungibile da
qualunque rete. Lo scraper continua a girare **sul PC di casa** come ha sempre fatto (è l'unico modo
per avere un IP italiano, necessario per non essere bloccati dai siti ADM — vedi più sotto): dopo ogni
esecuzione pubblica automaticamente il nuovo `promozioni.json`, così l'app online mostra sempre le promo
aggiornate su ogni dispositivo.

**Cosa ho già preparato io in questa cartella:**

- `index.html` — una pagina che reindirizza subito a `MatchBetting_Assistant.html`, così l'URL pubblico
  è corto e pulito (`https://marcocai-cyber.github.io/mb_brain/`) invece di dover scrivere il nome
  del file ogni volta.
- `.gitignore` — esclude dalla pubblicazione i file "di servizio" che non servono online
  (`scraper_log.txt`, `scraper_state.json`): nessun dato personale viene mai scritto su file (scommesse/
  conti/piano restano solo in `localStorage` nel browser), quindi non c'è nulla di sensibile da
  proteggere in questo repository.
- `scraper_promozioni.py` aggiornato: a fine di ogni run, se la cartella è collegata a un repository git
  (vedi setup sotto), pubblica automaticamente `promozioni.json` con `git add` + `commit` + `push`. Se il
  repository non è ancora collegato, o il push fallisce per qualsiasi motivo (rete assente, credenziali
  scadute...), lo script stampa solo un avviso nel log e **non si blocca**: lo scraping principale
  continua a funzionare comunque.

**Cosa devi fare tu, una tantum (circa 10-15 minuti — dopo non tocchi più nulla):**

Non posso creare un account GitHub o inserire le tue credenziali al posto tuo (per policy di sicurezza:
mai gestire password/token per conto dell'utente), quindi questi passaggi vanno fatti da te, direttamente
sul PC. Ho provato a preparare il repository automaticamente da qui, ma l'ambiente in cui lavoro ha un
limite tecnico nel gestire i file `git` su questa cartella condivisa (non riesce a rimuovere i file di
lock temporanei) — è per questo che il repository va inizializzato **direttamente dal tuo PC**, dove
questo problema non c'è. Se vedi una cartella `.git_da_eliminare_manualmente`, è un residuo innocuo di
quel tentativo: puoi cancellarla da Esplora File quando vuoi, non interferisce con nulla.

1. **Installa Git per Windows** se non ce l'hai già: apri il Prompt dei comandi e scrivi `git --version`;
   se dice comando non riconosciuto, scaricalo da [git-scm.com/download/win](https://git-scm.com/download/win)
   e installalo con le opzioni di default.
2. **Crea un account GitHub** se non ne hai già uno: [github.com/join](https://github.com/join), gratuito.
3. **Crea un nuovo repository**: su github.com clicca sul "+" in alto a destra → "New repository".
   ✅ Fatto: repository creato con il nome `mb_brain` (utente `marcocai-cyber`).
4. **Collega la cartella locale e fai la prima pubblicazione**: la cartella del progetto è
   `C:\Users\INDUSTRIAL TECH\Desktop\MatchBetting_Progetto_Completo` (quella con dentro
   `MatchBetting_Assistant.html`, `scraper_promozioni.py`, ecc. — la trovi sul Desktop). Aprila in
   Esplora File, poi apri il terminale già posizionato lì: tasto destro in un punto vuoto della
   cartella (non su un file) → "Apri nel Terminale" (oppure, su Windows meno recenti, "Apri finestra
   PowerShell qui"). Da lì esegui questi comandi uno alla volta:
   ```
   git config --global user.name "Marco"
   git config --global user.email "marcocairone.venaria@gmail.com"
   git init
   git add -A
   git commit -m "Prima pubblicazione"
   git branch -M main
   git remote add origin https://github.com/marcocai-cyber/mb_brain.git
   git push -u origin main
   ```
   Le prime due righe (`git config --global ...`) servono solo la primissima volta che usi git su
   questo PC: senza dire a git "chi sei", il comando `commit` fallisce silenziosamente e i comandi dopo
   (`push`) danno errore ("src refspec main does not match any") perché non c'è ancora nessun commit da
   spingere online — se ti capita, è quasi sempre questo il motivo.

   Al primo `git push`, Windows aprirà una finestra per accedere con il tuo account GitHub (Git
   Credential Manager): accedi lì, una volta sola — da quel momento le credenziali restano salvate sul PC
   e i push automatici dello scraper (dal task pianificato ogni 30 minuti) funzioneranno da soli, senza
   chiederti più nulla.
5. **Attiva GitHub Pages**: sul repository su github.com, vai su **Settings → Pages**. In "Source"
   scegli "Deploy from a branch", branch **main**, cartella **/ (root)**, poi Salva. Aspetta circa un
   minuto: l'URL pubblico apparirà in quella stessa pagina — sarà
   `https://marcocai-cyber.github.io/mb_brain/`.
6. **Testa dal telefono**: apri `https://marcocai-cyber.github.io/mb_brain/` dal browser dello
   smartphone — funziona su qualunque rete (dati mobili inclusi), non solo sul Wi-Fi di casa.

Dopo questi passaggi, tutto è automatico: ad ogni esecuzione dello scraper (ogni 30 minuti come già
configurato), `promozioni.json` viene pubblicato da solo e l'app online mostra sempre le promo più
recenti, su qualunque dispositivo.

**Limiti da tenere presenti:**

- **I dati personali non si sincronizzano tra dispositivi.** Scommesse segnate, conti, piano: restano
  in `localStorage`, quindi separati tra PC e telefono (come già succedeva aprendo l'app da due PC
  diversi). Per portare qualcosa da una parte all'altra usa il tab Backup → Esporta/Importa. Se in
  futuro vuoi anche questi dati sincronizzati automaticamente, serve un passo ulteriore (database cloud
  con un minimo di autenticazione) — dimmelo quando vuoi valutarlo.
- **Il sito è pubblico**: chiunque abbia il link `https://marcocai-cyber.github.io/mb_brain/` può
  aprirlo (GitHub Pages gratuito non ha un login integrato). Non è un problema per il catalogo promo
  (dati pubblici dei bookmaker), ma tienilo presente prima di condividere il link.
- **Il PC deve restare acceso** perché lo scraping e la pubblicazione avvengano — l'app resta comunque
  visitabile anche a PC spento, semplicemente mostrerà l'ultimo `promozioni.json` pubblicato fino alla
  prossima volta che il PC sarà acceso.
- **Se in futuro modifichiamo l'app stessa** (`MatchBetting_Assistant.html`), quell'aggiornamento non è
  automatico come per il JSON: serve un altro `git add -A && git commit -m "..." && git push` manuale
  (posso occuparmene io quando facciamo una modifica, se mi confermi che il repository è pronto).

## Portare l'app su un altro PC (tab "💾 Backup")

L'app salva scommesse, offerte, account e profilo nella memoria del browser **di questo PC**, non
dentro al file HTML: se apri lo stesso file su un altro computer parte vuoto. Per trasferire i dati:

1. Su questo PC, tab **Backup**: clicca "Esporta tutti i dati" → scarica `matchbetting_backup.json`.
2. Copia sia `MatchBetting_Assistant.html` sia `matchbetting_backup.json` (chiavetta USB, cloud,
   email) — e se usi lo scraper, anche `scraper_promozioni.py`, `scraper_config.json` e i `.bat`.
3. Sull'altro PC, apri l'HTML, vai su tab Backup e importa il file: "Unisci" aggiunge ai dati
   eventualmente già presenti, "Sostituisci tutto" li rimpiazza (utile su un PC vuoto).

# Lettura automatica delle promozioni — come funziona

## Perché serve uno script separato (e non è "magia" dentro l'app)

L'app (`MatchBetting_Assistant.html`) è un singolo file che gira nel tuo browser, senza server dietro.
I siti dei bookmaker ADM sono **geo-bloccati per legge ai soli IP italiani** e spesso protetti da
sistemi anti-bot. Ho verificato direttamente: da un server non italiano, siti come Sisal ed Eurobet
restituiscono errore di connessione. Per questo lo scraping deve girare **dal tuo computer**, con il
tuo IP italiano, non "nel cloud" in automatico.

Il flusso quindi è:

1. Esegui lo script Python `scraper_promozioni.py` sul tuo PC (una volta al giorno, per esempio).
2. Lo script visita le pagine promozioni dei bookmaker elencati in `scraper_config.json` e genera
   `promozioni.json`.
3. Apri `MatchBetting_Assistant.html` → tab **Offerte** → **Importa file** → seleziona
   `promozioni.json`. Le nuove promo vengono aggiunte automaticamente all'elenco (senza duplicati).

## Installazione (una tantum)

Serve Python 3 installato sul tuo computer. Poi, da terminale, nella cartella dove hai salvato i file:

```bash
pip install playwright beautifulsoup4
playwright install chromium
```

## Esecuzione

```bash
python scraper_promozioni.py
```

Vedrai a schermo, per ogni bookmaker, se sono state trovate promozioni o se il sito è stato saltato
(es. per login richiesto o protezione anti-bot). Al termine trovi `promozioni.json` nella cartella.

## Esecuzione automatica (ogni 30 minuti, dalle 9:00 alle 22:00)

Per non doverlo lanciare a mano, puoi registrarlo su Windows Task Scheduler:

1. Metti tutti i file (script, config, `.bat`) nella stessa cartella sul tuo PC.
2. Fai doppio click su `install_scheduled_task.bat`.
3. Fatto: da quel momento lo script gira da solo ogni 30 minuti, dalle 9:00 alle 22:00,
   tutti i giorni — anche a schermo bloccato, basta che il PC sia acceso e tu sia collegato
   (non serve salvare nessuna password).

Ogni esecuzione viene registrata in `scraper_log.txt` (nella stessa cartella), così puoi
controllare cosa è successo. Per fermarlo, fai doppio click su `disinstalla_scheduled_task.bat`,
oppure apri "Utilità di pianificazione" di Windows e disattiva/elimina il task
"MatchBettingScraper".

## Come riduco il rischio che un bookmaker mi blocchi l'IP?

Un controllo ogni 30 minuti, 13 ore al giorno, è un compromesso ragionevole ma non a rischio
zero. Lo script include già alcune protezioni automatiche:

- **Ritardo casuale**, non fisso, tra una richiesta e l'altra e prima di ogni partenza:
  un bot "perfettamente puntuale" è il pattern più facile da riconoscere.
- **Ordine casuale** dei bookmaker ad ogni esecuzione.
- **Browser reale** (Chromium via Playwright), non semplici richieste HTTP: si comporta più
  come un utente vero (esegue JavaScript, carica risorse, ecc.).
- **Backoff automatico**: se un bookmaker fallisce 3 volte di fila, lo script smette di
  contattarlo per 6 ore invece di continuare a insistere (lo vedrai segnalato come "in pausa"
  nel log).

Cose che puoi fare tu in più, se un bookmaker specifico ti sembra sospettoso o inizia a
bloccarti:

- Riduci la frequenza solo per quel bookmaker (rimuovilo dal config e tienilo per il
  controllo manuale).
- Allunga l'intervallo generale (es. ogni 60 minuti invece di 30) modificando `PT30M` in
  `ScraperTask.xml` prima di reinstallare il task.
- Non è possibile "ruotare l'IP" restando nei paletti legali: un proxy/VPN farebbe perdere
  proprio l'IP italiano necessario per accedere ai siti ADM. L'unica leva reale è la
  moderazione della frequenza, non il mascheramento.
- Nessuna di queste misure garantisce l'immunità da blocchi: restano scelte tecniche di
  buon senso, non una soluzione legale o definitiva.

## Cosa fare se un bookmaker smette di funzionare ("errore di caricamento" o "nessuna promo riconosciuta")

Dal 2026-08-16 lo script include due protezioni in più, aggiunte dopo aver verificato dal
vivo (con un browser reale) perché alcuni bookmaker fallivano:

- **Riprova automatica**: se un sito risponde con un errore "transitorio" (timeout,
  `ERR_HTTP2_PROTOCOL_ERROR`, connessione resettata...), lo script riprova fino a 2 volte
  con una pausa casuale prima di segnalarlo come fallito. Molti degli errori di rete visti
  finora erano proprio di questo tipo: il sito rispondeva normalmente al tentativo
  successivo.
- **Scroll automatico della pagina**: alcuni siti (es. Sisal, Snai, PokerStars, Goldbet,
  Lottomatica, Planetwin365) caricano le card delle promozioni solo quando entrano
  nell'inquadratura visibile (tecnica "lazy load"): senza scorrere la pagina, lo scraper le
  troverebbe vuote anche se i selettori configurati sono corretti. Ora lo script scorre
  automaticamente la pagina dall'alto in basso prima di leggerne il contenuto.

Se nonostante questo un bookmaker continua a dare "nessuna promo riconosciuta", lo script
salva automaticamente una copia della pagina che ha visto in `debug_pages/<nome-bookmaker>.html`
(un solo file per bookmaker, sovrascritto ad ogni run). Questa cartella non viene mai
pubblicata online (è esclusa dal `.gitignore`). Se capita, puoi semplicemente incollare il
nome del bookmaker in una conversazione con Claude e chiedere di controllare quel file: non
serve riaprire un browser, basta il file salvato.

## Immagine, link e slot (RTP/volatilità)

Ogni promozione rilevata ora include, quando disponibili:

- **Immagine**: presa dalla card della promo, o dall'immagine generale della pagina (og:image) se la
  card non ne ha una propria.
- **Link diretto**: alla promo specifica se trovato un link nella card, altrimenti alla pagina
  promozioni generale del bookmaker.
- **Slot idonee + RTP/volatilità**: lo script cerca nel testo della promo un elenco di slot (dopo
  frasi tipo "Slot idonee:", "Giochi partecipanti:", ecc.) e per ciascuna prova a recuperare RTP e
  volatilità tramite una ricerca web generica (funziona anche se il bookmaker stesso non pubblica
  questi dati, perché va a cercarli anche sui siti dei provider come Pragmatic Play, NetEnt, Play'n
  GO...).

**Limiti onesti di questa parte:**

- Il riconoscimento dei nomi delle slot dal testo è euristico: funziona bene se il bookmaker scrive
  un elenco chiaro, meno bene se il testo è scritto in modo diverso — in quel caso semplicemente non
  troverà nessuna slot candidata.
- Se RTP/volatilità non vengono trovati, la promozione viene marcata con **"ATTENZIONE: RTP/volatilità
  non trovati automaticamente"** direttamente nelle note, così lo sai sempre quando serve una verifica
  manuale.
- Per non appesantire troppo ogni esecuzione, le ricerche RTP sono limitate a poche slot per run
  (le altre vengono verificate nei run successivi).

## Tab "Strategia Slot" nell'app

Nuovo tab con le formule di targeting/rollover sui fun bonus:

- **Target** = Fun bonus × wagering × (1 − RTP/100) + max cap convertibile in reale.
- **Puntata fase Target** = Fun bonus ÷ 20.
- **Fase Rollover**: sempre alla puntata minima consentita dalla slot, su RTP alto e volatilità
  medio-bassa, fino a fine requisito.

Puoi collegare il calcolo a una promozione già salvata (auto-compila fun bonus, max cap, wagering e
RTP se lo scraper li ha trovati) oppure inserire tutto a mano. Il "max cap" viene rilevato dallo
scraper cercando frasi come "massimo convertibile"/"vincita massima convertibile" nel testo della
promo: se non lo trova, la promo viene marcata con un avviso e il campo va compilato a mano.

**Importante**: è un calcolo probabilistico basato sull'RTP dichiarato (perdita attesa nel lungo
periodo), non una previsione del singolo risultato. La varianza reale, soprattutto nella fase
Target con volatilità più alta, può discostarsi molto dalla media. Verifica sempre che il
bookmaker permetta questo tipo di utilizzo del bonus nei suoi termini — alcuni operatori
limitano o vietano l'uso di strategie di puntata "a target" sui bonus.

## Tab "Profilo & Piano"

Inserisci esperienza, budget, ore settimanali disponibili, propensione al rischio e guadagno
mensile desiderato: l'app genera un piano con split consigliato tra matched betting classico e
slot bonus hunting, esposizione massima per operazione, capacità stimata di offerte lavorabili
(limitata sia dal tuo tempo sia da un tetto di mercato realistico) e una stima di guadagno mensile
da confrontare con il tuo obiettivo.

Le "Ipotesi di mercato" (profitto medio per offerta, tetto di offerte disponibili) sono valori di
partenza modificabili — apri la sezione ⚙️ per adattarli alla tua esperienza reale: sono la parte
più incerta del calcolo, il resto (split, esposizione, capacità oraria) è aritmetica diretta sui
tuoi dati.

## Scaletta operativa (nel tab Profilo & Piano)

Dopo aver calcolato il piano, l'app genera automaticamente una scaletta prendendo le offerte
salvate nel tab Offerte e incrociandole con il piano:

- **Esclude** le offerte già completate/scadute o con scadenza passata, e quelle il cui valore
  supera l'esposizione massima consigliata.
- **Classifica** ogni offerta come matched betting o slot bonus hunting (in base al fatto che lo
  scraper le abbia rilevato o meno delle slot associate).
- **Alloca** le offerte rispettando lo split consigliato (es. 70% matched / 30% slot), fino alla
  capacità settimanale calcolata; se una categoria non ha abbastanza offerte disponibili, riempie i
  posti liberi con l'altra invece di sprecare capacità.
- **Ordina** per scadenza più vicina, mostrando bookmaker, valore, stake consigliato e link diretto
  alla promo.

Si aggiorna automaticamente ogni volta che premi "Calcola il mio piano" con le offerte presenti in
quel momento nel tab Offerte (manuali o importate dallo scraper).

## Filtri e cartelle per tipo di promo (dal 2026-08-16)

Dopo una revisione manuale dell'utente, lo script filtra molto di più prima di salvare una promo,
per ridurre il rumore:

- **Scartate sempre**: "porta un amico"/"invita un amico" (valore non garantito), quote maggiorate/
  potenziate (avranno una sezione dedicata in futuro), promo con classifica/torneo/leaderboard
  (premio a bacino condiviso tra i partecipanti, non un valore garantito per te), oltre alle
  esclusioni già esistenti (montepremi, bonus progressivo, rumore di navigazione/login/errori).
- **Scartate se il valore stimato è €0**: se lo script non riesce a individuare nessun importo
  economico nel testo, la promo viene scartata invece di essere mostrata a "€0" (spesso è rumore:
  link generici o testo troppo vago). Fa eccezione la famiglia bet365 "Ottieni un bonus di X€
  Aderisci" (bonus di partecipazione su una schedina): riconosciuta automaticamente e corretta a
  un valore fisso di 3€, che riflette il profitto medio reale verificato manualmente invece del
  valore di facciata mostrato dal bookmaker (che spesso risultava €0 perché scritto come "€5" con
  il simbolo prima del numero, non riconosciuto dal vecchio estrattore).
- **Auto-pulizia ad ogni run**: queste regole si applicano anche alle promo già salvate nei run
  precedenti, non solo a quelle nuove — quindi il file `promozioni.json` si "ripulisce" da solo nel
  tempo quando i filtri migliorano, senza dover aspettare che il sito smetta di proporle.

Ogni promo viene anche assegnata automaticamente a una **cartella** (campo `categoria`), visibile
nell'app come filtro nel tab Offerte:

- **Benvenuto**: bonus per nuovi clienti/prima registrazione/primo deposito.
- **Rimborso**: cashback, risk free, "ti rimborsiamo se perdi".
- **Ricorrenti**: tutto il resto (reload, bonus multipla, promo periodiche non legate alla
  registrazione).

Nell'app, il form per **aggiungere un'offerta a mano è stato rimosso**: le offerte arrivano solo
dallo scraper (tab "🔄 Aggiorna promozioni" → Importa). Restano invece i controlli su ogni card per
cambiare stato ed eliminare una singola offerta.

### Perché i T&C mancavano su molte promo (e come è stato corretto)

Il T&C completo viene scaricato dalla pagina di dettaglio della singola promo, seguendo il link
"Scopri di più"/"Dettagli" della card. Il problema era che su molti bookmaker (es. DAZN Bet,
Marathonbet, Betsson, StanleyBet...) quel link non veniva trovato: la card contiene spesso *più* di
un `<a>` (es. una "x" per chiudere un popup, un'immagine cliccabile che punta a "#"), e lo script
prendeva sempre il primo trovato — quasi mai quello giusto. Corretto scartando i link vuoti/"#"/
"javascript:" e preferendo quello il cui testo assomiglia a una call-to-action ("scopri", "dettagli",
"vai alla promo"...). Con questa correzione, i T&C dovrebbero iniziare a popolarsi sui prossimi run
(entro il budget di 40 nuove pagine di dettaglio per run — vedi sezione precedente).

## Attendibilità dei dati

Lo script prova prima selettori CSS specifici (se li aggiungi in `scraper_config.json`), altrimenti
usa un'estrazione **euristica** per parole chiave (bonus, free bet, cashback, quota maggiorata...).
Questo significa che:

- **Titolo e presenza della promo** sono affidabili come segnale ("c'è qualcosa di nuovo qui").
- **Valore, scadenza e requisiti di puntata** sono stime automatiche spesso imprecise: trattali come
  punto di partenza, poi verifica sempre sul sito del bookmaker prima di scommettere.

Se un bookmaker smette di funzionare (il sito cambia struttura), puoi migliorare la precisione
aggiungendo i selettori CSS esatti in `scraper_config.json` (tasto destro sulla pagina del bookmaker →
Ispeziona → individua la classe del blocco promozione).

## Aggiungere altri bookmaker ADM

Apri `scraper_config.json` e aggiungi una voce alla lista `bookmakers`:

```json
{ "name": "NomeBookmaker", "url": "https://.../promozioni", "card_selector": "", "title_selector": "" }
```

L'elenco incluso copre 41 operatori ADM: Sisal, Snai, Eurobet, Bet365, Goldbet, Planetwin365, StarVegas,
Betflag, William Hill, Lottomatica, Betfair Exchange, NetBet, Marathonbet, Bwin, LeoVegas, AdmiralBet,
Stake, Betsson, StanleyBet, DAZN Bet, Betpoint, Codere, Gioco Digitale, TotoSì, StarYes, Bgame, Casinò
di Sanremo, Casinò di Venezia, Vincitù, Giochi24, Gioca7, Eplay24, Betwin360, Sportium, Sunbet, Netwin,
Perlaplay, Domusbet, Sportbet, Quigioco, PokerStars — dopo il riordino delle concessioni ADM (nov. 2025)
sono rimasti 52 concessionari diretti: l'elenco ufficiale aggiornato è su adm.gov.it, aggiungi quelli
che ti interessano allo stesso modo.

### Due modalità di lettura del riepilogo: single-pass vs. detail_pages

Lo script legge il riepilogo delle promozioni in due modi diversi, a seconda del bookmaker. Su 41
bookmaker in config, **38 usano il metodo standard "single-pass"** e **3 usano "detail_pages"** (a due
passaggi). Non è una scelta stilistica: dipende da come ogni sito struttura fisicamente la pagina delle
promozioni.

**Single-pass (38 bookmaker, il metodo di default)** — Lo script apre **una sola volta** la pagina
indice (`url` nel config) e legge il riepilogo (titolo + importo sintetico) direttamente dalle card
promo trovate con `card_selector`/`title_selector` (o, se non configurati/non trovano nulla, con
l'estrazione euristica per parole chiave). Funziona perché su questi siti la card sull'indice contiene
già titolo + importo in testo semplice. È il metodo usato per tutti i bookmaker tranne i tre elencati
sotto, incluso PokerStars: benché sia un clone della stessa piattaforma di Sisal/Snai, quella
piattaforma scrive già il riepilogo direttamente nella card (`.cardBonusBenvenuto__button`/
`__subtitle`).

**Detail_pages (solo Eplay24, Betwin360, Sportium)** — Questi tre siti (stessa società, E-Play 24 Ita
Limited) sono un caso diverso: la card sull'indice `/promozioni` è **solo un banner-immagine**, senza
alcun testo estraibile dal DOM, e non hanno un'API JSON dietro al carosello (verificato controllando le
richieste di rete). Qui la pagina di dettaglio non è un arricchimento opzionale ma l'**unica fonte
possibile**, quindi la modalità `"mode": "detail_pages"` la visita sempre, per ognuna delle card trovate
sull'indice (max 15 per run, configurabile con `max_details`).

### Termini e condizioni completi per TUTTI i 41 bookmaker

La card sull'indice (in single-pass) riporta quasi sempre solo un riepilogo sintetico — "Bonus fino a
5.100€" — mentre i dati davvero necessari per il matched betting (quota minima, puntata minima,
wagering, tempistiche di erogazione, esclusioni) sono quasi sempre **solo nella pagina di dettaglio**
della singola promo. Verifica dal vivo su un campione (Sisal, Snai, Bwin, NetBet): la card indice di
Sisal "Scommesse: Bonus fino a 5.100€" non diceva nulla di operativo, mentre la pagina di dettaglio
collegata conteneva quota minima biglietto 10, minimo 5 eventi, ricarica minima 20€, e le tre tranche
di erogazione del bonus. Stesso riscontro su Snai (stessa piattaforma), Bwin (quota minima 2.00,
deposito minimo 20€, scommessa minima 10€, nascosti in un accordion "Condizioni di partecipazione") e
NetBet (wagering 10x sul fun bonus, 1x sul real bonus, win cap 40€, elenco giochi partecipanti).

Per questo lo script ora **arricchisce ogni promo, su tutti i 41 bookmaker**, con i T&C completi presi
dalla pagina di dettaglio collegata alla card (il link viene estratto automaticamente dalla card stessa:
sia da un normale `href`, sia — per piattaforme come NetBet/StanleyBet/Sunbet che aprono il link via
JavaScript — da un attributo `onclick="windowOpen('URL', ...)"`). Il testo va nel nuovo campo `terms` di
ogni promo (visibile in app col pulsante **📄 T&C** nella tab Offerte).

**Nota tecnica utile**: alcuni siti (es. Bwin) nascondono i T&C in un pannello "a comparsa" chiuso di
default (accordion CSS). Non serve simulare il click: il testo è comunque presente nell'HTML
renderizzato, ed essendo l'estrazione basata su BeautifulSoup (che legge il testo dal markup, non da
cosa è visibile a schermo), viene comunque catturato.

**Come si evita che questo appesantisca troppo lo scraping ogni 30 minuti — cache + budget, non un
salto di modalità:**

- **Cache incrementale**: ogni promo viene arricchita **una sola volta**. Se una promo (stesso
  bookmaker + stesso titolo) è già presente in `promozioni.json` con i T&C già scaricati, lo script
  riusa quelli senza rifare la richiesta. Solo le promo davvero nuove (mai viste prima) generano una
  richiesta aggiuntiva.
- **Budget per-run condiviso**: al massimo `MAX_ENRICH_PER_RUN = 40` nuove pagine di dettaglio vengono
  scaricate per l'arricchimento T&C in ogni singola esecuzione (in cima a `scraper_promozioni.py`,
  modificabile). Con al più 12 promo salvate per bookmaker × 38 bookmaker single-pass, il totale storico
  da arricchire è nell'ordine di poche centinaia — il primo "riempimento" di tutta la cache impiega
  quindi circa 6-8 esecuzioni (3-4 ore, dato l'intervallo di 30 minuti), poi va a regime: nei run
  successivi vengono arricchite solo le promo nuove del giorno, tipicamente pochissime, ben sotto il
  tetto di 40.
- **Nessun cambio all'intervallo di 30 minuti**: proprio grazie a cache + budget, anche durante il
  riempimento iniziale ogni run resta entro pochi minuti aggiuntivi (stimati 5-8 minuti in più nella
  fase di backfill, poi sostanzialmente zero a regime) — non c'è bisogno di allungare l'intervallo dello
  scheduled task.
- **Interruttore di sicurezza per singolo bookmaker**: `"enrich_terms": false` in una voce di
  `scraper_config.json` disattiva l'arricchimento solo per quel bookmaker (attivo su tutti per
  default), utile se in futuro un sito specifico desse problemi (pagine di dettaglio inutili, redirect
  loop...).

Le 3 promo in modalità `detail_pages` (Eplay24/Betwin360/Sportium) hanno i T&C popolati "gratis": la
pagina di dettaglio è già visitata come fonte primaria, quindi lo stesso testo viene riusato per il
campo `terms` senza una seconda richiesta.

Note su altri operatori valutati e non inclusi:
- Better è stato acquisito da Lottomatica e non è più un sito separato.
- 888sport (e quindi probabilmente 888casino, stessa società) usa un'architettura a iframe non
  compatibile con questo scraper.
- Winamax.it ha la concessione ADM ma il sito non è ancora online ("Prossimamente").
- BetPassion e Elabet non avevano, al momento del controllo, una pagina con una vera griglia di
  promozioni (solo testo SEO o pagina vuota): da riverificare in futuro, potrebbero cambiare.
- **StarCasinò/StarVegas**: `/promozioni` è stato riprovato il 2026-08-07 e dà ancora
  `ERR_TOO_MANY_REDIRECTS` — il problema è **confermato persistente**, non un errore temporaneo come
  ipotizzato in precedenza. Il config resta sulla homepage con estrazione euristica come miglior
  compromesso disponibile.
- **Betitaly**: pagina `/promozioni` è solo un testo descrittivo generale ("panoramica" dei bonus per
  categoria), nessuna griglia di card con promo singole da estrarre — ogni bonus ha una sua pagina
  dedicata ma non aggregata. Da riverificare se in futuro pubblicano un indice reale.
- **Fastbet**: pagina `/promo/bonus/index.html` ha solo 3 card (`.running-promo`), di cui 2 su 3 sono
  tornei a montepremi (scartati dal filtro) e 1 sola promo utilizzabile ("5€ per provare le slot"):
  volume troppo basso e instabile per giustificare una voce in config, da riconsiderare se il sito
  cambia struttura.
- **MyLotteries**: è un portale di verifica vincite Lotto/10eLotto/Gratta e Vinci, non un operatore
  con bonus/promozioni — nessuna sezione promo esistente.

Rimangono fuori dall'elenco anche gli operatori bingo-focused (es. Tombola.it).

## Nota legale — leggila prima di usarlo

Molti bookmaker vietano nei propri **Termini di Servizio** l'uso di strumenti automatizzati
(scraping/bot) sul loro sito, anche solo per leggere pagine pubbliche. Questo script è pensato per
**uso personale**, non per un servizio commerciale o richieste massive. Un controllo ogni
30 minuti è già un utilizzo moderatamente frequente: valuta se ti serve davvero per tutti i
bookmaker o solo per quelli con cui operi più spesso. Prima di usarlo su un bookmaker specifico:

- Controlla i Termini di Servizio/Condizioni d'uso di quel bookmaker.
- Evita di far girare lo script troppo frequentemente (rischio di blocco account o IP).
- Non è consulenza legale: se hai dubbi, valuta di limitarti alla lettura manuale delle promozioni
  (l'app supporta comunque l'inserimento manuale in ogni momento).
