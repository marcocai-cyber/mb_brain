@echo off
setlocal

REM Avvia il bridge locale per l'estensione "Lettore Promozioni".
REM Tienilo aperto finche' usi l'estensione in Chrome; chiudilo (o Ctrl+C)
REM quando hai finito, non serve lasciarlo sempre acceso.

cd /d "%~dp0"

echo ===============================================
echo   Bridge estensione Lettore Promozioni (porta 8766)
echo ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRORE] Python non trovato nel PATH.
    echo Installa Python da https://www.python.org/downloads/ e riprova.
    echo.
    pause
    exit /b 1
)

if not exist ponte_promozioni.py (
    echo [ERRORE] Non trovo ponte_promozioni.py in questa cartella:
    echo   %cd%
    echo.
    pause
    exit /b 1
)

python ponte_promozioni.py

echo.
echo Bridge fermato.
pause
