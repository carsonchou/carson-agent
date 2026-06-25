@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set "PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ========================================
echo   JARVIS Dashboard
echo ========================================
echo Checking server on port 8787 ...
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient;try{$c.Connect('127.0.0.1',8787);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 (
  echo Starting server ...
  start "JARVIS Dashboard Server" "%PYEXE%" "jarvis\dashboard\server.py"
  timeout /t 2 >nul
) else (
  echo Server already running.
)
echo Opening browser ...
start "" "http://127.0.0.1:8787"
echo.
echo Opened: http://127.0.0.1:8787   ^(press F11 for fullscreen^)
echo To stop: close the black "JARVIS Dashboard Server" window.
echo.
pause
