@echo off
chcp 65001 >nul
title Carson Quant - ecommerce webhook (port 8021)

:: Launches the v2 ecommerce payment webhook (four /sale-ping/* platform endpoints).
::
:: ASCII-ONLY FILE - DO NOT ADD CHINESE HERE.
::   cmd.exe parses .bat byte-wise in the system ANSI codepage (CP950/Big5 on this box).
::   UTF-8 Chinese bytes desync that parser and it swallows line breaks -> commands get
::   split mid-token and the launcher dies with garbage errors. Verified 2026-07-16.
::   Same lesson as the .vbs launchers. Chinese lives in the FILENAME and in the Python
::   banner below (chcp 65001 makes that render fine). Prose docs: see the runbook.
::
:: CWD MUST BE REPO ROOT (D:\carson-agent), not quant-service.
::   The import path is `quant-service.webhook.app:app` - `quant-service` is a namespace
::   package, importable only from the repo root. Running from inside quant-service dies
::   with: ModuleNotFoundError: No module named 'quant-service'.
::   The `cd /d "%~dp0.."` below jumps up automatically, so just double-click this file.
::
:: SECRETS: put them in quant-service\.env (webhook\config.py loads it; real environment
::   variables take priority over the file). On startup this prints a SET/MISSING summary
::   - anything MISSING means that platform returns 503 and you receive no money.
::   Edit .env -> restart this window for changes to take effect.
::
:: PUBLIC URL: platform dashboards need a public URL, not localhost. Run a cloudflared
::   tunnel to 127.0.0.1:8021. See docs\ecommerce\GO_LIVE_RUNBOOK.md section 3.
::
:: STOP: press Ctrl+C in this window.

cd /d "%~dp0.."

set PYTHON=D:\ClawWork\.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo [start] cwd=%CD%
echo [start] health check: http://127.0.0.1:8021/health   (Ctrl+C to stop)
echo.

"%PYTHON%" -m uvicorn quant-service.webhook.app:app --host 0.0.0.0 --port 8021

echo.
echo [stopped] webhook is down. If this was not intentional, read the error above.
pause
