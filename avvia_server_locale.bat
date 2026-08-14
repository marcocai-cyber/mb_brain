@echo off
REM Avvia un piccolo server web locale per rendere l'app MatchBetting
REM raggiungibile da smartphone/tablet sulla stessa rete Wi-Fi del PC.
REM Lascia questa finestra aperta (va bene minimizzata) finche' la usi dal
REM telefono: se la chiudi, il telefono non riuscira' piu' ad aprire l'app.

cd /d "%~dp0"

echo ============================================================
echo  Indirizzo/i IP di questo PC sulla rete locale:
echo ============================================================
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do echo   %%a
echo ============================================================
echo.
echo  Dal telefono, connesso alla STESSA rete Wi-Fi di questo PC, apri il
echo  browser e vai su (sostituisci con l'indirizzo IP mostrato sopra,
echo  di solito quello che inizia con 192.168. o 10.):
echo.
echo      http://INDIRIZZO-IP-QUI-SOPRA:8000/MatchBetting_Assistant.html
echo.
echo  Alla primissima esecuzione, Windows potrebbe chiedere il permesso di
echo  accesso alla rete per Python: scegli "Consenti l'accesso" (rete privata).
echo ============================================================
echo.
echo Premi CTRL+C per fermare il server quando hai finito.
echo.

python -m http.server 8000
