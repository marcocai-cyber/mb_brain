@echo off
REM Avvia il programmino Maggiorate EV+ (lettura maggiorate + calcolo EV).
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw maggiorate_app.py
) else (
    python maggiorate_app.py
)
