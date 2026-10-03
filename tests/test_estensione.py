"""Prova end-to-end dell'estensione in Chromium: pagine Sisal/Snai/PokerStars simulate
(stesse strutture viste dal vivo), estensione caricata, ponte locale in ascolto."""
import json, shutil, sys, tempfile, time
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
for f in ["scraper_maggiorate.py", "ponte_estensione.py", "maggiorate_config.json"]:
    shutil.copy(SRC / f, tmp / f)
sys.path.insert(0, str(tmp))
import ponte_estensione as P
from playwright.sync_api import sync_playwright

PORT = 8799
assert P.scrivi_estensione(port=PORT)
manifest = json.loads((P.EXT_DIR / "manifest.json").read_text())
print("domini estensione:", manifest["content_scripts"][0]["matches"])
eventi = []
ponte = P.Ponte(PORT, on_update=lambda b, n: eventi.append((b, n))).start()

CARD = """<html><body><h2>Da giocare in singola</h2><div class="row">
<div class="c"><div>INT Speciali Calcio</div><div>FRA-ITA</div><div>02/10 20:45</div><div>Francia - Italia: bomber con quota maggiorata!</div>
<div>Giocata</div><div>425</div><div>volte</div><div>{nomi}</div><div><span style="text-decoration:line-through">{bar}</span></div><button>{mag}</button></div>
<div class="c"><div>INT Nations League</div><div>Kazakistan - Moldova</div><button>1.85</button><button>3.25</button><button>4.50</button></div>
</div></body></html>"""
PAGES = {"sisal.it": CARD.format(nomi="Dembele e Pio Esposito segnano entrambi", bar="8.04", mag="12.00"),
         "snai.it": CARD.format(nomi="Olise e Sebastiano Esposito segnano o fanno assist", bar="4.88", mag="7.50"),
         "pokerstars.it": CARD.format(nomi="Zidane ammonito", bar="4.00", mag="6.00")}

import http.server, ssl, subprocess, threading
CERT = tmp / "cert.pem"
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(CERT), "-out", str(CERT),
                "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True)

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        html = next((v for d, v in PAGES.items() if host.endswith(d)), None)
        self.send_response(200 if html else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((html or "no").encode())

https = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), H)
sslctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
sslctx.load_cert_chain(str(CERT))
https.socket = sslctx.wrap_socket(https.socket, server_side=True)
threading.Thread(target=https.serve_forever, daemon=True).start()


def handler(route):
    host = route.request.url.split("/")[2]
    for d, html in PAGES.items():
        if host.endswith(d):
            return route.fulfill(status=200, content_type="text/html", body=html)
    route.abort()

ok = True
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(tmp / "profilo"), headless=False, args=[
        f"--disable-extensions-except={P.EXT_DIR}", f"--load-extension={P.EXT_DIR}",
        "--host-resolver-rules=MAP *.sisal.it 127.0.0.1:8443, MAP *.snai.it 127.0.0.1:8443, MAP *.pokerstars.it 127.0.0.1:8443",
        "--ignore-certificate-errors", "--no-proxy-server"], ignore_https_errors=True)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    # 1) navigazione normale: lettura automatica
    pg = ctx.new_page()
    pg.goto("https://www.sisal.it/scommesse-matchpoint")
    t0 = time.time()
    while time.time() - t0 < 20 and not eventi:
        time.sleep(0.5)
    data = json.loads((tmp / "maggiorate.json").read_text())
    sis = [m for m in data["maggiorate"] if m["book"] == "Sisal"]
    good = len(sis) == 1 and sis[0]["quota_maggiorata"] == 12.0 and sis[0]["quota_barrata"] == 8.04 and sis[0]["via"] == "estensione"
    ok &= good
    print("OK " if good else "XX ", "lettura automatica Sisal:", [(m["descrizione"], m["quota_barrata"], m["quota_maggiorata"]) for m in sis])
    pg.close()
    # 2) pulsante del popup: apre Sisal, Snai, PokerStars in background e li chiude
    popup = ctx.new_page()
    popup.goto(f"chrome-extension://{ext_id}/popup.html")
    popup.wait_for_timeout(1500)
    print("   popup:", popup.inner_text("#stato")[:80])
    popup.click("#cloni")
    t0 = time.time()
    while time.time() - t0 < 45:
        books = {b for b, _ in eventi}
        aperte = [x for x in ctx.pages if any(d in x.url for d in PAGES)]
        if {"Sisal", "Snai", "PokerStars"} <= books and not aperte:
            break
        time.sleep(1)
    data = json.loads((tmp / "maggiorate.json").read_text())
    got = sorted((m["book"], m["quota_maggiorata"]) for m in data["maggiorate"])
    good = got == [("PokerStars", 6.0), ("Sisal", 12.0), ("Snai", 7.5)]
    ok &= good
    aperte = [x.url for x in ctx.pages if any(d in x.url for d in PAGES)]
    print("OK " if good else "XX ", "pulsante 'Leggi Sisal, Snai e PokerStars':", got, "| schede book rimaste aperte:", aperte)
    ok &= not aperte
    print("   stato_book:", {k: v["stato"] for k, v in data["stato_book"].items()})
    popup.wait_for_timeout(3500)
    print("   log popup:", popup.inner_text("#log").replace("\n", " | ")[:300])
    ctx.close()
ponte.stop()
# 3) sicurezza: POST senza header -> 403
import urllib.request, urllib.error
ponte2 = P.Ponte(PORT).start()
try:
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/maggiorate", data=b"{}"))
    good = False
except urllib.error.HTTPError as e:
    good = e.code == 403
ponte2.stop()
ok &= good
print("OK " if good else "XX ", "POST senza header rifiutato")
sys.exit(0 if ok else 1)
