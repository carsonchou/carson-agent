@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
rem Full power lets the brain actually do things (open apps already work either way).
rem set JARVIS_FULL_POWER=1
set "PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ========================================
echo   JARVIS  -  Web Orb  (browser voice)
echo   Backend on http://127.0.0.1:8788
echo   Opening in Chrome - click the orb, allow mic, then talk.
echo ========================================
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient;try{$c.Connect('127.0.0.1',8788);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 (
  start "JARVIS Web Backend" "%PYEXE%" "jarvis\web\server.py"
  timeout /t 2 >nul
)
start "" "chrome.exe" "http://127.0.0.1:8788"
if errorlevel 1 start "" "http://127.0.0.1:8788"
echo.
echo Opened. Click the glowing ring, allow microphone, then just speak.
echo To stop: close the black "JARVIS Web Backend" window.
echo.
pause
