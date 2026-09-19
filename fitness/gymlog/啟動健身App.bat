@echo off
REM GymLog one-time installer server (needs only for install/update, not daily use)
cd /d "%~dp0"
echo.
echo  [GymLog] Starting local server on port 8787 ...
start "GymLogServer" /min python -m http.server 8787 --bind 127.0.0.1
timeout /t 2 /nobreak >nul
echo  [GymLog] Creating temporary https URL (wait ~10s, look for https://xxxx.trycloudflare.com below)
echo  [GymLog] Open that URL in iPhone Safari, then Share -^> Add to Home Screen.
echo  [GymLog] After install you can close this window (Ctrl+C, then close server window).
echo.
cloudflared tunnel --url http://127.0.0.1:8787
taskkill /fi "WINDOWTITLE eq GymLogServer*" >nul 2>&1
