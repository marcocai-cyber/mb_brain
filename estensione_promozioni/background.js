// background.js — orchestratore: apre le pagine, chiede l'estrazione al
// content script, invia i risultati al bridge locale (ponte_promozioni.py).
// Il fetch verso 127.0.0.1 va fatto da qui (service worker) e non dal
// content script: nella pagina del bookmaker il content script e' soggetto
// alla Content-Security-Policy del sito, che spesso blocca le richieste
// verso domini esterni/localhost.

const BRIDGE_URL = "http://127.0.0.1:8766/promozioni";

const DEFAULT_KEYWORDS = [
  "bonus", "free bet", "scommessa gratis", "cashback", "quota maggiorata",
  "quota potenziata", "promo", "promozione", "welcome", "benvenuto",
  "ricarica", "reload", "gratis",
];

// URL e selettori CSS verificati sui siti reali (gli stessi di
// scraper_config.json). Con card_selector la lettura e' precisa; senza, si
// usa l'euristica per parole chiave.
const DEFAULT_SITI = [
  { domain: "sisal.it", book: "Sisal", url: "https://www.sisal.it/bonus/bonus-benvenuto",
    card_selector: ".cardBonusBenvenuto__button", title_selector: ".cardBonusBenvenuto__subtitle" },
  { domain: "snai.it", book: "Snai", url: "https://www.snai.it/bonus/bonus-benvenuto",
    card_selector: ".cardBonusBenvenuto__button", title_selector: ".cardBonusBenvenuto__subtitle" },
  { domain: "goldbet.it", book: "Goldbet", url: "https://www.goldbet.it/bonus/tutti",
    card_selector: "article.promo--item", title_selector: ".promo--title" },
  { domain: "starvegas.it", book: "StarVegas", url: "https://www.starvegas.it/" },
  { domain: "starcasino.it", book: "StarCasino", url: "https://www.starcasino.it/promozioni" },
  { domain: "admiralbet.it", book: "Admiralbet", url: "https://www.admiralbet.it/promozioni",
    card_selector: ".big-card-promotion", title_selector: ".promo-card-title" },
  { domain: "betwin360.it", book: "Betwin360", url: "https://betwin360.it/promozioni",
    card_selector: "a[href*='/promozione/']" },
  { domain: "eplay24.it", book: "Eplay24", url: "https://eplay24.it/promozioni",
    card_selector: "a[href*='/promozione/']" },
  { domain: "quigioco.it", book: "Quigioco", url: "https://www.quigioco.it/promo",
    card_selector: ".promoCard", title_selector: ".promoCard__title" },
];

// URL della prima versione dell'estensione (alcuni davano 404 o redirect
// infinito): se l'utente non li ha cambiati a mano, vengono aggiornati.
const URL_VECCHI = [
  "https://www.sisal.it/scommesse/promozioni", "https://www.snai.it/promozioni",
  "https://www.goldbet.it/promozioni", "https://www.starvegas.it/promozioni",
  "https://www.betwin360.it/promozioni", "https://www.eplay24.it/promozioni",
  "https://www.quigioco.it/promozioni",
];

// gia' nel manifest (content_scripts statici), non serve registrarli di nuovo
const DOMINI_STATICI = [
  "sisal.it", "snai.it", "goldbet.it", "starvegas.it", "starcasino.it",
  "admiralbet.it", "betwin360.it", "eplay24.it", "quigioco.it",
];

chrome.runtime.onInstalled.addListener(initStorage);
chrome.runtime.onStartup.addListener(initStorage);

function initStorage() {
  chrome.storage.local.get(["keywords", "siti"], (cfg) => {
    const toSet = {};
    if (!cfg.keywords) toSet.keywords = DEFAULT_KEYWORDS;
    if (!cfg.siti) {
      toSet.siti = DEFAULT_SITI;
    } else {
      // aggiornamento: URL vecchi -> verificati, e selettori per i siti di default
      let cambiato = false;
      const siti = cfg.siti.map((s) => {
        const def = DEFAULT_SITI.find((d) => d.domain === s.domain);
        if (!def) return s;
        const nuovo = { ...s };
        if (URL_VECCHI.includes(s.url)) { nuovo.url = def.url; cambiato = true; }
        if (def.card_selector && !s.card_selector) {
          nuovo.card_selector = def.card_selector;
          nuovo.title_selector = def.title_selector || "";
          cambiato = true;
        }
        return nuovo;
      });
      if (cambiato) toSet.siti = siti;
    }
    if (Object.keys(toSet).length) chrome.storage.local.set(toSet);

    chrome.storage.local.get(["siti"], (cfg2) => {
      const extra = (cfg2.siti || []).filter((s) => !DOMINI_STATICI.includes(s.domain));
      for (const s of extra) registraContentScript(s.domain);
    });
  });
}

async function registraContentScript(domain) {
  try {
    await chrome.scripting.unregisterContentScripts({ ids: [domain] }).catch(() => {});
    await chrome.scripting.registerContentScripts([
      {
        id: domain,
        matches: [`https://*.${domain}/*`, `https://${domain}/*`],
        js: ["content.js"],
        runAt: "document_idle",
      },
    ]);
  } catch (e) {
    console.warn("Registrazione content script fallita per", domain, e);
  }
}

async function postToBridge(book, items) {
  if (!items.length) return { ok: true, salvate: 0, scadute: 0 };
  try {
    const res = await fetch(BRIDGE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Lettore-Promozioni": "1" },
      body: JSON.stringify({ book, items }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return { ok: true, salvate: data.salvate ?? items.length, scadute: data.scadute ?? 0 };
  } catch (e) {
    return { ok: false, errore: `bridge non raggiungibile (${String(e)}) — hai avviato ponte_promozioni.py?` };
  }
}

function chiediEstrazione(tabId) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, { type: "ESTRAI" }, (risposta) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, errore: chrome.runtime.lastError.message });
      } else {
        resolve(risposta || { ok: false, errore: "nessuna risposta dalla pagina" });
      }
    });
  });
}

const MAX_DETTAGLI_PER_SITO = 8;

function pausa(min, max) {
  return new Promise((r) => setTimeout(r, min + Math.random() * (max - min)));
}

// Apre la pagina di dettaglio di una promo in una scheda di sfondo e ne legge
// il testo principale: e' li' che stanno rollover, cap, quote e scadenze.
async function leggiDettaglio(url) {
  let tab;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    await attendiCaricamento(tab.id);
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const main = document.querySelector("main, article, [role=main]") || document.body;
        return (main.innerText || "").slice(0, 12000);
      },
    });
    return (res && res.result) || "";
  } catch (e) {
    return "";
  } finally {
    if (tab) chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function arricchisciConDettagli(items, paginaUrl) {
  let host = "";
  try { host = new URL(paginaUrl).hostname; } catch (e) {}
  let letti = 0;
  for (const it of items) {
    if (letti >= MAX_DETTAGLI_PER_SITO) break;
    if (!it.url || it.url === paginaUrl) continue;
    try {
      if (new URL(it.url).hostname !== host) continue;
    } catch (e) { continue; }
    await pausa(1500, 4000);
    it.testo_dettaglio = await leggiDettaglio(it.url);
    letti++;
  }
  return items;
}

async function leggiPaginaCorrente() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return { ok: false, errore: "nessuna scheda attiva" };
  const risposta = await chiediEstrazione(tab.id);
  if (!risposta.ok) return risposta;
  await arricchisciConDettagli(risposta.items, risposta.url);
  const esito = await postToBridge(risposta.book, risposta.items);
  return {
    ok: esito.ok,
    book: risposta.book,
    trovate: risposta.items.length,
    salvate: esito.salvate,
    scadute: esito.scadute,
    errore: esito.errore,
  };
}

function attendiCaricamento(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let finito = false;
    function fine() {
      if (finito) return;
      finito = true;
      chrome.tabs.onUpdated.removeListener(listener);
      setTimeout(resolve, 1500); // margine per contenuti lazy-load
    }
    function listener(id, info) {
      if (id === tabId && info.status === "complete") fine();
    }
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(fine, timeoutMs); // pagina che non finisce mai di caricare: si legge quel che c'e'
  });
}

async function leggiTutte() {
  const { siti } = await chrome.storage.local.get(["siti"]);
  const log = [];
  for (const sito of siti || []) {
    try {
      const tab = await chrome.tabs.create({ url: sito.url, active: false });
      await attendiCaricamento(tab.id);
      const risposta = await chiediEstrazione(tab.id);
      await chrome.tabs.remove(tab.id).catch(() => {});
      if (!risposta.ok) {
        log.push({ book: sito.book, ok: false, errore: risposta.errore });
        continue;
      }
      await arricchisciConDettagli(risposta.items, risposta.url);
      const esito = await postToBridge(risposta.book, risposta.items);
      log.push({
        book: sito.book, ok: esito.ok,
        trovate: risposta.items.length, salvate: esito.salvate, scadute: esito.scadute, errore: esito.errore,
      });
    } catch (e) {
      log.push({ book: sito.book, ok: false, errore: String(e) });
    }
  }
  return log;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "LEGGI_PAGINA_CORRENTE") {
    leggiPaginaCorrente().then(sendResponse);
    return true;
  }
  if (msg && msg.type === "LEGGI_TUTTE") {
    leggiTutte().then(sendResponse);
    return true;
  }
  if (msg && msg.type === "AGGIUNGI_DOMINIO") {
    (async () => {
      const origini = [`https://*.${msg.domain}/*`, `https://${msg.domain}/*`];
      const concesso = await chrome.permissions.request({ origins: origini });
      if (!concesso) {
        sendResponse({ ok: false, errore: "permesso negato" });
        return;
      }
      await registraContentScript(msg.domain);
      const { siti } = await chrome.storage.local.get(["siti"]);
      const nuovi = (siti || []).filter((s) => s.domain !== msg.domain);
      nuovi.push({ domain: msg.domain, book: msg.book || msg.domain, url: msg.url || `https://${msg.domain}` });
      await chrome.storage.local.set({ siti: nuovi });
      sendResponse({ ok: true });
    })();
    return true;
  }
});
