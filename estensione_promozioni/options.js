const tbody = document.querySelector("#tabellaSiti tbody");
const kwBox = document.getElementById("keywords");
const msg = document.getElementById("msg");

function mostraMsg(t) {
  msg.textContent = t;
  setTimeout(() => (msg.textContent = ""), 3000);
}

function carica() {
  chrome.storage.local.get(["siti", "keywords"], (cfg) => {
    tbody.innerHTML = "";
    (cfg.siti || []).forEach((s) => {
      const tr = document.createElement("tr");
      const tdBook = document.createElement("td");
      const tdDominio = document.createElement("td");
      const tdUrl = document.createElement("td");
      tdBook.textContent = s.book;
      tdDominio.textContent = s.domain;
      tdUrl.textContent = s.url || "";
      tr.append(tdBook, tdDominio, tdUrl);
      tbody.appendChild(tr);
    });
    kwBox.value = (cfg.keywords || []).join("\n");
  });
}

document.getElementById("btnAggiungi").addEventListener("click", () => {
  const book = document.getElementById("nuovoBook").value.trim();
  const domain = document
    .getElementById("nuovoDominio")
    .value.trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "");
  const url = document.getElementById("nuovoUrl").value.trim();
  if (!book || !domain) {
    mostraMsg("Inserisci almeno nome book e dominio.");
    return;
  }
  chrome.runtime.sendMessage({ type: "AGGIUNGI_DOMINIO", book, domain, url }, (r) => {
    if (r && r.ok) {
      mostraMsg(`${book} aggiunto.`);
      document.getElementById("nuovoBook").value = "";
      document.getElementById("nuovoDominio").value = "";
      document.getElementById("nuovoUrl").value = "";
      carica();
    } else {
      mostraMsg(`Non aggiunto: ${r && r.errore ? r.errore : "permesso negato"}`);
    }
  });
});

document.getElementById("btnSalvaKeywords").addEventListener("click", () => {
  const keywords = kwBox.value
    .split("\n")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  chrome.storage.local.set({ keywords }, () => mostraMsg("Parole chiave salvate."));
});

carica();
