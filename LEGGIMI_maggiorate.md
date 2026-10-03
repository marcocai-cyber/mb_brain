# Maggiorate EV+ — come funziona

Programmino per trovare le quote maggiorate **pagate in saldo reale** sui book ADM e capire quali sono davvero +EV.

## Avvio

Doppio clic su **`avvia_maggiorate.bat`**. Si apre la finestra "Maggiorate EV+":

1. A sinistra spunti i book da leggere (di default quelli attivi in `maggiorate_config.json`).
2. **▶ Leggi maggiorate + calcola EV**: legge i siti (2-5 minuti) e poi calcola fair ed EV.
3. Colori della tabella:
   - verde = EV+
   - grigio = EV negativo
   - azzurro = EV calcolato solo con la **stima** dalla quota barrata (vedi sotto)
   - giallo = fair mancante

   Click su una colonna per ordinare; **Solo EV+** e **anche stime** servono a filtrare.
4. Selezionando una riga, in basso vedi il post pronto, il dettaglio del calcolo e il testo letto dalla card.
5. **Copia post Telegram** copia i post delle righe selezionate (o di tutte le EV+ se non selezioni nulla).

Serve la stessa installazione dello scraper promozioni (`pip install playwright` + `playwright install chromium`), niente di nuovo.

## Sisal, Snai, PokerStars (e bet365, Admiralbet, Eplay24): estensione Chrome

Questi siti rifiutano il browser automatico dello scraper (anti-bot Akamai). Lo script non prova ad aggirarlo: le loro maggiorate le legge l'estensione **Lettore Maggiorate** dentro il tuo Chrome, cioè dalle pagine che apri tu.

**Installazione, una volta sola:**

1. In Chrome apri `chrome://extensions`.
2. Attiva **Modalità sviluppatore** (in alto a destra).
3. **Carica estensione non pacchettizzata** e scegli la cartella `estensione_maggiorate` (dentro questa cartella; la crea l'app al primo avvio).

**Uso** (con l'app Maggiorate EV+ aperta):

- Clicca l'icona dell'estensione e poi **Leggi Sisal, Snai e PokerStars**. Si aprono 3 schede in secondo piano, l'estensione legge le maggiorate, le schede si chiudono da sole dopo circa 25 secondi e l'app ricalcola l'EV.
- Oppure naviga normalmente su quei siti: la lettura è automatica su ogni pagina del book.
- **Leggi tutti i book con anti-bot** fa lo stesso anche per bet365, Admiralbet ed Eplay24.
- Se l'app è chiusa, le letture restano in coda nell'estensione e partono appena la riapri.

L'estensione parla solo con l'app sul tuo PC (`127.0.0.1`, porta 8765). Se l'app ti avvisa che i file dell'estensione sono cambiati, premi **Ricarica** su `chrome://extensions`.

## Da dove arriva la fair (in ordine)

1. **Fair inserita a mano**: doppio clic sulla riga (o **Imposta fair…**). Scrivi la fair (`2.45`) oppure back/lay letti sull'exchange (`2.40/2.46`). Ha sempre la precedenza.
2. **Mercato exchange diretto**: 1X2, doppia chance, over/under, goal/nogoal, risultato esatto (anche multiplo), parziale/finale, 1X2 + goal, over 1,5 primo tempo, combo "vincono tutte".
3. **Modello calibrato sull'exchange**, per i mercati speciali (`fair_speciali.py`).
   - Con 1X2, tutte le linee over/under, goal/nogoal, **risultato esatto**, over/under e **1X2 del primo tempo** di Betfair Exchange si calibra un modello di Poisson con correzione Dixon-Coles: gol attesi di casa e ospite, correzione dei punteggi bassi (dal risultato esatto) e quota di gol nel primo tempo.
   - Il modello calcola tempo per tempo multigol, gol range, over nei tempi, "segna in entrambi i tempi", "vince almeno un tempo", **"vince entrambi i tempi"**, **"in vantaggio a fine primo tempo"**, **"risultato x-y in qualsiasi momento"**, primo gol entro 15', e le combo dello stesso match (1 + over, X2 + over, over + goal, **My Combo** Snai/Sisal…), con la correlazione già dentro.
   - **Giocatori**: dal mercato marcatore dell'exchange si ricava la quota dei gol della squadra segnati dal giocatore. **Se l'exchange non lo quota** (succede quasi sempre con le nazionali) si usa il **Primo Marcatore del Betfair Sportsbook**: tolto il margine (metodo "power"), la quota di ogni giocatore dice quale parte dei gol della sua squadra segna; i gol attesi della squadra restano quelli dell'exchange. Coprono marcatore, doppietta, primo marcatore, marcatore + 1X2/doppia chance/parziale-finale, "segnano entrambi/tutti", goal o assist (con il mercato assist), ammonito e "gol o assist o ammonito" (con il mercato cartellino, solo exchange).
   - Se la card non dice la partita (DAZN "Tutti segnano", PokerStars "FRA-ITA"), la si ricava: codici delle nazionali, card gemelle Sisal/Snai/PokerStars con lo stesso testo, oppure cercando il giocatore tra i marcatori delle partite del giorno.
   - **Corner e cartellini totali**: dai mercati over/under dell'exchange; i **corner**, se mancano, dal Betfair Sportsbook. Considerati indipendenti dai gol.
   - **Combo su più partite** (Marathonbet, Fastbet, Betfair SuperCombo, DAZN): probabilità moltiplicate.
4. **STIMA dalla quota barrata**: si usa solo quando né l'exchange né il Sportsbook quotano quello che serve (assist e cartellini dei giocatori, tiri, rigore, 1X2 corner...) o quando Betfair non è configurato. La fair è la quota barrata senza un margine medio del book: `margine_speciali_pct` nel config, 10% di default per evento, che cresce con il numero di eventi della combo. È un'indicazione di massima: le righe sono azzurre e "EV+ (stima)" non conta come EV+.

- **EV%** = quota maggiorata × probabilità fair − 1.
- **EV% cons.** = lo stesso calcolo contro la quota lay (solo mercato diretto o back/lay manuali).

**Per i punti 2 e 3 serve Betfair:** premi **Betfair…** e inserisci app key, username e password. Restano solo in `betfair_credenziali.json` su questo PC (escluso da git). L'app key si crea gratis dall'account Betfair, sezione sviluppatori: va bene anche la "delayed". Senza credenziali tutte le fair automatiche diventano stime.

Se una squadra non viene trovata sull'exchange (nome diverso), aggiungila in `alias_squadre.json`.

**Ricerca della partita**: si usa la data della maggiorata, quindi "Belgio" del 02/10 è Belgio-Turchia e non Francia-Belgio del 05/10; "Irlanda" non viene più confusa con "Irlanda del Nord".

**Betfair Sportsbook** (`usa_sportsbook_betfair` nel config, attivo): viene aperto in un Chromium nascosto solo per le partite dove l'exchange non basta, una volta per partita, e le quote restano in `cache_sportsbook.json` per 30 minuti. Nel dettaglio della riga trovi "da primo marcatore Sportsbook @quota" quando è stato usato.

**Solo le maggiorate di oggi** (`solo_oggi` nel config, attivo): scraper, estensione e calcolo tengono solo le card con la data di oggi (riconosce `02/10`, `02/10/26`, `3 ott`, `Oggi`). Quelle senza data restano e si verifica la partita sull'exchange. Le partite **già iniziate** sono segnate "iniziata" e non hanno fair (le quote exchange sarebbero live).

## Book

La mappatura è in `maggiorate_config.json`, con la posizione del box di ogni book nella nota.

- **Scraper automatico**: Vincitu, Betfair Sportsbook (SuperCombo), William Hill, Bwin, Betsson, Marathonbet, DAZN Bet, Stake, Sunbet, NetBet, Fastbet, Codere.
- **Estensione Chrome** (`"lettura": "estensione"`): Sisal, Snai, PokerStars, bet365, Admiralbet, Eplay24.
- **Esclusi** (maggiorazione pagata in bonus): Goldbet, Lottomatica, Planetwin365, Betflag (MaxiQuote).
- **Zonagioco**: spento finché non si inserisce l'URL della sezione sport (riporta quasi sempre le maggiorate di Fastbet).

Per aggiungere un book basta una voce in `book` con `name`, `url` (la pagina dove compare il box), `pagamento: "reale"`, `attivo: true` e `mode`:

- `cards` = card con quota barrata o etichetta "maggiorata / super quota / boost";
- `list` = pagina dedicata dove ogni riga è una maggiorata.

Altri campi utili:

- `azioni`: se serve cliccare un tab prima di leggere, per esempio `[{"click_text": "Super Quote"}]`.
- `filtro_righe`: per scartare righe che non sono maggiorate.
- `lettura: "estensione"`: per i siti con anti-bot.

## Cose da sapere

- Le maggiorate dei book non letti in un run restano quelle del run precedente, marcate "(run precedente)". Quelle lette dall'estensione restano finché la stessa pagina non viene riletta (al massimo 12 ore).
- **Puntata massima**: viene letta dalla card quando c'è (Vincitu, Sunbet); altrimenti si usa `max_bet` del config (Sisal 100, Betfair 25, Vincitu 10, Sunbet 20).
- File prodotti, tutti esclusi da git:
  - `maggiorate.json`: lettura
  - `maggiorate_ev.json`: con fair ed EV
  - `maggiorate_report.html`: report da aprire nel browser
  - `maggiorate_manuali.json`: fair e maggiorate inserite a mano
- Uso da riga di comando:
  - `python scraper_maggiorate.py` (anche solo alcuni book: `python scraper_maggiorate.py Stake Sunbet`)
  - poi `python ev_maggiorate.py`
  - il ponte per l'estensione da solo: `python ponte_estensione.py`
- Test: `python tests/test_modello.py`, `tests/test_speciali.py`, `tests/test_precisione.py`, `tests/test_sportsbook_pagina.py`, `tests/test_ev.py`, `tests/test_parse.py`
