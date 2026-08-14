@echo off
REM Wrapper eseguito da Task Scheduler. Gira lo scraper e tiene un log.
REM %~dp0 = cartella in cui si trova questo file, cosi' funziona ovunque tu lo sposti.

cd /d "%~dp0"

REM Piccola attesa casuale (0-4 minuti) prima di partire: evita che le
REM richieste arrivino sempre esattamente allo stesso secondo ogni 30 min.
powershell -NoProfile -Command "Start-Sleep -Seconds (Get-Random -Minimum 0 -Maximum 240)"

echo ============================================== >> scraper_log.txt
echo Esecuzione: %date% %time% >> scraper_log.txt

python scraper_promozioni.py >> scraper_log.txt 2>&1

echo Fine esecuzione: %date% %time% >> scraper_log.txt
