import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper_maggiorate import parse_card

def card(book, txt, struck=(), why="barrata", **cfg):
    b = {"name": book, **cfg}
    return parse_card(b, {"text": txt.replace(" | ", "\n"), "struck": list(struck), "why": why})

CASES = [
 ("Sunbet", "Francia - Italia - 02/10/26 | Over 2,5 goal - Over 8,5 corner - Over 3,5 cartellini | Max Bet 20€ - Max 1 ticket | 4.38 | 5.10", ["4.38"], "barrata", dict(max_bet=20), ("Francia - Italia", 4.38, 5.10, 20)),
 ("Stake", "Nations League | 02/10 • 20:45 | Francia | vs | Italia | Gol range | 2-3 | 2.09 | 2.33", ["2.09"], "barrata", {}, ("Francia - Italia", 2.09, 2.33, None)),
 ("Betsson", "SUPER QUOTA | Francia | Italia | MARCATORE + DC | 02/10/26 | P.ESPOSITO+X2 | 8.00 | PRIMA | 7.10", [], "keyword", {}, ("Francia - Italia", 7.10, 8.00, None)),
 ("Bwin", "Quota maggiorata | Doppia Chance: l'Italia vince o pareggia | Francia - Italia | Prima | 2.55 | 2.80", ["2.55"], "barrata", {}, ("Francia - Italia", 2.55, 2.80, None)),
 ("Admiralbet", "Belgio - Turchia - 02/10/26 | OVER 0.5 1T + OVER 1.5 2T | Vengono segnati almeno un goal nel 1° tempo e almeno 2 goal nel 2° tempo | 2.01 | 2.20", ["2.01"], "barrata", {}, ("Belgio - Turchia", 2.01, 2.20, None)),
 ("DAZN Bet", "Speciali Calcio  - 02/10/26 | Tutti Segnano | Dembele O. & Esposito Pio Tutti A Segno (2/10) | 7.60 | 9.50", ["7.60"], "barrata", {}, ("", 7.60, 9.50, None)),
 ("Snai", "INT Speciali Calcio | + | 3 | FRA-ITA | 02/10 20:45 | Francia - Italia: goal o assist con quota maggiorata! | Giocata | 294 | volte | Olise e Sebastiano Esposito segnano o fanno assist | 4.88 | 7.50", ["4.88"], "barrata", {}, (None, 4.88, 7.50, None)),
 ("William Hill", "Quota Maggiorata | Bosnia-erzegovina - Svezia  - 02/10/26 | 1X2 + GG/NG | 1 + GG | 4.50 | 5.00", ["4.50"], "barrata", {}, ("Bosnia-erzegovina - Svezia", 4.50, 5.00, None)),
 ("Vincitu", "MAGGIORATA - MAX BET: 10€ | BELGIO - TURCHIA - 02/10/26 | OVER 1,5 PRIMO TEMPO | Nel corso del primo tempo vengono segnati almeno 2 gol. (Solo in singola) | 2.11 | 2.30", ["2.11"], "barrata", dict(max_bet=10), ("BELGIO - TURCHIA", 2.11, 2.30, 10)),
 ("Fastbet", "02/10 • 16:00 | Kazakistan  - Cipro - Montenegro (Vincono Tutte 2/10) | Si | 8.00 | No | + | 2", [], "lista", {}, (None, None, 8.00, None)),
 ("Marathonbet", "5754 | Oggi | - | 16:00 | Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10 / Lettonia / Montenegro 02/10 / Bosnia-erzegovina / Svezia 02/10 | TUTTE OVER | 2.5 | SI | 18.95 | NO", [], "lista", {}, (None, None, 18.95, None)),
 ("Betfair Sportsbook", "SuperCombo | 2 Ott: Francia e Belgio Vincenti e Over 2,5 gol in entrambi i match | 4.00", [], "lista", dict(max_bet=25), (None, None, 4.00, 25)),
]
ok = True
for book, txt, struck, why, cfg, exp in CASES:
    r = card(book, txt, struck, why, **cfg)
    ev, bar, mag, mb = exp
    got = (r["evento"], r["quota_barrata"], r["quota_maggiorata"], r["max_bet"]) if r else None
    good = r is not None and (ev is None or r["evento"] == ev) and r["quota_barrata"] == bar and r["quota_maggiorata"] == mag and r["max_bet"] == mb
    ok &= good
    print("OK " if good else "XX ", book, got, "|", r and r["descrizione"], "|", r and r["condizioni"])
assert card("Betsson", "MULTIPLA MAGGIORATA | Ungheria 02/10 | Svezia 02/10 | TUTTE VINCONO | 5.00 | PRIMA | 4.20", [], "keyword") is None
print("multipla scartata OK")
sys.exit(0 if ok else 1)
