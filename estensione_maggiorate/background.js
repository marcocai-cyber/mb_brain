// Lettore Maggiorate - background: riceve le card e le passa all'app locale.
const PONTE = "http://127.0.0.1:8765";

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
