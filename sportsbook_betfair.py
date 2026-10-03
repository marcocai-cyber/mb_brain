#!/usr/bin/env python3
"""
Quote del Betfair Sportsbook come seconda fonte per la fair
==========================================================
L'exchange spesso non quota marcatori e corner (es. partite delle nazionali).
Il Sportsbook Betfair invece li ha sempre, nella pagina dell'evento, che usa
lo stesso id evento dell'exchange:

    https://www.betfair.it/scommesse/calcio/x/x/e-<eventId>?tab=tutti-i-mercati

La pagina carica le quote da un servizio interno (bff-gql); qui si apre la
pagina con Playwright (come fa gia' lo scraper) e si leggono quelle risposte
JSON, senza interpretare l'HTML. Si usano:

* Primo Marcatore (FIRST_GOAL_SCORER): tutti i giocatori, prima quelli della
  squadra di casa, poi "Nessun goal" e "Autogoal", poi quelli ospiti.
  Tolto il margine (metodo "power", che corregge il favourite-longshot bias),
  la quota di ogni giocatore e' la sua parte dei gol attesi della partita.
* Corner under/over x,5: probabilita' over per ogni linea (margine tolto in
  proporzione).

I dati vengono letti solo quando servono (una volta per partita) e salvati in
cache su file per 30 minuti, cosi' ricalcoli ripetuti non riaprono la pagina.
"""

import json
import math
import re
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_PATH = BASE_DIR / "cache_sportsbook.json"
CACHE_TTL_SEC = 30 * 60
URL = "https://www.betfair.it/scommesse/calcio/x/x/e-{id}?tab={tab}"

# parte dei gol di una squadra segnata da giocatori che il Sportsbook non quota (riserve...)
QUOTA_NON_LISTATI = 0.03
NESSUN_GOL_RE = re.compile(r"(?i)^(nessun\w*\s+go?a?l\w*|no\s+go?a?l\w*|nessun marcatore)$")
AUTOGOL_RE = re.compile(r"(?i)^(autog\w*|own goal)$")


class SportsbookNonDisponibile(Exception):
    pass


# ---------------------------------------------------------------------------
# Dal JSON del Sportsbook ai mercati
# ---------------------------------------------------------------------------

def estrai_mercati(payloads):
    """Lista di risposte JSON -> {urn: {"name", "type", "runners": [(nome, quota)]}}.
    I runner restano nell'ordine della pagina (serve per capire la squadra nel
    Primo Marcatore)."""
    mercati = {}

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if o.get("__typename") == "SportsbookMarket" and isinstance(o.get("runners"), list):
                m = mercati.setdefault(o.get("urn") or o.get("name"), {"name": o.get("name") or "",
                                                                       "type": o.get("marketType") or "",
                                                                       "nomi": [], "quote": {}})
                if o["runners"] and isinstance(o["runners"][0], dict) and "name" in o["runners"][0]:
                    m["nomi"] = [(r.get("selectionId"), r.get("name")) for r in o["runners"]]
                live = (o.get("liveData") or {}).get("runners") or []
                for r in live:
                    dec = ((r.get("odds") or {}).get("decimal"))
                    if r.get("runnerStatus", "ACTIVE") == "ACTIVE" and dec:
                        m["quote"][r.get("selectionId")] = float(dec)
                ev = ((o.get("hierarchy") or {}).get("sportevent") or {})
                if ev.get("openDate"):
                    m["openDate"] = ev["openDate"]
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    for p in payloads:
        walk(p)
    out = {}
    for k, m in mercati.items():
        rs = [(n, m["quote"].get(sid)) for sid, n in m["nomi"] if m["quote"].get(sid)]
        if rs:
            out[k] = {"name": m["name"], "type": m["type"], "runners": rs, "openDate": m.get("openDate")}
    return out


def devig_power(quote):
    """Probabilita' senza margine con il metodo power: p_i = (1/q_i)^k, somma 1.
    Rispetto alla normalizzazione semplice toglie piu' margine ai longshot."""
    inv = [1 / q for q in quote]
    if sum(inv) <= 1:
        tot = sum(inv)
        return [x / tot for x in inv]
    lo, hi = 1.0, 10.0
    for _ in range(80):
        k = (lo + hi) / 2
        s = sum(x ** k for x in inv)
        if s > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    ps = [x ** k for x in inv]
    tot = sum(ps)
    return [p / tot for p in ps]


def analizza(mercati):
    """Mercati del Sportsbook -> dati utili alla fair.
    {"marcatori": {nome: {"quota_gol": frazione dei gol della partita, "chi": casa|ospite|None,
                          "quota": quota sportsbook}},
     "p_nessun_gol": p, "margine_primo": %, "corner": {8.5: p_over, ...}, "openDate": ...}"""
    out = {"marcatori": {}, "p_nessun_gol": None, "margine_primo": None, "corner": {}, "openDate": None}
    for m in mercati.values():
        out["openDate"] = out["openDate"] or m.get("openDate")
        nome_m = m["name"].lower()
        rs = m["runners"]
        if m["type"] == "FIRST_GOAL_SCORER" or "primo marcatore" in nome_m:
            nomi = [n for n, _ in rs]
            ps = devig_power([q for _, q in rs])
            out["margine_primo"] = round((sum(1 / q for _, q in rs) - 1) * 100, 1)
            i_ng = next((i for i, n in enumerate(nomi) if NESSUN_GOL_RE.match(n.strip())), None)
            i_og = next((i for i, n in enumerate(nomi) if AUTOGOL_RE.match(n.strip())), None)
            p_ng = ps[i_ng] if i_ng is not None else None
            out["p_nessun_gol"] = p_ng
            # parte dei gol: tolto "nessun gol", le probabilita' di primo marcatore
            # (autogol compreso) sono proporzionali ai gol attesi di ciascuno
            tot_gol = sum(p for i, p in enumerate(ps) if i != i_ng)
            sep = [i for i in (i_ng, i_og) if i is not None]
            for i, (n, q) in enumerate(rs):
                if i in (i_ng, i_og):
                    continue
                chi = None
                if sep:
                    chi = "casa" if i < min(sep) else ("ospite" if i > max(sep) else None)
                out["marcatori"][n] = {"quota_gol": ps[i] / tot_gol, "chi": chi, "quota": q}
            # parte dei gol della propria squadra (la forza delle squadre la da' l'exchange)
            p_og = ps[i_og] / tot_gol if i_og is not None else 0.0
            for chi in ("casa", "ospite"):
                tot_sq = sum(v["quota_gol"] for v in out["marcatori"].values() if v["chi"] == chi)
                for v in out["marcatori"].values():
                    if v["chi"] == chi and tot_sq > 0:
                        v["quota_squadra"] = v["quota_gol"] / (tot_sq + p_og / 2) * (1 - QUOTA_NON_LISTATI)
        elif re.search(r"corner", nome_m) and len(rs) == 2:
            lm = re.search(r"(\d+)[.,]5", m["name"])
            if not lm:
                continue
            over = next((q for n, q in rs if re.search(r"(?i)\bover\b|\bpi[uù]\b", n)), None)
            under = next((q for n, q in rs if re.search(r"(?i)\bunder\b|\bmeno\b", n)), None)
            if over and under and not re.search(r"(?i)\b(casa|ospite|squadra|1t|primo tempo|2t)\b", nome_m):
                out["corner"][int(lm.group(1)) + 0.5] = (1 / over) / (1 / over + 1 / under)
    return out


# ---------------------------------------------------------------------------
# Lettura con Playwright
# ---------------------------------------------------------------------------

class LettoreSportsbook:
    """Apre la pagina evento del Sportsbook in un Chromium headless (uno solo
    per tutto il calcolo) e ne raccoglie le quote."""

    def __init__(self, headless=True, log=print, cache_path=CACHE_PATH):
        self.headless = headless
        self.log = log
        self.cache_path = Path(cache_path)
        self._pw = self._browser = self._ctx = None
        self._mem = {}
        self.disattivato = None  # motivo, se Playwright non e' disponibile

    # -- cache su file --
    def _cache(self):
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _salva_cache(self, event_id, dati):
        c = self._cache()
        now = time.time()
        c = {k: v for k, v in c.items() if now - v.get("t", 0) < CACHE_TTL_SEC}
        c[str(event_id)] = {"t": now, "dati": dati}
        try:
            self.cache_path.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def dati(self, event_id):
        """Dati analizzati (vedi analizza) per l'evento; solleva SportsbookNonDisponibile."""
        key = str(event_id)
        if key in self._mem:
            return self._mem[key]
        c = self._cache().get(key)
        if c and time.time() - c.get("t", 0) < CACHE_TTL_SEC:
            d = c["dati"]
            d["corner"] = {float(k): v for k, v in d.get("corner", {}).items()}
            self._mem[key] = d
            return d
        d = analizza(self._leggi(event_id))
        self._mem[key] = d
        self._salva_cache(event_id, d)
        return d

    def _avvia(self):
        if self.disattivato:
            raise SportsbookNonDisponibile(self.disattivato)
        if self._browser:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.disattivato = "Playwright non installato"
            raise SportsbookNonDisponibile(self.disattivato)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(
            locale="it-IT", viewport={"width": 1400, "height": 1000},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"))

    def _leggi(self, event_id):
        self._avvia()
        page = self._ctx.new_page()
        risposte = []
        page.on("response", lambda r: risposte.append(r) if "bff-gql" in r.url else None)
        payloads = []

        def raccogli():
            while risposte:
                r = risposte.pop(0)
                try:
                    payloads.append(r.json())
                except Exception:
                    pass

        try:
            page.goto(URL.format(id=event_id, tab="tutti-i-mercati"), timeout=45000, wait_until="domcontentloaded")
            self._rifiuta_cookie(page)
            self._attendi(page, r"Primo Marcatore|Esito Finale", 15000)
            raccogli()
            if not any(m["type"] == "FIRST_GOAL_SCORER" for m in estrai_mercati(payloads).values()):
                try:  # il mercato e' chiuso: aprirlo carica le quote
                    page.get_by_text("Primo Marcatore", exact=True).first.click(timeout=5000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
                raccogli()
            page.goto(URL.format(id=event_id, tab="corner"), timeout=45000, wait_until="domcontentloaded")
            self._attendi(page, r"[Cc]orner", 12000)
            page.wait_for_timeout(1500)
            raccogli()
        except Exception as e:
            raise SportsbookNonDisponibile(f"pagina Sportsbook non leggibile: {str(e)[:100]}")
        finally:
            try:
                page.close()
            except Exception:
                pass
        mercati = estrai_mercati(payloads)
        if not mercati:
            raise SportsbookNonDisponibile(f"nessun mercato Sportsbook per l'evento {event_id}")
        return mercati

    @staticmethod
    def _rifiuta_cookie(page):
        # solo i cookie necessari (scelta piu' rispettosa della privacy)
        for sel in ("#onetrust-reject-all-handler", "button:has-text('Rifiuta')"):
            try:
                page.locator(sel).first.click(timeout=2500)
                return
            except Exception:
                continue

    @staticmethod
    def _attendi(page, regex, timeout_ms):
        try:
            js = ("() => new RegExp(%s).test(document.body.innerText) && "
                  "/\\d+\\.\\d\\d/.test(document.body.innerText)") % json.dumps(regex)
            page.wait_for_function(js, timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(2500)

    def chiudi(self):
        for x in (self._ctx, self._browser):
            try:
                x and x.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._ctx = None


def lambda_giocatore(info, lam_tot):
    """Gol attesi del giocatore = sua parte dei gol x gol attesi della partita."""
    return info["quota_gol"] * lam_tot


def p_segna(info, lam_tot):
    return 1 - math.exp(-lambda_giocatore(info, lam_tot))
