// content.js — gira dentro la pagina del bookmaker (Sisal, Snai, Goldbet, ecc.)
// Stessa logica euristica di scraper_promozioni.py (extract_heuristic e dintorni),
// tradotta in JS: cerca blocchi di testo brevi che contengono parole chiave
// tipiche delle promozioni, usando il DOM gia' renderizzato dal TUO browser
// (quindi senza i problemi di anti-bot del browser automatico).

const MIN_SNIPPET_LEN = 20;
const MAX_SNIPPET_LEN = 220;
const MAX_ITEMS_PER_SITE = 12;

const SLOT_LIST_MARKERS = [
  "slot idonee", "slot partecipanti", "giochi partecipanti", "giochi idonei",
  "slot valide", "giochi validi", "slot selezionate", "slot incluse",
];
const SLOT_SECTION_MAX_CHARS = 600;
const MAX_SLOTS_PER_OFFER = 8;

const MAX_CAP_MARKERS = [
  "massimo convertibile", "massimo prelevabile", "vincita massima convertibile",
  "importo massimo prelevabile", "max cap", "cap massimo", "prelievo massimo",
  "vincita massima", "convertibile fino a",
];

const DEFAULT_KEYWORDS = [
  "bonus", "free bet", "scommessa gratis", "cashback", "quota maggiorata",
  "quota potenziata", "promo", "promozione", "welcome", "benvenuto",
  "ricarica", "reload", "gratis",
];

function getOgImage() {
  const tag = document.querySelector('meta[property="og:image"]');
  return tag ? tag.getAttribute("content") || "" : "";
}

function resolveUrl(href) {
  try {
    return new URL(href, location.href).href;
  } catch (e) {
    return "";
  }
}

function guessDeadline(text) {
  const m = text.match(/\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b/);
  if (!m) return "";
  let [, d, mo, y] = m;
  if (y.length === 2) y = "20" + y;
  return `${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}`;
}

function guessValue(text) {
  const m = text.match(/(\d{1,4})\s*(?:€|euro)/i);
  return m ? parseFloat(m[1]) : 0;
}

function extractMaxCap(text) {
  const low = text.toLowerCase();
  for (const marker of MAX_CAP_MARKERS) {
    const idx = low.indexOf(marker);
    if (idx === -1) continue;
    const win = text.slice(idx, idx + 60);
    const m = win.match(/(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)/i);
    if (m) {
      const n = parseFloat(m[1].replace(",", "."));
      if (!Number.isNaN(n)) return n;
    }
  }
  return null;
}

function extractCandidateSlots(text) {
  const low = text.toLowerCase();
  let found = [];
  for (const marker of SLOT_LIST_MARKERS) {
    const idx = low.indexOf(marker);
    if (idx === -1) continue;
    const start = idx + marker.length;
    let section = text.slice(start, start + SLOT_SECTION_MAX_CHARS);
    section = section.split(
      /\brequisito\b|\bvalido fino\b|\bwagering\b|\bmassima\b|\bmassimo\b|\bminima\b|\bminimo\b|\bconvertibil\w*\b|\bvincita\b/i
    )[0];
    const parts = section.split(/[,;•\n.]| e (?=[A-Z])/);
    for (let p of parts) {
      const name = p.trim().replace(/^[\s.:\-–—]+|[\s.:\-–—]+$/g, "");
      const lowName = name.toLowerCase();
      if (
        name.length >= 3 && name.length <= 40 &&
        !lowName.startsWith("entro") && !lowName.startsWith("requisito") &&
        !lowName.startsWith("il bonus")
      ) {
        found.push(name);
      }
    }
  }
  const seen = new Set();
  const unique = [];
  for (const n of found) {
    const key = n.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(n);
    }
  }
  return unique.slice(0, MAX_SLOTS_PER_OFFER);
}

function extractImageAndLink(card, ogImage) {
  let image = "";
  const img = card.querySelector ? card.querySelector("img") : null;
  if (img) {
    const src = img.getAttribute("src") || img.getAttribute("data-src") || "";
    if (src) image = resolveUrl(src);
  }
  if (!image && ogImage) image = ogImage;

  let link = "";
  const a = card.tagName === "A" ? card : (card.querySelector ? card.querySelector("a") : null);
  if (a && a.getAttribute("href")) link = resolveUrl(a.getAttribute("href"));
  if (!link) link = location.href;

  return { image, link };
}

function findContainer(el) {
  let container = el;
  for (let i = 0; i < 3; i++) {
    const parent = container.parentElement;
    if (parent && !["BODY", "HTML"].includes(parent.tagName)) {
      container = parent;
    } else break;
  }
  return container;
}

function extractHeuristic(keywords) {
  const found = [];
  const seen = new Set();
  const candidates = document.querySelectorAll("h1,h2,h3,h4,a,div,span,p");
  for (const el of candidates) {
    const text = (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ");
    if (!text || text.length < MIN_SNIPPET_LEN || text.length > MAX_SNIPPET_LEN) continue;
    const low = text.toLowerCase();
    if (!keywords.some((k) => low.includes(k))) continue;
    const key = low.slice(0, 80);
    if (seen.has(key)) continue;
    seen.add(key);
    found.push({ title: text.slice(0, 140), snippet: text.slice(0, MAX_SNIPPET_LEN), el: findContainer(el) });
    if (found.length >= MAX_ITEMS_PER_SITE) break;
  }
  return found;
}

// Card lette coi selettori CSS del sito (se configurati): piu' precise
// dell'euristica, che resta il fallback.
function extractWithSelectors(cardSel, titleSel) {
  const out = [];
  if (!cardSel) return out;
  let cards = [];
  try { cards = document.querySelectorAll(cardSel); } catch (e) { return out; }
  for (const c of cards) {
    const titleEl = titleSel ? c.querySelector(titleSel) : c;
    const text = (c.innerText || c.textContent || "").trim().replace(/\s+/g, " ");
    const title = ((titleEl && (titleEl.innerText || titleEl.textContent)) || text).trim().replace(/\s+/g, " ");
    if (!title || title.length < 4) continue;
    out.push({ title: title.slice(0, 140), snippet: text.slice(0, MAX_SNIPPET_LEN), el: c });
    if (out.length >= 40) break;
  }
  return out;
}

// Il riassunto per punti chiave, la scadenza, il rollover e il cap NON si
// calcolano qui: il testo grezzo (card + pagina di dettaglio, letta dal
// background) va al bridge Python, che usa riassunto_promo.py come lo scraper.
function estrai(keywords, bookName, sito) {
  const ogImage = getOgImage();
  let items = sito ? extractWithSelectors(sito.card_selector, sito.title_selector) : [];
  if (!items.length) items = extractHeuristic(keywords && keywords.length ? keywords : DEFAULT_KEYWORDS);
  const linkVisti = new Set();
  const out = [];
  for (const it of items) {
    const { image, link } = extractImageAndLink(it.el, ogImage);
    // piu' frammenti della stessa card puntano allo stesso dettaglio: una promo sola
    if (link !== location.href) {
      if (linkVisti.has(link)) continue;
      linkVisti.add(link);
    }
    const fullText = (it.el.innerText || it.el.textContent || "").trim();
    out.push({
      book: bookName,
      title: it.title,
      value: guessValue(it.snippet),
      deadline: "",
      wager: "",
      status: "Da iniziare",
      note: "",
      image,
      url: link,
      max_cap: null,
      slots: [],
      testo: fullText.slice(0, 4000),
    });
  }
  return out;
}


chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "ESTRAI") {
    chrome.storage.local.get(["keywords", "siti"], (cfg) => {
      const siti = cfg.siti || [];
      const match = siti.find(
        (s) => location.hostname === s.domain || location.hostname.endsWith("." + s.domain)
      );
      const bookName = match ? match.book : location.hostname;
      const items = estrai(cfg.keywords, bookName, match);
      sendResponse({ ok: true, host: location.hostname, book: bookName, url: location.href, items });
    });
    return true; // risposta asincrona
  }
});
