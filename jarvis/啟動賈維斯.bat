@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
rem Use the python that already has the voice packages installed.
set "PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ========================================
echo   JARVIS  -  Voice Assistant  (Safe Mode)
echo   Open apps, control media/volume, see screen, chat.
echo   Say "Hey Jarvis" to wake.   Ctrl-C to quit.
echo ========================================
echo.
"%PYEXE%" jarvis\jarvis.py
echo.
echo JARVIS exited (code %errorlevel%). Press any key to close.
pause >nul
