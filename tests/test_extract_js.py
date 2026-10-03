"""Verifica l'estrattore JS su HTML sintetici che imitano le strutture viste dal vivo."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scraper_maggiorate import EXTRACT_JS, parse_card

CAROUSEL = """
<html><body><h1>Sport</h1><div class="carousel">
 <div class="card"><div class="h">Francia - Italia - 02/10/26</div><div>Over 2,5 goal - Over 8,5 corner</div>
   <div>Max Bet 20€ - Max 1 ticket</div><div><span style="text-decoration:line-through">4.38</span></div><button>5.10</button></div>
 <div class="card"><div class="h">Belgio - Turchia - 02/10/26</div><div>Over 2,5 goal</div>
   <div>Max Bet 20€ - Max 1 ticket</div><div><s>3.75</s></div><button>4.30</button></div>
</div>
<table><tr><td>Kazakistan - Moldova</td><td>1.85</td><td>3.25</td><td>4.50</td></tr></table>
</body></html>"""

SHADOW = """
<html><body><div id="host"></div><script>
const r = document.getElementById('host').attachShadow({mode:'open'});
r.innerHTML = `<div class="row">
 <div class="BetCard"><div>Nations League</div><div>02/10 • 20:45</div><div>Francia</div><div>vs</div><div>Italia</div>
 <div>Gol range</div><div>2-3</div><div><span style="text-decoration: line-through">2.09</span><span>2.33</span></div></div>
 <div class="BetCard"><div>Brasileiro</div><div>Sao Paulo FC</div><div>vs</div><div>Santos</div>
 <div>Casa segna in entrambi i tempi</div><div><span style="text-decoration: line-through">3.20</span><span>3.60</span></div></div></div>`;
</script></body></html>"""

KEYWORD = """
<html><body><div class="sw">
<div class="slide"><div>SUPER QUOTA</div><div>Francia</div><div>Italia</div><div>MARCATORE + DC</div><div>P.ESPOSITO+X2</div><div>8.00</div><div>PRIMA</div><div>7.10</div></div>
<div class="slide"><div>QUOTA MAGGIORATA</div><div>Francia</div><div>Italia</div><div>MARCATORE +1X2</div><div>M.OLISE+1</div><div>3.30</div><div>PRIMA</div><div>2.90</div></div>
</div></body></html>"""

LIST = """
<html><body><div class="lista">
<div class="riga"><div>02/10 • 16:00</div><div>Kazakistan - Cipro - Montenegro (Vincono Tutte 2/10)</div><div>Si</div><div>8.00</div><div>No</div></div>
<div class="riga"><div>02/10 • 20:45</div><div>Italia - Belgio - Polonia (Vincono Tutte 2/10)</div><div>Si</div><div>18.00</div><div>No</div></div>
</div></body></html>"""

LIST_GROUPS = """
<html><body><div class="tab">
<div class="sez"><div class="hdr"><span>TUTTE OVER</span><span>SI</span><span>NO</span></div>
 <div class="r"><div>5754</div><div>16:00</div><div>Kazakistan / Moldova 02/10 / Cipro / Armenia 02/10</div><div>2.5</div><div>18.75</div></div>
 <div class="r"><div>7889</div><div>16:15</div><div>Almeria / Burgos Cf 03/10 / Top Oss / Mvv Maastricht 03/10</div><div>2.5</div><div>6.15</div></div></div>
<div class="sez"><div class="hdr"><span>VINCERANNO TUTTI</span><span>SI</span><span>NO</span></div>
 <div class="r"><div>4966</div><div>16:00</div><div>Kazakistan 02/10 / Cipro 02/10 / Montenegro 02/10</div><div>7.50</div></div>
 <div class="r"><div>5902</div><div>20:45</div><div>Svezia 02/10 / Ungheria 02/10 / Ucraina 02/10</div><div>20.40</div></div></div>
</div></body></html>"""


def run_raw(html, mode):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html)
        raws = pg.evaluate(EXTRACT_JS, {"mode": mode})
        b.close()
    return raws


def run(html, mode="cards", book="Test"):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html)
        raws = pg.evaluate(EXTRACT_JS, {"mode": mode})
        b.close()
    return [parse_card({"name": book}, r) for r in raws]

ok = True
for name, html, mode, exp in [("carosello+barrate", CAROUSEL, "cards", [(4.38, 5.10), (3.75, 4.30)]),
                              ("shadow DOM", SHADOW, "cards", [(2.09, 2.33), (3.20, 3.60)]),
                              ("etichetta + PRIMA", KEYWORD, "cards", [(7.10, 8.00), (2.90, 3.30)]),
                              ("lista", LIST, "list", [(None, 8.00), (None, 18.00)])]:
    items = [i for i in run(html, mode) if i]
    got = sorted([(i["quota_barrata"], i["quota_maggiorata"]) for i in items], key=lambda x: x[1])
    good = got == sorted(exp, key=lambda x: x[1])
    ok &= good
    print("OK " if good else "XX ", name, got, [i["evento"] for i in items])
from scraper_maggiorate import parse_raws
its = parse_raws({"name": "Marathonbet", "mode": "list"}, run_raw(LIST_GROUPS, "list"))
got = [(i["gruppo"], i["quota_maggiorata"]) for i in its]
good = got == [("tutte over", 18.75), ("tutte over", 6.15), ("vinceranno tutti", 7.5), ("vinceranno tutti", 20.4)]
ok &= good
print("OK " if good else "XX ", "gruppi lista", got)
sys.exit(0 if ok else 1)
