import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper_maggiorate import parse_card
import ev_maggiorate as E

def item(book, txt, struck=(), why="barrata"):
    return parse_card({"name": book}, {"text": txt.replace(" | ", "\n"), "struck": list(struck), "why": why})

S = {
 "bwin_dc": item("Bwin", "Quota maggiorata | Doppia Chance: l'Italia vince o pareggia | Francia - Italia | Prima | 2.55 | 2.80", ["2.55"]),
 "wh_1gg": item("William Hill", "Quota Maggiorata | Bosnia-erzegovina - Svezia  - 02/10/26 | 1X2 + GG/NG | 1 + GG | 4.50 | 5.00", ["4.50"]),
 "wh_htft": item("William Hill", "Quota Maggiorata | Belgio - Turchia - 02/10/26 | Parziale/Finale | 1-1 | 2.18 | 2.40", ["2.18"]),
 "wh_re": item("William Hill", "Quota Maggiorata | Francia - Italia  - 02/10/26 | Risultato Esatto Multiplo | 1-0 2-0 3-0 | 3.15 | 3.50", ["3.15"]),
 "wh_scorer": item("William Hill", "Quota Maggiorata | Francia - Italia  - 02/10/26 | Segna o Assist | Esposito Francesco Pio (Italia):SI | 3.79 | 4.20", ["3.79"]),
 "wh_ou_gg": item("William Hill", "Quota Maggiorata | Svizzera - Slovenia  - 03/10/26 | U/O 3.5 + GG/NG | Over 3.5 + GG | 5.74 | 6.50", ["5.74"]),
 "vinc_1t": item("Vincitu", "MAGGIORATA - MAX BET: 10€ | BELGIO - TURCHIA - 02/10/26 | OVER 1,5 PRIMO TEMPO | Nel corso del primo tempo vengono segnati almeno 2 gol. (Solo in singola) | 2.11 | 2.30", ["2.11"]),
 "fast_vt": item("Fastbet", "02/10 • 16:00 | Kazakistan  - Cipro - Montenegro (Vincono Tutte 2/10) | Si | 8.00 | No", [], "lista"),
 "mara_over": item("Marathonbet", "5754 | Oggi | - | 16:00 | Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10 / Lettonia / Montenegro 02/10 | TUTTE OVER | 2.5 | SI | 18.95 | NO", [], "lista"),
 "mara_vt": item("Marathonbet", "4966 | Oggi | - | 16:00 | Kazakistan 02/10 / Cipro 02/10 / Montenegro 02/10 | VINCERANNO TUTTI | SI | 7.65 | NO", [], "lista"),
 "sun_combo": item("Sunbet", "Francia - Italia - 02/10/26 | Over 2,5 goal - Over 8,5 corner - Over 3,5 cartellini | Max Bet 20€ - Max 1 ticket | 4.38 | 5.10", ["4.38"]),
}
EXP = {"bwin_dc": ("MATCH_ODDS", ["X", "2"]), "wh_1gg": ("MATCH_ODDS_AND_BTTS", ["1/yes"]),
       "wh_htft": ("HALF_TIME_FULL_TIME", ["1/1"]), "wh_re": ("CORRECT_SCORE", ["1 - 0", "2 - 0", "3 - 0"]),
       "wh_scorer": 2, "wh_ou_gg": 2, "vinc_1t": ("FIRST_HALF_GOALS_15", ["over"]),
       "fast_vt": ("MATCH_ODDS", ["team"], 3), "mara_over": ("OVER_UNDER_25", ["over"], 3),
       "mara_vt": ("MATCH_ODDS", ["team"], 3), "sun_combo": 2}
ok = True
for k, it in S.items():
    spec = E.parse_market(it)
    exp = EXP[k]
    if isinstance(exp, int):
        good = spec["livello"] == exp
    else:
        legs = spec.get("legs") or []
        good = spec["livello"] == 1 and legs and legs[0]["market"] == exp[0] and legs[0]["sel"] == exp[1] \
            and (len(exp) < 3 or len(legs) == exp[2])
    ok &= bool(good)
    print("OK " if good else "XX ", k, spec)

# --- Betfair simulato ---
class Fake(E.BetfairClient):
    def __init__(self): super().__init__("k", token="t")
    def call(self, method, params, _retry=True):
        if method == "listEvents":
            q = params["filter"]["textQuery"].lower()
            evs = {"francia": ("1", "Francia v Italia"), "italia": ("1", "Francia v Italia"),
                   "kazakistan": ("2", "Kazakistan v Moldova"), "cipro": ("3", "Cipro v Armenia"),
                   "montenegro": ("4", "Lettonia v Montenegro")}
            return [{"event": {"id": evs[q][0], "name": evs[q][1]}}] if q in evs else []
        if method == "listMarketCatalogue":
            eid = params["filter"]["eventIds"][0]
            return [{"marketId": f"m{eid}", "runners": [
                {"selectionId": 1, "runnerName": "Casa", "sortPriority": 1},
                {"selectionId": 2, "runnerName": "Ospite", "sortPriority": 2},
                {"selectionId": 3, "runnerName": "Pareggio", "sortPriority": 3}]}]
        if method == "listMarketBook":
            mid = params["marketIds"][0]
            prices = {"m1": [(1.48, 1.49), (6.6, 6.8), (4.7, 4.8)], "m2": [(1.86, 1.88), (4.5, 4.6), (3.3, 3.35)],
                      "m3": [(2.18, 2.2), (3.4, 3.45), (3.3, 3.35)], "m4": [(4.8, 4.9), (1.75, 1.77), (3.6, 3.65)]}[mid]
            return [{"runners": [{"selectionId": i + 1, "status": "ACTIVE", "ex": {
                "availableToBack": [{"price": b}], "availableToLay": [{"price": l}]}} for i, (b, l) in enumerate(prices)]}]

rows = E.evaluate([S["bwin_dc"], S["fast_vt"], S["wh_scorer"]], {S["wh_scorer"]["id"]: {"back": 3.9, "lay": 4.0}}, Fake(), {}, 0.0, log=lambda *a: None)
for r in rows:
    print(r["book"], r["descrizione"][:40], "fair", r["fair"], "EV", r["ev_pct"], "cons", r["ev_cons_pct"], r["stato"], r.get("errore_fair", ""), "|", r["dettaglio_fair"][:120])
dc = rows[0]
# controllo manuale: p(X)+p(2) normalizzati
raw = [0.5*(1/1.48+1/1.49), 0.5*(1/6.6+1/6.8), 0.5*(1/4.7+1/4.8)]
p = (raw[1]+raw[2])/sum(raw)
assert abs(dc["prob_fair"] - round(p, 4)) < 1e-4, (dc["prob_fair"], p)
assert abs(dc["ev_pct"] - round((2.80*p-1)*100, 2)) < 0.01
vt = rows[1]
pk = 0.5*(1/1.86+1/1.88)/sum(0.5*(1/b+1/l) for b,l in [(1.86,1.88),(4.5,4.6),(3.3,3.35)])
pc = 0.5*(1/2.18+1/2.2)/sum(0.5*(1/b+1/l) for b,l in [(2.18,2.2),(3.4,3.45),(3.3,3.35)])
pm = 0.5*(1/1.75+1/1.77)/sum(0.5*(1/b+1/l) for b,l in [(4.8,4.9),(1.75,1.77),(3.6,3.65)])
assert abs(vt["prob_fair"] - round(pk*pc*pm, 4)) < 1e-4, (vt["prob_fair"], pk*pc*pm)
print("matematica EV verificata")
print()
print(E.telegram_post(rows[1]))
sys.exit(0 if ok else 1)
