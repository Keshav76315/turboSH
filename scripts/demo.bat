@echo off
rem ==============================================================================
rem turboSH Real-Time Monitoring Dashboard Demo (Windows CMD / Explorer Launcher)
rem ==============================================================================
rem Usage:
rem   scripts\demo.bat
rem   scripts\demo.bat -Light
rem   scripts\demo.bat -NoBrowser
rem ==============================================================================

setlocal
cd /d "%~dp0.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1" %*
endlocal
