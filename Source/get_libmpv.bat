@echo off
REM ============================================================
REM  Lumo - download the mpv engine (libmpv-2.dll)
REM  Double-click this to automatically fetch libmpv-2.dll.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0get_libmpv.ps1"
pause
