@echo off
REM Pubblica le modifiche locali su GitHub Pages (mb_brain).
REM Va lanciato da questo PC (io non ho accesso alle tue credenziali GitHub,
REM quindi il push deve partire sempre da qui). Basta un doppio click.

cd /d "%~dp0"

echo ==============================================
echo Pubblicazione MatchBetting Assistant
echo ==============================================
echo.

git add -A

set /p MSG="Messaggio del commit (invio per usare quello di default): "
if "%MSG%"=="" set MSG=Aggiornamento del %date% %time%

git commit -m "%MSG%"
if errorlevel 1 (
    echo.
    echo Nessuna modifica da salvare, oppure il commit e' fallito: vedi sopra.
)

echo.
echo Invio a GitHub in corso...
git push

echo.
if errorlevel 1 (
    echo ==============================================
    echo Qualcosa e' andato storto nel push. Controlla il messaggio sopra
    echo ^(es. serve un nuovo login GitHub, o mancano modifiche da inviare^).
    echo ==============================================
) else (
    echo ==============================================
    echo Fatto! Le modifiche sono online. Puo' volerci qualche minuto prima
    echo che GitHub Pages le mostri: se non le vedi, ricarica con un
    echo refresh forzato o in una scheda in incognito.
    echo ==============================================
)

echo.
pause
