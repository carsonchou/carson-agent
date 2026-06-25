@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo ========================================
echo   賈維斯儀表板
echo ========================================
echo 啟動伺服器中（若已在跑會自動略過）...
start "賈維斯儀表板伺服器" "%PYEXE%" "jarvis\dashboard\server.py"
timeout /t 2 >nul
echo 開啟儀表板...
start "" "http://127.0.0.1:8787"
echo.
echo 已開：http://127.0.0.1:8787
echo  ・ 全螢幕：在瀏覽器按 F11
echo  ・ 關閉：關掉「賈維斯儀表板伺服器」那個黑視窗
echo.
pause
