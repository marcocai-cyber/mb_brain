#!/usr/bin/env python3
"""
Ponte tra l'estensione Chrome "Lettore Maggiorate" e l'app
=========================================================
Sisal, Snai, PokerStars (e altri book con anti-bot) rifiutano il browser
automatico dello scraper. Le loro maggiorate le legge invece l'estensione
dentro il TUO Chrome, mentre navighi normalmente su quei siti (o quando premi
"Leggi Sisal e cloni" nel popup dell'estensione): nessun aggiramento, sono le
pagine che apri tu.

L'estensione manda le card trovate a questo piccolo server locale
(solo 127.0.0.1, porta 8765), che le interpreta con lo stesso parser dello
scraper e le aggiunge a maggiorate.json; poi l'app ricalcola l'EV.

Il server parte da solo con maggiorate_app.py. Si puo' anche lanciare da solo:
    python ponte_estensione.py
"""

import json
import re
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import scraper_maggiorate as SM  # noqa: E402

EXT_DIR = HERE / "estensione_maggiorate"
CONFIG_PATH = HERE / "maggiorate_config.json"
OUTPUT_PATH = HERE / "maggiorate.json"
DEFAULT_PORT = 8765
TENUTA_ORE = 12  # le maggiorate lette da una pagina restano finche' la pagina non viene riletta, max 12 ore

_lock = threading.Lock()


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def dominio(url):
    h = (urlparse(url).hostname or "").lower()
    h = re.sub(r"^(www|sports|sport|scommesse)\.", "", h)
    return h


def book_estensione(config):
    """Book da leggere con l'estensione: quelli con lettura 'estensione'."""
    out = []
    for b in config.get("book", []):
        if b.get("pagamento") == "reale" and b.get("lettura") == "estensione" and b.get("url"):
            out.append({"name": b["name"], "dominio": dominio(b["url"]), "mode": b.get("mode", "cards"),
                        "pagine": b.get("pagine_estensione") or [b["url"]], "max_bet": b.get("max_bet")})
    return out


# ---------------------------------------------------------------------------
# Unione delle maggiorate ricevute in maggiorate.json
# ---------------------------------------------------------------------------

def unisci(book_cfg, url, raws, now=None, solo_oggi=True):
    """Interpreta le card ricevute e le scrive in maggiorate.json, sostituendo
    quelle lette in precedenza dalla stessa pagina dello stesso book.
    Con solo_oggi si tengono solo le maggiorate di oggi (o senza data)."""
    now = now or datetime.now()
    items = SM.parse_raws(book_cfg, raws)
    if solo_oggi:
        items = [it for it in items if SM.di_oggi(it, now.date())]
    pagina = urlparse(url).netloc + urlparse(url).path
    for it in items:
        it["via"] = "estensione"
        it["pagina"] = pagina
        it["letta_il"] = now.isoformat(timespec="seconds")
    with _lock:
        data = {"maggiorate": [], "stato_book": {}}
        if OUTPUT_PATH.exists():
            try:
                data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        limite = now - timedelta(hours=TENUTA_ORE)
        tenute = []
        for it in data.get("maggiorate", []):
            if solo_oggi and not SM.di_oggi(it, now.date()):
                continue
            if it["book"] == book_cfg["name"] and it.get("via") == "estensione":
                if it.get("pagina") == pagina:
                    continue  # sostituita dalla nuova lettura
                try:
                    if datetime.fromisoformat(it.get("letta_il", "")) < limite:
                        continue
                except ValueError:
                    continue
            elif it["book"] == book_cfg["name"] and it.get("via") != "estensione":
                continue  # vecchie righe dello scraper per un book ora letto dall'estensione
            tenute.append(it)
        data["maggiorate"] = tenute + items
        tot = sum(1 for it in data["maggiorate"] if it["book"] == book_cfg["name"])
        data.setdefault("stato_book", {})[book_cfg["name"]] = {
            "stato": "ok (estensione Chrome)", "trovate": tot, "letto_il": now.isoformat(timespec="seconds")}
        data["aggiornato_il"] = now.isoformat(timespec="seconds")
        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


# ---------------------------------------------------------------------------
# Server HTTP locale
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "PonteMaggiorate/1.0"

    def log_message(self, *a):  # silenzioso
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/ping"):
            return self._send(200, {"ok": True, "app": "maggiorate"})
        if self.path.startswith("/config"):
            try:
                return self._send(200, {"book": book_estensione(load_config())})
            except Exception as e:
                return self._send(500, {"ok": False, "errore": str(e)})
        self._send(404, {"ok": False})

    def do_POST(self):
        # Header obbligatorio: una pagina web qualsiasi non puo' aggiungerlo senza
        # un preflight CORS (a cui il server non risponde), l'estensione si'.
        if self.headers.get("X-Maggiorate") != "1" or not self.path.startswith("/maggiorate"):
            return self._send(403, {"ok": False})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            msg = json.loads(self.rfile.read(min(n, 5_000_000)).decode("utf-8"))
            conf = load_config()
            cfg = next((b for b in conf.get("book", []) if b["name"] == msg.get("book")), None)
            if not cfg or cfg.get("pagamento") != "reale":
                return self._send(400, {"ok": False, "errore": "book sconosciuto"})
            items = unisci(cfg, msg.get("url", ""), msg.get("raws") or [], solo_oggi=conf.get("solo_oggi", True))
            cb = getattr(self.server, "on_update", None)
            if cb:
                cb(cfg["name"], len(items))
            return self._send(200, {"ok": True, "trovate": len(items)})
        except Exception as e:
            return self._send(500, {"ok": False, "errore": str(e)[:200]})


class Ponte:
    def __init__(self, port=DEFAULT_PORT, on_update=None):
        self.port = port
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.on_update = on_update
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---------------------------------------------------------------------------
# File dell'estensione (rigenerati dal config: domini dei book e porta)
# ---------------------------------------------------------------------------

def scrivi_estensione(config=None, port=DEFAULT_PORT, cartella=EXT_DIR):
    """Scrive/aggiorna i file dell'estensione. Ritorna True se qualcosa e' cambiato
    (in quel caso va premuto 'Ricarica' su chrome://extensions)."""
    config = config or load_config()
    books = book_estensione(config)
    matches = sorted({f"https://*.{b['dominio']}/*" for b in books} | {f"https://{b['dominio']}/*" for b in books})
    manifest = {
        "manifest_version": 3,
        "name": "Lettore Maggiorate",
        "version": "1.0",
        "description": "Legge le quote maggiorate di Sisal, Snai, PokerStars e degli altri book con anti-bot "
                       "mentre navighi, e le passa all'app Maggiorate EV+ sul tuo PC.",
        "permissions": ["storage"],
        "host_permissions": [f"http://127.0.0.1:{port}/*"],
        "background": {"service_worker": "background.js"},
        "content_scripts": [{"matches": matches, "js": ["estrattore.js", "content.js"], "run_at": "document_idle"}],
        "action": {"default_popup": "popup.html", "default_title": "Lettore Maggiorate"},
    }
    files = {
        "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False),
        "estrattore.js": "// Generato da ponte_estensione.py: stesso estrattore di scraper_maggiorate.py\n"
                         "window.__estraiMaggiorate = " + SM.EXTRACT_JS.strip() + ";\n",
        "content.js": CONTENT_JS,
        "background.js": BACKGROUND_JS.replace("__PORTA__", str(port)),
        "popup.html": POPUP_HTML,
        "popup.js": POPUP_JS,
    }
    cartella.mkdir(exist_ok=True)
    changed = False
    for name, txt in files.items():
        p = cartella / name
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != txt:
            p.write_text(txt, encoding="utf-8")
            changed = True
    return changed


CONTENT_JS = r"""// Lettore Maggiorate - legge le card nella pagina e le manda all'app tramite il background.
(async () => {
  let cfg;
  try { cfg = await chrome.runtime.sendMessage({ tipo: "config", host: location.hostname }); } catch (e) { return; }
  if (!cfg || !cfg.book) return;
  let ultimo = "";
  let inviati = 0;
  const pausa = (ms) => new Promise((r) => setTimeout(r, ms));

  async function scorri() {  // solo nelle schede aperte dal pulsante del popup
    const h = document.body.scrollHeight;
    for (let i = 1; i <= 6; i++) { window.scrollTo(0, (h * i) / 6); await pausa(400); }
    window.scrollTo(0, 0);
  }

  function estrai(finale) {
    let raws = [];
    try { raws = window.__estraiMaggiorate({ mode: cfg.mode === "list" ? "list" : "cards" }) || []; } catch (e) { raws = []; }
    const firma = JSON.stringify(raws.map((r) => r.text));
    if (raws.some((r) => r.why !== "gruppo") && firma !== ultimo) {
      ultimo = firma;
      inviati++;
      chrome.runtime.sendMessage({ tipo: "risultato", book: cfg.book, url: location.href, raws });
    } else if (finale) {
      chrome.runtime.sendMessage({ tipo: "fine", book: cfg.book, url: location.href, trovate: inviati > 0 });
    }
  }

  async function ciclo() {
    if (cfg.batch) await scorri();
    await pausa(5000); estrai(false);
    await pausa(7000); if (cfg.batch) await scorri(); estrai(false);
    await pausa(10000); estrai(true);
  }

  chrome.runtime.onMessage.addListener((m, _s, reply) => {
    if (m.tipo === "estrai") { ultimo = ""; estrai(true); reply({ ok: true }); }
  });
  // le pagine "a scheda singola" cambiano indirizzo senza ricaricare
  let href = location.href;
  setInterval(() => { if (location.href !== href) { href = location.href; ultimo = ""; ciclo(); } }, 2000);
  ciclo();
})();
"""

BACKGROUND_JS = r"""// Lettore Maggiorate - background: riceve le card e le passa all'app locale.
const PONTE = "http://127.0.0.1:__PORTA__";

async function ponte(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Maggiorate": "1" }, body: JSON.stringify(body) } : {};
  const r = await fetch(PONTE + path, opt);
  return r.json();
}

async function config() {
  try {
    const c = await ponte("/config");
    await chrome.storage.local.set({ config: c });
    return c;
  } catch (e) {
    const s = await chrome.storage.local.get("config");
    return s.config || { book: [] };
  }
}

function bookPerHost(c, host) {
  host = (host || "").toLowerCase();
  return (c.book || []).find((b) => host === b.dominio || host.endsWith("." + b.dominio));
}

async function log(riga) {
  const s = await chrome.storage.local.get("log");
  const l = (s.log || []).slice(-30);
  l.push(new Date().toLocaleTimeString("it-IT") + "  " + riga);
  await chrome.storage.local.set({ log: l });
}

async function invia(msg) {
  try {
    const r = await ponte("/maggiorate", msg);
    await log(`${msg.book}: ${r.ok ? r.trovate + " maggiorate inviate all'app" : "errore " + (r.errore || "")}`);
    return r;
  } catch (e) {
    // app spenta: le tengo in coda e le mando appena torna attiva
    const s = await chrome.storage.local.get("coda");
    const coda = (s.coda || []).filter((x) => !(x.book === msg.book && x.url === msg.url));
    coda.push(msg);
    await chrome.storage.local.set({ coda: coda.slice(-20) });
    await log(`${msg.book}: app non attiva, lettura messa in coda`);
    return { ok: false };
  }
}

async function svuotaCoda() {
  const s = await chrome.storage.local.get("coda");
  if (!s.coda || !s.coda.length) return;
  await chrome.storage.local.set({ coda: [] });
  for (const m of s.coda) await invia(m);
}

async function chiudiSeBatch(tabId) {
  const s = await chrome.storage.local.get("batch");
  const b = s.batch || [];
  if (b.includes(tabId)) {
    await chrome.storage.local.set({ batch: b.filter((x) => x !== tabId) });
    try { await chrome.tabs.remove(tabId); } catch (e) {}
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    if (msg.tipo === "config") {
      const c = await config();
      const b = bookPerHost(c, msg.host);
      const s = await chrome.storage.local.get("batch");
      reply(b ? { book: b.name, mode: b.mode, batch: (s.batch || []).includes(sender.tab && sender.tab.id) } : null);
    } else if (msg.tipo === "risultato") {
      await svuotaCoda();
      reply(await invia({ book: msg.book, url: msg.url, raws: msg.raws }));
    } else if (msg.tipo === "fine") {
      if (!msg.trovate) await log(`${msg.book}: nessuna maggiorata in ${new URL(msg.url).pathname}`);
      if (sender.tab) await chiudiSeBatch(sender.tab.id);
      reply({ ok: true });
    } else if (msg.tipo === "leggi_book") {
      const c = await config();
      const scelti = (c.book || []).filter((b) => !msg.nomi || msg.nomi.includes(b.name));
      const ids = [];
      for (const b of scelti) for (const url of b.pagine) {
        const t = await chrome.tabs.create({ url, active: false });
        ids.push(t.id);
        const s = await chrome.storage.local.get("batch");
        await chrome.storage.local.set({ batch: (s.batch || []).concat([t.id]) });
      }
      await log(`aperte ${ids.length} pagine: ${scelti.map((b) => b.name).join(", ")}`);
      reply({ ok: true, aperte: ids.length });
    } else if (msg.tipo === "stato") {
      let attiva = false;
      try { attiva = (await ponte("/ping")).ok; } catch (e) {}
      if (attiva) await svuotaCoda();
      const c = await config();
      const s = await chrome.storage.local.get(["log", "coda"]);
      reply({ attiva, book: (c.book || []).map((b) => b.name), log: s.log || [], coda: (s.coda || []).length });
    }
  })();
  return true;
});
"""

POPUP_HTML = r"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<style>
  body { font: 13px system-ui, Segoe UI, Arial; width: 330px; margin: 10px; color: #222; }
  h1 { font-size: 14px; margin: 0 0 6px; }
  .stato { padding: 6px 8px; border-radius: 6px; margin-bottom: 8px; }
  .ok { background: #e3f4e6; } .ko { background: #fde8e8; }
  button { width: 100%; padding: 8px; margin: 4px 0; font-size: 13px; cursor: pointer; }
  pre { background: #f5f5f5; padding: 6px; max-height: 170px; overflow: auto; font-size: 11px; white-space: pre-wrap; }
  small { color: #666; }
</style></head>
<body>
  <h1>Lettore Maggiorate</h1>
  <div id="stato" class="stato">…</div>
  <button id="cloni">Leggi Sisal, Snai e PokerStars</button>
  <button id="tutti">Leggi tutti i book con anti-bot</button>
  <button id="pagina">Leggi questa scheda</button>
  <small>Le pagine si aprono in schede in secondo piano e si chiudono da sole dopo circa 25 secondi.
  Mentre navighi su questi siti la lettura e' comunque automatica.</small>
  <pre id="log"></pre>
  <script src="popup.js"></script>
</body></html>
"""

POPUP_JS = r"""const $ = (id) => document.getElementById(id);
async function aggiorna() {
  const s = await chrome.runtime.sendMessage({ tipo: "stato" });
  $("stato").className = "stato " + (s.attiva ? "ok" : "ko");
  $("stato").textContent = s.attiva
    ? "App Maggiorate EV+ attiva. Book: " + s.book.join(", ")
    : "App non attiva: avvia avvia_maggiorate.bat (le letture restano in coda: " + s.coda + ")";
  $("log").textContent = s.log.slice().reverse().join("\n");
}
$("cloni").onclick = async () => {
  await chrome.runtime.sendMessage({ tipo: "leggi_book", nomi: ["Sisal", "Snai", "PokerStars"] });
  setTimeout(aggiorna, 500);
};
$("tutti").onclick = async () => {
  await chrome.runtime.sendMessage({ tipo: "leggi_book", nomi: null });
  setTimeout(aggiorna, 500);
};
$("pagina").onclick = async () => {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  try { await chrome.tabs.sendMessage(t.id, { tipo: "estrai" }); } catch (e) { $("log").textContent = "Questa scheda non e' di un book letto dall'estensione."; }
  setTimeout(aggiorna, 1500);
};
aggiorna();
setInterval(aggiorna, 3000);
"""


if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("porta_estensione", DEFAULT_PORT)
    if scrivi_estensione(cfg, port):
        print(f"File dell'estensione aggiornati in {EXT_DIR.name}/ (se gia' installata: chrome://extensions > Ricarica)")
    print(f"Ponte in ascolto su http://127.0.0.1:{port} — Ctrl+C per fermare")
    Ponte(port, on_update=lambda b, n: print(f"{datetime.now():%H:%M:%S}  {b}: {n} maggiorate")).httpd.serve_forever()
