@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
echo ========================================
echo   賈維斯啟動中...（首次會載入語音模型，稍等幾秒）
echo   待命後對麥克風說英文「Hey Jarvis」叫醒她
echo   要全能模式：先設 JARVIS_FULL_POWER=1 再開
echo   關閉：按 Ctrl-C
echo ========================================
python jarvis\jarvis.py
echo.
echo 賈維斯已結束。按任意鍵關閉視窗。
pause >nul
