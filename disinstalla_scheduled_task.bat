@echo off
REM Rimuove il task pianificato "MatchBettingScraper" da Windows Task Scheduler.
schtasks /delete /tn "MatchBettingScraper" /f
echo.
echo Task rimosso ^(se esisteva^).
pause
