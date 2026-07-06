@echo off
chcp 65001 >nul
title 量化阿森 · 數據獵手（看板＋手機遠端）
cd /d "%~dp0"
set PYTHON=D:\ClawWork\.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

:: 手機遠端公網通道（另開視窗；沒裝 ngrok/cloudflared 會印安裝說明，可略）
start "數據獵手·手機遠端" "%PYTHON%" tunnel.py

:: 看板本體（含當沖／即時推播／跨裝置同步）——關掉這個視窗即整個停止
"%PYTHON%" app.py

:: 常駐：把這個 .bat 的捷徑放進 Windows「啟動」資料夾(shell:startup)，開機自動跑
