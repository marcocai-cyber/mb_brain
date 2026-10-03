"""Azioni dello scraper: pulsante disegnato in ritardo e coperto dal banner cookie."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import scraper_maggiorate as S

HTML = """<!doctype html><html><body>
<div id="onetrust-banner-sdk" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9">
 <button id="onetrust-reject-all-handler" onclick="this.parentNode.remove()">Rifiuta tutti</button></div>
<div id="tabs"></div><div id="out"></div>
<script>setTimeout(() => { document.getElementById('tabs').innerHTML =
 '<button role="tab">Popolari</button><button role="tab" onclick="document.getElementById(\\'out\\').textContent=\\'SPECIALI\\'">Speciali</button>'; }, 3000);</script>
</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.route("https://www.betfair.it/**", lambda r: r.fulfill(status=200, content_type="text/html", body=HTML))
    pg.goto("https://www.betfair.it/scommesse/calcio/s-1")
    S.run_actions(pg, [{"click_role": "tab", "name": "Speciali", "wait": 1}])
    ok = pg.locator("#out").inner_text() == "SPECIALI"
    b.close()
print(("OK " if ok else "XX "), "click sul tab 'Speciali' disegnato in ritardo, con banner cookie")
sys.exit(0 if ok else 1)
