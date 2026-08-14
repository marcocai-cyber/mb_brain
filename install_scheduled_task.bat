@echo off
REM Registra il task in Windows Task Scheduler: esegue run_scraper.bat
REM ogni 30 minuti, dalle 9:00 alle 22:00, tutti i giorni.
REM Va lanciato una sola volta (doppio click), da questa stessa cartella.

setlocal
set "FOLDER=%~dp0"
if "%FOLDER:~-1%"=="\" set "FOLDER=%FOLDER:~0,-1%"

echo Cartella rilevata: %FOLDER%

REM Sostituisce il segnaposto __SCRAPER_FOLDER__ nell'XML con il percorso reale.
REM Il file va scritto in UTF-16 (Unicode): schtasks /create /xml non legge
REM correttamente l'UTF-8, anche se dichiarato nell'intestazione XML.
powershell -NoProfile -Command ^
  "(Get-Content -Raw -Encoding UTF8 'ScraperTask.xml') -replace '__SCRAPER_FOLDER__', '%FOLDER%' -replace 'encoding=\"UTF-8\"', 'encoding=\"UTF-16\"' | Set-Content -Encoding Unicode 'ScraperTask_ready.xml'"

if not exist "ScraperTask_ready.xml" (
  echo Errore: generazione del file XML fallita.
  pause
  exit /b 1
)

schtasks /create /tn "MatchBettingScraper" /xml "ScraperTask_ready.xml" /f

if %errorlevel%==0 (
  echo.
  echo Fatto! Il task "MatchBettingScraper" e' stato registrato.
  echo Girera' ogni 30 minuti dalle 9:00 alle 22:00, tutti i giorni,
  echo anche a schermo bloccato ^(basta che il PC sia acceso e tu sia collegato^).
  echo.
  echo Per verificarlo: apri "Utilita' di pianificazione" di Windows e cerca "MatchBettingScraper".
  echo Per disattivarlo: esegui disinstalla_scheduled_task.bat oppure eliminalo da li'.
) else (
  echo.
  echo Qualcosa e' andato storto nella registrazione del task.
)

pause
