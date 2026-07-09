@echo off
setlocal enabledelayedexpansion
REM ─────────────────────────────────────────────────────────────────────────
REM  build_app.bat — builds a self-contained Dashhy.exe (PyInstaller)
REM
REM  Run this ON Windows (PyInstaller does not cross-compile between OSes —
REM  it always packages for the OS it runs on). Needs Python 3 installed
REM  from https://www.python.org/downloads/ with "Add python.exe to PATH"
REM  checked during setup.
REM
REM  Re-run after any code change. Output: dist\Dashhy.exe (single file).
REM ─────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>&1
    if !errorlevel!==0 (
        set "PY=python"
    ) else (
        echo [!] Python not found. Install it from https://www.python.org/downloads/
        echo     and check "Add python.exe to PATH" during setup, then re-run this script.
        pause
        exit /b 1
    )
)

echo === Dashhy - PyInstaller build ===
echo Using: %PY%
%PY% --version

echo.
echo Installing build dependencies (pyinstaller, pywebview)...
%PY% -m pip install --upgrade pip >nul 2>&1
%PY% -m pip install --user pyinstaller pywebview
if errorlevel 1 (
    echo [!] pip install failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo Building Dashhy.exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

%PY% -m PyInstaller --noconfirm Dashhy.spec
if errorlevel 1 (
    echo [!] PyInstaller build failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo ✓ Done.
echo   Executable:  %cd%\dist\Dashhy.exe
echo   Run it directly, or right-click it -> Show more options -> Send to -> Desktop (create shortcut).
pause
