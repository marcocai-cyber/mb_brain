#!/usr/bin/env python3
"""
Calcolo EV delle quote maggiorate
=================================
Legge maggiorate.json (prodotto da scraper_maggiorate.py), ricava la quota
"fair" di ogni maggiorata e calcola l'EV:

    EV% = quota_maggiorata x probabilita_fair - 1

Da dove arriva la fair
  - Livello 1 (automatico): Betfair Exchange. Il testo della maggiorata viene
    tradotto in un mercato exchange (1X2, doppia chance, over/under, goal/nogoal,
    risultato esatto anche multiplo, parziale/finale, 1X2+goal, over 1,5 primo
    tempo, e le combo "vincono tutte / tutte over / tutte goal" su piu' partite
    come prodotto delle probabilita'). La probabilita' di ogni esito e' la
    media tra 1/back e 1/lay, poi normalizzata sul mercato (via il margine).
    Si calcola anche un EV "conservativo" contro la quota lay (EV cons. =
    quota / lay - 1), utile quando lo spread e' largo.
  - Livello 2 (manuale): marcatori, assist, cartellini, corner, multigol...
    La fair si inserisce a mano dall'app (o in maggiorate_manuali.json) come
    quota fair oppure come back/lay letti sull'exchange.

Le fair inserite a mano hanno sempre la precedenza su quelle automatiche.

Credenziali Betfair: file betfair_credenziali.json nella stessa cartella
(NON finisce su git, vedi .gitignore):
    {"app_key": "...", "username": "...", "password": "..."}
L'app key si crea gratis dall'account Betfair (sezione sviluppatori, "delayed
app key" va bene per leggere le quote). Senza credenziali il calcolo funziona
lo stesso con le sole fair manuali.

Esecuzione:
    python ev_maggiorate.py
Output:
    maggiorate_ev.json  e  maggiorate_report.html
"""

import difflib
import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
INPUT_PATH = HERE / "maggiorate.json"
OUTPUT_PATH = HERE / "maggiorate_ev.json"
REPORT_PATH = HERE / "maggiorate_report.html"
MANUAL_PATH = HERE / "maggiorate_manuali.json"
CRED_PATH = HERE / "betfair_credenziali.json"
SESSION_PATH = HERE / "betfair_sessione.json"
ALIAS_PATH = HERE / "alias_squadre.json"
CONFIG_PATH = HERE / "maggiorate_config.json"

BF_LOGIN_URL = "https://identitysso.betfair.it/api/login"
BF_API_URL = "https://api.betfair.it/exchange/betting/rest/v1.0/"
SPREAD_WARN = 0.10  # spread back/lay oltre il 10%: fair poco affidabile


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|ac|as|ssc|cf|sc|calcio|club|u\d\d)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def ev_pct(quota, prob):
    return round((quota * prob - 1) * 100, 2)


# ---------------------------------------------------------------------------
# Dal testo della maggiorata al mercato exchange
# ---------------------------------------------------------------------------

def split_event(evento):
    if not evento:
        return None
    parts = re.split(r"\s+(?:-|–|vs\.?|v)\s+", evento.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def team_side(name, home, away):
    """'home' / 'away' / None confrontando un nome squadra con le due squadre."""
    n = norm(name)
    if not n:
        return None
    sh = difflib.SequenceMatcher(None, n, norm(home)).ratio()
    sa = difflib.SequenceMatcher(None, n, norm(away)).ratio()
    if norm(home) and (norm(home) in n or n in norm(home)):
        sh = max(sh, 0.95)
    if norm(away) and (norm(away) in n or n in norm(away)):
        sa = max(sa, 0.95)
    if max(sh, sa) < 0.6:
        return None
    return "home" if sh >= sa else "away"


def _line(txt):
    m = re.search(r"(?:over|under|u/o)\s*(\d+)[.,]5", txt)
    return f"{m.group(1)}.5" if m else None


LEVEL2_WORDS = ["marcator", "segna", "assist", "cartellin", "ammonit", "espuls", "corner", "angol",
                "multigol", "multigoal", "tiri", "falli", "minuto", "primo goal", "primo gol", "palo",
                "traversa", "rigore", "sostitut", "range", "entrambi i tempi", "1t", "2t", "punti", "margine",
                " ace", "doppi falli", " set ", " game", "in ogni momento", "in vantaggio"]


def parse_market(item):
    """Ritorna {'livello': 1, 'legs': [...]} per i mercati calcolabili da
    exchange, {'livello': 2, 'motivo': ...} altrimenti.
    Ogni leg: {'home','away' (o 'team'), 'market', 'sel'}; le leg si
    moltiplicano (partite diverse), le 'sel' multiple di una leg si sommano."""
    desc = item.get("descrizione", "")
    testo = item.get("testo") or desc
    flat = " ".join(testo.split("\n")).lower()
    # Testo "pulito" della card: senza righe-quota, date, max bet e conteggi giocate
    keep = []
    for l in testo.split("\n"):
        l = l.strip()
        if not l or re.fullmatch(r"\d{1,4}[.,]\d{2,3}", l) or re.search(r"max\s*bet|giocata|volte", l, re.I):
            continue
        keep.append(re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", l))
    raw = (item.get("etichetta", "") + " " + " ".join(keep)).lower()
    raw = re.sub(r"\s+", " ", raw)
    t = norm(raw).replace(" x 2", " x2").replace(" 1 x", " 1x")

    # --- Combo su piu' partite (Fastbet / Marathonbet / Zonagioco) ---
    combo_line = _combo_line(testo)
    if re.search(r"vinc\w* tutt", flat) and combo_line:
        teams = _multi_teams(combo_line)
        if len(teams) >= 2:
            return {"livello": 1, "legs": [{"team": tm, "market": "MATCH_ODDS", "sel": ["team"]} for tm in teams]}
    if re.search(r"tutte\s+over", flat) and combo_line:
        pairs = _multi_pairs(combo_line)
        m = re.search(r"tutte over\D{0,5}(\d)[.,]5", flat)
        if pairs and m:
            return {"livello": 1, "legs": [{"home": h, "away": a, "market": f"OVER_UNDER_{m.group(1)}5",
                                             "sel": ["over"]} for h, a in pairs]}
    if re.search(r"tutte\s+goal", flat) and combo_line:
        pairs = _multi_pairs(combo_line)
        if pairs:
            return {"livello": 1, "legs": [{"home": h, "away": a, "market": "BOTH_TEAMS_TO_SCORE", "sel": ["yes"]}
                                           for h, a in pairs]}

    ev = split_event(item.get("evento"))
    if not ev:
        return {"livello": 2, "motivo": "evento non riconosciuto"}
    home, away = ev

    # --- Mercati della singola partita ---
    if "parziale" in raw and "finale" in raw:
        m = re.search(r"\b([12x])\s*[-/]\s*([12x])\b", raw)
        if m:
            return {"livello": 1, "legs": [{"home": home, "away": away, "market": "HALF_TIME_FULL_TIME",
                                             "sel": [f"{m.group(1)}/{m.group(2)}"]}]}
    if "risultato esatto" in raw:
        scores = re.findall(r"\b(\d)\s*-\s*(\d)\b", raw)
        if scores and not any(w in raw for w in ("corner", "cartell", "tempo")):
            return {"livello": 1, "legs": [{"home": home, "away": away, "market": "CORRECT_SCORE",
                                             "sel": [f"{a} - {b}" for a, b in scores]}]}

    if re.fullmatch(r".*\b(goal\s*/\s*no\s*goal|gg\s*/\s*ng)\b.*", raw) and "+" not in raw:
        sel = "no" if re.search(r"\b(ng|nogoal|no goal)\s*$", raw.strip()) else "yes"
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "BOTH_TEAMS_TO_SCORE", "sel": [sel]}]}
    if "entrambe segnano" in raw and not re.search(r"\+|over|under|1x2|vince", raw):
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "BOTH_TEAMS_TO_SCORE", "sel": ["yes"]}]}

    if any(w in raw for w in LEVEL2_WORDS) and not re.search(r"over\s*1[.,]5\s*primo tempo", raw):
        return {"livello": 2, "motivo": "mercato speciale (marcatori/cartellini/corner/...)"}

    if re.search(r"over\s*1[.,]5\s*primo tempo", raw):
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "FIRST_HALF_GOALS_15", "sel": ["over"]}]}

    # 1X2 + GG/NG
    m = re.search(r"\b([12x])\s*\+\s*(gg|ng|goal|nogoal|no goal)\b", raw)
    if m:
        btts = "yes" if m.group(2) in ("gg", "goal") else "no"
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "MATCH_ODDS_AND_BTTS",
                                         "sel": [f"{m.group(1)}/{btts}"]}]}

    # Doppia chance (anche "l'Italia vince o pareggia")
    m = re.search(r"([a-zà-ù' ]+?)\s+vince o pareggia", raw)
    if m or "doppia chance" in raw:
        sel = None
        if m:
            side = team_side(m.group(1).replace("l'", "").strip(), home, away)
            sel = {"home": "1X", "away": "X2"}.get(side)
        mm = re.search(r"\b(1x|x2|12)\b", t)
        if not sel and mm:
            sel = mm.group(1).upper()
        if sel and not re.search(r"\b(over|under|goal|gg|ng|nogoal)\b", raw):
            parts = {"1X": ["1", "X"], "X2": ["X", "2"], "12": ["1", "2"]}[sel]
            return {"livello": 1, "legs": [{"home": home, "away": away, "market": "MATCH_ODDS", "sel": parts}]}

    # Over/Under semplice
    line = _line(raw)
    ou_free = re.sub(r"(over|under|u/o)\s*\d+[.,]5\s*(goal|gol)?", " ", raw)
    if line and len(re.findall(r"(?:over|under)\s*\d+[.,]5", raw)) == 1 \
            and not re.search(r"\+|\bgg\b|\bng\b|goal|1x2|esito|vince", ou_free):
        sel = "over" if "over" in raw else "under"
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": f"OVER_UNDER_{line.replace('.', '')}",
                                         "sel": [sel]}]}

    # Goal / NoGoal
    if re.search(r"\b(gg|ng|goal|nogoal|no goal|entrambe segnano)\b", raw) and not line:
        sel = "no" if re.search(r"\b(ng|nogoal|no goal)\b", raw) else "yes"
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "BOTH_TEAMS_TO_SCORE", "sel": [sel]}]}

    # Esito finale 1X2
    m = re.search(r"(?:segno|esito|1x2)\D{0,12}\b([12x])\b", raw)
    if m:
        return {"livello": 1, "legs": [{"home": home, "away": away, "market": "MATCH_ODDS", "sel": [m.group(1).upper()]}]}
    m = re.search(r"([a-zà-ù' ]+?)\s+(?:vincente|vince)\b(?!\s+o\s+pareggia)", raw)
    if m and not re.search(r"tempo|almeno|entramb|minut|range|multi|segna|over|under|goal|gol\b", raw):
        side = team_side(m.group(1), home, away)
        if side:
            return {"livello": 1, "legs": [{"home": home, "away": away, "market": "MATCH_ODDS",
                                             "sel": ["1" if side == "home" else "2"]}]}

    return {"livello": 2, "motivo": "mercato non riconosciuto automaticamente"}


def _combo_line(testo):
    """La riga che elenca le squadre/partite di una combo su piu' partite."""
    best = ""
    for l in testo.split("\n"):
        if re.search(r"maggiorat|vincono|vinceranno|tutte|segnano", l, re.I) and "(" not in l:
            continue
        if (" / " in l or l.count(" - ") >= 2) and re.search(r"[A-Za-z]{3}", l) and len(l) > len(best):
            best = l
    return best


def _multi_teams(desc):
    """'Kazakistan - Cipro - Montenegro (Vincono Tutte)' / 'Kazakistan 02/10 / Cipro 02/10'."""
    s = re.sub(r"\(.*?\)", "", desc.split("·")[0])
    s = re.sub(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", "", s)
    parts = [p.strip() for p in re.split(r"\s+[-/]\s+|\s*/\s*", s) if p.strip()]
    return [p for p in parts if re.search(r"[A-Za-z]", p)]


def _multi_pairs(desc):
    """'Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10' -> [(Kazakistan, Moldova), (Cipro, Armenia)]."""
    s = desc.split("·")[0]
    chunks = [c.strip(" /") for c in re.split(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", s) if c.strip(" /")]
    pairs = []
    for c in chunks:
        p = [x.strip() for x in c.split("/") if x.strip()]
        if len(p) == 2:
            pairs.append((p[0], p[1]))
    return pairs


# ---------------------------------------------------------------------------
# Betfair Exchange
# ---------------------------------------------------------------------------

class BetfairError(Exception):
    pass


class BetfairClient:
    def __init__(self, app_key, username=None, password=None, token=None):
        self.app_key = app_key
        self.username = username
        self.password = password
        self.token = token
        self._event_cache = {}

    @classmethod
    def from_files(cls):
        cred = load_json(CRED_PATH, None)
        if not cred or not cred.get("app_key"):
            return None
        sess = load_json(SESSION_PATH, {})
        token = None
        if sess.get("token") and sess.get("creato_il"):
            try:
                age = datetime.now() - datetime.fromisoformat(sess["creato_il"])
                if age < timedelta(hours=6):
                    token = sess["token"]
            except ValueError:
                pass
        return cls(cred["app_key"], cred.get("username"), cred.get("password"), token)

    def login(self):
        if not (self.username and self.password):
            raise BetfairError("username/password Betfair mancanti in betfair_credenziali.json")
        data = urllib.parse.urlencode({"username": self.username, "password": self.password}).encode()
        req = urllib.request.Request(BF_LOGIN_URL, data=data, headers={
            "X-Application": self.app_key, "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
        if resp.get("status") != "SUCCESS":
            raise BetfairError(f"login Betfair non riuscito: {resp.get('error') or resp}")
        self.token = resp["token"]
        SESSION_PATH.write_text(json.dumps({"token": self.token,
                                            "creato_il": datetime.now().isoformat()}), encoding="utf-8")

    def call(self, method, params, _retry=True):
        if not self.token:
            self.login()
        req = urllib.request.Request(BF_API_URL + method + "/", data=json.dumps(params).encode(), headers={
            "X-Application": self.app_key, "X-Authentication": self.token,
            "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            if _retry and ("INVALID_SESSION" in body or "NO_SESSION" in body or e.code in (400, 401)):
                self.token = None
                return self.call(method, params, _retry=False)
            raise BetfairError(f"{method}: HTTP {e.code} {body[:200]}")

    # -- ricerca evento --
    def find_event(self, home=None, away=None, team=None, aliases=None, giorno=None):
        """Evento dell'exchange. Con 'giorno' (date) cerca da quel giorno (ora locale) ai 4
        successivi e, a parita' di nome, preferisce la partita piu' vicina a quel giorno:
        cosi' 'Belgio' del 02/10 e' Belgio-Turchia e non Francia-Belgio del 05/10."""
        aliases = aliases or {}
        key = (home, away, team, str(giorno))
        if key in self._event_cache:
            return self._event_cache[key]
        now = datetime.now(timezone.utc)
        if giorno:
            inizio = datetime(giorno.year, giorno.month, giorno.day).astimezone().astimezone(timezone.utc)
            da, a = inizio, inizio + timedelta(days=4, hours=3)
        else:
            inizio, da, a = None, now - timedelta(hours=3), now + timedelta(days=8)
        window = {"from": da.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": a.strftime("%Y-%m-%dT%H:%M:%SZ")}
        queries = []
        for name in [home, team, away]:
            if name:
                queries += [aliases.get(name.lower(), name), name]
        best, best_score = None, 0.0
        for q in dict.fromkeys(queries):
            res = self.call("listEvents", {"filter": {"eventTypeIds": ["1"], "textQuery": q,
                                                      "marketStartTime": window}, "locale": "it"})
            for r in res:
                ev = r["event"]
                parts = re.split(r"\s+v\s+|\s+-\s+|\s+vs\s+", ev["name"], maxsplit=1)
                if len(parts) != 2:
                    continue
                if team:
                    s = max(_sim(team, parts[0], aliases), _sim(team, parts[1], aliases))
                else:
                    s = min(_sim(home, parts[0], aliases), _sim(away, parts[1], aliases))
                if inizio and ev.get("openDate"):  # vicinanza al giorno indicato
                    try:
                        t = datetime.fromisoformat(ev["openDate"].replace("Z", "+00:00"))
                        s -= 0.02 * max(0.0, (t - inizio).total_seconds() / 86400 - 1)
                    except ValueError:
                        pass
                if s > best_score:
                    best, best_score = {"id": ev["id"], "name": ev["name"], "home": parts[0], "away": parts[1],
                                        "openDate": ev.get("openDate")}, s
        result = best if best_score >= 0.6 else None
        self._event_cache[key] = result
        return result

    def market(self, event_id, market_type):
        cat = self.call("listMarketCatalogue", {"filter": {"eventIds": [event_id], "marketTypeCodes": [market_type]},
                                                "marketProjection": ["RUNNER_DESCRIPTION"], "maxResults": 5,
                                                "locale": "it"})
        if not cat:
            return None
        mk = cat[0]
        book = self.call("listMarketBook", {"marketIds": [mk["marketId"]],
                                            "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}})
        if not book:
            return None
        names = {r["selectionId"]: (r["runnerName"], r.get("sortPriority")) for r in mk["runners"]}
        runners = []
        for r in book[0]["runners"]:
            if r.get("status") not in (None, "ACTIVE"):
                continue
            ex = r.get("ex", {})
            back = ex.get("availableToBack", [{}])[0].get("price") if ex.get("availableToBack") else None
            lay = ex.get("availableToLay", [{}])[0].get("price") if ex.get("availableToLay") else None
            name, prio = names.get(r["selectionId"], ("?", None))
            runners.append({"name": name, "prio": prio, "back": back, "lay": lay})
        return {"marketId": mk["marketId"], "market": market_type, "runners": runners}


_GENERICI = {"fc", "cf", "ac", "as", "ssd", "us", "sc", "afc", "calcio", "club", "cd", "ca", "sv", "fk", "nk",
             "sk", "if", "bk", "1909", "1913", "de", "1907", "ss", "asd", "ud", "sd", "rc", "real"}


def _toks(s):
    return [t for t in norm(s).split() if t not in _GENERICI]


def _sim(a, b, aliases):
    """Somiglianza tra due nomi di squadra (0-1). Uguaglianza delle parole
    significative = 1; un nome contenuto nell'altro vale meno se l'altro ha parole
    in piu' che lo distinguono (Irlanda != Irlanda del Nord, Bosnia ~ Bosnia Erzegovina)."""
    best = 0.0
    for x in dict.fromkeys([a, aliases.get(str(a).lower(), a)]):
        ta, tb = _toks(x), _toks(b)
        if not ta or not tb:
            continue
        if ta == tb:
            return 1.0
        r = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
        sa, sb = set(ta), set(tb)
        if sa <= sb or sb <= sa:
            extra = (sb - sa) | (sa - sb)
            # parole che indicano un'altra squadra/nazionale
            if extra & {"nord", "sud", "del", "north", "northern", "south", "u21", "u19", "u20", "u23",
                        "women", "femminile", "b", "ii", "reserves", "primavera"}:
                r = min(r, 0.5)
            else:
                r = max(r, 0.93)
        best = max(best, r)
    return best


def market_probs(market):
    """Probabilita' fair (media back/lay, normalizzata) e 'lay' di ogni runner."""
    raw = []
    for r in market["runners"]:
        b, l = r.get("back"), r.get("lay")
        if b and l:
            p = 0.5 * (1 / b + 1 / l)
        elif b:
            p = 1 / b
        elif l:
            p = 1 / l
        else:
            p = None
        raw.append(p)
    tot = sum(p for p in raw if p)
    out = []
    for r, p in zip(market["runners"], raw):
        out.append({**r, "p": (p / tot if p and tot else None)})
    return out


def _yes(name):
    return bool(re.search(r"\b(yes|si|sì)\b", name.lower()))


def pick_runners(market, leg, ev):
    """Trova i runner del mercato corrispondenti alle selezioni della leg."""
    rs = market_probs(market)
    home, away = ev["home"], ev["away"]

    def side_of(name):
        n = norm(name)
        if re.search(r"\b(draw|pareggio|the draw|x)\b", n):
            return "X"
        s = team_side(name, home, away)
        return {"home": "1", "away": "2"}.get(s)

    picked = []
    mt = leg["market"]
    for sel in leg["sel"]:
        found = None
        if mt == "MATCH_ODDS":
            want = sel
            if sel == "team":
                want = "1" if team_side(leg["team"], home, away) == "home" else "2"
            prio = {"1": 1, "2": 2, "X": 3}[want]
            found = next((r for r in rs if r["prio"] == prio), None) or next((r for r in rs if side_of(r["name"]) == want), None)
        elif mt.startswith("OVER_UNDER") or mt.startswith("FIRST_HALF_GOALS"):
            found = next((r for r in rs if sel in r["name"].lower()), None)
        elif mt == "BOTH_TEAMS_TO_SCORE":
            found = next((r for r in rs if _yes(r["name"]) == (sel == "yes")), None)
        elif mt == "CORRECT_SCORE":
            found = next((r for r in rs if re.sub(r"\s", "", r["name"]) == sel.replace(" ", "")), None)
        elif mt == "HALF_TIME_FULL_TIME":
            ht, ft = sel.upper().split("/")
            for r in rs:
                parts = r["name"].split("/")
                if len(parts) == 2 and side_of(parts[0]) == ht and side_of(parts[1]) == ft:
                    found = r
                    break
        elif mt == "MATCH_ODDS_AND_BTTS":
            res, btts = sel.split("/")
            for r in rs:
                parts = r["name"].split("/")
                if len(parts) == 2 and side_of(parts[0]) == res.upper() and _yes(parts[1]) == (btts == "yes"):
                    found = r
                    break
        if not found or found["p"] is None:
            return None
        picked.append(found)
    return picked


def fair_from_exchange(spec, client, aliases, giorno=None):
    """Ritorna dict con prob fair, quota fair, prob 'lay' (conservativa), dettaglio
    e avvisi; oppure solleva BetfairError con il motivo."""
    import fair_speciali as FS
    p_tot, p_lay_tot, detail, warn = 1.0, 1.0, [], []
    for leg in spec["legs"]:
        ev = client.find_event(leg.get("home"), leg.get("away"), leg.get("team"), aliases, giorno=giorno)
        if not ev:
            who = leg.get("team") or f"{leg.get('home')} - {leg.get('away')}"
            raise BetfairError(f"evento non trovato sull'exchange: {who}")
        FS.controlla_inizio(ev)
        mk = client.market(ev["id"], leg["market"])
        if not mk:
            raise BetfairError(f"mercato {leg['market']} non disponibile per {ev['name']}")
        picked = pick_runners(mk, leg, ev)
        if not picked:
            raise BetfairError(f"selezione {leg['sel']} non trovata in {leg['market']} ({ev['name']})")
        p_leg = sum(r["p"] for r in picked)
        p_lay = sum(1 / r["lay"] for r in picked) if all(r.get("lay") for r in picked) else None
        for r in picked:
            if r.get("back") and r.get("lay") and r["lay"] / r["back"] - 1 > SPREAD_WARN:
                warn.append(f"spread largo su {r['name']} ({r['back']}/{r['lay']})")
            if not (r.get("back") and r.get("lay")):
                warn.append(f"liquidita' solo da un lato su {r['name']}")
        p_tot *= p_leg
        p_lay_tot = p_lay_tot * p_lay if (p_lay is not None and p_lay_tot is not None) else None
        detail.append(f"{ev['name']} · {leg['market']} · " + " + ".join(
            f"{r['name']} {r.get('back') or '-'}/{r.get('lay') or '-'}" for r in picked))
    # prob "conservativa": la piu' bassa tra fair e 1/lay, cioe' EV mai piu' alto
    # di quello calcolato contro la quota lay (quota / lay - 1)
    p_cons = min(p_tot, p_lay_tot) if p_lay_tot else None
    return {"prob": p_tot, "fair": round(1 / p_tot, 3) if p_tot else None,
            "prob_lay": p_cons, "dettaglio": " | ".join(detail), "avvisi": warn}


# ---------------------------------------------------------------------------
# Calcolo complessivo
# ---------------------------------------------------------------------------

def manual_fair(entry):
    """Fair manuale: {'fair': 2.5} oppure {'back': 2.4, 'lay': 2.5}."""
    if not entry:
        return None
    if entry.get("fair"):
        f = float(entry["fair"])
        return {"prob": 1 / f, "fair": f, "prob_lay": None, "dettaglio": "fair inserita a mano", "avvisi": []}
    b, l = entry.get("back"), entry.get("lay")
    if b and l:
        p = 0.5 * (1 / float(b) + 1 / float(l))
        return {"prob": p, "fair": round(1 / p, 3), "prob_lay": min(p, 1 / float(l)),
                "dettaglio": f"back/lay inseriti a mano {b}/{l} (senza normalizzazione sul mercato)", "avvisi": []}
    return None


def data_maggiorata(it, oggi=None):
    """'dd/mm' della maggiorata -> date (anno piu' vicino a oggi), None se assente."""
    oggi = oggi or date.today()
    m = re.match(r"^(\d{1,2})/(\d{1,2})", (it.get("data") or "").strip())
    if not m:
        return None
    d, mth = int(m.group(1)), int(m.group(2))
    cands = []
    for y in (oggi.year - 1, oggi.year, oggi.year + 1):
        try:
            cands.append(date(y, mth, d))
        except ValueError:
            pass
    return min(cands, key=lambda x: abs((x - oggi).days)) if cands else None


def solo_di_oggi(items, oggi=None):
    """Tiene le maggiorate con la data di oggi (e quelle senza data, verificate poi
    sull'exchange). Ritorna (tenute, scartate)."""
    oggi = oggi or date.today()
    tenute, scartate = [], []
    for it in items:
        d = data_maggiorata(it, oggi)
        (tenute if d in (None, oggi) else scartate).append(it)
    return tenute, scartate


def _completa_eventi(items):
    """Sisal, Snai e PokerStars pubblicano le stesse maggiorate: se una card non
    riporta la partita (es. 'FRA-ITA'), la si prende da una gemella con lo stesso testo."""
    da_testo = {}
    for it in items:
        if it.get("evento") and it.get("descrizione"):
            da_testo.setdefault(norm(it["descrizione"]), it["evento"])
    for it in items:
        if not it.get("evento") and it.get("descrizione"):
            ev = da_testo.get(norm(it["descrizione"]))
            if ev:
                it["evento"] = ev


def evaluate(items, manual, client=None, aliases=None, soglia=0.0, log=print, margini=None,
             sportsbook=None, solo_oggi=False, oggi=None):
    """Calcola fair ed EV. Ordine delle fonti della fair:
    1. fair inserita a mano
    2. mercato exchange diretto (livello 1)
    3. modello calibrato sull'exchange (mercati speciali, fair_speciali.py), con marcatori
       e corner dal Betfair Sportsbook quando l'exchange non li quota
    4. STIMA dalla quota barrata meno un margine medio del book (segnalata come stima)
    Con solo_oggi=True si valutano solo le maggiorate di oggi; le partite gia' iniziate
    sono segnate 'iniziata' (niente fair: le quote exchange sono live)."""
    import fair_speciali as FS
    margini = margini or {"default": 10}
    oggi = oggi or date.today()
    items = [dict(i) for i in items]
    if solo_oggi:
        items, _ = solo_di_oggi(items, oggi)
    _completa_eventi(items)
    calc = FS.Calcolatore(client, aliases or {}, sportsbook=sportsbook) if client is not None else None
    if calc is not None:  # partite note del run: servono a trovare la partita dei giocatori senza squadra
        for it in items:
            parti = re.split(r"\s+(?:-|–|vs\.?|v)\s+", (it.get("evento") or "").strip(), maxsplit=1)
            if len(parti) == 2 and not re.search(r"(?i)speciali|calcio|\d{1,2}/\d{1,2}", it["evento"]):
                k = (parti[0].strip(), parti[1].strip(), data_maggiorata(it, oggi))
                if k not in calc.eventi_noti:
                    calc.eventi_noti.append(k)
    out = []
    for it in items:
        r = dict(it)
        giorno = data_maggiorata(it, oggi) or (oggi if solo_oggi else None)
        if calc is not None:
            calc.giorno = giorno
        spec = parse_market(it)
        r["livello"] = spec["livello"]
        r["mercato_exchange"] = spec.get("legs")
        fair, fonte, errori, iniziata = None, "", [], None
        man = manual_fair(manual.get(it["id"]))
        if man:
            fair, fonte = man, "manuale"
        if not fair and spec["livello"] == 1 and client is not None:
            try:
                fair, fonte = fair_from_exchange(spec, client, aliases or {}, giorno), "Betfair Exchange"
            except FS.PartitaIniziata as e:
                iniziata = str(e)
            except BetfairError as e:
                errori.append(str(e))
            except Exception as e:  # rete, formato inatteso...
                errori.append(f"errore exchange: {str(e)[:120]}")
        if not fair and not iniziata:
            try:
                FS.parse_speciale(it)  # verifica che il testo sia interpretabile
                if calc is None:
                    errori.append("Betfair non configurato: fair automatica non disponibile")
                else:
                    fair = calc.fair(it)
                    fonte = "modello exchange + Sportsbook" if "Sportsbook" in fair["dettaglio"] \
                        else "modello da exchange"
            except FS.PartitaIniziata as e:
                iniziata = str(e)
            except FS.NonRiconosciuto as e:
                errori.append(f"testo non interpretato ({e})")
            except (FS.DatoMancante, BetfairError) as e:
                errori.append(str(e))
            except Exception as e:
                errori.append(f"errore calcolo speciale: {str(e)[:120]}")
        if iniziata and not man:
            r.update({"fair": None, "prob_fair": None, "ev_pct": None, "ev_cons_pct": None, "fonte_fair": "",
                      "dettaglio_fair": "", "avvisi": [], "ev_plus": False, "ev_plus_stima": False,
                      "stima": False, "stato": "iniziata", "errore_fair": iniziata})
            out.append(r)
            continue
        stima = False
        if not fair:
            m = margini.get(it["book"], margini.get("default", 10))
            fair = FS.stima_da_barrata(it, m)
            if fair:
                fonte, stima = "STIMA da barrata", True
        q = it.get("quota_maggiorata")
        if fair and q:
            r["fair"] = fair["fair"]
            r["prob_fair"] = round(fair["prob"], 4)
            r["ev_pct"] = ev_pct(q, fair["prob"])
            r["ev_cons_pct"] = ev_pct(q, fair["prob_lay"]) if fair.get("prob_lay") else None
            r["fonte_fair"] = fonte
            r["dettaglio_fair"] = fair["dettaglio"]
            r["avvisi"] = fair["avvisi"] + ([f"perche' stima: {'; '.join(errori)}"] if stima and errori else [])
            r["stima"] = stima
            r["ev_plus"] = (r["ev_pct"] > soglia) and not stima
            r["ev_plus_stima"] = stima and r["ev_pct"] > soglia
            r["stato"] = ("EV+" if r["ev_pct"] > soglia else "EV-") + (" (stima)" if stima else "")
        else:
            r.update({"fair": None, "prob_fair": None, "ev_pct": None, "ev_cons_pct": None, "fonte_fair": "",
                      "dettaglio_fair": "", "avvisi": [], "ev_plus": False, "ev_plus_stima": False,
                      "stima": False, "stato": "fair mancante"})
            r["errore_fair"] = "; ".join(errori) or "fair non calcolabile: inseriscila a mano"
        out.append(r)
    return out


def telegram_post(r):
    """Testo del segnale nel formato del canale."""
    righe = [f"{r['book'].upper()} - QUOTA MAGGIORATA"]
    if r.get("evento"):
        righe.append(f"{r['evento']}" + (f" ({r['data']})" if r.get("data") else ""))
    righe.append(f"{r.get('descrizione') or r.get('etichetta')} @{r['quota_maggiorata']:.2f}")
    righe.append(f"Puntata massima: {('%g' % r['max_bet']) + ' euro' if r.get('max_bet') else 'n.d.'}")
    cond = ", ".join(r.get("condizioni") or []) or "singola"
    righe.append(f"Condizioni: {cond}")
    if r.get("fair"):
        righe.append(f"Valore Reale @{r['fair']:.2f} {r['ev_pct']:+.1f}% EV")
    return "\n".join(righe)


def write_report(rows, path=REPORT_PATH):
    def fmt(v, suf=""):
        return "" if v is None else (f"{v:.2f}{suf}" if isinstance(v, float) else f"{v}{suf}")
    rows = sorted(rows, key=lambda r: (r.get("ev_pct") is None, -(r.get("ev_pct") or 0)))
    trs = []
    for r in rows:
        cls = "pos" if r.get("ev_plus") else ("neg" if r.get("ev_pct") is not None else "na")
        trs.append(
            f"<tr class='{cls}'><td>{html.escape(r['book'])}</td><td>{html.escape(r.get('evento') or '')}</td>"
            f"<td>{html.escape(r.get('descrizione') or '')}</td><td>{fmt(r.get('quota_barrata'))}</td>"
            f"<td><b>{fmt(r.get('quota_maggiorata'))}</b></td><td>{fmt(r.get('max_bet'))}</td>"
            f"<td>{fmt(r.get('fair'))}</td><td><b>{fmt(r.get('ev_pct'), '%')}</b></td>"
            f"<td>{fmt(r.get('ev_cons_pct'), '%')}</td><td>{html.escape(r.get('fonte_fair') or r.get('errore_fair', ''))}</td></tr>")
    doc = f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Maggiorate EV</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,Segoe UI,Arial;margin:16px;background:#fafafa;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left}}
th{{background:#333;color:#fff;position:sticky;top:0}}tr.pos td{{background:#e6f6ea}}tr.neg td{{color:#777}}
tr.na td{{background:#fff8e1}}</style></head><body>
<h2>Quote maggiorate — EV</h2><p>Aggiornato: {datetime.now():%d/%m/%Y %H:%M}. Verde = EV+ · giallo = fair mancante.</p>
<table><tr><th>Book</th><th>Evento</th><th>Mercato</th><th>Barrata</th><th>Maggiorata</th><th>Max</th>
<th>Fair</th><th>EV%</th><th>EV% cons.</th><th>Fonte / nota</th></tr>{''.join(trs)}</table></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")


def crea_lettore_sportsbook(cfg):
    """Lettore del Betfair Sportsbook (marcatori/corner mancanti sull'exchange), se attivo."""
    if not cfg.get("usa_sportsbook_betfair", True):
        return None
    try:
        import sportsbook_betfair
        return sportsbook_betfair.LettoreSportsbook()
    except Exception:
        return None


def main():
    data = load_json(INPUT_PATH, None)
    if not data:
        print(f"{INPUT_PATH.name} non trovato: lancia prima scraper_maggiorate.py")
        sys.exit(1)
    items = data.get("maggiorate", [])
    manual = load_json(MANUAL_PATH, {})
    for mid, m in manual.items():  # maggiorate aggiunte a mano dall'app
        if m.get("aggiunta_manuale") and not any(i["id"] == mid for i in items):
            items.append(m["aggiunta_manuale"])
    soglia = load_json(CONFIG_PATH, {}).get("soglia_ev_pct", 0.0)
    client = BetfairClient.from_files()
    if client is None:
        print("Betfair non configurato (betfair_credenziali.json): uso solo le fair manuali.")
    cfg = load_json(CONFIG_PATH, {})
    sb = crea_lettore_sportsbook(cfg)
    try:
        rows = evaluate(items, manual, client, load_json(ALIAS_PATH, {}), soglia,
                        margini=cfg.get("margine_speciali_pct"), sportsbook=sb,
                        solo_oggi=cfg.get("solo_oggi", True))
    finally:
        if sb:
            sb.chiudi()
    OUTPUT_PATH.write_text(json.dumps({"calcolato_il": datetime.now().isoformat(timespec="seconds"),
                                       "righe": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(rows)
    n_pos = sum(1 for r in rows if r["ev_plus"])
    n_na = sum(1 for r in rows if r["ev_pct"] is None)
    print(f"{len(rows)} maggiorate: {n_pos} EV+, {n_na} senza fair. Report: {REPORT_PATH.name}")
    for r in rows:
        if r["ev_plus"]:
            print("\n" + telegram_post(r))


if __name__ == "__main__":
    main()
