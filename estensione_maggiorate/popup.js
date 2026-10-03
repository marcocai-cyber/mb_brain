const $ = (id) => document.getElementById(id);
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
