#!/usr/bin/env python3
"""
riassunto_promo.py — riassunto per punti chiave delle promozioni (solo regex)
=============================================================================
Usato da scraper_promozioni.py e da ponte_promozioni.py (estensione Chrome),
cosi' entrambi producono lo stesso formato.

Punti estratti (un punto compare solo se trovato nel testo):
  - Attivazione        promo da attivare / codice promo
  - Qualificante       deposito minimo o giocato qualificante
  - Requisito giocata  quota min evento / quota min totale / n. eventi / slot
  - Bonus              tipologia e ammontare
  - Dove spenderlo     dove si usa il bonus
  - Rollover / cap     requisito di puntata e massimo convertibile
  - Real bonus         conversione/accredito in real bonus e spendibilita'
  - Scadenze           fine promo, durata del bonus, termini per i requisiti

E' un'estrazione euristica: copre le formulazioni piu' comuni dei book ADM,
ma frasi scritte in modo insolito possono sfuggire. Il testo completo resta
sul sito (campo url).
"""

import re
from datetime import date

# ---------------------------------------------------------------- utilita'

NUM = r"\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
EURO = r"\s*(?:€|eur\b|euro\b)"
QUOTA = r"\d{1,2}[.,]\d{1,2}"

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
GIORNI_SETT = r"(?:luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)"


def _num(s):
    """'1.000' -> 1000.0 ; '12,50' -> 12.5 ; '2.00' -> 2.0"""
    s = s.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_euro(v):
    if v is None:
        return ""
    return f"{int(v)}€" if float(v).is_integer() else f"{v:.2f}€".replace(".", ",")


def _fmt_quota(s):
    return s.replace(",", ".")


def _pulisci(testo):
    testo = re.sub(r"\s+", " ", testo or "").strip()
    return testo


def _frasi(testo):
    """Spezza in frasi senza rompere numeri tipo 1.50 o 5.000€."""
    parti = re.split(r"(?<=[.;!?])\s+(?=[A-ZÀ-Ý•\-])|\s*[•▪●]\s*|\n+", testo)
    return [p.strip(" -–") for p in parti if p and len(p.strip()) > 3]


def _accorcia(s, n=110):
    s = s.strip(" .,;:")
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------- date

_RE_DATA_NUM = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?\b")
_RE_DATA_TXT = re.compile(
    r"\b(\d{1,2})(?:°|º)?\s+(" + "|".join(MESI) + r")(?:\s+(\d{4}))?\b", re.IGNORECASE)

# cio' che precede una data di FINE promo
_RE_MARCATORE_FINE = re.compile(
    r"(fino\s+al?l?['’]?|fino\s+a|entro\s+(?:e\s+non\s+oltre\s+)?(?:il|l['’])?|"
    r"scade\w*(?:\s+il)?|scadenza(?:\s+il)?|termin\w*(?:\s+il)?|valid\w*\s+fino\s+al?l?['’]?|"
    r"\bal|\ball['’]|\s-)\s*(?:" + GIORNI_SETT + r"\s+)?$",
    re.IGNORECASE)


def _costruisci_data(g, m, a, oggi):
    try:
        g, m = int(g), int(m)
        if a:
            a = int(a)
            if a < 100:
                a += 2000
            return date(a, m, g)
        d = date(oggi.year, m, g)
        # senza anno: se e' "molto" nel passato si riferisce all'anno prossimo
        if (oggi - d).days > 180:
            d = date(oggi.year + 1, m, g)
        return d
    except (ValueError, TypeError):
        return None


def trova_date_fine(testo, oggi=None):
    """Date precedute da un marcatore di fine (fino al, entro il, dal X al Y...)."""
    oggi = oggi or date.today()
    trovate = []
    for rx, testuale in ((_RE_DATA_NUM, False), (_RE_DATA_TXT, True)):
        for m in rx.finditer(testo):
            prima = testo[max(0, m.start() - 35): m.start()]
            if not _RE_MARCATORE_FINE.search(prima):
                continue
            if testuale:
                d = _costruisci_data(m.group(1), MESI[m.group(2).lower()], m.group(3), oggi)
            else:
                # evita orari (23.59) e quote (1.50): serve giorno<=31 e mese<=12
                if not m.group(3) and "." in m.group(0):
                    continue
                d = _costruisci_data(m.group(1), m.group(2), m.group(3), oggi)
            if d and 2020 <= d.year <= oggi.year + 2:
                trovate.append(d)
    return trovate


def scadenza_promo(testo, oggi=None):
    """Ultima data di fine trovata (ISO), o '' se non c'e'."""
    date_fine = trova_date_fine(_pulisci(testo), oggi)
    return max(date_fine).isoformat() if date_fine else ""


_RE_TERMINATA = re.compile(
    r"\b(?:promo(?:zione)?|offerta|iniziativa)\s+(?:e['’]\s+|è\s+)?(?:terminata|conclusa|scaduta)\b",
    re.IGNORECASE)


def e_scaduta(deadline_iso, testo="", oggi=None):
    oggi = oggi or date.today()
    if testo and _RE_TERMINATA.search(testo):
        return True
    if not deadline_iso:
        return False
    try:
        return date.fromisoformat(deadline_iso) < oggi
    except ValueError:
        return False


# ---------------------------------------------------------------- singoli punti

def punto_attivazione(testo):
    codice = re.search(
        r"(?i:codice\s+(?:promo(?:zionale)?|bonus|voucher)?)\s*[:\"“'‘]?\s*([A-Z0-9]{3,15})\b", testo)
    serve = re.search(
        r"\b(?:attiva(?:re|rla|zione)?\s+(?:la\s+)?(?:promo|promozione|offerta|bonus)|"
        r"aderi(?:re|sci)|opt[\s-]?in|clicca\s+(?:su\s+)?[\"“']?(?:partecipa|attiva|aderisci|accetta)|"
        r"seleziona(?:re)?\s+(?:la\s+voce|il\s+bonus|la\s+promo)|accetta(?:re)?\s+(?:la\s+)?(?:promo|promozione|offerta))",
        testo, re.IGNORECASE)
    if codice and codice.group(1).upper() not in ("ADM", "AAMS", "SPID", "PDF"):
        return f"necessaria, codice {codice.group(1)}"
    if serve:
        return "necessaria (opt-in sul sito)"
    return ""


def punto_qualificante(testo):
    parti = []
    dep = re.search(
        r"(?:deposit\w*|ricaric\w*|versament\w*)[^.;]{0,50}?(?:minim\w*\s+(?:di\s+)?|almeno\s+|di\s+)?(" + NUM + r")" + EURO,
        testo, re.IGNORECASE)
    if dep:
        parti.append(f"deposito min. {_fmt_euro(_num(dep.group(1)))}")
    gioc = re.search(
        r"(?:gioca(?:re|ndo|to)?|punta(?:re|ndo|to)?|scommett\w*|volume\s+di\s+gioco|giocat\w*)"
        r"[^.;]{0,45}?(?:almeno|minim\w*|totale\s+di|complessiv\w*\s+di|pari\s+a)\s+(" + NUM + r")" + EURO,
        testo, re.IGNORECASE)
    if not gioc:
        gioc = re.search(r"\b(?:gioca|punta|scommetti)\s+(?:almeno\s+)?(" + NUM + r")" + EURO, testo, re.IGNORECASE)
    if gioc:
        parti.append(f"giocato min. {_fmt_euro(_num(gioc.group(1)))}")
    return " · ".join(parti)


def punto_requisito(testo, slots=None):
    parti = []
    n_ev = re.search(r"(?:almeno|minimo|min\.?|con)\s+(\d{1,2})\s+(?:eventi|selezioni|esiti)", testo, re.IGNORECASE)
    if n_ev:
        parti.append(f"min {n_ev.group(1)} eventi")
    q_ev = (re.search(r"quota\s+(?:minima\s+)?(?:di\s+)?(?:per\s+)?(?:ogni|ciascun\w*|singol\w*)\s+(?:evento|selezione|esito)"
                      r"[^0-9]{0,20}(" + QUOTA + r")", testo, re.IGNORECASE)
            or re.search(r"(" + QUOTA + r")\s+(?:per|a|su)\s+(?:ogni|ciascun\w*)\s+(?:evento|selezione|esito)", testo, re.IGNORECASE)
            or re.search(r"(?:evento|selezione|esito)\s+(?:con\s+)?quota\s+(?:minima\s+)?(?:di\s+|pari\s+a\s+)?(" + QUOTA + r")", testo, re.IGNORECASE))
    if q_ev:
        parti.append(f"quota min evento {_fmt_quota(q_ev.group(1))}")
    q_tot = re.search(
        r"(?:quota\s+(?:totale|complessiva)\s+(?:minima\s+)?|quota\s+minima\s+(?:totale|complessiva)\s+|"
        r"moltiplicatore\s+(?:totale\s+)?(?:minimo\s+)?)(?:di\s+|pari\s+a\s+|a\s+)?(" + QUOTA + r")",
        testo, re.IGNORECASE)
    if q_tot:
        parti.append(f"quota min totale {_fmt_quota(q_tot.group(1))}")
    elif not q_ev:
        q_gen = re.search(r"quota\s+minima\s+(?:di\s+|pari\s+a\s+|a\s+)?(" + QUOTA + r")", testo, re.IGNORECASE)
        if q_gen:
            parti.append(f"quota min {_fmt_quota(q_gen.group(1))}")
    if re.search(r"\bsolo\s+(?:scommesse\s+)?singol\w*|\bin\s+singola\b|\bscommess\w*\s+singol\w*", testo, re.IGNORECASE):
        parti.append("singola")
    elif re.search(r"\bscommess\w*\s+multipl\w*|\bmultipl\w*\b", testo, re.IGNORECASE) and n_ev:
        parti.append("multipla")
    if slots:
        parti.append("slot: " + ", ".join(slots[:5]) + ("…" if len(slots) > 5 else ""))
    else:
        prov = re.search(r"slot\s+(?:del\s+provider\s+|di\s+)?(Pragmatic Play|NetEnt|Play'?n ?GO|Endorphina|Novomatic|"
                         r"Playtech|Microgaming|Red Tiger|Push Gaming|Nolimit City|Hacksaw|Relax Gaming|Capecod|Spike|Bally Wulff)",
                         testo, re.IGNORECASE)
        if prov:
            parti.append(f"slot {prov.group(1)}")
        elif re.search(r"\btutte\s+le\s+slot\b", testo, re.IGNORECASE):
            parti.append("tutte le slot")
    return " · ".join(parti)


_TIPI_BONUS = [
    (r"free\s?bet|scommess\w*\s+gratuit\w*", "Free bet"),
    (r"fun\s?bonus", "Fun bonus"),
    (r"real\s?bonus", "Real bonus"),
    (r"bonus\s+cash|cash\s+bonus|saldo\s+reale|denaro\s+reale|prelevabil\w+", "Saldo reale"),
    (r"free\s?spin\w*|giri\s+gratis|giri\s+gratuiti", "Free spin"),
    (r"cash\s?back|rimborso", "Cashback"),
    (r"quota\s+maggiorat\w*|super\s?quota|quota\s+potenziat\w*", "Quota maggiorata"),
    (r"bonus\s+multipla", "Bonus multipla"),
]


def punto_bonus(testo):
    """Ritorna (testo_punto, importo_max_euro_o_None)."""
    tipo = ""
    for rx, nome in _TIPI_BONUS:
        if re.search(rx, testo, re.IGNORECASE):
            tipo = nome
            break
    importo = None
    descr = ""
    perc = re.search(r"(\d{1,3})\s*%[^.;]{0,40}?(?:fino\s+(?:a|ad)\s+(?:un\s+massimo\s+di\s+)?|max\.?\s*)(" + NUM + r")" + EURO,
                     testo, re.IGNORECASE)
    spin = re.search(r"(\d{1,4})\s+(?:free\s?spin\w*|giri\s+gratis|giri\s+gratuiti)", testo, re.IGNORECASE)
    fisso = re.search(r"(" + NUM + r")" + EURO + r"\s+(?:di|in)\s+(?:bonus|free\s?bet|real\s?bonus|fun\s?bonus|cashback)",
                      testo, re.IGNORECASE)
    tipo_di = re.search(r"(?:free\s?bet|real\s?bonus|fun\s?bonus|bonus|cashback)\s+(?:di|da)\s+(" + NUM + r")" + EURO,
                        testo, re.IGNORECASE)
    fino = re.search(r"(?:bonus|free\s?bet|cashback|rimborso)[^.;]{0,30}?fino\s+(?:a|ad)\s+(" + NUM + r")" + EURO,
                     testo, re.IGNORECASE)
    if perc:
        importo = _num(perc.group(2))
        descr = f"{perc.group(1)}% fino a {_fmt_euro(importo)}"
    elif fisso:
        importo = _num(fisso.group(1))
        descr = _fmt_euro(importo)
    elif tipo_di:
        importo = _num(tipo_di.group(1))
        descr = _fmt_euro(importo)
    elif fino:
        importo = _num(fino.group(1))
        descr = f"fino a {_fmt_euro(importo)}"
    if spin:
        descr = (descr + " + " if descr else "") + f"{spin.group(1)} free spin"
        if tipo == "Free spin" and not importo:
            tipo = "Free spin"
    if not tipo and not descr:
        return "", None
    return " ".join(x for x in (tipo, descr) if x), importo


_DOVE = [
    (r"scommess\w*\s+sportiv\w*|\bsport\b|scommess\w*\s+(?:pre-?match|live|multipl\w*|singol\w*)", "scommesse sport"),
    (r"\bslot\b", "slot"),
    (r"casin[oò]\s+live|live\s+casin[oò]", "casinò live"),
    (r"\bcasin[oò]\b", "casinò"),
    (r"\bvirtual\w*", "virtual"),
    (r"\bbingo\b", "bingo"),
    (r"\bpoker\b", "poker"),
    (r"\bippic\w*", "ippica"),
]


def punto_dove(testo):
    m = re.search(
        r"(?:spendibil\w*|utilizzabil\w*|da\s+(?:usare|utilizzare|giocare|spendere)|giocabil\w*|valid\w*\s+(?:solo\s+)?(?:su|per)|"
        r"(?:potr\w+|puoi)\s+(?:usar\w*|utilizzar\w*|giocar\w*|spender\w*))"
        r"\s*(?:esclusivamente\s+|solo\s+|unicamente\s+)?(?:su|sul|sulle|sui|sugli|per|nella|nel|nelle|in)?\s+([^.;]{3,90})",
        testo, re.IGNORECASE)
    if not m:
        return ""
    frammento = m.group(1)
    trovati = [nome for rx, nome in _DOVE if re.search(rx, frammento, re.IGNORECASE)]
    if trovati:
        uniq = list(dict.fromkeys(trovati))
        if "casinò live" in uniq and "casinò" in uniq:
            uniq.remove("casinò")
        extra = re.search(r"\b(?:escluse?|tranne|ad\s+eccezione\s+di)\s+([^.;]{3,50})", frammento, re.IGNORECASE)
        return ", ".join(uniq) + (f" (escluse {_accorcia(extra.group(1), 50)})" if extra else "")
    return _accorcia(frammento, 70)


MAX_CAP_MARKERS = [
    "massimo convertibile", "massimo prelevabile", "vincita massima convertibile",
    "importo massimo prelevabile", "max cap", "cap massimo", "prelievo massimo",
    "vincita massima", "convertibile fino a", "conversione massima", "massimo convertibile in",
]


def estrai_max_cap(testo):
    low = testo.lower()
    for marker in MAX_CAP_MARKERS:
        idx = low.find(marker)
        if idx == -1:
            continue
        m = re.search(r"(" + NUM + r")" + EURO, testo[idx: idx + 70], re.IGNORECASE)
        if m:
            return _num(m.group(1))
    return None


def estrai_rollover(testo):
    """Ritorna il moltiplicatore (int) o None."""
    m = (re.search(r"(?:requisit\w*\s+di\s+(?:puntata|giocata|rigioco|gioco)|rollover|wagering|rigiocat\w*|"
                   r"rigiocar\w*|giocat\w*)[^.;]{0,40}?\b(\d{1,3})\s*(?:x\b|volte)", testo, re.IGNORECASE)
         or re.search(r"\b(\d{1,3})\s*(?:x|volte)\s+(?:l['’]importo|il\s+(?:valore|bonus|deposito)|la\s+somma)", testo, re.IGNORECASE))
    if m:
        return int(m.group(1))
    if re.search(r"rigioca\w*\s+(?:una\s+sola\s+volta|1\s+volta|una\s+volta)", testo, re.IGNORECASE):
        return 1
    return None


def punto_rollover_cap(testo):
    parti = []
    roll = estrai_rollover(testo)
    if roll:
        parti.append(f"rollover {roll}x")
    cap = estrai_max_cap(testo)
    if cap:
        parti.append(f"max cap {_fmt_euro(cap)}")
    return " · ".join(parti), roll, cap


def punto_real_bonus(frasi):
    """Frase su accredito/conversione in real bonus e sua spendibilita'."""
    pezzi = []
    for f in frasi:
        if not re.search(r"real\s?bonus", f, re.IGNORECASE):
            continue
        if not re.search(r"accredit|convert|trasform|ricev|spendibil|utilizzabil|rigioc|quota|moltiplicatore|prelevabil|vincit",
                         f, re.IGNORECASE):
            continue
        pezzi.append(_accorcia(f, 120))
        if len(pezzi) == 2:
            break
    return " / ".join(pezzi)


def punto_scadenze(testo, deadline_iso):
    parti = []
    if deadline_iso:
        a, m, g = deadline_iso.split("-")
        parti.append(f"promo fino al {g}/{m}/{a}")
    visti = set()
    for m in re.finditer(r"(?:entro|per|in|valid\w*(?:\s+per)?|disposizione)\s+(\d{1,3})\s*(giorni|gg|ore|h)\b", testo, re.IGNORECASE):
        prima = testo[max(0, m.start() - 160): m.start(1)]
        prima = re.split(r"[.;!?]\s+(?=[A-ZÀ-Ý])", prima)[-1].lower()
        n, unita = m.group(1), m.group(2).lower()
        unita = "giorni" if unita in ("giorni", "gg") else "ore"
        categorie = [
            (r"accredit|ricev|erogat", f"accredito entro {n} {unita}"),
            (r"rigioc|rollover|requisit|wagering", f"requisito da completare in {n} {unita}"),
            (r"deposit|ricaric|registraz", f"deposito entro {n} {unita}"),
            (r"utilizz|spend|usar|valid|scad|giocabil", f"bonus valido {n} {unita}"),
        ]
        etichetta, pos_max = f"entro {n} {unita}", -1
        for rx, lab in categorie:
            for k in re.finditer(rx, prima):
                if k.start() > pos_max:
                    pos_max, etichetta = k.start(), lab
        if etichetta not in visti:
            visti.add(etichetta)
            parti.append(etichetta)
        if len(parti) >= 4:
            break
    return " · ".join(parti)


# ---------------------------------------------------------------- slot

SLOT_LIST_MARKERS = [
    "slot idonee", "slot partecipanti", "giochi partecipanti", "giochi idonei",
    "slot valide", "giochi validi", "slot selezionate", "slot incluse",
]


def estrai_slot(testo, massimo=8):
    low = testo.lower()
    trovati = []
    for marker in SLOT_LIST_MARKERS:
        idx = low.find(marker)
        if idx == -1:
            continue
        sezione = testo[idx + len(marker): idx + len(marker) + 600]
        sezione = re.split(r"\brequisito\b|\bvalido fino\b|\bwagering\b|\bmassima\b|\bmassimo\b|\bminima\b|"
                           r"\bminimo\b|\bconvertibil\w*\b|\bvincita\b", sezione, flags=re.IGNORECASE)[0]
        for p in re.split(r"[,;•\n.]| e (?=[A-Z])", sezione):
            nome = p.strip(" .:-–—")
            if 3 <= len(nome) <= 40 and not nome.lower().startswith(("entro", "requisito", "il bonus")):
                trovati.append(nome)
    return list(dict.fromkeys(trovati))[:massimo]


# ---------------------------------------------------------------- funzione principale

def riassumi(testo, oggi=None):
    """Analizza il testo grezzo di una promo.

    Ritorna un dict con:
      note      testo del riassunto (una riga per punto trovato, "• Punto: valore")
      deadline  data fine promo ISO o ''
      scaduta   True/False
      wager     es. '35x' o ''
      value     importo bonus in € (float) o None
      max_cap   float o None
      slots     lista nomi slot
    """
    testo = _pulisci(testo)
    frasi = _frasi(testo)
    deadline = scadenza_promo(testo, oggi)
    slots = estrai_slot(testo)

    bonus_txt, importo = punto_bonus(testo)
    rc_txt, roll, cap = punto_rollover_cap(testo)

    punti = [
        ("Attivazione", punto_attivazione(testo)),
        ("Qualificante", punto_qualificante(testo)),
        ("Requisito giocata", punto_requisito(testo, slots)),
        ("Bonus", bonus_txt),
        ("Dove spenderlo", punto_dove(testo)),
        ("Rollover / cap", rc_txt),
        ("Real bonus", punto_real_bonus(frasi)),
        ("Scadenze", punto_scadenze(testo, deadline)),
    ]
    note = "\n".join(f"• {k}: {v}" for k, v in punti if v)
    return {
        "note": note,
        "deadline": deadline,
        "scaduta": e_scaduta(deadline, testo, oggi),
        "wager": f"{roll}x" if roll else "",
        "value": importo,
        "max_cap": cap,
        "slots": slots,
    }


def rimuovi_scadute(offerte, oggi=None):
    """Toglie da una lista di offerte (formato promozioni.json) quelle scadute."""
    tenute, tolte = [], 0
    for o in offerte:
        if e_scaduta(o.get("deadline", ""), "", oggi):
            tolte += 1
        else:
            tenute.append(o)
    return tenute, tolte
