@echo off
chcp 65001 >nul
title 量化阿森 決策中心
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem ── 防呆：殺掉任何舊的 web_center server/app（避免卡 port→打不開）──
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*web_center*server.py*' -or $_.CommandLine -like '*web_center*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

rem 用 pythonw 開原生 App 視窗（無主控台黑窗）。app.py 自己找空 port、起 server、開 pywebview 視窗。
start "" "%PY%" "%~dp0scripts\web_center\app.py"
