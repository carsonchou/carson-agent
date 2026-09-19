#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:原子化強制重渲旗艦2(殺舊渲染→刪壞mp4→同步渲→驗證)。
背景:watcher 用舊碼渲出 scene=0 的壞版;make_video 看到 mp4 存在就跳過,重渲變 no-op。"""
import os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLUG = "L_台股每年飆股Top10追3年60的人倒賠21年210檔"
MP4 = ROOT / "output" / f"{SLUG}.mp4"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 1) 殺掉所有 make_video(含 watcher 派的)
out = subprocess.run(["powershell", "-NoProfile", "-Command",
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
    "Where-Object { $_.CommandLine -match 'make_video' -and $_.ProcessId -ne %d } | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }" % os.getpid()],
    capture_output=True, text=True, timeout=30)
print("killed:", out.stdout.strip() or "(none)")

time.sleep(2)
# 2) 刪壞 mp4
if MP4.exists():
    MP4.unlink()
    print("deleted bad mp4")

# 3) 同步渲(這個進程活到渲完)
print("render start", time.strftime("%H:%M:%S"))
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_video.py"), "--slug", SLUG],
                   cwd=str(ROOT), timeout=5400)
print("render done rc=", r.returncode, time.strftime("%H:%M:%S"))

# 4) 驗證
if MP4.exists():
    print("mp4 size MB:", round(MP4.stat().st_size / 1e6, 1))
else:
    print("FAIL: no mp4 produced")
