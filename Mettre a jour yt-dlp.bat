@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Mise a jour de yt-dlp (a faire si des videos YouTube echouent soudainement)...
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]" || (
    echo Echec de la mise a jour.
    pause
    exit /b 1
)
echo Termine.
pause
