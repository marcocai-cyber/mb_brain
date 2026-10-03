@echo off
setlocal

REM Lancia manualmente lo scraper_promozioni.py con un doppio click.
REM A differenza di run_scraper.bat (pensato per il Task Scheduler, silenzioso
REM e con log su file) questo mostra l'output a schermo e resta aperto alla fine.

cd /d "%~dp0"

echo ===============================================
echo   Lettura promozioni bookmaker ADM
echo ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRORE] Python non trovato nel PATH.
    echo Installa Python da https://www.python.org/downloads/ e assicurati
    echo di spuntare "Add python.exe to PATH" durante l'installazione.
    echo.
    pause
    exit /b 1
)

if not exist scraper_promozioni.py (
    echo [ERRORE] Non trovo scraper_promozioni.py in questa cartella:
    echo   %cd%
    echo Sposta questo file nella stessa cartella dello scraper e riprova.
    echo.
    pause
    exit /b 1
)

echo Avvio dello scraper... puo' richiedere qualche minuto
echo (legge 4 siti alla volta, con ritardi casuali anti-blocco).
echo.

python scraper_promozioni.py

echo.
echo ===============================================
if exist promozioni.json (
    echo Fatto. Risultati salvati in promozioni.json
    echo Apri MatchBetting_Assistant.html, tab Offerte ^> "Importa da file"
    echo e seleziona promozioni.json per caricarle nell'app.
) else (
    echo Attenzione: non trovo promozioni.json nella cartella.
    echo Controlla gli errori stampati sopra prima di riprovare.
)
echo ===============================================
echo.
pause
