@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set JARVIS_FULL_POWER=1
cd /d "%~dp0.."
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo ========================================
echo   賈維斯【全能模式】啟動中...
echo   喊什麼都會直接做(跑腳本/改檔/開程式)。
echo   危險指令(刪檔/格式化/關機)她會先開口問你確認。
echo   關閉：按 Ctrl-C
echo ========================================
"%PYEXE%" jarvis\jarvis.py
echo.
echo 賈維斯已結束。按任意鍵關閉視窗。
pause >nul
