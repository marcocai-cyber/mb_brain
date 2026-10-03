const stato = document.getElementById("stato");

function scrivi(testo) {
  stato.textContent = testo;
}

document.getElementById("btnPagina").addEventListener("click", () => {
  scrivi("Lettura in corso (apro anche le pagine di dettaglio, ci vuole qualche secondo)...");
  chrome.runtime.sendMessage({ type: "LEGGI_PAGINA_CORRENTE" }, (r) => {
    if (!r || !r.ok) {
      scrivi(`Errore: ${r && r.errore ? r.errore : "sconosciuto"}`);
      return;
    }
    scrivi(`${r.book}: ${r.trovate} promo trovate, ${r.salvate} salvate, ${r.scadute || 0} scadute scartate`);
  });
});

document.getElementById("btnTutte").addEventListener("click", () => {
  scrivi("Apro e leggo i siti configurati...");
  chrome.runtime.sendMessage({ type: "LEGGI_TUTTE" }, (log) => {
    if (!log || !log.length) {
      scrivi("Nessun sito configurato (vedi Gestisci siti).");
      return;
    }
    const righe = log.map((v) =>
      v.ok ? `${v.book}: ${v.trovate} trovate, ${v.salvate} salvate, ${v.scadute || 0} scadute` : `${v.book}: ERRORE ${v.errore}`
    );
    scrivi(righe.join("\n"));
  });
});

document.getElementById("linkOpzioni").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
