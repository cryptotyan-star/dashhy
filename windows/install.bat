@echo off
setlocal enabledelayedexpansion
REM ─────────────────────────────────────────────────────────────────────────
REM  install.bat — set up and launch Dashhy (no build step, no admin rights).
REM
REM  What it does:
REM    1. checks Python 3 is available
REM    2. installs pywebview (for the native window)
REM    3. launches Dashhy
REM
REM  If pywebview can't be installed, it falls back to browser mode (no deps).
REM
REM  Usage: double-click install.bat, or run it from a terminal.
REM ─────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"
set "APP_DIR=%cd%\project-dashboard"

REM ── 1. Python 3 ──────────────────────────────────────────────────────────
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>&1
    if !errorlevel!==0 (
        set "PY=python"
    ) else (
        echo [!] Python not found.
        echo     Install it from https://www.python.org/downloads/
        echo     and check "Add python.exe to PATH" during setup, then re-run this script.
        pause
        exit /b 1
    )
)
echo [OK] Python: %PY%
%PY% --version

if not exist "%APP_DIR%" (
    echo [!] Can't find project-dashboard\ next to this script.
    pause
    exit /b 1
)

REM ── 2. pywebview (best effort — only needed for the native window) ───────
echo.
echo Installing pywebview (native window)...
set "NATIVE=1"
%PY% -c "import webview" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] pywebview already installed.
) else (
    %PY% -m pip install --upgrade pip >nul 2>&1
    %PY% -m pip install --user pywebview >nul 2>&1
    %PY% -c "import webview" >nul 2>&1
    if !errorlevel!==0 (
        echo [OK] pywebview installed.
    ) else (
        set "NATIVE=0"
        echo [!] Couldn't install pywebview - falling back to browser mode.
    )
)

REM ── 3. Launch ──────────────────────────────────────────────────────────
cd /d "%APP_DIR%"
if "%NATIVE%"=="1" (
    echo.
    echo Launching Dashhy (native window)...
    %PY% app.py
) else (
    echo.
    echo Launching Dashhy (browser) - http://127.0.0.1:7777/
    %PY% server.py
)
