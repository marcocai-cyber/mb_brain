#!/usr/bin/env python3
"""
Fair automatica dei mercati speciali
====================================
Usato da ev_maggiorate.py per le maggiorate che non corrispondono a un singolo
mercato dell'exchange (livello 2): multigol, gol range, over/under nei tempi,
"segna in entrambi i tempi", "vince almeno un tempo", combo dello stesso
match (1X2 + over + goal...), marcatori (anche "+ 1X2", primo marcatore,
doppietta), goal o assist, ammoniti, corner e cartellini totali, e le combo su
piu' partite (vincono/segnano tutte, tutte over, tutte goal).

Come funziona, in breve
-----------------------
1. Per ogni partita si legge Betfair Exchange: 1X2, tutte le linee
   over/under, goal/nogoal, over/under del primo tempo e, se ci sono, i
   mercati giocatore (marcatore, assist, cartellino), corner e cartellini.
2. Con 1X2 + over/under (+ goal/nogoal) si calibra un modello di Poisson
   con correzione Dixon-Coles: gol attesi casa e ospite, piu' la quota di gol
   nel primo tempo (dal mercato over/under 1T, altrimenti 45%).
3. Il modello da' la probabilita' congiunta di tutto cio' che dipende dai gol,
   tempo per tempo: le condizioni dello stesso match si calcolano insieme, cosi'
   la correlazione (es. 1 + Over, marcatore + vittoria) e' gia' compresa.
4. I marcatori: la probabilita' "segna" letta sull'exchange diventa la quota
   dei gol della squadra segnati dal giocatore; dato il numero di gol della
   squadra, il giocatore ne segna almeno uno con 1 - (1 - quota)^gol.
5. Cartellini dei giocatori, corner e cartellini totali vengono dall'exchange
   e si considerano indipendenti dai gol.
6. Partite diverse si moltiplicano.

Se manca un dato indispensabile (es. l'exchange non quota il mercato
marcatore di quella partita) si solleva DatoMancante e ev_maggiorate.py passa
alla stima dalla quota barrata, segnalata come "stima".
"""

import difflib
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone

MAX_GOL_TEMPO = 6      # gol per squadra per tempo enumerati (oltre: probabilita' trascurabile)
QUOTA_1T_DEFAULT = 0.45  # quota media dei gol segnati nel primo tempo
QUOTA_0_15_DEFAULT = 0.14  # quota media dei gol segnati nei primi 15 minuti


class DatoMancante(Exception):
    """Manca un dato dell'exchange necessario per la fair automatica."""


class NonRiconosciuto(Exception):
    """Il testo della maggiorata non e' stato tradotto in condizioni calcolabili."""


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def poi(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def dc_tau(h, a, lh, la, rho):
    if h == 0 and a == 0:
        return 1 - lh * la * rho
    if h == 0 and a == 1:
        return 1 + lh * rho
    if h == 1 and a == 0:
        return 1 + la * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def nelder_mead(f, x0, step=0.2, iters=400, tol=1e-10):
    """Minimizzazione senza dipendenze esterne (niente scipy)."""
    n = len(x0)
    pts = [list(x0)]
    for i in range(n):
        p = list(x0)
        p[i] += step
        pts.append(p)
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        c = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [c[j] + (c[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [c[j] + 2 * (c[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = [c[j] + 0.5 * (pts[-1][j] - c[j]) for j in range(n)]
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    best = min(range(n + 1), key=lambda i: vals[i])
    return pts[best], vals[best]


# ---------------------------------------------------------------------------
# Modello della partita
# ---------------------------------------------------------------------------

class MatchModel:
    def __init__(self, lh, la, rho=0.0, s1=QUOTA_1T_DEFAULT, fit_error=None):
        self.lh, self.la, self.rho, self.s1 = lh, la, rho, s1
        self.fit_error = fit_error
        self._states = None

    def __repr__(self):
        return (f"MatchModel(gol attesi casa={self.lh:.2f}, ospite={self.la:.2f}, rho={self.rho:+.3f}, "
                f"quota 1T={self.s1:.2f})")

    # -- distribuzione a fine partita (per la calibrazione) --
    def ft(self, maxg=10):
        m = {}
        for h in range(maxg + 1):
            ph = poi(h, self.lh)
            for a in range(maxg + 1):
                m[(h, a)] = ph * poi(a, self.la) * dc_tau(h, a, self.lh, self.la, self.rho)
        tot = sum(m.values())
        return {k: v / tot for k, v in m.items()}

    def summary(self):
        m = self.ft()
        p1 = sum(v for (h, a), v in m.items() if h > a)
        px = sum(v for (h, a), v in m.items() if h == a)
        out = {"1": p1, "X": px, "2": 1 - p1 - px,
               "btts": sum(v for (h, a), v in m.items() if h > 0 and a > 0), "_ft": m}
        for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
            out[f"over{line}"] = sum(v for (h, a), v in m.items() if h + a > line)
        return out

    # -- distribuzione tempo per tempo (per gli eventi) --
    def states(self):
        """Lista di (gol casa 1T, ospite 1T, casa 2T, ospite 2T, probabilita')."""
        if self._states is None:
            n = MAX_GOL_TEMPO
            h1 = [poi(k, self.lh * self.s1) for k in range(n + 1)]
            h2 = [poi(k, self.lh * (1 - self.s1)) for k in range(n + 1)]
            a1 = [poi(k, self.la * self.s1) for k in range(n + 1)]
            a2 = [poi(k, self.la * (1 - self.s1)) for k in range(n + 1)]
            st = []
            for i in range(n + 1):
                for j in range(n + 1):
                    for k in range(n + 1):
                        for l in range(n + 1):
                            w = h1[i] * a1[j] * h2[k] * a2[l] * dc_tau(i + k, j + l, self.lh, self.la, self.rho)
                            if w > 1e-10:
                                st.append((i, j, k, l, w))
            tot = sum(s[4] for s in st)
            self._states = [(i, j, k, l, w / tot) for i, j, k, l, w in st]
        return self._states

    @classmethod
    def fit(cls, targets):
        """targets: {'1x2': (p1, pX, p2), 'ou': {2.5: p_over, ...}, 'btts': p, 'ou1t': {0.5: p_over, ...}}"""
        tx = targets.get("1x2")
        if not tx:
            raise DatoMancante("1X2 dell'exchange non disponibile: impossibile calibrare il modello")
        ou = targets.get("ou") or {}
        btts = targets.get("btts")
        cs = targets.get("cs") or {}
        free_rho = bool(ou) or len(cs) >= 6

        # punto di partenza: gol totali dall'over 2.5 (se c'e'), ripartiti col 1X2
        tot0 = 2.6
        if 2.5 in ou:
            for t in [x / 20 for x in range(20, 100)]:
                if 1 - sum(poi(k, t) for k in range(3)) >= ou[2.5]:
                    tot0 = t
                    break
        share = 0.5 + 0.6 * (tx[0] - tx[2])
        share = min(max(share, 0.15), 0.85)
        x0 = [math.log(tot0 * share), math.log(tot0 * (1 - share)), 0.0]

        def loss(x):
            lh, la = math.exp(x[0]), math.exp(x[1])
            rho = x[2] if free_rho else 0.0
            if not (0.05 < lh < 6 and 0.05 < la < 6) or abs(rho) > 0.25:
                return 1e3
            m = cls(lh, la, rho).summary()
            err = (m["1"] - tx[0]) ** 2 + (m["X"] - tx[1]) ** 2 + (m["2"] - tx[2]) ** 2
            for line, p in ou.items():
                key = f"over{line}"
                if key in m:
                    err += (m[key] - p) ** 2
            if btts is not None:
                err += 0.5 * (m["btts"] - btts) ** 2
            if cs:  # risultato esatto: pesa soprattutto i punteggi bassi (rho Dixon-Coles)
                ftm = m["_ft"]
                err += 0.5 * sum((ftm.get(k, 0.0) - v) ** 2 for k, v in cs.items())
            return err

        x, err = nelder_mead(loss, x0, step=0.15)
        model = cls(math.exp(x[0]), math.exp(x[1]), x[2] if free_rho else 0.0, fit_error=math.sqrt(err))

        # quota di gol nel primo tempo dagli over/under 1T
        ou1t = targets.get("ou1t") or {}
        ht = targets.get("ht1x2")
        if ou1t or ht:
            lt = model.lh + model.la
            best, best_e = QUOTA_1T_DEFAULT, 9e9
            for s in [x / 1000 for x in range(330, 581, 2)]:
                e = 0.0
                for line, p in ou1t.items():
                    pm = 1 - sum(poi(k, lt * s) for k in range(int(line) + 1))
                    e += (pm - p) ** 2
                if ht:  # 1X2 primo tempo: soprattutto la probabilita' del pareggio al 45'
                    hh = [poi(k, model.lh * s) for k in range(8)]
                    aa = [poi(k, model.la * s) for k in range(8)]
                    p1 = sum(hh[i] * aa[j] for i in range(8) for j in range(8) if i > j)
                    px = sum(hh[i] * aa[i] for i in range(8))
                    e += (p1 - ht[0]) ** 2 + (px - ht[1]) ** 2 + (1 - p1 - px - ht[2]) ** 2
                if e < best_e:
                    best, best_e = s, e
            model.s1 = best
        return model


# ---------------------------------------------------------------------------
# Condizioni e calcolo della probabilita' di una "gamba" (una partita)
# ---------------------------------------------------------------------------
#
# Condizioni sui gol (dipendono dallo stato della partita):
#   {"t": "esito", "sel": ["1", "X"], "tempo": "ft"|"1t"|"2t"}
#   {"t": "gol", "chi": "tot"|"casa"|"ospite", "tempo": "ft"|"1t"|"2t", "min": a, "max": b|None}
#   {"t": "gg", "val": True|False, "tempo": "ft"}
#   {"t": "risultato", "lista": [(h, a), ...]}
#   {"t": "pt_ft", "pt": "1"|"X"|"2", "ft": "1"|"X"|"2"}
#   {"t": "vince_un_tempo", "chi": "casa"|"ospite"}
#   {"t": "vince_entrambi_tempi", "chi": "casa"|"ospite"}
#   {"t": "passa_per", "h": 1, "a": 1}          (risultato x-y in qualsiasi momento)
#   {"t": "primo_gol_squadra", "chi": "casa"|"ospite"}
#   {"t": "gol_entro", "minuto": 15}            (solo da sola, modello a intensita' costante)
# Condizioni giocatore (dipendono dai gol della sua squadra):
#   {"t": "giocatore", "nome": "...", "chi": "casa"|"ospite"|None,
#    "cosa": "segna"|"doppietta"|"primo"|"segna_o_assist"|"segna_assist_o_ammonito"|"ammonito"}
# Condizioni indipendenti dai gol (probabilita' letta sull'exchange):
#   {"t": "corner", "linea": 8.5, "over": True}
#   {"t": "cartellini", "linea": 3.5, "over": True}


def _esito(h, a):
    return "1" if h > a else ("X" if h == a else "2")


def _gol(st, chi, tempo):
    h1, a1, h2, a2 = st
    if tempo == "1t":
        h, a = h1, a1
    elif tempo == "2t":
        h, a = h2, a2
    else:
        h, a = h1 + h2, a1 + a2
    return {"casa": h, "ospite": a, "tot": h + a}[chi]


def cond_vera(c, st):
    """Condizioni deterministiche dato lo stato (gol tempo per tempo)."""
    h1, a1, h2, a2 = st
    t = c["t"]
    if t == "esito":
        tempo = c.get("tempo", "ft")
        h, a = (h1, a1) if tempo == "1t" else (h2, a2) if tempo == "2t" else (h1 + h2, a1 + a2)
        return _esito(h, a) in c["sel"]
    if t == "gol":
        g = _gol(st, c["chi"], c.get("tempo", "ft"))
        return g >= c.get("min", 0) and (c.get("max") is None or g <= c["max"])
    if t == "gg":
        return ((h1 + h2) > 0 and (a1 + a2) > 0) == c.get("val", True)
    if t == "risultato":
        return (h1 + h2, a1 + a2) in [tuple(x) for x in c["lista"]]
    if t == "pt_ft":
        return _esito(h1, a1) == c["pt"] and _esito(h1 + h2, a1 + a2) == c["ft"]
    if t == "vince_un_tempo":
        if c["chi"] == "casa":
            return h1 > a1 or h2 > a2
        return a1 > h1 or a2 > h2
    if t == "vince_entrambi_tempi":
        if c["chi"] == "casa":
            return h1 > a1 and h2 > a2
        return a1 > h1 and a2 > h2
    raise NonRiconosciuto(f"condizione sconosciuta {t}")


def _quota_primo_gol(st, chi):
    """Probabilita' che il primo gol della partita sia della squadra 'chi' (dato lo stato)."""
    h1, a1, h2, a2 = st
    if h1 + a1 > 0:
        return (h1 if chi == "casa" else a1) / (h1 + a1)
    if h2 + a2 > 0:
        return (h2 if chi == "casa" else a2) / (h2 + a2)
    return 0.0


def _p_passa_per(H, A, x, y):
    """Probabilita' che il punteggio passi per x-y in qualche momento, dato il finale H-A.
    Con gol a intensita' costante l'ordine dei gol e' casuale: tra le C(H+A, H) sequenze
    quelle che passano per x-y sono C(x+y, x) * C(H+A-x-y, H-x)."""
    if H < x or A < y:
        return 0.0
    return math.comb(x + y, x) * math.comb(H + A - x - y, H - x) / math.comb(H + A, H)


def prob_leg(model, conds, giocatori=None):
    """Probabilita' che si verifichino TUTTE le condizioni di una partita.
    giocatori: {nome: {"chi", "quota_gol", "quota_assist", "p_cartellino"}} (quote = frazione
    dei gol della squadra)."""
    giocatori = giocatori or {}
    det = [c for c in conds if c["t"] in ("esito", "gol", "gg", "risultato", "pt_ft", "vince_un_tempo",
                                          "vince_entrambi_tempi")]
    passa = [c for c in conds if c["t"] == "passa_per"]
    prime = [c for c in conds if c["t"] == "primo_gol_squadra"]
    gioc = [c for c in conds if c["t"] == "giocatore"]
    indip = 1.0
    for c in conds:
        if c["t"] in ("corner", "cartellini", "prob_fissa"):
            indip *= c["p"]
        elif c["t"] == "giocatore" and c["cosa"] == "ammonito":
            indip *= giocatori[c["nome"]]["p_cartellino"]
    entro = [c for c in conds if c["t"] == "gol_entro"]
    if entro:
        if len(conds) > 1:
            raise NonRiconosciuto("'gol entro il minuto' combinato con altre condizioni")
        lt = model.lh + model.la
        return (1 - math.exp(-lt * QUOTA_0_15_DEFAULT * entro[0]["minuto"] / 15)) * indip

    gioc_gol = [c for c in gioc if c["cosa"] != "ammonito"]
    tot = 0.0
    for (h1, a1, h2, a2, w) in model.states():
        st = (h1, a1, h2, a2)
        if not all(cond_vera(c, st) for c in det):
            continue
        p = w
        for c in prime:
            p *= _quota_primo_gol(st, c["chi"])
        for c in passa:
            p *= _p_passa_per(h1 + h2, a1 + a2, c["h"], c["a"])
        if gioc_gol:
            p *= _prob_giocatori(gioc_gol, giocatori, st)
        tot += p
    return tot * indip


def _prob_giocatori(conds, giocatori, st):
    """Probabilita' delle condizioni giocatore dato lo stato. Per i soli
    marcatori della stessa squadra e' esatta (inclusione-esclusione); per gli
    altri casi si moltiplicano le probabilita' condizionate."""
    h1, a1, h2, a2 = st
    n = {"casa": h1 + h2, "ospite": a1 + a2}
    out = 1.0
    per_squadra = {}
    for c in conds:
        g = giocatori[c["nome"]]
        per_squadra.setdefault(g["chi"], []).append((c, g))
    for chi, lst in per_squadra.items():
        ng = n[chi]
        solo_segna = all(c["cosa"] == "segna" for c, _ in lst)
        if solo_segna and len(lst) > 1:
            shares = [g["quota_gol"] for _, g in lst]
            tot = 0.0
            k = len(shares)
            for mask in range(1 << k):
                sub = [shares[i] for i in range(k) if mask >> i & 1]
                tot += (-1) ** len(sub) * max(0.0, 1 - sum(sub)) ** ng
            out *= max(tot, 0.0)
            continue
        for c, g in lst:
            s = g["quota_gol"]
            cosa = c["cosa"]
            if cosa == "segna":
                out *= 1 - (1 - s) ** ng
            elif cosa == "doppietta":
                out *= 1 - (1 - s) ** ng - (ng * s * (1 - s) ** (ng - 1) if ng >= 1 else 0)
            elif cosa == "primo":
                out *= s * _quota_primo_gol(st, chi)
            elif cosa in ("segna_o_assist", "segna_assist_o_ammonito"):
                q = min(s + g["quota_assist"], 0.95)
                p_no = (1 - q) ** ng
                if cosa == "segna_assist_o_ammonito":
                    p_no *= 1 - g["p_cartellino"]
                out *= 1 - p_no
    return out



# ---------------------------------------------------------------------------
# Partita dal testo della card quando manca la riga "A - B"
# ---------------------------------------------------------------------------

CODICI_SQUADRE = {
    "ITA": "Italia", "FRA": "Francia", "BEL": "Belgio", "TUR": "Turchia", "ENG": "Inghilterra", "CRO": "Croazia",
    "ESP": "Spagna", "CZE": "Repubblica Ceca", "GER": "Germania", "NED": "Olanda", "POR": "Portogallo",
    "NOR": "Norvegia", "DEN": "Danimarca", "WAL": "Galles", "SUI": "Svizzera", "SVN": "Slovenia", "SCO": "Scozia",
    "MKD": "Macedonia del Nord", "HUN": "Ungheria", "GEO": "Georgia", "POL": "Polonia", "ROU": "Romania",
    "SRB": "Serbia", "GRE": "Grecia", "AUT": "Austria", "KOS": "Kosovo", "FIN": "Finlandia", "ALB": "Albania",
    "IRL": "Irlanda", "ISR": "Israele", "UKR": "Ucraina", "NIR": "Irlanda del Nord", "BIH": "Bosnia",
    "SWE": "Svezia", "ISL": "Islanda", "BUL": "Bulgaria", "EST": "Estonia", "LUX": "Lussemburgo",
    "SVK": "Slovacchia", "FRO": "Isole Far Oer", "ARM": "Armenia", "CYP": "Cipro", "KAZ": "Kazakistan",
    "MDA": "Moldova", "LTU": "Lituania", "LVA": "Lettonia", "MNE": "Montenegro", "AZE": "Azerbaigian",
    "ARG": "Argentina", "BRA": "Brasile", "USA": "Stati Uniti", "MEX": "Messico", "JPN": "Giappone",
    "JUV": "Juventus", "INT": "Inter", "MIL": "Milan", "NAP": "Napoli", "ROM": "Roma", "LAZ": "Lazio",
    "ATA": "Atalanta", "FIO": "Fiorentina", "BOL": "Bologna", "TOR": "Torino", "COM": "Como", "GEN": "Genoa",
}
_NOME_SQ = re.compile(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ.'’ -]{2,28}$")
_NON_SQ = re.compile(r"(?i)\b(promo|quota|maggiorat|my combo|nations|league|lega|serie|speciali|calcio|giocata|"
                     r"volte|super|boost|turbo|starter|ultra|max|prima|oggi|domani|int|coppa|cup|liga|"
                     r"marcator\w*|doppiett\w*|parz\w*|1x2|over|under|goal|gol|vince\w*|segna\w*|multigo\w*)\b")
_DATA_RIGA = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s+\d{1,2}:\d{2})?$|^\d{1,2}:\d{2}$")


def evento_da_righe(righe):
    """'Francia', 'Italia', '02/10 20:45' -> 'Francia - Italia'; 'FRA-ITA' -> 'Francia - Italia'."""
    for l in righe:
        m = re.fullmatch(r"([A-Z]{3})\s*-\s*([A-Z]{3})", l.strip())
        if m and m.group(1) in CODICI_SQUADRE and m.group(2) in CODICI_SQUADRE:
            return f"{CODICI_SQUADRE[m.group(1)]} - {CODICI_SQUADRE[m.group(2)]}"
    i_data = next((i for i, l in enumerate(righe) if re.match(r"^\d{1,2}/\d{1,2}", l.strip())), None)
    if i_data is None:
        return ""

    def nome(l, maiuscolo_ok=True):
        l = l.strip()
        if not _NOME_SQ.match(l) or _NON_SQ.search(l):
            return False
        return maiuscolo_ok or not l.isupper()

    prima = []
    for l in reversed(righe[max(0, i_data - 4):i_data]):
        if nome(l):
            prima.insert(0, l.strip())
        elif prima:
            break
        if len(prima) == 2:
            break
    if len(prima) == 2:
        return f"{prima[0]} - {prima[1]}"
    if len(prima) == 1:
        for l in righe[i_data + 1:i_data + 4]:
            if _DATA_RIGA.match(l.strip()) or re.fullmatch(r"[\d:]+", l.strip()):
                continue
            if nome(l, maiuscolo_ok=False):
                return f"{prima[0]} - {l.strip()}"
            break
    return ""

# ---------------------------------------------------------------------------
# Dal testo della maggiorata alle condizioni
# ---------------------------------------------------------------------------

_NUM = r"(\d+)[.,]5"


def _tempo(txt):
    if re.search(r"(1\s*°?\s*t\b|primo tempo|1t\b|1° tempo)", txt):
        return "1t"
    if re.search(r"(2\s*°?\s*t\b|secondo tempo|2t\b|2° tempo)", txt):
        return "2t"
    return "ft"


def _chi_squadra(txt, casa, ospite):
    t = norm(txt)
    if re.search(r"\b(casa|team 1|squadra 1)\b", t):
        return "casa"
    if re.search(r"\b(ospite|team 2|squadra 2|trasferta)\b", t):
        return "ospite"
    if casa and norm(casa) and norm(casa) in t:
        return "casa"
    if ospite and norm(ospite) and norm(ospite) in t:
        return "ospite"
    return None


def _clausola(cl, casa, ospite):
    """Una clausola di testo -> lista di condizioni (o NonRiconosciuto)."""
    c = cl.strip().lower()
    c = re.sub(r"\s+", " ", c)
    out = []

    # mercati che l'exchange non quota (o altri sport): meglio dirlo chiaramente
    if re.search(r"\b(ace|doppi falli|set|game|punti|canestr|tie.?break)\b", c):
        raise NonRiconosciuto("non e' un mercato di calcio")
    if re.search(r"rigor", c):
        raise NonRiconosciuto("rigore si/no: mercato non quotato sull'exchange")
    if re.search(r"\btiri\b|in porta|fuorigioc|falli\b|rimess|parate", c):
        raise NonRiconosciuto("statistiche (tiri/falli...): mercato non quotato sull'exchange")
    if re.search(r"1x2 corner|pi[uù] (calci d.angolo|corner)|corner 1x2|testa a testa corner", c):
        raise NonRiconosciuto("1X2 corner: mercato non quotato sull'exchange")
    if re.search(r"espuls|cartellino rosso", c):
        raise NonRiconosciuto("espulsione: mercato non quotato sull'exchange")
    # risultato esatto in qualsiasi momento ("1-1 in ogni momento")
    if re.search(r"(in ogni momento|in qualsiasi momento|any ?time)", c) and re.search(r"\b(\d)\s*-\s*(\d)\b", c):
        m = re.search(r"\b(\d)\s*-\s*(\d)\b", c)
        return [{"t": "passa_per", "h": int(m.group(1)), "a": int(m.group(2))}]
    # "<squadra> vince entrambi i tempi" / "vince sia il primo che il secondo tempo"
    if re.search(r"vinc\w* (entrambi i tempi|sia il (primo|1.?) (tempo )?(che|sia) il (secondo|2.?))", c):
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            return [{"t": "vince_entrambi_tempi", "chi": chi}]
        raise NonRiconosciuto("vince entrambi i tempi: squadra non individuata")
    # "<squadra> in vantaggio a fine primo tempo" (+ eventualmente "vince")
    if re.search(r"(in vantaggio (a fine|al termine del|alla fine del) (primo|1.?) tempo|vince il (primo|1.?) tempo)", c):
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            sel = "1" if chi == "casa" else "2"
            if re.search(r",?\s*vince\b(?! il (primo|1))", c.split("tempo", 1)[1] if "tempo" in c else ""):
                return [{"t": "pt_ft", "pt": sel, "ft": sel}]
            return [{"t": "esito", "sel": [sel], "tempo": "1t"}]

    # risultato esatto (anche multiplo)
    if "risultato esatto" in c or re.fullmatch(r"(\d\s*-\s*\d\s*)+", c):
        sc = re.findall(r"\b(\d)\s*-\s*(\d)\b", c)
        if sc:
            return [{"t": "risultato", "lista": [(int(h), int(a)) for h, a in sc]}]
    # parziale/finale "1-1", "x/2"
    m = re.search(r"\b([12x])\s*[-/]\s*([12x])\b", c)
    if m and ("parziale" in c or "finale" in c or re.fullmatch(r"[12x]\s*[-/]\s*[12x]", c)):
        return [{"t": "pt_ft", "pt": m.group(1).upper(), "ft": m.group(2).upper()}]
    # "<squadra> vince almeno un tempo"
    if "almeno un tempo" in c or "almeno uno tra il primo e il secondo tempo" in c:
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            return [{"t": "vince_un_tempo", "chi": chi}]
    # "<squadra> segna in entrambi i tempi" / "casa segna in entrambi i tempi"
    if "entrambi i tempi" in c and re.search(r"segn", c) and "over" not in c:
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            return [{"t": "gol", "chi": chi, "tempo": "1t", "min": 1}, {"t": "gol", "chi": chi, "tempo": "2t", "min": 1}]
    # gol entro i primi N minuti / minuto primo goal 0-15
    m = re.search(r"(?:primi|entro i?)\s*(\d{1,2})\s*(?:minuti|')", c) or re.search(r"minuto primo go?a?l\w*\s*0\s*-\s*(\d{1,2})", c)
    if m and ("gol" in c or "goal" in c):
        return [{"t": "gol_entro", "minuto": int(m.group(1))}]
    # <squadra> segna il primo gol
    if re.search(r"segna il (1°|primo) go?a?l", c):
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            return [{"t": "primo_gol_squadra", "chi": chi}]
    # corner / cartellini totali
    m = re.search(r"(over|under)\s*" + _NUM + r"\s*(corner|angol)", c)
    if m:
        return [{"t": "corner", "linea": int(m.group(2)) + 0.5, "over": m.group(1) == "over"}]
    m = re.search(r"(over|under)\s*" + _NUM + r"\s*(cartellin|ammonizion|card)", c)
    if m:
        return [{"t": "cartellini", "linea": int(m.group(2)) + 0.5, "over": m.group(1) == "over"}]
    # multigol squadra/match "multigol casa 2-3", "gol range 2-3", "la francia segna 2-3 goal"
    m = re.search(r"(multigo?a?l|range)\D{0,25}?(\d)\s*[-–]\s*(\d)", c)
    if m:
        chi = _chi_squadra(c, casa, ospite) or "tot"
        return [{"t": "gol", "chi": chi, "tempo": _tempo(c), "min": int(m.group(2)), "max": int(m.group(3))}]
    m = re.search(r"segna (\d)\s*[-–]\s*(\d) go?a?l", c)
    if m:
        chi = _chi_squadra(c, casa, ospite)
        if chi:
            return [{"t": "gol", "chi": chi, "tempo": "ft", "min": int(m.group(1)), "max": int(m.group(2))}]
    # testi esplicativi: "vengono segnati piu' di 2 goal", "almeno 2 gol nel primo tempo",
    # "la polonia realizza da 2 a 3 gol"
    m = re.search(r"da (\d) a (\d) go?a?l", c)
    if m:
        chi = _chi_squadra(c, casa, ospite) or "tot"
        return [{"t": "gol", "chi": chi, "tempo": _tempo(c), "min": int(m.group(1)), "max": int(m.group(2))}]
    m = re.search(r"pi[uù] di (\d+) go?a?l", c) or re.search(r"almeno (\d+|un|uno) go?a?l", c)
    if m and not re.search(r"sia nel primo", c):
        n = 1 if m.group(1) in ("un", "uno") else int(m.group(1))
        mn = n + 1 if "di " + m.group(1) in c and re.search(r"pi[uù]", c) else n
        chi = _chi_squadra(c, casa, ospite) if re.search(r"realizza|segna\b", c) else None
        return [{"t": "gol", "chi": chi or "tot", "tempo": _tempo(c), "min": mn}]
    # segna casa/ospite (nel 1°T), "<squadra> segna almeno N"
    m = re.search(r"segna\s+(casa|ospite)", c) or re.search(r"(casa|ospite)\s+segna", c)
    if m and not re.search(r"entrambi", c):
        return [{"t": "gol", "chi": m.group(1), "tempo": _tempo(c), "min": 1}]
    # over/under gol (match, squadra, tempo); anche "over 0,5 1°t + over 0,5 2°t" (gestito dallo split)
    if re.search(r"\bu/o\b", c) and not re.search(r"\b(over|under)\b", c):
        raise NonRiconosciuto("u/o senza over/under")
    m = re.search(r"(over|under)\s*" + _NUM, c)
    if m and not re.search(r"corner|angol|cartell|tiri|falli", c):
        line = int(m.group(2))
        over = m.group(1) != "under"
        chi = "tot"
        if re.search(r"\b(casa|ospite|team)\b", c):
            chi = _chi_squadra(c, casa, ospite) or "tot"
        cond = {"t": "gol", "chi": chi, "tempo": _tempo(c)}
        cond.update({"min": line + 1, "max": None} if over else {"min": 0, "max": line})
        out.append(cond)
        return out
    # goal / nogoal
    if re.fullmatch(r"(gg|goal|ng|nogoal|no goal|entrambe segnano|segnano entrambe)", c):
        return [{"t": "gg", "val": c in ("gg", "goal", "entrambe segnano", "segnano entrambe")}]
    # doppia chance / esito
    m = re.fullmatch(r"(1x|x2|12|1|x|2)", c)
    if m:
        v = m.group(1).upper()
        return [{"t": "esito", "sel": {"1X": ["1", "X"], "X2": ["X", "2"], "12": ["1", "2"]}.get(v, [v])}]
    m = re.search(r"([a-zà-ù' ]+?)\s+vince o pareggia", c)
    if m:
        chi = _chi_squadra(m.group(1), casa, ospite)
        if chi:
            return [{"t": "esito", "sel": ["1", "X"] if chi == "casa" else ["X", "2"]}]
    m = re.search(r"([a-zà-ù' ]+?)\s+(?:vince|vincente|vincenti)\b", c)
    if m and not re.search(r"tempo|corner|angol|punti|margine|set\b|game|scarto|almeno|entrambi|\d", c):
        chi = _chi_squadra(m.group(1), casa, ospite)
        if chi:
            return [{"t": "esito", "sel": ["1" if chi == "casa" else "2"]}]
    raise NonRiconosciuto(f"clausola non riconosciuta: '{cl.strip()}'")


# -- giocatori --
_P_SEGNA = r"(segna|segnano|a segno|marcatore|goal\b|gol\b)"
_P_ASSIST = r"assist"
_P_CART = r"(ammonit|cartellin|card)"


def _cosa_giocatore(txt):
    t = txt.lower()
    if "primo marcatore" in t:
        return "primo"
    if "doppietta" in t or re.search(r"almeno 2 go?a?l", t):
        return "doppietta"
    if re.search(_P_ASSIST, t) and re.search(_P_CART, t):
        return "segna_assist_o_ammonito"
    if re.search(_P_ASSIST, t):
        return "segna_o_assist"
    if re.search(_P_CART, t):
        return "ammonito"
    if re.search(_P_SEGNA, t):
        return "segna"
    return None


def _nomi_giocatori(txt):
    """Nomi di giocatori da testi tipo 'Dembele O. & Esposito Pio', 'Rabiot, Tonali e Bastoni',
    'P.ESPOSITO+X2', 'Esposito Francesco Pio (Italia):SI', 'Kane  Harry (inghilterra) 03/10 / ...'."""
    t = re.sub(r"\(\d{1,2}/\d{1,2}\)|\d{1,2}/\d{1,2}", " ", txt)
    t = re.sub(r"(?i)\b(tutti|tutte|alm\.?|almeno|1 goal o 1 assist|goal o assist|a segno|segnano|segna|"
               r"segneranno|entrambi|cartellino|ammonito|marcatore plus|marcatore|primo|doppietta|o fanno assist|"
               r"fanno|assist|gol o assist o ammonito|si|sì)\b", " ", t)
    t = re.sub(r":\s*\w+.*$", "", t)
    parts = re.split(r"\s*(?:&|\+|,|/|\be\b)\s*", t)
    nomi = []
    for p in parts:
        team = None
        m = re.search(r"\(([^)]+)\)", p)
        if m:
            team = m.group(1).strip()
            p = p.replace(m.group(0), " ")
        p = re.sub(r"\s+", " ", p).strip(" .-")
        if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", p)) >= 3 and not re.fullmatch(r"(?i)(x2|1x|12|1|2|x)", p):
            nomi.append((p, team))
    return nomi


def parse_speciale(item):
    """Ritorna lista di gambe: [{"casa", "ospite", "conds": [...]} | {"squadra": nome, ...}]
    oppure solleva NonRiconosciuto."""
    testo = item.get("testo") or ""
    desc = item.get("descrizione") or ""
    gruppo = (item.get("gruppo") or "").lower()
    evento = item.get("evento") or ""
    casa = ospite = None
    m = re.split(r"\s+(?:-|–|vs\.?|v)\s+", evento.strip(), maxsplit=1)
    if len(m) == 2 and not re.search(r"(?i)speciali|calcio|\d{1,2}/\d{1,2}", evento):
        casa, ospite = m[0].strip(), m[1].strip()
    righe = [l.strip() for l in testo.split("\n") if l.strip()]
    if not casa:
        ev2 = evento_da_righe(righe)
        if ev2:
            casa, ospite = [x.strip() for x in ev2.split(" - ", 1)]
    corpo = [l for l in righe if not re.fullmatch(r"\d{1,4}[.,]\d{2,3}", l)
             and not re.search(r"max\s*bet|giocata|volte|^\d+$|^(si|sì|no|\+|prima|alias|hcp|oggi|domani)$", l, re.I)]
    flat = " ".join(corpo)
    low = flat.lower()

    # ---- combo su piu' partite (Marathonbet / Fastbet / Betfair SuperCombo / DAZN) ----
    lista = next((l for l in corpo if " / " in l and re.search(r"[A-Za-z]{3}", l)), "")
    if "tutte over" in gruppo or "tutte over" in low:
        m = re.search(r"\b(\d)[.,]5\b", testo)
        coppie = _coppie(lista)
        if coppie and m:
            return [{"casa": a, "ospite": b, "conds": [{"t": "gol", "chi": "tot", "min": int(m.group(1)) + 1}]}
                    for a, b in coppie]
    if "tutte goal" in gruppo or "tutte goal" in low:
        coppie = _coppie(lista)
        if coppie:
            return [{"casa": a, "ospite": b, "conds": [{"t": "gg", "val": True}]} for a, b in coppie]
    if re.search(r"vinc\w* tutt|all teams winners", gruppo + " " + low):
        squadre = _squadre(lista or next((l for l in corpo if l.count(" - ") >= 2), ""))
        if len(squadre) >= 2:
            return [{"squadra": s, "conds": [{"t": "esito_squadra", "val": "vince"}]} for s in squadre]
    if re.search(r"segn\w* tutt|tutti segnano|tutti a segno|tutti marcatori", gruppo + " " + low) and lista:
        if "(" in lista:  # giocatori con nazionale tra parentesi
            gs = _nomi_giocatori(lista)
            return [{"giocatore": n, "squadra_g": tm, "conds": [{"t": "giocatore", "nome": n, "chi": None, "cosa": "segna"}]}
                    for n, tm in gs]
        squadre = _squadre(lista)
        if len(squadre) >= 2:
            return [{"squadra": s, "conds": [{"t": "esito_squadra", "val": "segna"}]} for s in squadre]
    m = re.search(r"([A-Za-zÀ-ÿ' ]+?)\s+e\s+([A-Za-zÀ-ÿ' ]+?)\s+vincenti\s+e\s+over\s+" + _NUM + r".{0,20}entrambi i match", flat, re.I)
    if m:  # Betfair SuperCombo
        line = int(m.group(3))
        return [{"squadra": s.strip(), "conds": [{"t": "esito_squadra", "val": "vince"},
                                                 {"t": "gol", "chi": "tot", "min": line + 1}]}
                for s in (m.group(1), m.group(2))]

    # ---- My Combo (Snai/Sisal): una selezione per riga, in maiuscolo ----
    if re.search(r"(?i)my ?combo", testo) and casa and ospite:
        sel = [l for l in corpo if l.isupper() and len(l) > 6 and re.search(r"[A-Z]{3}", l)
               and not re.search(r"NATIONS|LEAGUE|SERIE|MY COMBO|^INT\b", l)]
        conds = []
        for l in sel:
            mg = re.match(r"^(.+?)\s+(PRIMO\s+)?MARCATORE(\s+\w+)?$", l)
            if mg:
                nome = mg.group(1).title()
                conds.append({"t": "giocatore", "nome": nome, "chi": _chi_squadra(nome, casa, ospite),
                              "cosa": "primo" if mg.group(2) else "segna", "squadra_testo": None})
            else:
                conds.extend(_clausola(l, casa, ospite))
        if conds:
            return [{"casa": casa, "ospite": ospite, "conds": conds}]
        raise NonRiconosciuto("My Combo senza selezioni leggibili")

    # ---- mercati della singola partita (prima prova: righe "tecniche") ----
    err_mercato = None
    if casa and ospite:
        try:
            conds = _prova_mercato(corpo, casa, ospite)
            return [{"casa": casa, "ospite": ospite, "conds": conds}]
        except NonRiconosciuto as e:
            err_mercato = e

    # ---- giocatori ----
    riga_g, nomi = _riga_giocatori(corpo, casa, ospite)
    cosa = _cosa_giocatore(" ".join(corpo))
    if nomi and cosa:
        conds_match = []
        mp = re.search(r"\+\s*([12x])\s*/\s*([12x])\b", riga_g, re.I)
        m = None if mp else (re.search(r"\+\s*(1x|x2|12|1|x|2)\b", riga_g, re.I)
                             or re.search(r":\s*(1|x|2)\s*\+\s*segna", riga_g, re.I))
        if mp:
            conds_match.append({"t": "pt_ft", "pt": mp.group(1).upper(), "ft": mp.group(2).upper()})
        elif m:
            v = m.group(1).upper()
            conds_match.append({"t": "esito", "sel": {"1X": ["1", "X"], "X2": ["X", "2"], "12": ["1", "2"]}.get(v, [v])})
        elif re.search(r"\+\s*$", riga_g) or re.search(r"parz\w*\s*/\s*fin", flat, re.I):
            raise NonRiconosciuto("marcatore + parziale/finale senza selezione leggibile")
        conds = list(conds_match)
        for n, tm in nomi:
            chi = _chi_squadra(tm, casa, ospite) if (tm and casa) else None
            sel0 = (conds_match[0].get("sel") or [conds_match[0].get("ft")]) if conds_match else None
            if chi is None and sel0 in (["1"], ["2"], ["1", "X"], ["X", "2"]):
                # convenzione dei book: il marcatore e' della squadra a cui si abbina l'esito
                chi = "casa" if sel0[0] == "1" else "ospite"
            conds.append({"t": "giocatore", "nome": n, "chi": chi, "cosa": cosa, "squadra_testo": tm})
        if conds_match and casa and ospite:
            return [{"casa": casa, "ospite": ospite, "conds": conds}]
        # solo giocatori: ognuno e' una "gamba" a se' (indipendenti nel modello di Poisson)
        return [{"giocatore": c["nome"], "casa": casa, "ospite": ospite, "conds": [c]} for c in conds]
    raise err_mercato or NonRiconosciuto("mercato non riconosciuto")


_STOP = {"tutti", "tutte", "segnano", "segna", "segno", "goal", "gol", "assist", "cartellino", "cartellini",
         "ammonito", "marcatore", "primo", "doppietta", "over", "under", "quota", "maggiorata", "speciali",
         "calcio", "nel", "corso", "del", "della", "tempo", "viene", "vengono", "almeno", "con", "fanno", "plus",
         "entrambi", "bomber", "alm", "oggi", "domani", "the", "e", "o", "si", "no", "super", "combo", "ott",
         "minuti", "partita", "match", "squadra", "casa", "ospite", "vince", "pareggia", "segnati", "realizza",
         "parz", "fin", "dc", "out", "team", "multigoal", "multigol", "ultra", "starter", "turbo", "nations",
         "league", "int"}


def _plausibile(nome, casa, ospite):
    toks = nome.replace(".", ". ").split()
    if not 1 <= len(toks) <= 4 or re.search(r"\d", nome):
        return False
    if casa and norm(nome) in (norm(casa), norm(ospite)):
        return False
    if " - " in nome or ":" in nome:
        return False
    sig = [t for t in toks if norm(t) and norm(t) not in _STOP]
    if not sig:
        return False
    return all(t[:1].isupper() for t in sig)


def _riga_giocatori(corpo, casa, ospite):
    """La riga con i nomi dei giocatori: quella con piu' nomi plausibili."""
    best, best_n = "", []
    for l in corpo:
        if re.search(r"maggiorat|^(tutti|segna o assist|ammonito|marcatore)\b", l, re.I) and "(" not in l:
            continue
        if re.search(r"(?i)^(primo )?marcatore\s*\+|\+\s*(1x2|dc|parz)", l):
            continue
        l2 = re.sub(r"^\d{1,2}\s+\w{3}:\s*", "", l)  # "2 Ott: ..." (Betfair SuperCombo)
        cand = [(n.strip(" :"), tm) for n, tm in _nomi_giocatori(l2)]
        cand = [(n, tm) for n, tm in cand if _plausibile(n, casa, ospite)]
        if len(cand) >= len(best_n) and cand:
            best, best_n = l2, cand
    return best, best_n


def _prova_mercato(corpo, casa, ospite):
    cand = _righe_selezione(corpo, casa, ospite)
    tentativi = []
    if cand:
        tentativi.append(cand[0])
        if len(cand) > 1:
            tentativi += [f"{cand[0]} {cand[1]}", cand[1]]
        for l in cand[1:]:
            tentativi.append(l)
    ultimo = None
    for t in tentativi:
        clausole = re.split(r"\s+\+\s+|\s+-\s+(?=over|under|\d)|\s*\+\s*(?=gg|ng|goal|over|under|\d)|\s+e\s+(?=l'|la |il |lo |vengono|viene|over|under)",
                            t, flags=re.I)
        try:
            conds = []
            for cl in clausole:
                if cl.strip():
                    conds.extend(_clausola(cl, casa, ospite))
            if conds:
                return conds
        except NonRiconosciuto as e:
            ultimo = e
    raise ultimo or NonRiconosciuto("nessuna selezione")


def _righe_selezione(corpo, casa, ospite):
    """Righe che descrivono la selezione, in ordine (salta evento, competizione, etichette)."""
    out = []
    for l in corpo:
        ll = l.lower()
        if re.search(r"maggiorat|super ?quota|stake boost|^turbo$|^starter$|^ultra$|nations league|serie a|"
                     r"brasileiro|speciali calcio|^calcio\b|amichevol|\d{1,2}:\d{2}|^\(?solo in singola", ll):
            continue
        if casa and ospite and norm(casa) in norm(l) and norm(ospite) in norm(l) and len(l) < 60 \
                and re.search(r"\s(-|–|vs\.?|v)\s", l):
            continue
        if ll in ("vs", "v", "-"):
            continue
        if casa and norm(l) in (norm(casa), norm(ospite)):
            continue
        out.append(re.sub(r"\(solo in singola\)", "", l, flags=re.I).strip())
    return out


def _coppie(riga):
    """'Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10' -> [(Kazakistan, Moldova), (Cipro, Armenia)]."""
    out = []
    for chunk in re.split(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", riga):
        p = [x.strip() for x in chunk.strip(" /").split("/") if x.strip()]
        if len(p) == 2:
            out.append((p[0], p[1]))
    return out


def _squadre(riga):
    s = re.sub(r"\(.*?\)", "", riga)
    s = re.sub(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", "", s)
    return [p.strip() for p in re.split(r"\s+[-/]\s+|\s*/\s*", s) if re.search(r"[A-Za-z]{3}", p)]


# ---------------------------------------------------------------------------
# Dati exchange per una partita
# ---------------------------------------------------------------------------

def _mid(r):
    b, l = r.get("back"), r.get("lay")
    if b and l:
        return 0.5 * (1 / b + 1 / l)
    return (1 / b) if b else ((1 / l) if l else None)


def _line_from(text):
    m = re.search(r"(\d+)[.,]5", text)
    return int(m.group(1)) + 0.5 if m else None


def _is_yes(name):
    return bool(re.search(r"\b(yes|si|sì)\b", name.lower()))


class Snapshot:
    """Quote exchange di una partita, gia' trasformate in probabilita'."""

    def __init__(self, event):
        self.event = event
        self.p1x2 = None
        self.ou, self.ou1t = {}, {}
        self.btts = None
        self.cs = {}        # risultato esatto {(h, a): p}
        self.ht1x2 = None   # 1X2 primo tempo
        self.corner, self.cartellini = {}, {}
        self.segna, self.assist, self.cartellino, self.primo = {}, {}, {}, {}
        self.dettagli = []

    def targets(self):
        return {"1x2": self.p1x2, "ou": self.ou, "btts": self.btts, "ou1t": self.ou1t,
                "cs": self.cs, "ht1x2": self.ht1x2}


def load_snapshot(client, event):
    """Legge tutti i mercati della partita su Betfair e li classifica."""
    snap = Snapshot(event)
    cat = client.call("listMarketCatalogue", {
        "filter": {"eventIds": [event["id"]]},
        "marketProjection": ["RUNNER_DESCRIPTION", "MARKET_DESCRIPTION"],
        "maxResults": 200, "locale": "it"})
    if not cat:
        raise DatoMancante(f"nessun mercato exchange per {event['name']}")
    by_id = {m["marketId"]: m for m in cat}

    def utile(m):
        t = (m.get("description") or {}).get("marketType", "")
        n = m.get("marketName", "").lower()
        return (t in ("MATCH_ODDS", "BOTH_TEAMS_TO_SCORE", "TO_SCORE", "FIRST_GOAL_SCORER", "CORRECT_SCORE",
                      "HALF_TIME")
                or t.startswith(("OVER_UNDER_", "FIRST_HALF_GOALS_"))
                or re.search(r"corner|angol|cartellin|card|booking|ammon|assist|marcator|score", n))
    ids = [mid for mid, m in by_id.items() if utile(m)]
    books = []
    for i in range(0, len(ids), 25):
        books += client.call("listMarketBook", {"marketIds": ids[i:i + 25],
                                                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}})
    for bk in books:
        mk = by_id.get(bk["marketId"])
        if not mk:
            continue
        mtype = (mk.get("description") or {}).get("marketType", "")
        name = mk.get("marketName", "")
        lname = name.lower()
        names = {r["selectionId"]: (r["runnerName"], r.get("sortPriority")) for r in mk.get("runners", [])}
        rs = []
        for r in bk.get("runners", []):
            if r.get("status") not in (None, "ACTIVE"):
                continue
            ex = r.get("ex", {})
            back = ex["availableToBack"][0]["price"] if ex.get("availableToBack") else None
            lay = ex["availableToLay"][0]["price"] if ex.get("availableToLay") else None
            nm, pr = names.get(r["selectionId"], ("?", None))
            rs.append({"name": nm, "prio": pr, "back": back, "lay": lay, "p": None})
        for r in rs:
            r["p"] = _mid(r)
        if not rs or not any(r["p"] for r in rs):
            continue
        yesno = len(rs) == 2 and any(_is_yes(r["name"]) for r in rs)

        def norm_probs(rs_):
            tot = sum(r["p"] for r in rs_ if r["p"])
            return {r["name"]: r["p"] / tot for r in rs_ if r["p"]}

        if mtype == "MATCH_ODDS":
            byp = {r["prio"]: r["p"] for r in rs}
            if all(byp.get(k) for k in (1, 2, 3)):
                t = byp[1] + byp[2] + byp[3]
                snap.p1x2 = (byp[1] / t, byp[3] / t, byp[2] / t)
        elif mtype == "HALF_TIME":
            byp = {r["prio"]: r["p"] for r in rs}
            if all(byp.get(k) for k in (1, 2, 3)):
                t = byp[1] + byp[2] + byp[3]
                snap.ht1x2 = (byp[1] / t, byp[3] / t, byp[2] / t)
        elif mtype == "CORRECT_SCORE":
            pr = norm_probs(rs)
            for k, v in pr.items():
                mm = re.fullmatch(r"\s*(\d)\s*-\s*(\d)\s*", k)
                if mm:
                    snap.cs[(int(mm.group(1)), int(mm.group(2)))] = v
        elif mtype.startswith("OVER_UNDER_") and len(rs) == 2:
            line = int(mtype.rsplit("_", 1)[1]) / 10 if mtype.rsplit("_", 1)[1].isdigit() else _line_from(name)
            pr = norm_probs(rs)
            over = next((v for k, v in pr.items() if "over" in k.lower()), None)
            if over is None:  # nomi non standard: su Betfair il runner Over ha priorita' 2
                r2 = next((r for r in rs if r["prio"] == 2 and r["p"]), None)
                over = pr.get(r2["name"]) if r2 else None
            if over is not None and line:
                snap.ou[line] = over
        elif mtype.startswith("FIRST_HALF_GOALS_") and len(rs) == 2:
            line = int(mtype.rsplit("_", 1)[1]) / 10
            pr = norm_probs(rs)
            over = next((v for k, v in pr.items() if "over" in k.lower()), None)
            if over is not None:
                snap.ou1t[line] = over
        elif mtype == "BOTH_TEAMS_TO_SCORE":
            pr = norm_probs(rs)
            snap.btts = next((v for k, v in pr.items() if _is_yes(k)), None)
        elif mtype == "TO_SCORE" or (("marcator" in lname or "to score" in lname) and not yesno and "primo" not in lname
                                     and "first" not in lname and len(rs) > 3):
            for r in rs:  # mercato a piu' vincitori: ogni runner e' gia' una probabilita'
                if r["p"]:
                    snap.segna[r["name"]] = min(r["p"], 0.95)
        elif mtype == "FIRST_GOAL_SCORER" or "primo marcatore" in lname or "first goalscorer" in lname:
            snap.primo.update(norm_probs(rs))
        elif re.search(r"corner|angol", lname) and len(rs) == 2 and _line_from(name):
            pr = norm_probs(rs)
            over = next((v for k, v in pr.items() if "over" in k.lower()), None)
            if over is not None:
                snap.corner[_line_from(name)] = over
        elif re.search(r"cartellin|card|booking|ammonizion", lname) and len(rs) == 2 and _line_from(name) and not yesno:
            pr = norm_probs(rs)
            over = next((v for k, v in pr.items() if "over" in k.lower()), None)
            if over is not None:
                snap.cartellini[_line_from(name)] = over
        elif re.search(r"assist", lname):
            _player_market(snap.assist, name, rs, yesno)
        elif re.search(r"cartellin|card|ammonit|booked", lname):
            _player_market(snap.cartellino, name, rs, yesno)
        elif yesno and re.search(r"segna|score|marcator", lname):
            _player_market(snap.segna, name, rs, yesno)
    return snap


def _player_market(dest, market_name, rs, yesno):
    if yesno:  # un mercato per giocatore, runner Si/No: il nome e' nel mercato
        tot = sum(r["p"] for r in rs if r["p"])
        yes = next((r for r in rs if _is_yes(r["name"])), None)
        if yes and yes["p"] and tot:
            dest[re.sub(r"(?i)\b(to be|shown a|card|cartellino|ammonito|assist|anytime|segna|to score)\b", " ",
                        market_name).strip(" -:")] = yes["p"] / tot
    else:
        for r in rs:
            if r["p"]:
                dest[r["name"]] = min(r["p"], 0.95)


def match_player(nome, candidati):
    """Trova il giocatore tra i runner dell'exchange: cognome obbligatorio,
    nome/iniziale per distinguere gli omonimi (es. Pio vs Sebastiano Esposito)."""
    toks = [t for t in norm(nome.replace(".", ". ")).split() if t]
    if not toks or not candidati:
        return None
    best, best_s = None, 0
    for cand in candidati:
        ct = norm(cand).split()
        s = 0
        long_hit = False
        for t in toks:
            if len(t) >= 3 and t in ct:
                s += 3
                long_hit = True
            elif len(t) >= 3 and any(difflib.SequenceMatcher(None, t, c).ratio() > 0.85 for c in ct):
                s += 2
                long_hit = True
            elif len(t) <= 2 and any(c.startswith(t) for c in ct):
                s += 1
        if long_hit and s > best_s:
            best, best_s = cand, s
        elif long_hit and s == best_s:
            best = None  # ambiguo
    return best


# ---------------------------------------------------------------------------
# Calcolo completo di una maggiorata speciale
# ---------------------------------------------------------------------------

class Calcolatore:
    def __init__(self, client, aliases=None, sportsbook=None, giorno=None):
        self.client = client
        self.aliases = aliases or {}
        self.sportsbook = sportsbook   # LettoreSportsbook (opzionale): marcatori e corner
        self.giorno = giorno           # data della maggiorata in esame (date) per cercare l'evento giusto
        self._snap = {}
        self._model = {}
        self._sb = {}
        self.eventi_noti = []          # [(casa, ospite, date|None)] dalle altre maggiorate del run

    def snapshot(self, ev):
        if ev["id"] not in self._snap:
            self._snap[ev["id"]] = load_snapshot(self.client, ev)
        return self._snap[ev["id"]]

    def model(self, ev):
        if ev["id"] not in self._model:
            self._model[ev["id"]] = MatchModel.fit(self.snapshot(ev).targets())
        return self._model[ev["id"]]

    def sb(self, ev):
        """Dati del Betfair Sportsbook della partita (None se non disponibili)."""
        if self.sportsbook is None:
            return None
        if ev["id"] not in self._sb:
            try:
                self._sb[ev["id"]] = self.sportsbook.dati(ev["id"])
            except Exception as e:  # Playwright assente, pagina non leggibile...
                self._sb[ev["id"]] = None
                self._sb_err = str(e)[:120]
        return self._sb[ev["id"]]

    def evento(self, casa=None, ospite=None, squadra=None):
        ev = self.client.find_event(casa, ospite, squadra, self.aliases, giorno=self.giorno)
        if not ev:
            who = squadra or f"{casa} - {ospite}"
            quando = f" il {self.giorno:%d/%m}" if self.giorno else ""
            raise DatoMancante(f"partita non trovata sull'exchange{quando}: {who}")
        controlla_inizio(ev)
        return ev

    def evento_del_giocatore(self, nome):
        """Partita del giocatore cercando nei mercati marcatore dei prossimi giorni."""
        now = datetime.now(timezone.utc)
        da, a = now - timedelta(hours=3), now + timedelta(days=4)
        if self.giorno:
            da, a = finestra_giorno(self.giorno)
        cat = self.client.call("listMarketCatalogue", {
            "filter": {"eventTypeIds": ["1"], "marketTypeCodes": ["TO_SCORE"],
                       "marketStartTime": {"from": da.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                           "to": a.strftime("%Y-%m-%dT%H:%M:%SZ")}},
            "marketProjection": ["RUNNER_DESCRIPTION", "EVENT"], "maxResults": 200, "locale": "it"})
        for m in cat or []:
            if match_player(nome, [r["runnerName"] for r in m.get("runners", [])]):
                ev = m["event"]
                parts = re.split(r"\s+v\s+|\s+-\s+|\s+vs\s+", ev["name"], maxsplit=1)
                if len(parts) == 2:
                    ev = {"id": ev["id"], "name": ev["name"], "home": parts[0], "away": parts[1],
                          "openDate": ev.get("openDate")}
                    controlla_inizio(ev)
                    return ev
        # partite delle altre maggiorate dello stesso giorno: il giocatore e' tra i marcatori quotati?
        for casa, ospite, g in self.eventi_noti:
            if self.giorno and g and g != self.giorno:
                continue
            try:
                ev = self.client.find_event(casa, ospite, None, self.aliases, giorno=self.giorno or g)
            except Exception:
                continue
            if not ev:
                continue
            nomi = list(self.snapshot(ev).segna)
            sb = self.sb(ev)
            if sb:
                nomi += list(sb.get("marcatori") or {})
            if match_player(nome, nomi):
                controlla_inizio(ev)
                return ev
        raise DatoMancante(f"partita di {nome} non individuata (manca la partita nel testo e il giocatore "
                           f"non e' tra i marcatori quotati delle partite del giorno)")

    # -- marcatori: exchange, altrimenti Betfair Sportsbook (primo marcatore) --
    def _segna(self, nome, snap, model, ev, chi):
        """-> (p segna, quota dei gol della squadra, squadra, nota)."""
        k = match_player(nome, list(snap.segna))
        if k:
            p = snap.segna[k]
            if chi is None:
                raise DatoMancante(f"squadra di {nome} non determinata")
            lam_t = model.lh if chi == "casa" else model.la
            q = min(-math.log(1 - p) / lam_t, 0.9)
            return p, q, chi, f"{k} segna {p:.3f} (exchange)"
        sb = self.sb(ev)
        if sb and sb.get("marcatori"):
            k = match_player(nome, list(sb["marcatori"]))
            if k:
                info = sb["marcatori"][k]
                chi = chi or info.get("chi")
                if chi is None or "quota_squadra" not in info:
                    raise DatoMancante(f"squadra di {nome} non determinata")
                lam_t = model.lh if chi == "casa" else model.la
                q = min(info["quota_squadra"], 0.9)
                p = 1 - math.exp(-q * lam_t)
                return p, q, chi, (f"{k} segna {p:.3f} (da primo marcatore Sportsbook @{info['quota']:g}: "
                                   f"{q * 100:.0f}% dei gol della squadra)")
            raise DatoMancante(f"{nome} non e' tra i marcatori quotati (exchange e Sportsbook)")
        motivo = getattr(self, "_sb_err", None)
        raise DatoMancante(f"mercato marcatore di {nome} non quotato sull'exchange"
                           + (f"; Sportsbook non letto ({motivo})" if motivo else ""))

    def _giocatori(self, conds, snap, model, ev):
        info, note = {}, []
        for c in conds:
            if c["t"] != "giocatore":
                continue
            nome = c["nome"]
            chi = c.get("chi")
            if chi is None and c.get("squadra_testo"):
                chi = _side(c["squadra_testo"], ev)
            g = {"chi": chi}
            if c["cosa"] == "ammonito" or c["cosa"] == "segna_assist_o_ammonito":
                k = match_player(nome, list(snap.cartellino))
                if not k:
                    raise DatoMancante(f"mercato cartellino di {nome} non quotato (exchange)")
                g["p_cartellino"] = snap.cartellino[k]
                note.append(f"cartellino {k} {g['p_cartellino']:.3f}")
            if c["cosa"] != "ammonito":
                p, q, chi, n = self._segna(nome, snap, model, ev, chi)
                g["chi"], g["quota_gol"] = chi, q
                note.append(n)
                if c["cosa"] in ("segna_o_assist", "segna_assist_o_ammonito"):
                    ka = match_player(nome, list(snap.assist))
                    if not ka:
                        raise DatoMancante(f"mercato assist di {nome} non quotato (exchange)")
                    lam_t = model.lh if chi == "casa" else model.la
                    g["quota_assist"] = min(-math.log(1 - snap.assist[ka]) / lam_t, 0.9)
                    note.append(f"{ka} assist {snap.assist[ka]:.3f}")
            info[nome] = g
            c["chi"] = g["chi"]
        return info, note

    def _marginale(self, c, snap, ev):
        def pick(pool, what):
            k = match_player(c["nome"], list(pool))
            if not k:
                raise DatoMancante(f"mercato {what} di {c['nome']} non quotato (exchange)")
            return k, pool[k]
        cosa = c["cosa"]
        if cosa == "ammonito":
            k, pc = pick(snap.cartellino, "cartellino")
            return pc, f"{k} cartellino {pc:.3f}"
        chi = c.get("chi")
        if chi is None and c.get("squadra_testo"):
            chi = _side(c["squadra_testo"], ev)
        if match_player(c["nome"], list(snap.segna)):
            k, pg = pick(snap.segna, "marcatore")
            nota_g = f"{k} segna {pg:.3f}"
        else:  # dal Sportsbook: serve il modello della partita per i gol attesi
            pg, _, _, nota_g = self._segna(c["nome"], snap, self.model(ev), ev, chi)
        lg = -math.log(1 - pg)
        if cosa == "segna":
            return pg, nota_g
        if cosa == "doppietta":
            return 1 - math.exp(-lg) * (1 + lg), nota_g + " -> doppietta"
        ka, pa = pick(snap.assist, "assist")
        la_ = -math.log(1 - pa)
        p = 1 - math.exp(-(lg + la_))
        nota = f"{nota_g}, assist {pa:.3f}"
        if cosa == "segna_assist_o_ammonito":
            kc, pc = pick(snap.cartellino, "cartellino")
            p = 1 - math.exp(-(lg + la_)) * (1 - pc)
            nota += f", cartellino {pc:.3f}"
        return p, nota

    def prob_gamba(self, gamba):
        """Probabilita' di una gamba (una partita) + nota del calcolo."""
        conds = [dict(c) for c in gamba["conds"]]
        if "squadra" in gamba:  # "vincono tutte" / "segnano tutte": squadra senza avversaria nota
            ev = self.evento(squadra=gamba["squadra"])
            chi = _side(gamba["squadra"], ev)
            new = []
            for c in conds:
                if c["t"] == "esito_squadra":
                    new.append({"t": "esito", "sel": ["1" if chi == "casa" else "2"]} if c["val"] == "vince"
                               else {"t": "gol", "chi": chi, "min": 1})
                else:
                    new.append(c)
            conds = new
        elif "giocatore" in gamba:
            if gamba.get("casa") and gamba.get("ospite"):
                ev = self.evento(gamba["casa"], gamba["ospite"])
            elif gamba.get("squadra_g"):  # "Kane Harry (inghilterra)": partita della sua nazionale/squadra
                ev = self.evento(squadra=gamba["squadra_g"])
                for c in conds:
                    if c["t"] == "giocatore" and not c.get("chi"):
                        c["chi"] = _side(gamba["squadra_g"], ev)
            else:
                ev = self.evento_del_giocatore(gamba["giocatore"])
        else:
            ev = self.evento(gamba["casa"], gamba["ospite"])
        snap = self.snapshot(ev)
        if all(c["t"] == "giocatore" for c in conds) and all(c["cosa"] != "primo" for c in conds):
            # solo condizioni giocatore: nel modello di Poisson i gol di giocatori diversi
            # sono indipendenti (anche della stessa squadra), basta moltiplicare
            p, note = 1.0, []
            for c in conds:
                pc, n = self._marginale(c, snap, ev)
                p *= pc
                note.append(n)
            return p, f"{ev['name']}: " + ", ".join(note)
        model = self.model(ev)
        for c in conds:
            if c["t"] in ("corner", "cartellini"):
                tab = dict(snap.corner if c["t"] == "corner" else snap.cartellini)
                fonte = "exchange"
                if c["linea"] not in tab and c["t"] == "corner":
                    sb = self.sb(ev)
                    if sb and c["linea"] in (sb.get("corner") or {}):
                        tab, fonte = sb["corner"], "Sportsbook"
                if c["linea"] not in tab:
                    raise DatoMancante(f"{c['t']} over/under {c['linea']} non quotato per {ev['name']}"
                                       + (" (exchange e Sportsbook)" if c["t"] == "corner" else " (exchange)"))
                c["p"] = tab[c["linea"]] if c["over"] else 1 - tab[c["linea"]]
                c["fonte"] = fonte
        gioc, note = self._giocatori(conds, snap, model, ev)
        note += [f"{c['t']} {'over' if c['over'] else 'under'} {c['linea']} {c['p']:.3f} ({c['fonte']})"
                 for c in conds if c["t"] in ("corner", "cartellini")]
        p = prob_leg(model, conds, gioc)
        nota = f"{ev['name']}: {model}" + (" · " + "; ".join(note) if note else "")
        if model.fit_error and model.fit_error > 0.03:
            nota += f" · ATTENZIONE calibrazione imprecisa (errore {model.fit_error:.3f})"
        return p, nota

    def fair(self, item):
        gambe = parse_speciale(item)
        p, note = 1.0, []
        for g in gambe:
            pg, n = self.prob_gamba(g)
            p *= pg
            note.append(n)
        if not p or p <= 0:
            raise DatoMancante("probabilita' nulla")
        fonti = "exchange + Sportsbook" if "Sportsbook" in " ".join(note) else "exchange"
        return {"prob": p, "fair": round(1 / p, 3), "prob_lay": None,
                "dettaglio": f"modello Poisson/Dixon-Coles ({fonti}) | " + " | ".join(note), "avvisi": []}


class PartitaIniziata(DatoMancante):
    """La partita e' gia' iniziata: le quote exchange sono live, la fair pre-match non e' calcolabile."""


def controlla_inizio(ev, margine_min=2):
    od = ev.get("openDate")
    if not od:
        return
    try:
        t = datetime.fromisoformat(od.replace("Z", "+00:00"))
    except ValueError:
        return
    if t <= datetime.now(timezone.utc) - timedelta(minutes=margine_min):
        raise PartitaIniziata(f"{ev['name']} e' gia' iniziata ({t.astimezone():%H:%M})")


def finestra_giorno(giorno):
    """Inizio e fine (UTC) della giornata locale 'giorno'."""
    inizio = datetime(giorno.year, giorno.month, giorno.day).astimezone()
    return inizio.astimezone(timezone.utc), (inizio + timedelta(days=1, hours=3)).astimezone(timezone.utc)


def _side(team, ev):
    a = difflib.SequenceMatcher(None, norm(team), norm(ev["home"])).ratio()
    b = difflib.SequenceMatcher(None, norm(team), norm(ev["away"])).ratio()
    if norm(team) and norm(team) in norm(ev["home"]):
        a = 1
    if norm(team) and norm(team) in norm(ev["away"]):
        b = 1
    return "casa" if a >= b else "ospite"


def stima_da_barrata(item, margine_pct):
    """Ultima risorsa: fair = quota barrata ripulita da un margine medio del book,
    che cresce con il numero di eventi della combo."""
    bar = item.get("quota_barrata")
    if not bar:
        return None
    k = max(1, len(re.findall(r"\+|&|,|\be\b|/", item.get("descrizione", ""))) + 1)
    k = min(k, 4)
    m = 1 - (1 - margine_pct / 100) ** k
    fair = bar / (1 - m)
    return {"prob": 1 / fair, "fair": round(fair, 3), "prob_lay": None,
            "dettaglio": f"STIMA: quota barrata {bar} senza margine ~{m * 100:.0f}% ({k} eventi)", "avvisi": []}
