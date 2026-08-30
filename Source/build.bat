@echo off
REM ============================================================
REM  Lumo - build a standalone .exe with PyInstaller
REM  Run this on Windows. Output: dist\Lumo\Lumo.exe
REM ============================================================
cd /d "%~dp0"

python -m pip install pyinstaller pillow

REM make sure we have the mpv engine (libmpv-2.dll)
if not exist "libmpv-2.dll" (
    echo.
    echo The mpv engine ^(libmpv-2.dll^) is missing - downloading it now...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0get_libmpv.ps1"
    if not exist "libmpv-2.dll" (
        echo.
        echo Could not obtain libmpv-2.dll. See README.md for the manual download link.
        pause
        exit /b 1
    )
)

REM generate the icon (optional, needs Pillow)
python make_icon.py

set "ICON="
if exist icon.ico set "ICON=--icon=icon.ico"

python -m PyInstaller --noconfirm --clean --windowed %ICON% --add-binary "libmpv-2.dll;." --name "Lumo" main.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Done. libmpv-2.dll was bundled next to the exe.
echo Output: dist\Lumo\Lumo.exe
pause
