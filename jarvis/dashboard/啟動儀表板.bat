@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo ========================================
echo   賈維斯儀表板
echo ========================================
echo 檢查伺服器...
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient;try{$c.Connect('127.0.0.1',8787);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 (
  echo 啟動伺服器...
  start "賈維斯儀表板伺服器" "%PYEXE%" "jarvis\dashboard\server.py"
  timeout /t 2 >nul
) else (
  echo 伺服器已在運行。
)
echo 開啟瀏覽器...
start "" "http://127.0.0.1:8787"
echo.
echo 已開：http://127.0.0.1:8787    全螢幕按 F11
echo 關閉伺服器：關掉「賈維斯儀表板伺服器」黑視窗
echo.
pause
