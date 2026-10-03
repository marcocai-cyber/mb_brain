#!/usr/bin/env python3
"""
Scraper quote maggiorate (vincita in saldo reale) sui book ADM
=============================================================
Da eseguire SUL TUO COMPUTER (serve un IP italiano, come scraper_promozioni.py).

Cosa fa:
  1. Legge maggiorate_config.json e apre, con un browser headless (Playwright),
     la pagina di ogni book con "attivo": true e "pagamento": "reale".
     I book che pagano la maggiorazione in bonus vengono sempre saltati.
  2. Esegue le eventuali "azioni" del book (click su un tab, filtri).
  3. Cerca le maggiorate con un estrattore generico che gira dentro la pagina:
       - modalita' "cards": ogni quota BARRATA (line-through) o ogni etichetta
         "maggiorata / super quota / boost" individua una card; si risale fino
         al blocco che contiene evento, mercato e quote, senza inglobare le
         card vicine. Funziona anche dentro lo shadow DOM (es. Stake).
       - modalita' "list": la pagina e' una categoria dedicata (Marathonbet,
         Fastbet, Betfair SuperCombo): ogni riga con una quota e' una maggiorata.
  4. Ricava da ogni card: evento, mercato/descrizione, quota barrata, quota
     maggiorata, puntata massima, condizioni. Scarta le multiple.
  5. Scrive tutto in maggiorate.json (letto da ev_maggiorate.py e dall'app
     maggiorate_app.py).

Come lo scraper promozioni, NON prova ad aggirare le protezioni anti-bot: se un
sito rifiuta il browser automatico il book viene segnalato "bloccato dal sito"
e le sue maggiorate si possono aggiungere a mano dall'app.

Installazione (una tantum, se non l'hai gia' fatta per scraper_promozioni.py):
    pip install playwright
    playwright install chromium

Esecuzione:
    python scraper_maggiorate.py                 (tutti i book attivi)
    python scraper_maggiorate.py Sisal Stake     (solo i book indicati)
"""

import hashlib
import json
import queue
import random
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # l'import vero serve solo per lo scraping, non per il parsing/test
    sync_playwright = None


HERE = Path(__file__).parent
CONFIG_PATH = HERE / "maggiorate_config.json"
OUTPUT_PATH = HERE / "maggiorate.json"
DEBUG_DIR = HERE / "debug_pages"

PARALLEL_WORKERS = 3
PAGE_TIMEOUT_MS = 30000
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BLOCKED_PAGE_MARKERS = [
    "<title>access denied</title>", "errors.edgesuite.net",
    "you don't have permission to access",
]
BLOCKED_ERROR_MARKERS = ["err_http2_protocol_error"]

# Estrattore eseguito dentro la pagina (vedi docstring). Ritorna una lista di
# {why, text, cls, struck}: 'text' e' il testo visibile della card, una riga
# per elemento; 'struck' sono le quote barrate trovate nella card.
EXTRACT_JS = r"""
(opts) => {
  opts = opts || {};
  const ODD = /^\s*\d{1,4}[.,]\d{1,3}\s*$/;
  const ODDG = /(?<![\d.,])\d{1,4}[.,]\d{2}(?![\d])/g;
  const KW = new RegExp(opts.keyword || "maggiorat|super\\s?quot|boost|quota\\s?top|potenziat", "i");
  const MAXLEN = opts.maxLen || 600;
  const GR = opts.mode === 'list' ? /(segnano tutt|segneranno tutt|tutti segnano|tutte over|tutte goal|vincono tutt|vinceranno tutt|all teams winners|tutti marcatori)/i : null;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden' && (r.width > 0 || r.height > 0); };
  const isStruck = el => { for (let e = el, i = 0; e && i < 3; e = e.parentElement, i++) { const t = getComputedStyle(e).textDecorationLine || ''; if (t.includes('line-through') || ['S', 'DEL', 'STRIKE'].includes(e.tagName)) return true; } return false; };
  const ownText = el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const cards = new Map();
  const leafText = (node) => {
    const out = [];
    const walk = (n) => {
      for (const ch of n.childNodes) {
        if (ch.nodeType === 3) { const t = ch.textContent.trim(); if (t) out.push(t); }
        else if (ch.nodeType === 1) {
          const s = getComputedStyle(ch);
          if (s.display === 'none' || s.visibility === 'hidden') continue;
          if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(ch.tagName)) continue;
          walk(ch.shadowRoot || ch);
        }
      }
    };
    walk(node);
    return out.join('\n');
  };
  const climb = (el, why) => {
    let c = el, best = null, bestN = 0;
    for (let i = 0; c && i < 16; c = c.parentElement, i++) {
      if ((c.textContent || '').length > MAXLEN * 4) break;
      const t = leafText(c);
      if (t.length > MAXLEN) break;
      const n = (t.match(ODDG) || []).length;
      const lines = t.split('\n').length;
      if (best && (n > 4 || lines > 16)) break;
      if (best && n > bestN && (bestN >= 2 || why === 'lista')) break;
      if (n >= 1 && t.length >= 20 && /[a-zà-ù]{3}/i.test(t)) { best = c; bestN = n; }
    }
    if (best) {
      if (!cards.has(best)) cards.set(best, { why: why, text: leafText(best), cls: String(best.className || '').slice(0, 80), struck: [] });
      else if (why === 'barrata') cards.get(best).why = 'barrata';
    }
    return best;
  };
  const root = opts.root ? (document.querySelector(opts.root) || document.body) : document.body;
  const allEls = (r, out) => { for (const e of r.querySelectorAll('*')) { out.push(e); if (e.shadowRoot) allEls(e.shadowRoot, out); } return out; };
  for (const el of allEls(root, [])) {
    if (el.children.length > 2) continue;
    const ot = ownText(el) || (el.children.length === 0 ? (el.textContent || '').trim() : '');
    if (!ot || ot.length > 80) continue;
    if (ODD.test(ot)) {
      if (!vis(el)) continue;
      if (isStruck(el)) { const c = climb(el, 'barrata'); if (c) cards.get(c).struck.push(ot.trim()); }
      else if (opts.mode === 'list') climb(el, 'lista');
    }
    else if (GR && GR.test(ot) && vis(el)) { if (!cards.has(el)) cards.set(el, { why: 'gruppo', text: ot, cls: '', struck: [] }); }
    else if (KW.test(ot) && vis(el)) climb(el, 'keyword');
  }
  const arr = Array.from(cards.entries());
  // tieni solo le card piu' interne (scarta i contenitori che includono altre card);
  // le intestazioni di gruppo restano sempre, nell'ordine della pagina
  const kept = arr.filter(([el, v]) => v.why === 'gruppo' || !arr.some(([o, ov]) => ov.why !== 'gruppo' && o !== el && el.contains(o)));
  kept.sort((x, y) => (x[0].compareDocumentPosition(y[0]) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return kept.map(([el, v]) => v);
}
"""


# ---------------------------------------------------------------------------
# Parsing del testo di una card (puro Python, testabile senza browser)
# ---------------------------------------------------------------------------

ODD_LINE_RE = re.compile(r"^\d{1,4}[.,]\d{2,3}$")
ODD_ANY_RE = re.compile(r"(?<![\d.,])(\d{1,4}[.,]\d{2})(?!\d)")
MAX_BET_RES = [
    re.compile(r"max\s*bet[:\s]*(\d+(?:[.,]\d+)?)\s*(?:€|eur)?", re.I),
    re.compile(r"puntata\s+mass?ima[^\d]{0,15}(\d+(?:[.,]\d+)?)", re.I),
    re.compile(r"(?:max|massimo)\s+(\d+(?:[.,]\d+)?)\s*€", re.I),
]
LABEL_RE = re.compile(r"^(super\s?quota|quota\s+maggiorata|quote\s+maggiorate|maggiorata(?:\s+daznbet\s+club)?|"
                      r"stake\s+boost|turbo|starter|ultra|promo|my\s+combo|quota\s+top)$", re.I)
NOISE_RE = re.compile(r"^(si|sì|no|\+|\d{1,5}|prima|giocata|volte|:|-|vs|v|oggi|domani|alias|hcp|quickbet|"
                      r"\d{1,2}|\d{1,2}:\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s+\d{1,2}:\d{2})?)$", re.I)
COND_RE = re.compile(r"(solo in singola|max\s*1\s*ticket|valida per il primo ticket|riservat[ao]|club)", re.I)
MULTIPLA_RE = re.compile(r"multipla\s+maggiorata", re.I)
# Etichette dei gruppi nelle pagine "lista" (Marathonbet, Fastbet): compaiono
# solo nella prima riga del gruppo e vanno riportate sulle righe successive.
GROUP_RE = re.compile(r"(segnano tutt\w*|segneranno tutt\w*|tutti segnano|tutti a segno|tutte over|tutte goal|"
                      r"vincono tutt\w*|vinceranno tutt\w*|all teams winners|tutti marcatori)", re.I)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
EVENT_RE = re.compile(r"^(?P<a>[A-ZÀ-Ýa-zà-ÿ][\w.'’ À-ÿ-]{1,40}?)\s+(?:-|–|vs\.?|v)\s+"
                      r"(?P<b>[A-ZÀ-Ýa-zà-ÿ][\w.'’ À-ÿ-]{1,40}?)\s*(?::.*)?$")
TIME_WORD_RE = re.compile(r"^(oggi|domani|\d{1,2}:\d{2}|[•\d\s:/.-]+)$", re.I)


_MESI = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9, "ott": 10,
         "nov": 11, "dic": 12}


def data_card(text, oggi=None):
    """Data della partita in formato 'dd/mm': '02/10', '02/10/26', '3 ott', 'Oggi', 'Domani'.
    Si accettano solo date plausibili (da ieri a +14 giorni), cosi' '+1/1' (parziale/finale)
    non viene scambiato per una data."""
    oggi = oggi or date.today()
    cands = []
    for m in DATE_RE.finditer(text):
        try:
            cands.append((m.start(), int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"(?i)\b(\d{1,2})\s+(gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\w*\b", text):
        cands.append((m.start(), int(m.group(1)), _MESI[m.group(2).lower()]))
    for m in re.finditer(r"(?i)\b(oggi|domani)\b", text):
        d = oggi + timedelta(days=1 if m.group(1).lower() == "domani" else 0)
        cands.append((m.start(), d.day, d.month))
    for _, d, mth in sorted(cands):
        for y in (oggi.year, oggi.year + 1, oggi.year - 1):
            try:
                x = date(y, mth, d)
            except ValueError:
                continue
            if -1 <= (x - oggi).days <= 14:
                return f"{d:02d}/{mth:02d}"
    return ""


def di_oggi(it, oggi=None):
    """True se la maggiorata e' di oggi o non ha data."""
    d = (it.get("data") or "").strip()
    if not d:
        return True
    oggi = oggi or date.today()
    return d[:5] == f"{oggi.day:02d}/{oggi.month:02d}"


def to_float(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def card_id(book, text):
    """Id stabile della maggiorata: book + testo senza quote (le quote possono
    muoversi di poco tra un run e l'altro senza che sia una maggiorata nuova)."""
    norm = ODD_ANY_RE.sub("", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(f"{book}|{norm}".encode("utf-8")).hexdigest()[:12]


def parse_card(book_cfg, raw):
    """Trasforma una card grezza {why, text, struck} in una maggiorata
    strutturata, oppure None se non e' una maggiorata utilizzabile."""
    book = book_cfg["name"]
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    if MULTIPLA_RE.search(text):
        return None  # solo quota singola: le multiple maggiorate non interessano
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Quote presenti nella card, in ordine
    odds = []  # (indice_riga, valore)
    for i, l in enumerate(lines):
        for m in ODD_ANY_RE.finditer(l):
            if l.lower().startswith("max bet") or "€" in l:
                continue
            odds.append((i, to_float(m.group(1))))
    if not odds:
        return None

    # Quota barrata: prima quella line-through, poi quella dopo "PRIMA"
    barrata = None
    struck_vals = [to_float(s) for s in raw.get("struck") or [] if to_float(s)]
    if struck_vals:
        barrata = struck_vals[0]
    else:
        for i, l in enumerate(lines):
            m = re.match(r"^prima\s*(\d{1,4}[.,]\d{2})?$", l, re.I)
            if m:
                if m.group(1):
                    barrata = to_float(m.group(1))
                elif i + 1 < len(lines) and ODD_LINE_RE.match(lines[i + 1]):
                    barrata = to_float(lines[i + 1])
                break

    # Book che mostrano la quota vecchia senza barrarla (PokerStars): due quote
    # consecutive in fondo alla card, la prima piu' bassa = barrata
    if barrata is None and book_cfg.get("barrata_senza_stile") and len(odds) >= 2:
        (i1, v1), (i2, v2) = odds[-2], odds[-1]
        if i2 == i1 + 1 and v1 and v2 and v1 < v2:
            barrata = v1

    # Quota maggiorata: l'ultima quota della card diversa dalla barrata e, se
    # c'e' una barrata, superiore ad essa.
    vals = [v for _, v in odds]
    if barrata is not None:
        rest = list(vals)
        if barrata in rest:
            rest.remove(barrata)
        above = [v for v in rest if v > barrata]
        if not above:
            return None
        maggiorata = above[-1]
    else:
        maggiorata = vals[-1]
    if maggiorata is None or maggiorata < 1.01:
        return None

    # Puntata massima
    max_bet = None
    for rx in MAX_BET_RES:
        m = rx.search(text)
        if m:
            max_bet = to_float(m.group(1))
            break
    if max_bet is None:
        max_bet = book_cfg.get("max_bet")

    condizioni = sorted({m.group(1).strip() for m in COND_RE.finditer(text)}, key=str.lower)

    # Evento: riga "A - B" / "A vs B", oppure tre righe "A", "vs", "B"
    evento = ""
    used = set()
    for i, l in enumerate(lines):
        if i + 2 < len(lines) and lines[i + 1].lower() in ("vs", "v", "-") and not ODD_LINE_RE.match(l) \
                and not TIME_WORD_RE.match(l) and not TIME_WORD_RE.match(lines[i + 2]):
            evento = f"{l} - {lines[i + 2]}"
            used.update({i, i + 1, i + 2})
            break
        l_nodate = re.sub(r"\s+", " ", DATE_RE.sub("", l)).strip(" -–")
        head = l.split(":")[0] if ":" in l else l
        if re.search(r"max\s*bet|maggiorat|super\s?quot|boost", head, re.I):
            continue
        if re.search(r"(?i)\b(calcio|league|lega|serie [abc]|coppa|cup|speciali|brasileiro|liga)\b", head):
            continue  # riga della competizione, non dell'evento
        if l.count(" - ") >= 2 and "(" in l:
            continue  # "A - B - C (Vincono Tutte)": combinazione su piu' partite, non un evento
        m = EVENT_RE.match(l_nodate)
        if m and not LABEL_RE.match(l) and not re.match(r"^max", l, re.I):
            evento = f"{m.group('a').strip()} - {m.group('b').strip()}"
            used.add(i)
            break
    if not evento:
        # Betsson: etichetta, poi squadra casa e squadra ospite su due righe
        for i in range(len(lines) - 1):
            a, b = lines[i], lines[i + 1]
            if (LABEL_RE.match(lines[i - 1]) if i > 0 else False) and a[:1].isupper() and b[:1].isupper() \
                    and not ODD_LINE_RE.match(a) and not ODD_LINE_RE.match(b) and len(a) < 30 and len(b) < 30:
                evento = f"{a} - {b}"
                used.update({i, i + 1})
                break

    if not evento:
        # Sisal/Snai/PokerStars: squadre su righe separate attorno alla data, o codici "FRA-ITA"
        try:
            from fair_speciali import evento_da_righe
            evento = evento_da_righe(lines)
        except Exception:
            pass

    date = data_card(text)

    etichetta = next((l for l in lines if LABEL_RE.match(l)), "")
    desc = []
    for i, l in enumerate(lines):
        if i in used or ODD_LINE_RE.match(l) or NOISE_RE.match(l) or LABEL_RE.match(l):
            continue
        if re.search(r"max\s*bet", l, re.I) or re.search(r"giocata\s+\d+\s+volte", l, re.I):
            continue
        if not re.search(r"[A-Za-zÀ-ÿ]{2}", l) or TIME_WORD_RE.match(l):
            continue
        if l.lower().startswith(("int speciali", "speciali calcio")) or re.match(r"^[A-Z]{3}-[A-Z]{3}", l):
            continue
        clean = re.sub(r"\(\s*\)", "", DATE_RE.sub("", l))
        clean = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", clean))
        clean = re.sub(r"\s+", " ", clean).strip(" -–|•")
        if clean and clean not in desc:
            desc.append(clean)
    descrizione = " · ".join(desc[:5])
    if not descrizione and not evento:
        return None  # es. "My Combo" senza selezioni visibili: non interpretabile

    gm = GROUP_RE.search(text)
    gruppo = gm.group(1).lower() if gm else ""
    return {
        "id": card_id(book, text),
        "gruppo": gruppo,
        "book": book,
        "evento": evento,
        "data": date,
        "descrizione": descrizione,
        "etichetta": etichetta,
        "quota_barrata": barrata,
        "quota_maggiorata": maggiorata,
        "max_bet": max_bet,
        "condizioni": condizioni,
        "origine": raw.get("why", ""),
        "testo": text,
        "trovata_il": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def parse_raws(b, raws):
    """Card grezze -> maggiorate. In modalita' lista riporta l'etichetta del
    gruppo sulle righe che non ce l'hanno e applica l'eventuale filtro righe."""
    items, seen, gruppo = [], set(), ""
    filtro = re.compile(b["filtro_righe"], re.I) if b.get("filtro_righe") else None
    for raw in raws:
        if raw.get("why") == "gruppo":
            gm = GROUP_RE.search(raw.get("text", ""))
            if gm:
                gruppo = gm.group(1).lower()
            continue
        it = parse_card(b, raw)
        if not it or it["id"] in seen:
            continue
        if b.get("mode") == "list":
            if it["gruppo"]:
                gruppo = it["gruppo"]
            else:
                it["gruppo"] = gruppo
            if filtro and not filtro.search(it["testo"]):
                continue
        seen.add(it["id"])
        items.append(it)
    return items


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def selected_books(config, names=None):
    out = []
    for b in config.get("book", []):
        if b.get("pagamento") != "reale" or not b.get("attivo") or not b.get("url"):
            continue
        if b.get("lettura") == "estensione":
            continue  # letto dall'estensione Chrome (sito che rifiuta il browser automatico)
        if names and b["name"].lower() not in {n.lower() for n in names}:
            continue
        out.append(b)
    return out


def new_page(browser):
    context = browser.new_context(
        locale="it-IT",
        viewport={"width": 1366, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    )

    def skip_heavy(route):
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    context.route("**/*", skip_heavy)
    return context.new_page()


def scroll_page(page, steps=5, pause=0.4):
    try:
        for i in range(1, steps + 1):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {i} / {steps})")
            time.sleep(pause)
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


def run_actions(page, actions):
    for a in actions or []:
        try:
            if "click_text" in a:
                loc = page.get_by_text(a["click_text"], exact=True)
                for i in range(loc.count()):
                    if loc.nth(i).is_visible():
                        loc.nth(i).click(timeout=5000)
                        break
            elif "click_role" in a:
                page.get_by_role(a["click_role"], name=a.get("name", "")).first.click(timeout=5000)
            elif "click_all" in a:
                loc = page.locator(a["click_all"])
                for i in range(loc.count()):
                    if loc.nth(i).is_visible():
                        loc.nth(i).click(timeout=5000)
                        time.sleep(0.2)
            elif "click" in a:
                page.locator(a["click"]).first.click(timeout=5000)
            time.sleep(a.get("wait", 2))
        except Exception as e:
            print(f"   [azione non riuscita] {a}: {str(e).splitlines()[0][:80]}")


def save_debug(name, html):
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
        (DEBUG_DIR / f"maggiorate_{safe}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


def scrape_book(page, b, wait_sec):
    """Ritorna (lista_maggiorate, stato)."""
    try:
        page.goto(b["url"], timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    except Exception as e:
        msg = str(e).lower()
        detail = str(e).splitlines()[0][:60] if str(e) else e.__class__.__name__
        if any(m in msg for m in BLOCKED_ERROR_MARKERS):
            return [], f"bloccato dal sito (anti-bot: {detail[:40]})"
        return [], f"errore di caricamento ({detail})"
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    time.sleep(wait_sec)
    html_head = page.content()[:5000].lower()
    if any(m in html_head for m in BLOCKED_PAGE_MARKERS):
        return [], "bloccato dal sito (anti-bot)"
    scroll_page(page)
    run_actions(page, b.get("azioni"))
    opts = {"mode": b.get("mode", "cards")}
    if b.get("root"):
        opts["root"] = b["root"]
    raws = []
    for attempt in range(2):  # alcuni siti caricano le card in ritardo (lazy-load)
        try:
            raws = page.evaluate(EXTRACT_JS, opts) or []
        except Exception as e:
            return [], f"errore estrazione ({str(e).splitlines()[0][:60]})"
        if raws:
            break
        time.sleep(4)
        scroll_page(page)
    items = parse_raws(b, raws)
    if not items:
        save_debug(b["name"], page.content())
        return [], "nessuna maggiorata trovata"
    return items, "ok"


def main(argv=None):
    if sync_playwright is None:
        print("Manca 'playwright'. Installa con:\n    pip install playwright\n    playwright install chromium")
        sys.exit(1)
    argv = sys.argv[1:] if argv is None else argv
    config = load_config()
    books = selected_books(config, [a for a in argv if not a.startswith("-")])
    wait_sec = config.get("attesa_caricamento_sec", 6)
    if not books:
        print("Nessun book attivo con pagamento reale da leggere (controlla maggiorate_config.json).")
        return
    random.shuffle(books)
    started = time.monotonic()
    print(f"Lettura maggiorate su {len(books)} book...")

    todo = queue.Queue()
    for b in books:
        todo.put(b)
    results = []
    lock = threading.Lock()

    def worker():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = new_page(browser)
            while True:
                try:
                    b = todo.get_nowait()
                except queue.Empty:
                    break
                try:
                    items, status = scrape_book(page, b, wait_sec)
                except Exception as e:
                    items, status = [], f"errore imprevisto ({str(e).splitlines()[0][:60] if str(e) else e})"
                with lock:
                    results.append((b["name"], items, status))
                    mark = "OK " if status == "ok" else "!! "
                    print(f"{mark}{b['name']:<20} {status:<40} ({len(items)} trovate)", flush=True)
                time.sleep(random.uniform(1.5, 4))
            try:
                browser.close()
            except Exception:
                pass

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(PARALLEL_WORKERS, len(books))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Le maggiorate dei book non letti in questo run (bloccati/errore) restano
    # quelle del run precedente, marcate come "non riconfermate".
    previous = []
    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")).get("maggiorate", [])
        except (json.JSONDecodeError, OSError):
            previous = []
    ok_books = {name for name, _, status in results if status in ("ok", "nessuna maggiorata trovata")}
    solo_oggi = config.get("solo_oggi", True)
    altri = {}
    if solo_oggi:  # solo le maggiorate di oggi (quelle senza data restano: si verifica poi la partita)
        res2 = []
        for name, items, status in results:
            tenute = [it for it in items if di_oggi(it)]
            if len(tenute) < len(items):
                altri[name] = len(items) - len(tenute)
            res2.append((name, tenute, status))
        results = res2
        previous = [it for it in previous if di_oggi(it)]
    all_items = [it for _, items, _ in results for it in items]
    kept = []
    for it in previous:
        if it.get("via") == "estensione" and it["book"] not in ok_books:
            kept.append(it)  # lette dall'estensione Chrome: le aggiorna lei
        elif it["book"] not in ok_books and it.get("origine") != "manuale":
            it["non_riconfermata"] = True
            kept.append(it)
    stato_prec = {}
    try:
        stato_prec = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")).get("stato_book", {}) if OUTPUT_PATH.exists() else {}
    except (json.JSONDecodeError, OSError):
        pass
    out = {
        "aggiornato_il": datetime.now().isoformat(timespec="seconds"),
        "stato_book": {**{k: v for k, v in stato_prec.items() if "estensione" in str(v.get("stato", ""))},
                       **{name: {"stato": status, "trovate": len(items),
                                 **({"altri_giorni": altri[name]} if name in altri else {})}
                          for name, items, status in results}},
        "maggiorate": all_items + kept,
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    el = time.monotonic() - started
    if altri:
        print(f"Escluse {sum(altri.values())} maggiorate di altri giorni (solo_oggi attivo).")
    print(f"\nCompletato in {int(el // 60)} min {int(el % 60)} s: {len(all_items)} maggiorate lette "
          f"({len(kept)} conservate dal run precedente) -> {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
