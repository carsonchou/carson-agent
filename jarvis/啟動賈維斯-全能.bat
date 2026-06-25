@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set JARVIS_FULL_POWER=1
cd /d "%~dp0.."
set "PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ========================================
echo   JARVIS  -  FULL POWER
echo   Controls the whole PC, runs scripts, edits files.
echo   Risky actions (delete/format/shutdown) ask first.
echo   Say "Hey Jarvis" to wake.   Ctrl-C to quit.
echo ========================================
echo.
"%PYEXE%" jarvis\jarvis.py
echo.
echo JARVIS exited. Press any key to close.
pause >nul
