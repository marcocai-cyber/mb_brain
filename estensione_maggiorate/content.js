// Lettore Maggiorate - legge le card nella pagina e le manda all'app tramite il background.
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
