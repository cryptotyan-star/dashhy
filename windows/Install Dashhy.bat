@echo off
setlocal
REM ─────────────────────────────────────────────────────────────────────────
REM  Install Dashhy.bat — copies Dashhy.exe to a permanent location, creates
REM  a Desktop shortcut, then launches it. Double-click and done — no Python
REM  needed, Dashhy.exe is fully self-contained.
REM ─────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

if not exist "Dashhy.exe" (
    echo [!] Dashhy.exe not found next to this script.
    echo     Unzip the whole folder first, then run this from inside it.
    pause
    exit /b 1
)

set "DEST_DIR=%LOCALAPPDATA%\Programs\Dashhy"
set "DEST_EXE=%DEST_DIR%\Dashhy.exe"
set "SHORTCUT=%USERPROFILE%\Desktop\Dashhy.lnk"

echo Installing Dashhy to %DEST_DIR% ...
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
copy /y "Dashhy.exe" "%DEST_EXE%" >nul
if errorlevel 1 (
    echo [!] Couldn't copy Dashhy.exe to %DEST_DIR%.
    pause
    exit /b 1
)

echo Creating Desktop shortcut...
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%DEST_EXE%'; $s.WorkingDirectory = '%DEST_DIR%'; $s.IconLocation = '%DEST_EXE%'; $s.Save()"
if errorlevel 1 (
    echo [!] Couldn't create the Desktop shortcut automatically.
    echo     You can still run Dashhy directly from: %DEST_EXE%
) else (
    echo [OK] Shortcut created: %SHORTCUT%
)

echo.
echo Launching Dashhy...
start "" "%DEST_EXE%"
