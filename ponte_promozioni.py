#!/usr/bin/env python3
"""
Bridge locale per l'estensione Chrome "Lettore Promozioni"
============================================================
Riceve le promozioni estratte dall'estensione (pagine aperte nel TUO Chrome,
per i siti bloccati dall'anti-bot: Sisal, Snai, Goldbet e quelli che
aggiungerai) e le scrive in promozioni.json, nello stesso formato e nella
stessa cartella usati da scraper_promozioni.py — cosi' l'app le importa allo
stesso modo (tab Offerte > "Importa da file").

Esecuzione:
    python ponte_promozioni.py

Resta in ascolto finche' non lo fermi (Ctrl+C). Va avviato solo mentre usi
l'estensione, non deve girare sempre.

Porta: 127.0.0.1:8766 — diversa da quella del bridge Maggiorate (8765),
cosi' puoi tenerli accesi insieme senza conflitti.
"""

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from riassunto_promo import riassumi, e_scaduta  # noqa: E402
# Stesse regole dello scraper per categoria, scadenza e storico delle promo
# (first_seen/last_seen, cartella "Scaduti" dell'app): il file e' uno solo.
from scraper_promozioni import (  # noqa: E402
    BONUS_PROGRESSIVO_RE, EXCLUDE_PATTERNS_DEFAULT, TERMS_EXCLUDE_KEYWORDS, TERMS_VALUE_CHARS,
    classify_with_context, guess_deadline, load_config, merge_with_expiry, is_sport_or_slot_welcome,
    motivo_esclusione,
)
from urllib.parse import urlparse  # noqa: E402
OUTPUT_PATH = HERE / "promozioni.json"
PORT = 8766
HEADER_ATTESO = "X-Lettore-Promozioni"


def carica_esistenti():
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def salva(offerte):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(offerte, f, ensure_ascii=False, indent=2)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def _rifiuta(self, codice, messaggio):
        self.send_response(codice)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": False, "errore": messaggio}).encode("utf-8"))

    def do_POST(self):
        if self.path != "/promozioni":
            self._rifiuta(404, "endpoint non trovato")
            return
        # Controllo minimo: la richiesta deve avere l'header dell'estensione.
        # Non e' una vera autenticazione (siamo in locale), serve solo a
        # evitare che una pagina web qualsiasi scriva per sbaglio nel file.
        if self.headers.get(HEADER_ATTESO) != "1":
            self._rifiuta(403, "richiesta non proveniente dall'estensione")
            return

        lunghezza = int(self.headers.get("Content-Length", 0))
        try:
            corpo = json.loads(self.rfile.read(lunghezza).decode("utf-8"))
        except (json.JSONDecodeError, ValueError):
            self._rifiuta(400, "JSON non valido")
            return

        book = corpo.get("book", "")
        items = corpo.get("items", [])
        if not book or not isinstance(items, list):
            self._rifiuta(400, "formato non valido: servono 'book' e 'items'")
            return

        try:
            esclusioni = [k.lower() for k in load_config().get("exclude_keywords", EXCLUDE_PATTERNS_DEFAULT)]
        except Exception:
            esclusioni = [k.lower() for k in EXCLUDE_PATTERNS_DEFAULT]

        nuove, scadute, scartate = [], 0, 0
        for it in items:
            testo_card = it.pop("testo", "")
            testo_dett = it.pop("testo_dettaglio", "")
            testo = f"{testo_card} {testo_dett}"
            if not it.get("title"):
                continue
            card = f"{it['title']} {testo_card}"
            # stessi filtri dello scraper: frasi escluse (menu, tornei, porta un
            # amico...), bonus progressivo, montepremi nei T&C
            breve = f"{it['title']} {testo_card[:220]}".lower()  # come lo snippet dello scraper
            if (any(k in breve for k in esclusioni) or BONUS_PROGRESSIVO_RE.search(card)
                    or any(k in testo_dett[:TERMS_VALUE_CHARS].lower() for k in TERMS_EXCLUDE_KEYWORDS)):
                scartate += 1
                continue
            r = riassumi(testo)
            deadline = guess_deadline(testo) or r["deadline"]
            if e_scaduta(deadline, testo):
                scadute += 1
                continue
            categoria = classify_with_context(card, it.get("url", ""), testo_dett)
            path_words = urlparse(it.get("url", "")).path.replace("-", " ")
            if motivo_esclusione(it["title"], testo_card[:220], it.get("image", ""), testo_dett, categoria):
                scartate += 1  # torneo/gara/bingo/virtual/compleanno/amico
                continue
            if categoria == "Benvenuto" and not is_sport_or_slot_welcome(card + " " + path_words):
                scartate += 1  # come lo scraper: tra i benvenuto solo sport e slot
                continue
            it["book"] = book
            it["categoria"] = categoria
            it["snippet"] = " ".join(testo_card.split())[:220]
            it["note"] = r["note"] or it.get("note", "")
            it["deadline"] = deadline
            it["wager"] = r["wager"]
            if r["value"] is not None:
                it["value"] = r["value"]
            if not it.get("value"):
                scartate += 1  # come lo scraper: niente promo a €0
                continue
            it["max_cap"] = r["max_cap"] if r["max_cap"] is not None else 0
            it["slots"] = [{"name": n, "rtp": "", "volatility": "", "source": "",
                            "note": "non verificata (estensione)"} for n in r["slots"]]
            nuove.append(it)

        # Se la pagina e' stata letta (almeno una card), le promo di questo
        # book gia' salvate che non ci sono piu' passano tra le Scadute.
        ok_books = {book} if items else set()
        finali, tolte = merge_with_expiry(carica_esistenti(), nuove, ok_books)
        salva(finali)

        print(f"  {book}: {len(nuove)} promo salvate, {scadute} scadute scartate"
              f"{f', {scartate} scartate dai filtri (esclusioni, bonus progressivo, senza importo, benvenuto non sport/slot)' if scartate else ''}"
              f"{f', {tolte} scadute da oltre 14 giorni tolte dal file' if tolte else ''}"
              f" — {len(finali)} totali in {OUTPUT_PATH.name}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "salvate": len(nuove), "scadute": scadute}).encode("utf-8"))

    def do_GET(self):
        self._rifiuta(404, "solo POST su /promozioni")


def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 60)
    print(f"Bridge Lettore Promozioni in ascolto su http://127.0.0.1:{PORT}")
    print(f"Scrive in: {OUTPUT_PATH}")
    print("Ora apri Chrome, vai sui siti bloccati e usa l'estensione.")
    print("Ctrl+C per fermare.")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFermato.")


if __name__ == "__main__":
    main()
