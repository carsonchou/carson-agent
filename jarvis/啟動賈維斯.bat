@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
rem 直接指定「已裝好套件」的那支 python，避免雙擊時抓到別的 python / Store 假 python
set PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe
if not exist "%PYEXE%" set PYEXE=python
echo ========================================
echo   賈維斯啟動中...（首次會載入語音模型，稍等幾秒）
echo   待命後對麥克風說英文「Hey Jarvis」叫醒她
echo   關閉：按 Ctrl-C
echo ========================================
"%PYEXE%" jarvis\jarvis.py
echo.
echo 賈維斯已結束（離開代碼 %errorlevel%）。按任意鍵關閉視窗。
pause >nul
