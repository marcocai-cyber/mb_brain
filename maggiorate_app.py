#!/usr/bin/env python3
"""
Maggiorate EV+ — programmino di controllo
=========================================
Finestra unica per:
  1. lanciare la lettura delle maggiorate sui book mappati (scraper_maggiorate.py)
  2. calcolare la fair e l'EV di ognuna (ev_maggiorate.py, fair da Betfair Exchange)
  3. inserire a mano la fair dei mercati speciali (livello 2) o aggiungere una
     maggiorata vista sul sito (es. book bloccati dall'anti-bot)
  4. copiare il post per il canale Telegram delle maggiorate EV+

Avvio: doppio clic su avvia_maggiorate.bat (oppure: python maggiorate_app.py)
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import ev_maggiorate as EV  # noqa: E402
import ponte_estensione as PE  # noqa: E402

CONFIG_PATH = HERE / "maggiorate_config.json"
SCRAPER = HERE / "scraper_maggiorate.py"

COLS = [("stato", "Stato", 95), ("book", "Book", 110), ("evento", "Evento", 170), ("descrizione", "Mercato", 330),
        ("quota_barrata", "Barrata", 65), ("quota_maggiorata", "Maggiorata", 80), ("max_bet", "Max", 50),
        ("fair", "Fair", 60), ("ev_pct", "EV%", 60), ("ev_cons_pct", "EV% cons.", 70), ("fonte", "Fonte / nota", 260)]


def fmt(v, dec=2):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.{dec}f}"
    return str(v)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Maggiorate EV+")
        self.geometry("1400x760")
        self.minsize(1000, 560)
        self.msgs = queue.Queue()
        self.rows = []
        self.busy = False
        self.config_data = EV.load_json(CONFIG_PATH, {"book": []})
        self.book_vars = {}
        self._ev_pending = False
        self._build()
        self._load_results()
        self._avvia_ponte()
        self.after(200, self._poll)

    def _avvia_ponte(self):
        """Server locale per l'estensione Chrome (Sisal, Snai, PokerStars & co.)."""
        port = self.config_data.get("porta_estensione", PE.DEFAULT_PORT)
        try:
            if PE.scrivi_estensione(self.config_data, port):
                self._log("File dell'estensione aggiornati: se e' gia' installata, premi 'Ricarica' su chrome://extensions.")
            self.ponte = PE.Ponte(port, on_update=lambda b, n: self.msgs.put(("ext", (b, n)))).start()
            self.ext_status.set(f"Estensione: in ascolto (porta {port})")
        except OSError as e:
            self.ponte = None
            self.ext_status.set("Estensione: porta occupata (app gia' aperta?)")
            self._log(f"Ponte estensione non avviato: {e}")

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        self.btn_all = ttk.Button(top, text="▶  Leggi maggiorate + calcola EV", command=self.run_all)
        self.btn_all.pack(side="left")
        self.btn_ev = ttk.Button(top, text="Ricalcola solo EV", command=self.run_ev)
        self.btn_ev.pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(top, text="Imposta fair…", command=self.set_fair).pack(side="left")
        ttk.Button(top, text="Aggiungi a mano…", command=self.add_manual).pack(side="left", padx=4)
        ttk.Button(top, text="Copia post Telegram", command=self.copy_post).pack(side="left")
        ttk.Button(top, text="Apri report", command=self.open_report).pack(side="left", padx=4)
        ttk.Button(top, text="Betfair…", command=self.betfair_settings).pack(side="left")
        ttk.Button(top, text="Estensione Chrome…", command=self.estensione_info).pack(side="left", padx=4)
        self.only_pos = tk.BooleanVar(value=False)
        self.with_est = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="anche stime", variable=self.with_est, command=self._fill_table).pack(side="right")
        ttk.Checkbutton(top, text="Solo EV+", variable=self.only_pos, command=self._fill_table).pack(side="right")
        self.ext_status = tk.StringVar(value="Estensione: …")
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(top, textvariable=self.status).pack(side="right", padx=12)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        # Book
        left = ttk.Frame(body, padding=6)
        ttk.Label(left, text="Book (vincita in saldo reale)", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        lf = ttk.Frame(left)
        lf.pack(fill="both", expand=True)
        for b in self.config_data.get("book", []):
            if b.get("pagamento") != "reale":
                continue
            v = tk.BooleanVar(value=bool(b.get("attivo") and b.get("url")))
            self.book_vars[b["name"]] = v
            cb = ttk.Checkbutton(lf, text=b["name"], variable=v)
            cb.pack(anchor="w")
            if not b.get("url"):
                cb.state(["disabled"])
        excluded = [b["name"] for b in self.config_data.get("book", []) if b.get("pagamento") != "reale"]
        if excluded:
            ttk.Label(left, text="Esclusi (maggiorazione in bonus):\n" + ", ".join(excluded),
                      foreground="#888", wraplength=170).pack(anchor="w", pady=(8, 0))
        ttk.Label(left, textvariable=self.ext_status, foreground="#2a6", wraplength=170).pack(anchor="w", pady=(8, 0))
        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="Tutti", width=7, command=lambda: [v.set(True) for v in self.book_vars.values()]).pack(side="left")
        ttk.Button(bf, text="Nessuno", width=8, command=lambda: [v.set(False) for v in self.book_vars.values()]).pack(side="left", padx=4)
        body.add(left, weight=0)

        # Tabella + log
        right = ttk.PanedWindow(body, orient="vertical")
        tf = ttk.Frame(right)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLS], show="headings", selectmode="extended")
        for key, title, w in COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=w, anchor="w", stretch=key in ("descrizione", "fonte"))
        self.tree.tag_configure("pos", background="#dff3e3")
        self.tree.tag_configure("neg", foreground="#888888")
        self.tree.tag_configure("na", background="#fff6d6")
        self.tree.tag_configure("stima_pos", background="#e3eefc")
        self.tree.tag_configure("stima_neg", foreground="#8aa0bb")
        ys = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.set_fair())
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        right.add(tf, weight=4)

        df = ttk.Frame(right)
        self.detail = tk.Text(df, height=9, wrap="word", font=("Consolas", 9))
        self.detail.pack(fill="both", expand=True)
        right.add(df, weight=1)
        body.add(right, weight=1)
        self.sort_key, self.sort_rev = "ev_pct", True

    # --------------------------------------------------------------- dati
    def _load_results(self):
        data = EV.load_json(EV.OUTPUT_PATH, None)
        if data:
            self.rows = data.get("righe", [])
            self.status.set(f"Ultimo calcolo: {data.get('calcolato_il', '')[:16].replace('T', ' ')}")
        self._fill_table()

    def _fill_table(self):
        self.tree.delete(*self.tree.get_children())
        def visibile(r):
            if not self.with_est.get() and r.get("stima"):
                return False
            return not self.only_pos.get() or r.get("ev_plus") or (r.get("ev_plus_stima") and self.with_est.get())
        rows = [r for r in self.rows if visibile(r)]

        def keyf(r):
            v = r.get(self.sort_key)
            return (0, v, "") if isinstance(v, (int, float)) else (1, 0, str(v).lower())
        with_val = [r for r in rows if r.get(self.sort_key) not in (None, "")]
        no_val = [r for r in rows if r.get(self.sort_key) in (None, "")]
        rows = sorted(with_val, key=keyf, reverse=self.sort_rev) + no_val  # le righe vuote restano in fondo
        for r in rows:
            if r.get("stato") == "iniziata":
                tag = "neg"
            elif r.get("stima"):
                tag = "stima_pos" if r.get("ev_plus_stima") else "stima_neg"
            else:
                tag = "pos" if r.get("ev_plus") else ("neg" if r.get("ev_pct") is not None else "na")
            fonte = r.get("fonte_fair") or r.get("errore_fair", "")
            if r.get("avvisi"):
                fonte += " ⚠ " + "; ".join(r["avvisi"])
            if r.get("non_riconfermata"):
                fonte = "(run precedente) " + fonte
            vals = [r.get("stato", ""), r["book"], r.get("evento", ""), r.get("descrizione", ""),
                    fmt(r.get("quota_barrata")), fmt(r.get("quota_maggiorata")), fmt(r.get("max_bet"), 0),
                    fmt(r.get("fair")), fmt(r.get("ev_pct"), 1), fmt(r.get("ev_cons_pct"), 1), fonte]
            self.tree.insert("", "end", iid=r["id"], values=vals, tags=(tag,))

    def _sort(self, key):
        self.sort_rev = not self.sort_rev if self.sort_key == key else True
        self.sort_key = key
        self._fill_table()

    def _selected(self):
        ids = set(self.tree.selection())
        return [r for r in self.rows if r["id"] in ids]

    def _show_detail(self, _e=None):
        sel = self._selected()
        self.detail.delete("1.0", "end")
        if not sel:
            return
        r = sel[0]
        lines = [EV.telegram_post(r) if r.get("quota_maggiorata") else "", "",
                 f"Livello: {r.get('livello')}   Fonte fair: {r.get('fonte_fair') or '-'}",
                 f"Dettaglio exchange: {r.get('dettaglio_fair') or r.get('errore_fair', '')}",
                 f"Mercato riconosciuto: {json.dumps(r.get('mercato_exchange'), ensure_ascii=False)}",
                 "", "Testo letto dalla card:", r.get("testo", "")]
        self.detail.insert("1.0", "\n".join(lines))

    # ------------------------------------------------------------- azioni
    def _log(self, msg):
        self.msgs.put(("log", msg))

    def _poll(self):
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "log":
                    self.detail.insert("end", payload + "\n")
                    self.detail.see("end")
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "ext":
                    book, n = payload
                    self.detail.insert("end", f"{datetime.now():%H:%M:%S}  estensione Chrome: {book}, {n} maggiorate\n")
                    self.detail.see("end")
                    if not self._ev_pending:  # piu' book in arrivo insieme: un solo ricalcolo
                        self._ev_pending = True
                        self.after(4000, self._ev_da_estensione)
                elif kind == "done":
                    self.busy = False
                    self.btn_all.state(["!disabled"])
                    self.btn_ev.state(["!disabled"])
                    self._load_results()
                    if payload:
                        self.status.set(payload)
        except queue.Empty:
            pass
        self.after(200, self._poll)

    def _ev_da_estensione(self):
        self._ev_pending = False
        if self.busy:
            self.after(4000, self._ev_da_estensione)
            return
        self._start(lambda: self._job(None), clear=False)

    def _start(self, target, clear=True):
        if self.busy:
            return
        self.busy = True
        self.btn_all.state(["disabled"])
        self.btn_ev.state(["disabled"])
        if clear:
            self.detail.delete("1.0", "end")
        threading.Thread(target=target, daemon=True).start()

    def run_all(self):
        books = [n for n, v in self.book_vars.items() if v.get()]
        if not books:
            messagebox.showinfo("Maggiorate", "Seleziona almeno un book.")
            return
        self._start(lambda: self._job(books))

    def run_ev(self):
        self._start(lambda: self._job(None))

    def _job(self, books):
        t0 = time.monotonic()
        try:
            if books is not None:
                self.msgs.put(("status", f"Lettura maggiorate su {len(books)} book…"))
                cmd = [sys.executable, "-u", str(SCRAPER)] + books
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                env = dict(os.environ, PYTHONIOENCODING="utf-8")
                proc = subprocess.Popen(cmd, cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=flags, env=env)
                for line in proc.stdout:
                    self._log(line.rstrip())
                proc.wait()
            self.msgs.put(("status", "Calcolo fair ed EV…"))
            self._compute_ev()
            el = time.monotonic() - t0
            self.msgs.put(("done", f"Fatto in {int(el)} s — {datetime.now():%H:%M}"))
        except Exception as e:
            self._log(f"ERRORE: {e}")
            self.msgs.put(("done", "Errore: vedi il riquadro in basso"))

    def _compute_ev(self):
        data = EV.load_json(EV.INPUT_PATH, {"maggiorate": []})
        items = list(data.get("maggiorate", []))
        manual = EV.load_json(EV.MANUAL_PATH, {})
        for mid, m in manual.items():
            if m.get("aggiunta_manuale") and not any(i["id"] == mid for i in items):
                items.append(m["aggiunta_manuale"])
        for name, st in (data.get("stato_book") or {}).items():
            if not str(st.get("stato", "")).startswith("ok"):
                self._log(f"!! {name}: {st.get('stato')}")
        client = EV.BetfairClient.from_files()
        if client is None:
            self._log("Betfair non configurato: senza exchange la fair e' solo STIMA dalla quota barrata. "
                      "Premi 'Betfair…' per la fair automatica.")
        soglia = self.config_data.get("soglia_ev_pct", 0.0)
        solo_oggi = self.config_data.get("solo_oggi", True)
        if solo_oggi:
            _, altre = EV.solo_di_oggi(items)
            if altre:
                self._log(f"{len(altre)} maggiorate di altri giorni escluse (solo_oggi attivo).")
        sb = EV.crea_lettore_sportsbook(self.config_data) if client is not None else None
        try:
            rows = EV.evaluate(items, manual, client, EV.load_json(EV.ALIAS_PATH, {}), soglia, log=self._log,
                               margini=self.config_data.get("margine_speciali_pct"), sportsbook=sb,
                               solo_oggi=solo_oggi)
        finally:
            if sb:
                sb.chiudi()
        n_ini = sum(1 for r in rows if r.get("stato") == "iniziata")
        if n_ini:
            self._log(f"{n_ini} maggiorate su partite gia' iniziate: niente fair (quote exchange live).")
        EV.OUTPUT_PATH.write_text(json.dumps({"calcolato_il": datetime.now().isoformat(timespec="seconds"),
                                              "righe": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        EV.write_report(rows)
        n_pos = sum(1 for r in rows if r["ev_plus"])
        n_st = sum(1 for r in rows if r.get("ev_plus_stima"))
        self._log(f"{len(rows)} maggiorate: {n_pos} EV+ (fair da exchange/modello), {n_st} EV+ solo stimate.")

    def _save_manual(self, mid, entry):
        manual = EV.load_json(EV.MANUAL_PATH, {})
        cur = manual.get(mid, {})
        cur.update(entry)
        manual[mid] = cur
        EV.MANUAL_PATH.write_text(json.dumps(manual, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_fair(self):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Imposta fair", "Seleziona una maggiorata nella tabella.")
            return
        r = sel[0]
        cur = r.get("fair") or ""
        s = simpledialog.askstring(
            "Imposta fair",
            f"{r['book']} — {r.get('evento', '')}\n{r.get('descrizione', '')} @{r.get('quota_maggiorata')}\n\n"
            "Scrivi la quota fair (es. 2.45)\noppure back/lay dell'exchange (es. 2.40/2.46).\n"
            "Lascia vuoto per tornare alla fair automatica.",
            initialvalue=str(cur), parent=self)
        if s is None:
            return
        s = s.replace(",", ".").strip()
        try:
            if not s:
                entry = {"fair": None, "back": None, "lay": None}
            elif "/" in s:
                b, l = [float(x) for x in s.split("/", 1)]
                entry = {"fair": None, "back": b, "lay": l}
            else:
                entry = {"fair": float(s), "back": None, "lay": None}
        except ValueError:
            messagebox.showerror("Imposta fair", "Valore non valido.")
            return
        self._save_manual(r["id"], entry)
        self.run_ev()

    def add_manual(self):
        win = tk.Toplevel(self)
        win.title("Aggiungi maggiorata a mano")
        win.transient(self)
        fields = [("Book", "book"), ("Evento (Casa - Ospite)", "evento"), ("Mercato / descrizione", "descrizione"),
                  ("Quota maggiorata", "quota_maggiorata"), ("Quota barrata (facoltativa)", "quota_barrata"),
                  ("Puntata massima (facoltativa)", "max_bet"), ("Fair o back/lay (facoltativa)", "fair")]
        vars_ = {}
        for i, (lab, key) in enumerate(fields):
            ttk.Label(win, text=lab).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            if key == "book":
                v = tk.StringVar()
                ttk.Combobox(win, textvariable=v, values=list(self.book_vars), width=40).grid(row=i, column=1, padx=8)
            else:
                v = tk.StringVar()
                ttk.Entry(win, textvariable=v, width=43).grid(row=i, column=1, padx=8)
            vars_[key] = v

        def num(x):
            x = x.get().replace(",", ".").strip()
            return float(x) if x else None

        def save():
            try:
                q = num(vars_["quota_maggiorata"])
                if not q or not vars_["book"].get().strip():
                    raise ValueError
                mid = "man-" + datetime.now().strftime("%Y%m%d%H%M%S")
                item = {"id": mid, "book": vars_["book"].get().strip(), "evento": vars_["evento"].get().strip(),
                        "data": "", "descrizione": vars_["descrizione"].get().strip(), "etichetta": "",
                        "quota_barrata": num(vars_["quota_barrata"]), "quota_maggiorata": q,
                        "max_bet": num(vars_["max_bet"]), "condizioni": [], "origine": "manuale",
                        "testo": f"{vars_['evento'].get()}\n{vars_['descrizione'].get()}",
                        "trovata_il": datetime.now().isoformat(timespec="seconds")}
                entry = {"aggiunta_manuale": item}
                f = vars_["fair"].get().replace(",", ".").strip()
                if "/" in f:
                    b, l = [float(x) for x in f.split("/", 1)]
                    entry.update({"back": b, "lay": l})
                elif f:
                    entry["fair"] = float(f)
            except ValueError:
                messagebox.showerror("Aggiungi", "Book e quota maggiorata sono obbligatori; i numeri vanno scritti come 2.35.",
                                     parent=win)
                return
            self._save_manual(mid, entry)
            win.destroy()
            self.run_ev()

        ttk.Button(win, text="Salva", command=save).grid(row=len(fields), column=1, sticky="e", padx=8, pady=8)

    def copy_post(self):
        sel = self._selected() or [r for r in self.rows if r.get("ev_plus")]
        if not sel:
            messagebox.showinfo("Post Telegram", "Nessuna maggiorata EV+ (o selezionata) da copiare.")
            return
        txt = "\n\n".join(EV.telegram_post(r) for r in sel if r.get("quota_maggiorata"))
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.status.set(f"Copiati {len(sel)} post negli appunti.")

    def open_report(self):
        if EV.REPORT_PATH.exists():
            webbrowser.open(EV.REPORT_PATH.resolve().as_uri())
        else:
            messagebox.showinfo("Report", "Nessun report: lancia prima il calcolo.")

    def estensione_info(self):
        msg = ("Sisal, Snai, PokerStars, bet365, Admiralbet ed Eplay24 rifiutano il browser automatico.\n"
               "Le loro maggiorate le legge l'estensione 'Lettore Maggiorate' nel tuo Chrome.\n\n"
               "Installazione (una volta):\n"
               "1. In Chrome apri chrome://extensions\n"
               "2. Attiva 'Modalita' sviluppatore' (in alto a destra)\n"
               "3. 'Carica estensione non pacchettizzata' e scegli la cartella:\n"
               f"   {PE.EXT_DIR}\n\n"
               "Uso: con questa app aperta, premi l'icona dell'estensione > 'Leggi Sisal, Snai e PokerStars'\n"
               "(si aprono e chiudono da sole 3 schede), oppure naviga su quei siti: legge da sola.\n\n"
               "Aprire ora la cartella dell'estensione?")
        if messagebox.askyesno("Estensione Chrome", msg):
            try:
                os.startfile(str(PE.EXT_DIR))  # Windows
            except AttributeError:
                webbrowser.open(PE.EXT_DIR.resolve().as_uri())

    def betfair_settings(self):
        cred = EV.load_json(EV.CRED_PATH, {})
        win = tk.Toplevel(self)
        win.title("Betfair Exchange (per la fair automatica)")
        win.transient(self)
        ttk.Label(win, text="Le credenziali restano solo in betfair_credenziali.json su questo PC\n"
                            "(escluso da git). App key: account Betfair > sviluppatori (va bene la 'delayed').",
                  foreground="#555").grid(row=0, column=0, columnspan=2, padx=8, pady=6, sticky="w")
        vals = {}
        for i, (lab, key, show) in enumerate([("App key", "app_key", ""), ("Username", "username", ""),
                                               ("Password", "password", "*")], start=1):
            ttk.Label(win, text=lab).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            v = tk.StringVar(value=cred.get(key, ""))
            ttk.Entry(win, textvariable=v, width=40, show=show).grid(row=i, column=1, padx=8)
            vals[key] = v

        def save():
            EV.CRED_PATH.write_text(json.dumps({k: v.get().strip() for k, v in vals.items()}, indent=2),
                                    encoding="utf-8")
            try:
                EV.SESSION_PATH.unlink()
            except OSError:
                pass
            win.destroy()
            self.status.set("Credenziali Betfair salvate.")

        ttk.Button(win, text="Salva", command=save).grid(row=4, column=1, sticky="e", padx=8, pady=8)


if __name__ == "__main__":
    App().mainloop()
