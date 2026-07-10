' ============================================================
'  Carson Quant - 本機工作室 背景啟動器 (windowless)
'  雙擊即在背景無視窗啟動:對帳 -> tunnel -> 排程器
'  不佔桌面、不會被誤關;要停排程器用工作管理員找 python.exe(local_cron)
'  (需要看即時 log 的話才用「啟動本機工作室.bat」前景版)
' ============================================================
Dim sh, root, py
Set sh = CreateObject("WScript.Shell")
root = "D:\carson-agent\youtube_channel"
py = root & "\.venv\Scripts\python.exe"
sh.CurrentDirectory = root

' 1) 對帳:比對頻道實際已發布,避免重複發片(隱藏視窗,等它跑完)
sh.Run "cmd /c """ & py & """ scripts\reconcile_ledger.py", 0, True

' 2) 公網 tunnel:供 IG 抓影片發 Reels(--ensure 只在不健康時才起,隱藏、不等待)
sh.Run """" & py & """ scripts\tunnel_up.py --ensure", 0, False

' 3) 排程器常駐:照 deploy\crontab.txt 每分鐘檢查該跑什麼(隱藏、不等待、背景長跑)
sh.Run """" & py & """ scripts\local_cron.py", 0, False
