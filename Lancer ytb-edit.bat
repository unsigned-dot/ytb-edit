@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo ytb-edit n'est pas encore installe : lancez d'abord installer.bat
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m ytb_edit
