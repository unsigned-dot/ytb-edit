@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Installation de ytb-edit

echo ============================================
echo   Installation de ytb-edit
echo ============================================
echo.

rem --- 1. Python (3.13, 3.12 ou 3.11 de preference) -------------------------
set "PY="
for %%V in (3.13 3.12 3.11) do (
    if not defined PY (
        py -%%V -c "pass" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERREUR] Python 3.11, 3.12 ou 3.13 est introuvable.
    echo Installez-le avec :  winget install Python.Python.3.12
    echo puis relancez ce script.
    goto :fail
)
echo [OK] Python : %PY%

rem --- 2. Environnement virtuel + dependances ---------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement Python...
    %PY% -m venv .venv || goto :fail
)
echo Installation des dependances (quelques minutes la premiere fois)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade -e . --quiet || goto :fail
echo [OK] Dependances installees
echo.

rem --- 3. FFmpeg ---------------------------------------------------------------
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [!] FFmpeg est introuvable : il est indispensable pour la decoupe.
    choice /c ON /m "Installer FFmpeg maintenant avec winget (O = oui, N = non)"
    if not errorlevel 2 winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
) else (
    echo [OK] FFmpeg trouve
)

rem --- 4. Deno (moteur JavaScript utilise par yt-dlp pour YouTube) -------------
where deno >nul 2>&1
if errorlevel 1 (
    echo [!] Deno est introuvable : recommande pour que YouTube fonctionne correctement.
    choice /c ON /m "Installer Deno maintenant avec winget (O = oui, N = non)"
    if not errorlevel 2 winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements
) else (
    echo [OK] Deno trouve
)

echo.
echo ============================================
echo   Installation terminee.
echo   Lancez l'application avec "Lancer ytb-edit.bat"
echo ============================================
pause
exit /b 0

:fail
echo.
echo L'installation a echoue. Voir les messages ci-dessus.
pause
exit /b 1
