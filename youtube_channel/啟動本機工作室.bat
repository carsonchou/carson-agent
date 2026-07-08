@echo off
chcp 65001 >nul
cd /d D:\carson-agent\youtube_channel
title 量化阿森 · 本機工作室排程器
echo ================================================================
echo   量化阿森 YT 工作室 - 本機模式(取代停權的雲端主機)
echo   這個視窗別關;關掉=排程停。要 24 小時跑就設開機自動啟動。
echo ================================================================
echo.

echo [1/4] 補裝缺的套件(yfinance/pandas 給台股真數字, opencc 給簡轉繁)...
.venv\Scripts\python.exe -m pip install -q yfinance pandas opencc-python-reimported 2>nul
echo     完成(裝不了也沒關係,台股會用示意數字、簡轉繁略過)。
echo.

echo [LLM改道] 確保 OpenRouter 路由掛鉤在 venv(所有部門腳本零改動走 OpenRouter)...
copy /Y scripts\sitecustomize.py .venv\Lib\site-packages\sitecustomize.py >nul 2>&1
echo.

echo [2/4] 對帳:比對頻道實際已發布,避免重複發片...
.venv\Scripts\python.exe scripts\reconcile_ledger.py
echo.

echo [3/4] 種子:建 Short-長片連看對應 + 更新台股真回測數據...
.venv\Scripts\python.exe scripts\build_short_to_long.py
.venv\Scripts\python.exe scripts\tw_stock_data.py
.venv\Scripts\python.exe scripts\tw_stock_series.py --boost
echo.

echo [公網URL] 起本機檔案伺服器 + cloudflared tunnel(供 IG 抓影片發 Reels)...
start "量化阿森·公網tunnel" /min .venv\Scripts\python.exe scripts\tunnel_up.py
echo     (獨立小視窗常駐;IG 跨發靠它給公網網址。關掉=IG 發布暫停,不影響 YouTube。)
echo.

echo [4/4] 啟動排程器(照 deploy\crontab.txt 每分鐘檢查該跑什麼)...
echo     LLM=OpenRouter;發布走本機 token;產片/發布/渲染全自動。
echo     新片自動跨發 IG + 近期舊片小量回填 IG(TikTok/FB/Threads 待 token)。
echo     停止:直接關這個視窗,或按 Ctrl+C。
echo ----------------------------------------------------------------
.venv\Scripts\python.exe scripts\local_cron.py
pause
