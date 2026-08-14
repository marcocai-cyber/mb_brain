#!/usr/bin/env python3
"""
Scraper promozioni bookmaker ADM
=================================
Da eseguire SUL TUO COMPUTER (serve un IP italiano: i siti dei bookmaker
ADM sono geo-bloccati e non raggiungibili da server esteri).

Cosa fa:
  1. Apre ogni pagina promozioni elencata in scraper_config.json con un
     browser headless (Playwright), cosi' anche i siti "a pagina singola"
     (React/Vue) vengono renderizzati correttamente.
  2. Prova prima i selettori CSS specifici indicati nel config (se presenti).
  3. Se non trova nulla, usa un'estrazione euristica: cerca blocchi di testo
     brevi che contengono parole chiave tipiche delle promozioni (bonus,
     free bet, cashback, quota maggiorata, ecc.).
  4. Scrive tutto in promozioni.json, nello stesso formato che l'app
     MatchBetting_Assistant.html sa importare (tab Offerte > Importa da file).

NOTE IMPORTANTI:
  - Alcuni siti potrebbero bloccare comunque il traffico automatizzato
    (protezioni anti-bot, captcha) o richiedere login per vedere le
    promozioni riservate ai clienti registrati: in quel caso lo script
    salta il bookmaker e lo segnala nel log finale.
  - I dati estratti (soprattutto valore, scadenza, requisito di puntata)
    sono spesso IMPRECISI con l'estrazione euristica: trattali come un
    "radar" che ti segnala che c'e' una nuova promo, poi vai a leggerla
    tu sul sito prima di scommettere.
  - Verifica sempre i Termini di Servizio del bookmaker prima di usare
    strumenti automatizzati sul loro sito: alcuni operatori vietano lo
    scraping nelle proprie condizioni d'uso. Usa lo script in modo
    responsabile (frequenza bassa, es. 1 volta al giorno) e a tuo rischio.

Installazione (una tantum):
    pip install playwright beautifulsoup4
    playwright install chromium

Esecuzione:
    python scraper_promozioni.py

Output:
    promozioni.json (nella stessa cartella) — da importare nell'app.
"""

import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, quote_plus

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Manca 'beautifulsoup4'. Installa con: pip install beautifulsoup4")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Manca 'playwright'. Installa con:")
    print("    pip install playwright")
    print("    playwright install chromium")
    sys.exit(1)


HERE = Path(__file__).parent
CONFIG_PATH = HERE / "scraper_config.json"
OUTPUT_PATH = HERE / "promozioni.json"
STATE_PATH = HERE / "scraper_state.json"
GIT_DIR = HERE / ".git"
GIT_PUSH_TIMEOUT_SEC = 30

MIN_SNIPPET_LEN = 20
MAX_SNIPPET_LEN = 220
MAX_ITEMS_PER_SITE = 12

# Anti-blocco IP: dopo N errori consecutivi su un bookmaker, lo si mette in
# "pausa" per alcune ore invece di continuare a martellarlo ad ogni run.
MAX_CONSECUTIVE_FAILURES = 3
COOLDOWN_HOURS = 6
# Ritardo casuale (non fisso) tra una richiesta e l'altra: rende il traffico
# meno riconoscibile come "bot con timing perfetto".
MIN_DELAY_SEC = 3
MAX_DELAY_SEC = 9

# Marcatori tipici che precedono un elenco di slot idonee ad una promo,
# usati per l'estrazione euristica dei nomi delle slot.
SLOT_LIST_MARKERS = [
    "slot idonee", "slot partecipanti", "giochi partecipanti", "giochi idonei",
    "slot valide", "giochi validi", "slot selezionate", "slot incluse",
]
SLOT_SECTION_MAX_CHARS = 600
MAX_SLOTS_PER_OFFER = 8
RTP_LOOKUP_MAX_SLOTS = 6  # limite per non appesantire troppo ogni run

# Marcatori tipici che precedono l'importo massimo convertibile in denaro
# reale di un fun bonus / bonus non prelevabile.
MAX_CAP_MARKERS = [
    "massimo convertibile", "massimo prelevabile", "vincita massima convertibile",
    "importo massimo prelevabile", "max cap", "cap massimo", "prelievo massimo",
    "vincita massima", "convertibile fino a",
]


def load_state():
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_in_cooldown(state, name):
    entry = state.get(name)
    if not entry or not entry.get("cooldown_until"):
        return False
    try:
        until = datetime.fromisoformat(entry["cooldown_until"])
    except ValueError:
        return False
    return datetime.now() < until


def record_result(state, name, success):
    entry = state.setdefault(name, {"consecutive_failures": 0, "cooldown_until": None})
    if success:
        entry["consecutive_failures"] = 0
        entry["cooldown_until"] = None
    else:
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        if entry["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
            cooldown_until = datetime.now() + timedelta(hours=COOLDOWN_HOURS)
            entry["cooldown_until"] = cooldown_until.isoformat()


def load_config():
    if not CONFIG_PATH.exists():
        print(f"File di configurazione non trovato: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_rendered_html(page, url, timeout_ms=25000):
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    time.sleep(1.5)  # margine per contenuti lazy-load
    return page.content()


def extract_with_selectors(soup, card_sel, title_sel):
    items = []
    if not card_sel:
        return items
    cards = soup.select(card_sel)
    for c in cards[:MAX_ITEMS_PER_SITE]:
        title_el = c.select_one(title_sel) if title_sel else c
        title = title_el.get_text(strip=True) if title_el else ""
        text = c.get_text(" ", strip=True)
        if title and len(title) >= 4:
            items.append({"title": title[:140], "snippet": text[:MAX_SNIPPET_LEN], "el": c})
    return items


def extract_heuristic(soup, keywords):
    """Cerca blocchi di testo brevi (titoli/card) che contengono parole chiave."""
    found = []
    seen = set()
    candidates = soup.find_all(["h1", "h2", "h3", "h4", "a", "div", "span", "p"])
    for el in candidates:
        text = el.get_text(" ", strip=True)
        if not text or not (MIN_SNIPPET_LEN <= len(text) <= MAX_SNIPPET_LEN):
            continue
        low = text.lower()
        if not any(k in low for k in keywords):
            continue
        key = low[:80]
        if key in seen:
            continue
        seen.add(key)
        # per il contesto immagine/link, prova a risalire a un contenitore
        # piu' ampio (es. la card che avvolge titolo + immagine + bottone)
        container = el
        for _ in range(3):
            if container.parent and container.parent.name not in ("body", "html", "[document]"):
                container = container.parent
            else:
                break
        found.append({"title": text[:140], "snippet": text[:MAX_SNIPPET_LEN], "el": container})
        if len(found) >= MAX_ITEMS_PER_SITE:
            break
    return found


def guess_deadline(text):
    # Cerca pattern data tipo 31/12/2026 o 31-12-2026
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if not m:
        return ""
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    try:
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return ""


ONCLICK_URL_PATTERNS = [
    r"windowOpen\(\s*['\"]([^'\"]+)['\"]",
    r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
    r"window\.open\(\s*['\"]([^'\"]+)['\"]",
]


def extract_onclick_url(el):
    """Alcune piattaforme (es. la famiglia 'rettangolo-promo' di NetBet/
    StanleyBet/Sunbet/ecc.) non mettono il link della promo in un href, ma in
    un attributo onclick tipo windowOpen('https://...', '_self'): questa
    funzione prova i pattern piu' comuni per estrarlo comunque."""
    onclick = el.get("onclick", "") or ""
    for pattern in ONCLICK_URL_PATTERNS:
        m = re.search(pattern, onclick)
        if m:
            return m.group(1)
    return ""


def extract_image_and_link(card, page_url, page_og_image):
    """Cerca un'immagine e un link 'approfondisci' dentro la card della promo.
    Se la card non ha immagine propria, usa l'og:image dell'intera pagina."""
    image = ""
    img_el = card.find("img")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or ""
        if src:
            image = urljoin(page_url, src)
    if not image and page_og_image:
        image = page_og_image

    link = ""
    a_el = card if card.name == "a" else card.find("a")
    if a_el:
        href = a_el.get("href")
        if href:
            link = urljoin(page_url, href)
        else:
            onclick_url = extract_onclick_url(a_el)
            if onclick_url:
                link = urljoin(page_url, onclick_url)
    if not link:
        # cerca un qualunque discendente con onclick che porti a una URL
        # (non sempre il primo <a> trovato e' quello giusto)
        for a2 in card.find_all(["a", "button", "div"]):
            onclick_url = extract_onclick_url(a2)
            if onclick_url:
                link = urljoin(page_url, onclick_url)
                break
    if not link:
        link = page_url

    return image, link


# ---------------------------------------------------------------------------
# Arricchimento con Termini e Condizioni completi (pagina di dettaglio)
# ---------------------------------------------------------------------------
# Le card sulla pagina indice riportano quasi sempre solo un titolo/importo
# sintetico ("Bonus fino a 5.100€"): i dati davvero utili per il matched
# betting (quota minima, puntata minima, wagering, tempistiche, esclusioni)
# sono quasi sempre SOLO nella pagina di dettaglio della singola promo, a cui
# la card linka. Per questo lo script visita anche quella pagina — ma solo
# se non l'ha gia' fatto in un run precedente (cache) e solo entro un tetto
# massimo di richieste per run (budget), per non appesantire troppo ogni
# esecuzione ne' aumentare il rischio di blocco IP.
MAX_ENRICH_PER_RUN = 40
MIN_ENRICH_DELAY_SEC = 1.5
MAX_ENRICH_DELAY_SEC = 3.5
TERMS_MAX_CHARS = 3000

# Tag e classi di boilerplate da rimuovere prima di estrarre il testo della
# pagina di dettaglio: menu, footer, cookie banner, script — non servono e
# renderebbero i T&C illeggibili se lasciati in mezzo.
BOILERPLATE_TAGS = ["nav", "header", "footer", "script", "style", "noscript", "form", "svg"]
BOILERPLATE_CLASS_MARKERS = [
    "cookie", "menu-principale", "breadcrumb", "newsletter", "site-footer",
    "site-header", "main-nav", "navbar", "sitemap",
]


def extract_terms_from_soup(soup):
    """Rimuove i blocchi di boilerplate piu' comuni (nav, header, footer,
    script, cookie banner...) da un BeautifulSoup gia' parsato e ritorna il
    testo residuo. ATTENZIONE: e' distruttivo (usa .decompose()), quindi va
    chiamato per ultimo se lo stesso soup serve anche per altro.

    Nota tecnica importante: BeautifulSoup legge il testo dall'HTML
    renderizzato cosi' com'e', comprese le sezioni 'a comparsa' (accordion/
    toggle chiusi via CSS, es. i 'Termini e condizioni' di bwin): il testo e'
    presente nel markup anche se visivamente nascosto finche' l'utente non
    clicca, quindi viene comunque estratto senza bisogno di simulare click."""
    for tag_name in BOILERPLATE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()
    for marker in BOILERPLATE_CLASS_MARKERS:
        for el in soup.select(f'[class*="{marker}" i]'):
            el.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:TERMS_MAX_CHARS]


def extract_terms_text(html):
    """Estrazione generica del testo (T&C inclusi) di una pagina di
    dettaglio promo a partire dall'HTML grezzo, senza bisogno di selettori
    specifici per sito. Fa il parsing e poi delega a extract_terms_from_soup."""
    soup = BeautifulSoup(html, "html.parser")
    return extract_terms_from_soup(soup)


def enrich_with_terms(page, offer, terms_cache, run_state, index_url):
    """Popola offer['terms'] con i T&C completi presi dalla pagina di
    dettaglio della promo (offer['url']), rispettando cache e budget."""
    key = (offer["book"], offer["title"])
    cached = terms_cache.get(key)
    if cached:
        offer["terms"] = cached
        return

    url = offer.get("url", "")
    if not url or url == index_url:
        # nessun link per-promo distinto dalla pagina indice generale: non
        # c'e' una pagina di dettaglio diversa da visitare.
        offer["terms"] = ""
        return

    if run_state["enrich_budget"] <= 0:
        offer["terms"] = ""
        return

    try:
        time.sleep(random.uniform(MIN_ENRICH_DELAY_SEC, MAX_ENRICH_DELAY_SEC))
        html = fetch_rendered_html(page, url, timeout_ms=20000)
        offer["terms"] = extract_terms_text(html)
    except Exception:
        offer["terms"] = ""
    run_state["enrich_budget"] -= 1


def extract_og_image(soup, page_url):
    tag = soup.find("meta", attrs={"property": "og:image"})
    if tag and tag.get("content"):
        return urljoin(page_url, tag["content"])
    return ""


def extract_candidate_slots(text):
    """Estrazione euristica dei nomi delle slot citate vicino a marcatori tipo
    'Slot idonee:'. Affidabilita' variabile: dipende da come il bookmaker
    scrive il testo. Ritorna una lista di nomi (stringhe) unica e limitata."""
    low = text.lower()
    found = []
    for marker in SLOT_LIST_MARKERS:
        idx = low.find(marker)
        if idx == -1:
            continue
        start = idx + len(marker)
        section = text[start: start + SLOT_SECTION_MAX_CHARS]
        # Tronca alla prima frase che introduce condizioni (non fa piu' parte
        # dell'elenco slot), poi spezza su virgole, punti elenco o "e" finale.
        section = re.split(
            r"\brequisito\b|\bvalido fino\b|\bwagering\b|\bmassima\b|\bmassimo\b|\bminima\b|\bminimo\b"
            r"|\bconvertibil\w*\b|\bvincita\b",
            section, flags=re.IGNORECASE)[0]
        parts = re.split(r"[,;•\n.]| e (?=[A-Z])", section)
        for p in parts:
            name = p.strip(" .:-–—")
            low_name = name.lower()
            if (3 <= len(name) <= 40
                    and not low_name.startswith(("entro", "requisito", "il bonus"))):
                found.append(name)
    # dedup mantenendo l'ordine
    seen = set()
    unique = []
    for n in found:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return unique[:MAX_SLOTS_PER_OFFER]


def lookup_slot_rtp_volatility(page, slot_name):
    """Cerca RTP e volatilita' di una slot: prima non abbiamo un database
    proprio, quindi interroghiamo una ricerca web generica (DuckDuckGo HTML,
    non richiede JS) e proviamo a leggere RTP/volatilita' dagli snippet dei
    risultati (spesso pagine dei provider come Pragmatic Play, NetEnt,
    Play'n GO, Novomatic, ecc). Se non troviamo nulla, segnaliamo che va
    verificato a mano."""
    query = f"{slot_name} slot RTP volatilita"
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
        time.sleep(1)
        html = page.content()
    except Exception:
        return {"name": slot_name, "rtp": "", "volatility": "", "source": "",
                "note": "ricerca fallita, verifica manuale necessaria"}

    soup = BeautifulSoup(html, "html.parser")
    results_text = soup.get_text(" ", strip=True)

    rtp = ""
    m = re.search(r"rtp[^0-9]{0,15}(\d{2}[.,]\d{1,2})\s*%", results_text, re.IGNORECASE)
    if m:
        rtp = m.group(1).replace(",", ".") + "%"

    volatility = ""
    vm = re.search(
        r"volatilit[aà\'a]{1,2}\s*[:\-]?\s*(bassa|medio[- ]bassa|media|medio[- ]alta|alta|low|medium|high)",
        results_text, re.IGNORECASE)
    if vm:
        volatility = vm.group(1).lower()

    first_link = ""
    link_el = soup.select_one("a.result__a") or soup.find("a", href=True)
    if link_el:
        first_link = link_el.get("href", "")

    if not rtp and not volatility:
        return {"name": slot_name, "rtp": "", "volatility": "", "source": first_link,
                "note": "RTP/volatilita' non trovati automaticamente: verifica sul sito del "
                        "bookmaker o del provider della slot"}

    return {"name": slot_name, "rtp": rtp, "volatility": volatility, "source": first_link, "note": ""}


def extract_max_cap(text):
    """Cerca l'importo massimo convertibile in denaro reale di un fun bonus,
    vicino a marcatori tipo 'massimo convertibile', 'max cap', ecc."""
    low = text.lower()
    for marker in MAX_CAP_MARKERS:
        idx = low.find(marker)
        if idx == -1:
            continue
        window = text[idx: idx + 60]
        m = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)", window, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                continue
    return None


def guess_value(text):
    m = re.search(r"(\d{1,4})\s*(?:€|euro)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0
    return 0



# Frasi tipiche di navigazione/boilerplate che NON sono mai una vera promo,
# anche se contengono per caso una parola chiave (es. "promozioni" nel menu):
# login/password, errori 404, popup cookie/marketing, giochi a classifica o a
# estrazione (valore non garantito per il singolo giocatore, quindi non
# "matematicamente monetizzabile" in modo affidabile). Ci rientrano anche
# "porta un amico" (valore non garantito/difficile da calcolare in modo
# affidabile), "montepremi" (premio a bacino condiviso tra tutti i
# partecipanti, non un valore personale garantito) e "bonus progressivo"
# (percentuale legata a condizioni di puntata multiple, poco calcolabile a
# priori) su richiesta esplicita dell'utente dopo revisione manuale.
EXCLUDE_PATTERNS_DEFAULT = [
    "recupera password", "hai dimenticato", "inserisci le tue credenziali",
    "username", "accedi con passkey", "non hai un account", "non hai ancora un conto",
    "errore 404", "si è verificato un errore", "ci scusiamo per il disagio",
    "preferenze di contatto", "comunicazioni di marketing", "cookie policy",
    "faq aiuto", "orari di gioco", "scala la classifica", "classifica generale",
    "gioco gratuito giornaliero", "svelamenti al giorno", "punti convertibili",
    "club riservato", "regolamento completo", "assistenza clienti",
    "porta un amico", "invita un amico", "montepremi", "bonus progressivo",
]

# Meccanismi di bonus riconosciuti come potenzialmente calcolabili (matched
# betting o EV di slot bonus hunting). Elenco di partenza, estendibile in
# scraper_config.json (chiave "monetizable_keywords") senza toccare il codice.
MONETIZABLE_KEYWORDS_DEFAULT = [
    "bonus di benvenuto", "welcome bonus", "free bet", "freebet", "bonus cash",
    "fun bonus", "bonus deposito", "primo deposito", "cashback", "rimborso",
    "quota maggiorata", "quota potenziata", "giri gratis", "free spin",
    "bonus sport", "bonus scommesse", "bonus slot", "deposito minimo",
    "scommessa minima", "quota minima", "moltiplicatore",
]


def has_quantifiable_signal(text):
    """Vero se nel testo c'e' un numero legato a un valore economico concreto
    (importo, percentuale, giri gratis, quota minima) e non solo parole.
    L'importo puo' precedere o seguire il simbolo € (es. sia "100€" che "€5")."""
    if re.search(r"\d+[.,]?\d*\s*(?:€|eur\b|euro)", text, re.IGNORECASE):
        return True
    if re.search(r"(?:€|eur\b|euro)\s*\d+[.,]?\d*", text, re.IGNORECASE):
        return True
    if re.search(r"\d+\s*%", text):
        return True
    if re.search(r"\d+\s*(?:free\s?spin|giri\s+gratis)", text, re.IGNORECASE):
        return True
    if re.search(r"quota\s*minima\s*\d", text, re.IGNORECASE):
        return True
    return False


def is_monetizable(text, monetizable_keywords, exclude_keywords):
    """Filtro di 'monetizzabilita'': tiene solo i blocchi di testo che
    sembrano una vera offerta calcolabile (meccanismo di bonus riconosciuto +
    valore quantificabile), scartando navigazione/login/errori/giochi a
    classifica o estrazione (valore non garantito)."""
    low = text.lower()
    if len(text.strip()) < 15:
        return False
    if any(p in low for p in exclude_keywords):
        return False
    has_mechanic = any(k in low for k in monetizable_keywords)
    if not has_mechanic:
        # "bonus" direttamente legato a un numero (es. "bonus di €5", "50€ di
        # bonus") e' un segnale forte anche senza una frase specifica in elenco.
        if re.search(r"bonus\s+(?:di|fino a|pari a|del)\s*(?:€|eur\b|euro)?\s*\d", low):
            has_mechanic = True
        elif re.search(r"\d+[.,]?\d*\s*(?:€|eur\b|euro)?\s*(?:di\s+|in\s+)?bonus", low):
            has_mechanic = True
    return has_mechanic and has_quantifiable_signal(text)


def dedupe_by_containment(items):
    """Rimuove i doppioni generati quando l'estrazione euristica risale a piu'
    livelli di uno stesso blocco (contenitore esterno + testo interno): se il
    testo di un elemento e' interamente contenuto in quello di un altro, tiene
    solo la versione piu' completa."""
    # Lo snippet e' sempre un troncamento piu' lungo (fino a 220 caratteri) dello
    # stesso testo sorgente del titolo (troncato a 140): usare solo lo snippet
    # evita di duplicare artificialmente il testo (title+snippet uguali per i
    # blocchi brevi), il che romperebbe il confronto "e' contenuto in un altro".
    texts = [(it, (it.get("snippet") or it.get("title") or "").lower().strip()) for it in items]
    keep = []
    for i, (it, t) in enumerate(texts):
        if not t:
            continue
        redundant = False
        for j, (_, t2) in enumerate(texts):
            if i == j or not t2:
                continue
            if t != t2 and t in t2:
                redundant = True
                break
            if t == t2 and j < i:
                redundant = True
                break
        if not redundant:
            keep.append(it)
    return keep


MAX_DETAIL_PAGES = 12
MIN_DETAIL_DELAY_SEC = 1.2
MAX_DETAIL_DELAY_SEC = 3


def scrape_detail_pages(page, bm, monetizable_keywords, exclude_keywords):
    """Modalita' 'a due passaggi' per siti dove la pagina indice mostra solo
    banner-immagine senza testo estraibile (es. piattaforma Eplay24/Betwin360/
    Sportium): la pagina indice serve solo a raccogliere i link (href) di ogni
    promo, poi si visita ogni pagina di dettaglio (che sui questi siti
    contiene testo reale e ricco: titolo + descrizione + condizioni) e si
    estrae il contenuto da li'."""
    name = bm["name"]
    url = bm["url"]
    link_sel = bm.get("link_selector", "")
    title_sel = bm.get("detail_title_selector", "")
    content_sel = bm.get("detail_content_selector", "")
    max_details = bm.get("max_details", MAX_DETAIL_PAGES)

    print(f"-> {name}: {url} (modalita' pagina dettaglio)")
    try:
        html = fetch_rendered_html(page, url)
    except Exception as e:
        print(f"   [SALTATO] Errore di caricamento indice: {e}")
        detail = str(e).splitlines()[0][:80] if str(e) else e.__class__.__name__
        return [], f"errore di caricamento ({detail})"

    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(link_sel) if link_sel else []
    hrefs = []
    seen_href = set()
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        full = urljoin(url, href)
        if full not in seen_href:
            seen_href.add(full)
            hrefs.append(full)

    if not hrefs:
        print("   [NESSUN RISULTATO] nessun link a pagine di dettaglio trovato nell'indice")
        return [], "nessuna promo riconosciuta"

    hrefs = hrefs[:max_details]
    items = []
    for detail_url in hrefs:
        try:
            time.sleep(random.uniform(MIN_DETAIL_DELAY_SEC, MAX_DETAIL_DELAY_SEC))
            dhtml = fetch_rendered_html(page, detail_url, timeout_ms=20000)
        except Exception as e:
            print(f"   [dettaglio saltato] {detail_url}: {e}")
            continue
        dsoup = BeautifulSoup(dhtml, "html.parser")
        content_el = dsoup.select_one(content_sel) if content_sel else None
        title_el = dsoup.select_one(title_sel) if title_sel else None
        if not content_el:
            continue
        text = content_el.get_text(" ", strip=True)
        title = title_el.get_text(strip=True) if title_el else text[:60]
        if not title or len(text) < MIN_SNIPPET_LEN:
            continue
        items.append({
            "title": title[:140],
            "snippet": text[:MAX_SNIPPET_LEN],
            "el": content_el,
            "_detail_url": detail_url,
            "_page_soup": dsoup,
        })

    if not items:
        print("   [NESSUN RISULTATO] pagine di dettaglio raggiunte ma nessun contenuto estraibile")
        return [], "nessuna promo riconosciuta"

    n_before = len(items)
    items = [it for it in items
             if is_monetizable(it["title"] + " " + it["snippet"], monetizable_keywords, exclude_keywords)]
    items = dedupe_by_containment(items)
    n_scartate = n_before - len(items)

    if not items:
        print(f"   [NESSUNA PROMO MONETIZZABILE] {n_before} pagine dettaglio esaminate ma nessuna "
              f"con un meccanismo di bonus riconosciuto e un valore quantificabile")
        return [], "nessuna promo monetizzabile"

    scarti_txt = f", {n_scartate} scartate come non monetizzabili/doppioni" if n_scartate else ""
    print(f"   trovate {len(items)} promo (pagina dettaglio, 2 step{scarti_txt})")
    results = []
    for it in items:
        detail_url = it["_detail_url"]
        dsoup = it["_page_soup"]
        page_og_image = extract_og_image(dsoup, detail_url)
        image, _link = extract_image_and_link(it["el"], detail_url, page_og_image)
        full_text = it["el"].get_text(" ", strip=True)
        candidate_slots = extract_candidate_slots(full_text)
        max_cap = extract_max_cap(full_text)
        # Il T&C completo viene ricavato dalla stessa pagina di dettaglio gia'
        # visitata (nessuna richiesta aggiuntiva): decompose() e' distruttivo,
        # quindi va chiamato per ultimo su questo soup.
        terms = extract_terms_from_soup(dsoup)
        results.append({
            "book": name,
            "title": it["title"],
            "value": guess_value(it["snippet"]),
            "deadline": guess_deadline(it["snippet"]),
            "wager": "",
            "status": "Da iniziare",
            "note": f"[auto {datetime.now().strftime('%Y-%m-%d')}] {it['snippet']} — fonte: {detail_url}",
            "image": image,
            "url": detail_url,
            "max_cap": max_cap,
            "candidate_slots": candidate_slots,
            "terms": terms,
        })
    return results, "ok"


def scrape_bookmaker(page, bm, keywords, monetizable_keywords, exclude_keywords, terms_cache, run_state):
    name = bm["name"]
    url = bm["url"]

    if bm.get("mode") == "detail_pages":
        return scrape_detail_pages(page, bm, monetizable_keywords, exclude_keywords)

    print(f"-> {name}: {url}")
    try:
        html = fetch_rendered_html(page, url)
    except Exception as e:
        print(f"   [SALTATO] Errore di caricamento: {e}")
        detail = str(e).splitlines()[0][:80] if str(e) else e.__class__.__name__
        return [], f"errore di caricamento ({detail})"

    soup = BeautifulSoup(html, "html.parser")
    page_og_image = extract_og_image(soup, url)

    items = extract_with_selectors(soup, bm.get("card_selector", ""), bm.get("title_selector", ""))
    method = "selettori CSS"
    if not items:
        items = extract_heuristic(soup, keywords)
        method = "euristica per parole chiave"

    if not items:
        print("   [NESSUN RISULTATO] pagina caricata ma nessuna promo riconosciuta "
              "(possibile paywall/login richiesto, o struttura pagina non standard)")
        return [], "nessuna promo riconosciuta"

    n_before = len(items)
    if method == "euristica per parole chiave":
        # L'estrazione euristica e' quella che cattura piu' rumore (menu,
        # login, errori...): applichiamo il filtro completo di monetizzabilita'
        # (serve un meccanismo di bonus riconosciuto + un valore quantificabile).
        items = [it for it in items
                 if is_monetizable(it["title"] + " " + it["snippet"], monetizable_keywords, exclude_keywords)]
    else:
        # Le card da selettori CSS sono gia' mirate (non serve il requisito di
        # parola chiave+valore), ma possono comunque contenere frasi da
        # escludere sempre (es. "montepremi" condiviso tra piu' partecipanti,
        # "porta un amico"): applichiamo solo il controllo delle esclusioni.
        items = [it for it in items
                 if not any(p in (it["title"] + " " + it["snippet"]).lower() for p in exclude_keywords)]
    items = dedupe_by_containment(items)
    n_scartate = n_before - len(items)

    if not items:
        print(f"   [NESSUNA PROMO MONETIZZABILE] {n_before} blocchi trovati ({method}) ma nessuno "
              f"con un meccanismo di bonus riconosciuto e un valore quantificabile")
        return [], "nessuna promo monetizzabile"

    scarti_txt = f", {n_scartate} scartate come non monetizzabili/doppioni" if n_scartate else ""
    print(f"   trovate {len(items)} promo ({method}{scarti_txt})")
    results = []
    for it in items:
        image, link = extract_image_and_link(it["el"], url, page_og_image)
        full_text = it["el"].get_text(" ", strip=True)
        candidate_slots = extract_candidate_slots(full_text)
        max_cap = extract_max_cap(full_text)
        results.append({
            "book": name,
            "title": it["title"],
            "value": guess_value(it["snippet"]),
            "deadline": guess_deadline(it["snippet"]),
            "wager": "",
            "status": "Da iniziare",
            "note": f"[auto {datetime.now().strftime('%Y-%m-%d')}] {it['snippet']} — fonte: {url}",
            "image": image,
            "url": link,
            "max_cap": max_cap,
            "candidate_slots": candidate_slots,
        })

    # Arricchimento con i T&C completi dalla pagina di dettaglio di ogni
    # singola promo (link estratto dalla card): rispetta cache (non ri-scarica
    # promo gia' arricchite in un run precedente) e budget per-run condiviso
    # tra tutti i bookmaker, per restare dentro tempi/traffico ragionevoli.
    # Attivo di default su tutti; disattivabile per singolo bookmaker con
    # "enrich_terms": false in scraper_config.json se in futuro un sito
    # specifico desse problemi (redirect loop, pagine di dettaglio inutili...).
    if bm.get("enrich_terms", True):
        enriched_now = 0
        for r in results:
            budget_before = run_state["enrich_budget"]
            enrich_with_terms(page, r, terms_cache, run_state, url)
            if run_state["enrich_budget"] < budget_before:
                enriched_now += 1
        if enriched_now:
            print(f"   +{enriched_now} T&C completi scaricati dalla pagina di dettaglio "
                  f"(budget rimanente questo run: {run_state['enrich_budget']})")

    return results, "ok"


# ---------------------------------------------------------------------------
# Pubblicazione automatica su GitHub Pages (Opzione A: hosting statico +
# scraping locale)
# ---------------------------------------------------------------------------
# Dopo ogni run, se questa cartella e' collegata a un repository git (l'utente
# lo configura una tantum seguendo i passaggi in LEGGIMI_scraper.md), lo
# script pubblica il nuovo promozioni.json cosi' l'app online mostra sempre i
# dati aggiornati, su qualunque dispositivo. E' completamente automatico e
# NON blocca lo scraping: se git non e' configurato, non c'e' connessione, o
# il push fallisce per qualsiasi motivo, viene solo stampato un avviso (finisce
# in scraper_log.txt) e lo script continua/termina normalmente.
def publish_to_git():
    if not GIT_DIR.exists():
        print("\n(pubblicazione online non configurata: nessun repository git in questa "
              "cartella — vedi LEGGIMI_scraper.md per il setup una tantum, opzionale)")
        return

    def run_git(args):
        return subprocess.run(
            ["git"] + args, cwd=str(HERE), capture_output=True, text=True,
            timeout=GIT_PUSH_TIMEOUT_SEC,
        )

    try:
        add = run_git(["add", "promozioni.json"])
        if add.returncode != 0:
            print(f"[pubblicazione online] 'git add' fallito: {add.stderr.strip()[:200]}")
            return

        commit = run_git(["commit", "-m",
                           f"Aggiornamento automatico promozioni {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
        if commit.returncode != 0:
            # Caso normalissimo: nessuna modifica rispetto all'ultimo run
            # pubblicato (stesse promo di prima) -> "nothing to commit", non
            # e' un errore.
            if "nothing to commit" in (commit.stdout + commit.stderr).lower():
                print("(pubblicazione online: nessuna modifica rispetto all'ultimo run, nulla da pubblicare)")
            else:
                print(f"[pubblicazione online] 'git commit' fallito: {commit.stderr.strip()[:200]}")
            return

        push = run_git(["push"])
        if push.returncode != 0:
            print(f"[pubblicazione online] 'git push' fallito (verifica connessione/credenziali "
                  f"salvate): {push.stderr.strip()[:300]}")
            return

        print("(pubblicazione online: promozioni.json aggiornato con successo sull'app pubblica)")
    except subprocess.TimeoutExpired:
        print("[pubblicazione online] timeout durante git push (rete lenta/assente): salto questo run, "
              "riprovera' al prossimo.")
    except Exception as e:
        print(f"[pubblicazione online] errore imprevisto, non blocca lo scraping: {e}")


def main():
    config = load_config()
    bookmakers = list(config.get("bookmakers", []))
    keywords = [k.lower() for k in config.get("keywords", [])]
    monetizable_keywords = [k.lower() for k in config.get("monetizable_keywords", MONETIZABLE_KEYWORDS_DEFAULT)]
    exclude_keywords = [k.lower() for k in config.get("exclude_keywords", EXCLUDE_PATTERNS_DEFAULT)]
    state = load_state()

    # Carica le promozioni gia' salvate PRIMA di scrapare: serve sia per il
    # merge finale (invariato) sia per costruire la cache dei T&C gia'
    # scaricati in run precedenti, cosi' non li ri-scarichiamo ogni volta.
    existing = []
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []
    terms_cache = {(o["book"], o["title"]): o["terms"] for o in existing if o.get("terms")}
    run_state = {"enrich_budget": MAX_ENRICH_PER_RUN}

    # Ordine casuale ad ogni run: un pattern di richieste sempre identico
    # (stessa sequenza, stessi orari) e' piu' facile da riconoscere come bot.
    random.shuffle(bookmakers)

    all_offers = []
    log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="it-IT",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )
        page = context.new_page()

        for bm in bookmakers:
            name = bm["name"]

            if is_in_cooldown(state, name):
                until = state[name]["cooldown_until"]
                print(f"-> {name}: in pausa fino a {until} (troppi errori consecutivi, salto)")
                log.append({"bookmaker": name, "status": "in pausa (cooldown anti-blocco)", "trovate": 0})
                continue

            offers, status = scrape_bookmaker(page, bm, keywords, monetizable_keywords, exclude_keywords,
                                               terms_cache, run_state)
            all_offers.extend(offers)
            log.append({"bookmaker": name, "status": status, "trovate": len(offers)})
            record_result(state, name, success=(status in ("ok", "nessuna promo riconosciuta", "nessuna promo monetizzabile")))

            # Ritardo casuale tra un bookmaker e l'altro, non fisso.
            time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))

        # Lookup RTP/volatilita' per le slot candidate individuate nelle promo,
        # con un tetto massimo di ricerche per run (per non appesantire troppo
        # l'esecuzione ne' generare traffico eccessivo verso il motore di ricerca).
        lookups_done = 0
        for offer in all_offers:
            if offer.get("max_cap") is None:
                offer["note"] += (" | ATTENZIONE: importo massimo convertibile (cap) non trovato "
                                   "automaticamente — verifica nei termini della promo e inseriscilo "
                                   "a mano nel tab Strategia Slot.")
                offer["max_cap"] = 0
            candidates = offer.pop("candidate_slots", [])
            if not candidates:
                offer["slots"] = []
                continue
            slot_infos = []
            for slot_name in candidates:
                if lookups_done >= RTP_LOOKUP_MAX_SLOTS:
                    slot_infos.append({"name": slot_name, "rtp": "", "volatility": "", "source": "",
                                        "note": "non verificata in questo run (limite ricerche raggiunto)"})
                    continue
                info = lookup_slot_rtp_volatility(page, slot_name)
                slot_infos.append(info)
                lookups_done += 1
                time.sleep(random.uniform(1.5, 3))
            offer["slots"] = slot_infos
            missing = [s["name"] for s in slot_infos if not s["rtp"] and not s["volatility"]]
            if missing:
                offer["note"] += (f" | ATTENZIONE: RTP/volatilita' non trovati automaticamente per: "
                                   f"{', '.join(missing)} — verifica manualmente sul bookmaker o sul "
                                   f"sito del provider della slot.")
            found = [f"{s['name']} (RTP {s['rtp'] or '?'}, volatilita' {s['volatility'] or '?'})"
                     for s in slot_infos if s["rtp"] or s["volatility"]]
            if found:
                offer["note"] += f" | Slot rilevate: {'; '.join(found)}. Rollover a spin minimi."

        browser.close()

    save_state(state)

    # Unisce con le promozioni gia' presenti nel file (evita di perdere lo
    # storico se un run trova meno risultati di uno precedente). 'existing' e'
    # gia' stato caricato a inizio funzione (serviva anche per la cache T&C).
    merged = {(o["book"], o["title"]): o for o in existing}
    for o in all_offers:
        merged[(o["book"], o["title"])] = o

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(list(merged.values()), f, ensure_ascii=False, indent=2)

    publish_to_git()

    with_terms = sum(1 for o in merged.values() if o.get("terms"))
    used_budget = MAX_ENRICH_PER_RUN - run_state["enrich_budget"]

    print("\n" + "=" * 60)
    print(f"Completato. {len(merged)} promozioni totali salvate in {OUTPUT_PATH.name} "
          f"({len(all_offers)} trovate in questo run)")
    print(f"T&C completi: {with_terms}/{len(merged)} promozioni arricchite in totale "
          f"({used_budget}/{MAX_ENRICH_PER_RUN} nuove pagine di dettaglio scaricate in questo run)")
    print("=" * 60)
    for entry in log:
        marker = "OK " if entry["status"] == "ok" else "!! "
        print(f"{marker}{entry['bookmaker']:<28} {entry['status']:<35} ({entry['trovate']} trovate)")
    print("\nOra apri MatchBetting_Assistant.html > tab Offerte > 'Importa da file' "
          f"e seleziona {OUTPUT_PATH.name}.")


if __name__ == "__main__":
    main()
