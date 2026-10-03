"""Calcolo end-to-end della fair dei mercati speciali contro un exchange simulato,
generato da un modello 'vero': il calcolatore deve ritrovare le stesse probabilita'."""
import json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fair_speciali as F
import ev_maggiorate as E
from scraper_maggiorate import parse_card

# --- mondo "vero" ---
MATCHES = {
  "1": ("Francia", "Italia", 1.55, 0.95, {"Ousmane Dembele": ("casa", .22, .12, .10), "Michael Olise": ("casa", .15, .16, .08),
         "Francesco Pio Esposito": ("ospite", .25, .06, .07), "Sebastiano Esposito": ("ospite", .10, .08, .06),
         "Sandro Tonali": ("ospite", .05, .07, .22), "Adrien Rabiot": ("casa", .07, .05, .20), "Alessandro Bastoni": ("ospite", .03, .05, .18),
         "Riccardo Calafiori": ("ospite", .03, .05, .17)}),
  "2": ("Kazakistan", "Moldova", 1.25, 0.80, {}),
  "3": ("Cipro", "Armenia", 1.30, 1.05, {}),
  "4": ("Lettonia", "Montenegro", 0.85, 1.45, {}),
  "5": ("Belgio", "Turchia", 1.75, 1.05, {"Kevin De Bruyne": ("casa", .14, .22, .08), "Arda Guler": ("ospite", .16, .14, .09)}),
}
CORNER_OVER85 = {"1": 0.52, "5": 0.55}
CARDS_OVER = {"1": {3.5: 0.58, 4.5: 0.40}, "5": {3.5: 0.62}}
TRUE = {k: F.MatchModel(v[2], v[3], -0.05, 0.45) for k, v in MATCHES.items()}

def price(p, spread=0.01):
    p = min(max(p, 0.002), 0.995)
    o = 1 / p
    return round(o * (1 - spread / 2), 2), round(o * (1 + spread / 2), 2)

def runner(i, name, p, prio=None):
    return {"selectionId": i, "runnerName": name, "sortPriority": prio or i}, p

class FakeBF(E.BetfairClient):
    def __init__(self):
        super().__init__("k", token="t")
        self.books = {}
        self.cats = {}
        for eid, (h, a, lh, la, players) in MATCHES.items():
            m = TRUE[eid]; s = m.summary()
            mk = []
            mk.append(("MATCH_ODDS", "Esito finale", [runner(1, h, s["1"], 1), runner(2, a, s["2"], 2), runner(3, "Pareggio", s["X"], 3)]))
            for line in (1.5, 2.5, 3.5):
                o = s[f"over{line}"]
                mk.append((f"OVER_UNDER_{int(line*10)}", f"Under/Over {line} gol", [runner(1, f"Under {line} Goal", 1 - o), runner(2, f"Over {line} Goal", o)]))
            lt = (lh + la) * 0.45
            for line in (0.5, 1.5):
                o = 1 - sum(math.exp(-lt) * lt ** k / math.factorial(k) for k in range(int(line) + 1))
                mk.append((f"FIRST_HALF_GOALS_{int(line*10)}", f"1° tempo Under/Over {line}", [runner(1, f"Under {line}", 1 - o), runner(2, f"Over {line}", o)]))
            mk.append(("BOTH_TEAMS_TO_SCORE", "Goal/No Goal", [runner(1, "Sì", s["btts"]), runner(2, "No", 1 - s["btts"])]))
            if players:
                lam = {"casa": lh, "ospite": la}
                mk.append(("TO_SCORE", "Marcatore", [runner(i + 1, n, 1 - math.exp(-lam[t] * sg)) for i, (n, (t, sg, sa, c)) in enumerate(players.items())]))
                mk.append(("PLAYER_ASSIST", "Assist giocatore", [runner(i + 1, n, 1 - math.exp(-lam[t] * sa)) for i, (n, (t, sg, sa, c)) in enumerate(players.items())]))
                mk.append(("PLAYER_CARDED", "Giocatore ammonito", [runner(i + 1, n, c) for i, (n, (t, sg, sa, c)) in enumerate(players.items())]))
            if eid in CORNER_OVER85:
                mk.append(("CORNER_OU", "Corner Over/Under 8.5", [runner(1, "Under 8.5", 1 - CORNER_OVER85[eid]), runner(2, "Over 8.5", CORNER_OVER85[eid])]))
            for line, p in CARDS_OVER.get(eid, {}).items():
                mk.append(("CARDS_OU", f"Cartellini Over/Under {line}", [runner(1, f"Under {line}", 1 - p), runner(2, f"Over {line}", p)]))
            cat = []
            for j, (mtype, name, rs) in enumerate(mk):
                mid = f"{eid}.{j}"
                cat.append({"marketId": mid, "marketName": name, "description": {"marketType": mtype},
                            "runners": [r for r, _ in rs], "event": {"id": eid, "name": f"{h} v {a}"}})
                self.books[mid] = [{"selectionId": r["selectionId"], "status": "ACTIVE",
                                    "ex": dict(zip(("availableToBack", "availableToLay"), ([{"price": price(p)[0]}], [{"price": price(p)[1]}])))}
                                   for r, p in rs]
            self.cats[eid] = cat

    def call(self, method, params, _retry=True):
        f = params.get("filter", {})
        if method == "listEvents":
            q = F.norm(f["textQuery"])
            return [{"event": {"id": eid, "name": f"{h} v {a}"}} for eid, (h, a, *_r) in MATCHES.items()
                    if q in F.norm(h) or q in F.norm(a)]
        if method == "listMarketCatalogue":
            if "eventIds" in f:
                cat = self.cats[f["eventIds"][0]]
                if f.get("marketTypeCodes"):
                    cat = [m for m in cat if m["description"]["marketType"] in f["marketTypeCodes"]]
                return cat
            return [m for c in self.cats.values() for m in c if m["description"]["marketType"] in f.get("marketTypeCodes", [])]
        if method == "listMarketBook":
            return [{"marketId": mid, "runners": self.books[mid]} for mid in params["marketIds"]]
        raise AssertionError(method)

PL = {n: {"chi": t, "quota_gol": sg, "quota_assist": sa, "p_cartellino": c} for _, (_, _, _, _, ps) in MATCHES.items() for n, (t, sg, sa, c) in ps.items()}

def truth(eid, conds):
    return F.prob_leg(TRUE[eid], conds, PL)

def item(book, txt, struck=None):
    return parse_card({"name": book}, {"text": txt.replace(" | ", "\n"), "struck": [struck] if struck else [], "why": "barrata"})

pd = lambda n: 1 - math.exp(-{"casa": 1.55, "ospite": .95}[PL[n]["chi"]] * PL[n]["quota_gol"])
CASES = [
 ("Vincitu over 1.5 1T", item("Vincitu", "MAGGIORATA - MAX BET: 10€ | BELGIO - TURCHIA - 02/10/26 | OVER 1,5 PRIMO TEMPO | spiegazione | 2.06 | 2.30", "2.06"),
  truth("5", [{"t": "gol", "chi": "tot", "tempo": "1t", "min": 2}])),
 ("Stake gol range 2-3", item("Stake", "Turbo | Nations League | 02/10 • 20:45 | Francia | vs | Italia | Gol range | 2-3 | 2.14 | 2.40", "2.14"),
  truth("1", [{"t": "gol", "chi": "tot", "min": 2, "max": 3}])),
 ("Vincitu Italia vince un tempo", item("Vincitu", "MAGGIORATA - MAX BET: 10€ | FRANCIA - ITALIA - 02/10/26 | ITALIA VINCE ALMENO UN TEMPO | L'Italia vince almeno uno tra il primo e il secondo tempo. (Solo in singola) | 2.92 | 3.50", "2.92"),
  truth("1", [{"t": "vince_un_tempo", "chi": "ospite"}])),
 ("Betsson Esposito + X2", item("Betsson", "QUOTA MAGGIORATA | Francia | Italia | MARCATORE + DC | 02/10/26 | P.ESPOSITO+X2 | 8.00 | PRIMA | 7.10"),
  truth("1", [{"t": "esito", "sel": ["X", "2"]}, {"t": "giocatore", "nome": "Francesco Pio Esposito", "chi": "ospite", "cosa": "segna"}])),
 ("Sisal Dembele e Pio Esposito", item("Sisal", "INT Speciali Calcio | FRA-ITA | 02/10 20:45 | Francia - Italia: bomber con quota maggiorata! | Dembele e Pio Esposito segnano entrambi | 8.04 | 12.00", "8.04"),
  pd("Ousmane Dembele") * pd("Francesco Pio Esposito")),
 ("Snai Olise e S.Esposito goal o assist", item("Snai", "INT Speciali Calcio | FRA-ITA | 02/10 20:45 | Francia - Italia: goal o assist con quota maggiorata! | Olise e Sebastiano Esposito segnano o fanno assist | 4.88 | 7.50", "4.88"),
  (1 - math.exp(-1.55 * (.15 + .16))) * (1 - math.exp(-.95 * (.10 + .08)))),
 ("Snai tre cartellini", item("Snai", "INT Speciali Calcio | FRA-ITA | 02/10 20:45 | Francia - Italia: cartellini con quota maggiorata! | Rabiot, Tonali e Bastoni tutti cartellino | 69.66 | 81.00", "69.66"),
  .20 * .22 * .18),
 ("Sunbet over goal+corner+cartellini", item("Sunbet", "Calcio - Nations League | Francia - Italia - 02/10/26 | Over 2,5 goal - Over 8,5 corner - Over 3,5 cartellini | Max Bet 20€ - Max 1 ticket | 4.38 | 5.10", "4.38"),
  truth("1", [{"t": "gol", "chi": "tot", "min": 3}]) * 0.52 * 0.58),
 ("Sunbet Calafiori gol/assist/ammonito", item("Sunbet", "Calcio - Nations League | Francia - Italia - 02/10/26 | Gol o Assist o Ammonito - Calafiori (Italia) | Max Bet 20€ - Max 1 ticket | 2.52 | 3.00", "2.52"),
  1 - math.exp(-.95 * .08) * (1 - .17)),
 ("Marathon tutte over", dict(item("Marathonbet", "5754 | 16:00 | Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10 / Lettonia / Montenegro 02/10 | 2.5 | 18.75"), gruppo="tutte over"),
  truth("2", [{"t": "gol", "chi": "tot", "min": 3}]) * truth("3", [{"t": "gol", "chi": "tot", "min": 3}]) * truth("4", [{"t": "gol", "chi": "tot", "min": 3}])),
 ("Fastbet vincono tutte", dict(item("Fastbet", "8111 | 02/10 • 16:00 | Kazakistan  - Cipro - Montenegro (Vincono Tutte 2/10) | Si | 8.00 | No"), gruppo="vincono tutte"),
  truth("2", [{"t": "esito", "sel": ["1"]}]) * truth("3", [{"t": "esito", "sel": ["1"]}]) * truth("4", [{"t": "esito", "sel": ["2"]}])),
 ("DAZN De Bruyne+Guler goal o assist", item("DAZN Bet", "Maggiorata DAZNBet Club | Speciali Calcio  - 02/10/26 | Tutti Goal O Assist | De Bruyne K.+Guler A. Tutti Alm. 1 Goal O 1 Assist (02/10) | 6.00 | 7.00", "6.00"),
  (1 - math.exp(-1.75 * .36)) * (1 - math.exp(-1.05 * .30))),
 ("Admiral multigol team1+team2", item("Admiralbet", "Francia - Italia - 02/10/26 | MULTIGOAL TEAM 1 + MULTIGOAL TEAM 2 | La Francia segna 2-3 goal e l'Italia segna 0-1 goal | 2.41 | 2.70", "2.41"),
  truth("1", [{"t": "gol", "chi": "casa", "min": 2, "max": 3}, {"t": "gol", "chi": "ospite", "min": 0, "max": 1}])),
 ("WH Esposito 1X2 marcatore (non quotato) -> stima", item("William Hill", "Quota Maggiorata | Spagna - Repubblica Ceca  - 03/10/26 | 1X2 + Marcatore | Oyarzabal Mikel (Spagna):1 + SEGNA | 1.66 | 1.80", "1.66"), None),
]
client = FakeBF()
calc = F.Calcolatore(client, {})
ok = True
for name, it, exp in CASES:
    try:
        r = calc.fair(it)
        p = r["prob"]
        good = exp is not None and abs(p - exp) / exp < 0.03
        print(("OK " if good else "XX "), f"{name:40} p={p:.4f} vero={exp if exp is None else round(exp,4)}  fair {r['fair']}")
    except (F.DatoMancante, F.NonRiconosciuto) as e:
        good = exp is None
        print(("OK " if good else "XX "), f"{name:40} -> {type(e).__name__}: {e}")
    ok &= good

# integrazione con ev_maggiorate.evaluate (incl. stima da barrata)
rows = E.evaluate([c[1] for c in CASES], {}, client, {}, 0.0, margini={"default": 10})
for r in rows:
    print(f"   {r['book'][:10]:10} {r['stato']:13} fair {r['fair']}  EV {r['ev_pct']}  [{r['fonte_fair']}]")
assert rows[-1]["stima"] and rows[-1]["stato"].endswith("(stima)")
sys.exit(0 if ok else 1)
