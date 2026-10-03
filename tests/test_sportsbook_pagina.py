"""Lettura del Betfair Sportsbook con Playwright contro una pagina simulata (route
intercettate): la pagina carica i mercati con fetch verso bff-gql, il Primo Marcatore
arriva solo dopo il clic sull'intestazione, i corner dalla scheda ?tab=corner."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sportsbook_betfair as S

FIX = json.loads((Path(__file__).parent / "fixture_sportsbook.json").read_text(encoding="utf-8"))
FGS, CORNER = FIX[0], FIX[1]

PAGINA = """<!doctype html><html><body><div id="m">Esito Finale 2.10 3.40 3.60</div>
<div id="pm" style="cursor:pointer">Primo Marcatore</div><script>
const tab = new URLSearchParams(location.search).get('tab');
const q = (k) => fetch('https://apitbd.betfair.it/api/tbd/bff-gql/v11/?k=' + k, {method: 'POST', body: '{}'}).then(r => r.json());
if (tab === 'corner') { q('corner').then(() => document.getElementById('m').innerText += ' Corner under/over 8,5 1.85'); }
else { q('base'); document.getElementById('pm').onclick = () => q('fgs'); }
</script></body></html>"""

lettore = S.LettoreSportsbook(cache_path=Path(tempfile.mkdtemp()) / "c.json")
lettore._avvia()
chiamate = []

def gql(route):
    k = route.request.url.split("k=")[-1]
    chiamate.append(k)
    body = {"fgs": FGS, "corner": CORNER}.get(k, {"data": {}})
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body),
                  headers={"Access-Control-Allow-Origin": "*"})

lettore._ctx.route("https://apitbd.betfair.it/**", gql)
lettore._ctx.route("https://www.betfair.it/**", lambda r: r.fulfill(status=200, content_type="text/html", body=PAGINA))
try:
    d = lettore.dati(36131309)
finally:
    lettore.chiudi()
ok = (sorted(chiamate) == ["base", "corner", "fgs"] and "Harry Kane" in d["marcatori"]
      and d["marcatori"]["Harry Kane"]["chi"] == "ospite" and 8.5 in d["corner"])
print(("OK " if ok else "XX "), "lettura pagina Sportsbook:", chiamate, len(d["marcatori"]), "marcatori, corner", sorted(d["corner"]))
sys.exit(0 if ok else 1)
