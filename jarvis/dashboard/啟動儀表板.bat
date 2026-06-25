@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo 啟動賈維斯儀表板伺服器...
start "賈維斯儀表板" "%PYEXE%" "jarvis\dashboard\server.py"
timeout /t 2 >nul
rem 用 Edge 全螢幕 kiosk 開（丟牆上 TV 的鋼鐵人感）；關閉按 Alt+F4
start msedge --kiosk "http://127.0.0.1:8787" --edge-kiosk-type=fullscreen
echo.
echo 儀表板已開：http://127.0.0.1:8787
echo （沒自動開瀏覽器的話，手動開上面網址；全螢幕按 F11）
