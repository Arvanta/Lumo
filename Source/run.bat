@echo off
REM ============================================================
REM  Lumo - run from source
REM ============================================================
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Please install Python 3.9+ from python.org
    pause
    exit /b 1
)
python -m pip install -r requirements.txt

if not exist "libmpv-2.dll" (
    echo.
    echo The mpv engine ^(libmpv-2.dll^) is missing - downloading it now...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0get_libmpv.ps1"
)

python main.py
pause
