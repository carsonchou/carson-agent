@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo ========================================
echo   賈維斯儀表板
echo ========================================
echo 關閉舊的伺服器(若有在跑)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:8787" ^| findstr LISTENING') do taskkill /f /pid %%p >nul 2>&1
echo 啟動伺服器(最新版)...
start "賈維斯儀表板伺服器" "%PYEXE%" "jarvis\dashboard\server.py"
timeout /t 2 >nul
echo 開啟儀表板...
start "" "http://127.0.0.1:8787"
echo.
echo 已開：http://127.0.0.1:8787
echo  ・ 全螢幕：在瀏覽器按 F11
echo  ・ 操作：拖曳旋轉球 / 滾輪縮放 / 點清單列展開細節
echo  ・ 關閉：關掉「賈維斯儀表板伺服器」黑視窗
echo.
pause
