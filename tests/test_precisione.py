"""Test delle migliorie di precisione: marcatori/corner dal Betfair Sportsbook, calibrazione
con risultato esatto e 1X2 primo tempo, ricerca evento per data, partite iniziate,
filtro 'solo oggi', nuovi mercati (vince entrambi i tempi, risultato in ogni momento),
date e partite lette dalle card."""
import json, math, random, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fair_speciali as F
import ev_maggiorate as E
import sportsbook_betfair as S
from scraper_maggiorate import parse_card, data_card, di_oggi

ok = True
def check(nome, cond, info=""):
    global ok
    print(("OK " if cond else "XX "), nome, info)
    ok &= bool(cond)

OGGI = date.today()
DOMANI_ISO = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT18:00:00.000Z")

# ---------------------------------------------------------------- mondo "vero"
LH, LA = 1.05, 1.45
TRUE = F.MatchModel(LH, LA, -0.06, 0.44)
CRO = {"Ante Budimir": .26, "Andrej Kramaric": .20, "Luka Modric": .08, "Ivan Perisic": .13, "Mario Pasalic": .09,
       "Josko Gvardiol": .05, "Luka Sucic": .07, "Marco Pasalic": .10, "Altri Croazia": .02}
ENG = {"Harry Kane": .36, "Jude Bellingham": .14, "Bukayo Saka": .13, "Anthony Gordon": .11, "Morgan Rogers": .08,
       "Declan Rice": .12, "Marc Guehi": .03, "Altri Inghilterra": .03}
L_OG = 0.04

def price(p, spread=0.01):
    p = min(max(p, 0.002), 0.995)
    o = 1 / p
    return round(o * (1 - spread / 2), 2), round(o * (1 + spread / 2), 2)

class FakeBF(E.BetfairClient):
    def __init__(self, open_date=DOMANI_ISO):
        super().__init__("k", token="t")
        s = TRUE.summary()
        ft = TRUE.ft()
        lt1 = (LH + LA) * 0.44
        hh = [F.poi(k, LH * .44) for k in range(9)]
        aa = [F.poi(k, LA * .44) for k in range(9)]
        p1h = sum(hh[i] * aa[j] for i in range(9) for j in range(9) if i > j)
        pxh = sum(hh[i] * aa[i] for i in range(9))
        mk = [("MATCH_ODDS", [("Croazia", s["1"], 1), ("Inghilterra", s["2"], 2), ("Pareggio", s["X"], 3)])]
        for line in (1.5, 2.5, 3.5):
            o = s[f"over{line}"]
            mk.append((f"OVER_UNDER_{int(line * 10)}", [(f"Under {line} Goal", 1 - o, 1), (f"Over {line} Goal", o, 2)]))
        mk.append(("BOTH_TEAMS_TO_SCORE", [("Sì", s["btts"], 1), ("No", 1 - s["btts"], 2)]))
        cs = [(f"{h} - {a}", ft[(h, a)], i + 1) for i, (h, a) in enumerate([(h, a) for h in range(4) for a in range(4)])]
        mk.append(("CORRECT_SCORE", cs))
        mk.append(("HALF_TIME", [("Croazia", p1h, 1), ("Inghilterra", 1 - p1h - pxh, 2), ("Pareggio", pxh, 3)]))
        self.cat, self.books = [], {}
        for j, (mt, rs) in enumerate(mk):
            mid = f"m{j}"
            self.cat.append({"marketId": mid, "marketName": mt, "description": {"marketType": mt},
                             "runners": [{"selectionId": k, "runnerName": n, "sortPriority": pr} for k, (n, p, pr) in enumerate(rs)]})
            self.books[mid] = [{"selectionId": k, "status": "ACTIVE",
                                "ex": {"availableToBack": [{"price": price(p)[0]}], "availableToLay": [{"price": price(p)[1]}]}}
                               for k, (n, p, pr) in enumerate(rs)]
        self.events = [{"id": "36131309", "name": "Croazia v Inghilterra", "openDate": open_date}]

    def call(self, method, params, _retry=True):
        f = params.get("filter", {})
        if method == "listEvents":
            q = F.norm(f["textQuery"])
            return [{"event": e} for e in self.events if q in F.norm(e["name"])]
        if method == "listMarketCatalogue":
            if "eventIds" in f:
                return self.cat
            return []  # nessun mercato marcatore sull'exchange (come per le nazionali)
        if method == "listMarketBook":
            return [{"marketId": mid, "runners": self.books[mid]} for mid in params["marketIds"]]
        raise AssertionError(method)

# Sportsbook simulato: primo marcatore "vero" con margine (power), corner over/under
# i gol attesi delle squadre (LH, LA) comprendono gli autogol a favore (L_OG/2 ciascuna)
def fgs_runner_quote():
    lt = LH + LA
    rs = []
    for n, sh in CRO.items():
        if not n.startswith("Altri"):
            rs.append((n, (LH - L_OG / 2) * sh / lt * (1 - math.exp(-lt))))
    rs.append(("Nessun goal", math.exp(-lt)))
    rs.append(("Autogoal", L_OG / lt * (1 - math.exp(-lt))))
    for n, sh in ENG.items():
        if not n.startswith("Altri"):
            rs.append((n, (LA - L_OG / 2) * sh / lt * (1 - math.exp(-lt))))
    k = 0.8  # margine "power" del book
    return [(n, round(1 / p ** k, 2)) for n, p in rs]

CORNER_TRUE = {7.5: 0.66, 8.5: 0.52, 9.5: 0.39}
def sb_payload():
    rs = fgs_runner_quote()
    m = {"__typename": "SportsbookMarket", "urn": "fgs", "name": "Primo Marcatore", "marketType": "FIRST_GOAL_SCORER",
         "runners": [{"name": n, "selectionId": i} for i, (n, q) in enumerate(rs)],
         "liveData": {"runners": [{"selectionId": i, "odds": {"decimal": q}} for i, (n, q) in enumerate(rs)]}}
    corners = []
    for line, p in CORNER_TRUE.items():
        o, u = 1 / (p * 1.04), 1 / ((1 - p) * 1.04)
        corners.append({"__typename": "SportsbookMarket", "urn": f"c{line}", "name": f"Corner under/over {str(line).replace('.', ',')}",
                        "marketType": "TOTAL_CORNERS", "runners": [{"name": f"Over {line} corner", "selectionId": 1}, {"name": f"Under {line} corner", "selectionId": 2}],
                        "liveData": {"runners": [{"selectionId": 1, "odds": {"decimal": round(o, 2)}}, {"selectionId": 2, "odds": {"decimal": round(u, 2)}}]}})
    return [{"data": {"Cards": [{"displayRunners": {"sportsbook": {"market": m}}}]}}, {"data": {"x": corners}}]

class FakeSB:
    def __init__(self):
        self.letture = 0
    def dati(self, event_id):
        self.letture += 1
        return S.analizza(S.estrai_mercati(sb_payload()))

# ---------------------------------------------------------------- 1. calibrazione
snap = F.load_snapshot(FakeBF(), {"id": "36131309", "name": "Croazia v Inghilterra"})
mod = F.MatchModel.fit(snap.targets())
check("calibrazione gol attesi (con risultato esatto)", abs(mod.lh - LH) < .05 and abs(mod.la - LA) < .05, repr(mod))
check("rho dal risultato esatto", abs(mod.rho - (-0.06)) < .04, f"{mod.rho:+.3f}")
check("quota gol 1T dal 1X2 primo tempo", abs(mod.s1 - .44) < .02, f"{mod.s1:.3f}")

# ---------------------------------------------------------------- 2. marcatori dal Sportsbook
def item(book, txt, struck=None, cfg=None):
    return parse_card(dict({"name": book}, **(cfg or {})), {"text": txt.replace(" | ", "\n"), "struck": [struck] if struck else [], "why": "barrata"})

def p_vera_segna(team, share):
    lam = ((LH if team == "casa" else LA) - L_OG / 2) * share
    return 1 - math.exp(-lam)

sb = FakeSB()
calc = F.Calcolatore(FakeBF(), {}, sportsbook=sb)
casi = [
    ("Kane segna (Sportsbook)", item("Sisal", "INT Speciali Calcio | CRO-ENG | 03/10 18:00 | Croazia - Inghilterra: bomber! | Kane segna | 2.10 | 2.60", "2.10"),
     p_vera_segna("ospite", .36)),
    ("Kane e Budimir entrambi a segno", item("Snai", "INT Speciali Calcio | CRO-ENG | 03/10 18:00 | Croazia - Inghilterra: bomber! | Kane e Budimir entrambi a segno | 7.00 | 9.00", "7.00"),
     p_vera_segna("ospite", .36) * p_vera_segna("casa", .26)),
    ("Betsson H.KANE+2", item("Betsson", "QUOTA MAGGIORATA | Croazia | Inghilterra | MARCATORE + 1X2 | 03/10/26 | H.KANE+2 | 3.10 | Prima | 2.80"),
     F.prob_leg(TRUE, [{"t": "esito", "sel": ["2"]}, {"t": "giocatore", "nome": "K", "chi": "ospite", "cosa": "segna"}],
                {"K": {"chi": "ospite", "quota_gol": .36 * (LA - L_OG / 2) / LA}})),
    ("Sunbet over 2,5 + over 8,5 corner", item("Sunbet", "Calcio - Nations League | Croazia - Inghilterra - 03/10/26 | Over 2,5 goal - Over 8,5 corner | 3.10 | 3.60", "3.10"),
     TRUE.summary()["over2.5"] * CORNER_TRUE[8.5]),
]
# nel mondo "vero" una parte dei gol e' di giocatori non quotati dal Sportsbook (Altri, 2-3%):
# il calcolo li ridistribuisce sui quotati, stimati al 3%: tolleranza 4%
for nome, it, vero in casi:
    try:
        r = calc.fair(it)
        err = abs(r["prob"] - vero) / vero
        check(nome, err < 0.04, f"p={r['prob']:.4f} vero={vero:.4f} | {r['dettaglio'][-110:]}")
    except Exception as e:
        check(nome, False, f"{type(e).__name__}: {e}")
check("Sportsbook letto una volta sola per partita", sb.letture == 1, sb.letture)

# ---------------------------------------------------------------- 3. nuovi mercati
st = TRUE.states()
p_ent = F.prob_leg(TRUE, [{"t": "vince_entrambi_tempi", "chi": "ospite"}])
mc_ent = sum(w for h1, a1, h2, a2, w in st if a1 > h1 and a2 > h2)
check("vince entrambi i tempi", abs(p_ent - mc_ent) < 1e-9 and 0 < p_ent < TRUE.summary()["2"], f"{p_ent:.4f}")
g = F.parse_speciale(item("Admiralbet", "NATIONS LEAGUE | Croazia - Inghilterra - 03/10/26 | SQUADRA X VINCE ENTRAMBI I TEMPI | L'Inghilterra vince sia il 1° che il 2° tempo | 2.10 | 2.30", "2.10"))
check("parser 'squadra X vince entrambi i tempi'", g[0]["conds"] == [{"t": "vince_entrambi_tempi", "chi": "ospite"}], g)

random.seed(7)
def sim_passa(n=60000):
    hit = 0
    for _ in range(n):
        h = a = 0
        t, passa = 0.0, False
        while True:
            t += random.expovariate(LH + LA)
            if t > 1:
                break
            if random.random() < LH / (LH + LA):
                h += 1
            else:
                a += 1
            if (h, a) == (1, 1):
                passa = True
        hit += passa
    return hit / n
m0 = F.MatchModel(LH, LA, 0.0, 0.45)
p_pp = F.prob_leg(m0, [{"t": "passa_per", "h": 1, "a": 1}])
mc = sim_passa()
check("risultato 1-1 in qualsiasi momento (vs simulazione)", abs(p_pp - mc) < 0.006, f"{p_pp:.4f} sim {mc:.4f}")
g = F.parse_speciale(item("Snai", "INT Nations League | + | 2048 | Croazia | 03/10 | 18:00 | Inghilterra | Promo 1-1 risultato esatto in ogni momento! | Risultato esatto in ogni momento 1-1 | 1.75 | 7.00"))
check("parser 'risultato esatto in ogni momento' + partita da righe separate", g == [{"casa": "Croazia", "ospite": "Inghilterra", "conds": [{"t": "passa_per", "h": 1, "a": 1}]}], g)
g = F.parse_speciale(item("Snai", "INT Nations League | +2048 | Croazia | Inghilterra | 03/10 | 18 | : | 00 | Testo | ALMENO 3 GOAL NEL MATCH | INGHILTERRA SEGNA IL 1° GOAL | KANE MARCATORE ULTRA | Giocata | 282 | volte | My Combo | 7.03 | 7.81", "7.03"))
check("parser My Combo Snai", [c["t"] for c in g[0]["conds"]] == ["gol", "primo_gol_squadra", "giocatore"], g)
for testo, atteso in [("Combo Ace + Doppi Falli", "calcio"), ("RIGORE SI/NO", "rigore"), ("La Germania batte più calci d'angolo della Grecia", "1X2 corner")]:
    try:
        F._clausola(testo, "Grecia", "Germania")
        check(f"non riconosciuto: {testo}", False)
    except F.NonRiconosciuto as e:
        check(f"non riconosciuto: {testo}", atteso in str(e), str(e))

# ---------------------------------------------------------------- 4. ricerca evento per data
class BFDate(E.BetfairClient):
    def __init__(self):
        super().__init__("k", token="t")
        d = lambda gg: f"2026-10-{gg:02d}T18:45:00.000Z"
        self.ev = [("1", "Belgio v Turchia", d(2)), ("2", "Francia v Belgio", d(5)), ("3", "Irlanda del Nord v Islanda", d(2)),
                   ("4", "Irlanda v Israele", d(4))]
    def call(self, method, params, _retry=True):
        f = params["filter"]
        q = F.norm(f["textQuery"])
        w = f["marketStartTime"]
        return [{"event": {"id": i, "name": n, "openDate": o}} for i, n, o in self.ev
                if q in F.norm(n) and w["from"] <= o[:19] + "Z" <= w["to"]]
bf = BFDate()
check("Belgio del 02/10 = Belgio-Turchia", (bf.find_event(team="Belgio", giorno=date(2026, 10, 2)) or {}).get("id") == "1")
check("Belgio del 05/10 = Francia-Belgio", (bf.find_event(team="Belgio", giorno=date(2026, 10, 5)) or {}).get("id") == "2")
check("Irlanda non e' Irlanda del Nord", (bf.find_event(team="Irlanda", giorno=date(2026, 10, 2)) or {}).get("id") == "4")
check("Irlanda del Nord trovata", (bf.find_event(team="Irlanda del Nord", giorno=date(2026, 10, 2)) or {}).get("id") == "3")

# ---------------------------------------------------------------- 5. partita iniziata, solo oggi
oggi_s = f"{OGGI:%d/%m}"
it_oggi = item("Vincitu", f"MAGGIORATA - MAX BET: 10€ | CROAZIA - INGHILTERRA - {OGGI:%d/%m/%y} | OVER 2,5 | spiegazione | 1.80 | 2.00", "1.80")
it_dom = item("Vincitu", f"MAGGIORATA - MAX BET: 10€ | CROAZIA - INGHILTERRA - {OGGI + timedelta(days=1):%d/%m/%y} | OVER 2,5 | spiegazione | 1.80 | 2.00", "1.80")
check("data della card", it_oggi["data"] == oggi_s and di_oggi(it_oggi) and not di_oggi(it_dom), (it_oggi["data"], it_dom["data"]))
iniziata = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
rows = E.evaluate([it_oggi, it_dom], {}, FakeBF(open_date=iniziata), {}, 0.0, solo_oggi=True)
check("solo oggi: scartata la maggiorata di domani", len(rows) == 1, [r["data"] for r in rows])
check("partita gia' iniziata: niente fair ne' stima", rows and rows[0]["stato"] == "iniziata" and rows[0]["fair"] is None,
      rows and rows[0].get("errore_fair"))
rows = E.evaluate([it_oggi], {}, FakeBF(open_date=DOMANI_ISO.replace(DOMANI_ISO[:10], f"{OGGI:%Y-%m-%d}").replace("T18:00", "T23:30")), {}, 0.0, solo_oggi=True)
check("partita non iniziata: fair dall'exchange", rows[0]["fair"] and not rows[0]["stima"], rows[0]["stato"])

# ---------------------------------------------------------------- 6. date e partite dalle card
check("data '03/10/26' con '+1/1' nel testo", data_card("Svizzera\nSlovenia\n03/10/26\nJ.MANZAMBI+1/1", date(2026, 10, 2)) == "03/10")
check("data 'Oggi'", data_card("Oggi 20:45\nFrancia - Italia", date(2026, 10, 2)) == "02/10")
check("data '3 ott'", data_card("3 ott, 18:00", date(2026, 10, 2)) == "03/10")
check("'1/1' da solo non e' una data", data_card("MARCATORE + PARZ/FIN\nJ.MANZAMBI+1/1", date(2026, 10, 2)) == "")
check("partita da codici FRA-ITA", F.evento_da_righe(["INT Speciali Calcio", "FRA-ITA", "02/10 20:45"]) == "Francia - Italia")
check("partita da righe PokerStars", F.evento_da_righe(["Francia", "Italia", "02/10 20:45", "INT Nations League"]) == "Francia - Italia")
ps = item("PokerStars", "Francia | Italia | 02/10 20:45 | INT Nations League | Quota maggiorata | Zidane ammonito | 4.00 | 7.50",
          cfg={"barrata_senza_stile": True})
check("PokerStars: barrata senza stile + partita", ps["quota_barrata"] == 4.0 and ps["quota_maggiorata"] == 7.5 and ps["evento"] == "Francia - Italia",
      (ps["quota_barrata"], ps["evento"]))
check("My Combo vuota scartata", item("Snai", "My Combo | 17.17 | 19.08", "17.17") is None)

# completamento partita tra book gemelli
a = {"id": "a", "book": "Sisal", "evento": "Francia - Italia", "descrizione": "Dembele e Pio Esposito segnano entrambi"}
b = {"id": "b", "book": "PokerStars", "evento": "", "descrizione": "Dembele e Pio Esposito segnano entrambi"}
E._completa_eventi([a, b])
check("partita copiata dalla card gemella", b["evento"] == "Francia - Italia")

# giocatori senza partita nel testo (DAZN) o con la nazionale tra parentesi (Marathonbet)
dom = OGGI + timedelta(days=1)
dazn = item("DAZN Bet", f"Maggiorata DAZNBet Club | Speciali Calcio  - {dom:%d/%m/%y} | Tutti Segnano | Kane H. & Budimir A. Tutti A Segno | 7.00 | 9.00", "7.00")
altra = item("Vincitu", f"MAGGIORATA - MAX BET: 10€ | CROAZIA - INGHILTERRA - {dom:%d/%m/%y} | OVER 2,5 | spiegazione | 1.80 | 2.00", "1.80")
mara = dict(item("Marathonbet", f"5754 | 16:00 | Kane Harry (inghilterra) {dom:%d/%m} / Budimir Ante (croazia) {dom:%d/%m} | 9.15"), gruppo="segnano tutte")
rows = E.evaluate([dazn, altra, mara], {}, FakeBF(), {}, 0.0, sportsbook=FakeSB())
vero = p_vera_segna("ospite", .36) * p_vera_segna("casa", .26)
for r in (rows[0], rows[2]):
    check(f"{r['book']}: partita dei giocatori trovata", r["fonte_fair"].startswith("modello") and abs(r["prob_fair"] - vero) / vero < .05,
          f"{r['stato']} p={r['prob_fair']} vero={vero:.4f} {r.get('errore_fair') or ''}")

print("\nTUTTO OK" if ok else "\nCI SONO ERRORI")
sys.exit(0 if ok else 1)
