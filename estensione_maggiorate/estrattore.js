// Generato da ponte_estensione.py: stesso estrattore di scraper_maggiorate.py
window.__estraiMaggiorate = (opts) => {
  opts = opts || {};
  const ODD = /^\s*\d{1,4}[.,]\d{1,3}\s*$/;
  const ODDG = /(?<![\d.,])\d{1,4}[.,]\d{2}(?![\d])/g;
  const KW = new RegExp(opts.keyword || "maggiorat|super\\s?quot|boost|quota\\s?top|potenziat", "i");
  const MAXLEN = opts.maxLen || 600;
  const GR = opts.mode === 'list' ? /(segnano tutt|segneranno tutt|tutti segnano|tutte over|tutte goal|vincono tutt|vinceranno tutt|all teams winners|tutti marcatori)/i : null;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden' && (r.width > 0 || r.height > 0); };
  const isStruck = el => { for (let e = el, i = 0; e && i < 3; e = e.parentElement, i++) { const t = getComputedStyle(e).textDecorationLine || ''; if (t.includes('line-through') || ['S', 'DEL', 'STRIKE'].includes(e.tagName)) return true; } return false; };
  const ownText = el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const cards = new Map();
  const leafText = (node) => {
    const out = [];
    const walk = (n) => {
      for (const ch of n.childNodes) {
        if (ch.nodeType === 3) { const t = ch.textContent.trim(); if (t) out.push(t); }
        else if (ch.nodeType === 1) {
          const s = getComputedStyle(ch);
          if (s.display === 'none' || s.visibility === 'hidden') continue;
          if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(ch.tagName)) continue;
          walk(ch.shadowRoot || ch);
        }
      }
    };
    walk(node);
    return out.join('\n');
  };
  const climb = (el, why) => {
    let c = el, best = null, bestN = 0;
    for (let i = 0; c && i < 16; c = c.parentElement, i++) {
      if ((c.textContent || '').length > MAXLEN * 4) break;
      const t = leafText(c);
      if (t.length > MAXLEN) break;
      const n = (t.match(ODDG) || []).length;
      const lines = t.split('\n').length;
      if (best && (n > 4 || lines > 16)) break;
      if (best && n > bestN && (bestN >= 2 || why === 'lista')) break;
      if (n >= 1 && t.length >= 20 && /[a-zà-ù]{3}/i.test(t)) { best = c; bestN = n; }
    }
    if (best) {
      if (!cards.has(best)) cards.set(best, { why: why, text: leafText(best), cls: String(best.className || '').slice(0, 80), struck: [] });
      else if (why === 'barrata') cards.get(best).why = 'barrata';
    }
    return best;
  };
  const root = opts.root ? (document.querySelector(opts.root) || document.body) : document.body;
  const allEls = (r, out) => { for (const e of r.querySelectorAll('*')) { out.push(e); if (e.shadowRoot) allEls(e.shadowRoot, out); } return out; };
  for (const el of allEls(root, [])) {
    if (el.children.length > 2) continue;
    const ot = ownText(el) || (el.children.length === 0 ? (el.textContent || '').trim() : '');
    if (!ot || ot.length > 80) continue;
    if (ODD.test(ot)) {
      if (!vis(el)) continue;
      if (isStruck(el)) { const c = climb(el, 'barrata'); if (c) cards.get(c).struck.push(ot.trim()); }
      else if (opts.mode === 'list') climb(el, 'lista');
    }
    else if (GR && GR.test(ot) && vis(el)) { if (!cards.has(el)) cards.set(el, { why: 'gruppo', text: ot, cls: '', struck: [] }); }
    else if (KW.test(ot) && vis(el)) climb(el, 'keyword');
  }
  const arr = Array.from(cards.entries());
  // tieni solo le card piu' interne (scarta i contenitori che includono altre card);
  // le intestazioni di gruppo restano sempre, nell'ordine della pagina
  const kept = arr.filter(([el, v]) => v.why === 'gruppo' || !arr.some(([o, ov]) => ov.why !== 'gruppo' && o !== el && el.contains(o)));
  kept.sort((x, y) => (x[0].compareDocumentPosition(y[0]) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return kept.map(([el, v]) => v);
};
