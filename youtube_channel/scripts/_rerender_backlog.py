#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_rerender_backlog.py — 一鍵在雲端「背景」重渲未發布庫存(新畫面)。
Carson 用 ! 跑(他本人動作才放行寫/跑雲端):
  ! /d/carson-agent/youtube_channel/.venv/Scripts/python.exe /d/carson-agent/youtube_channel/scripts/_rerender_backlog.py
做:① 上傳 _rerender_worker.py ② 用 run.sh nohup 背景啟動(載 .env 帶 PEXELS) ③ 立刻返回,不卡終端
跑完 worker 會 ntfy 推你手機。要先小量測試:加 5 → 只渲 5 支驗證。
查進度:tail -f /root/yt/logs/rerender_backlog.log"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "_rerender_worker.py")
CLOUD_JSON = os.path.join(os.path.dirname(HERE), "cloud.json")

limit = ""
for a in sys.argv[1:]:
    if a.isdigit():
        limit = a

import paramiko  # noqa: E402
c = json.load(open(CLOUD_JSON, encoding="utf-8"))
root = c.get("remote_root", "/root/yt")
cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(c["ip"], port=22, username=c.get("user", "root"), password=c["password"], timeout=30)


def run(cmd, t=120):
    i, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


print("① 上傳 _rerender_worker.py + 最新 render_ffmpeg.py(含推鏡 1.06 護浮水印)")
sf = cli.open_sftp()
sf.put(WORKER, root + "/scripts/_rerender_worker.py")
sf.put(os.path.join(HERE, "render_ffmpeg.py"), root + "/scripts/render_ffmpeg.py")
sf.close()
print("   uploaded worker:", os.path.getsize(WORKER), "bytes ; render_ffmpeg 已同步")

print("② 背景啟動重渲" + (f"(限 {limit} 支測試)" if limit else "(全部未發布庫存)"))
lim_env = f"RERENDER_LIMIT={limit} " if limit else ""
# run.sh 會 cd /root/yt + 載 .env + 用 .venv/bin/python;setsid+</dev/null 讓任務徹底脫離 SSH session
# (否則 paramiko 等不到 channel EOF 會逾時——上次的 cosmetic bug),background 立刻返回
launch = (f"mkdir -p {root}/logs && cd {root} && "
          f"{lim_env}setsid bash run.sh scripts/_rerender_worker.py "
          f"> {root}/logs/rerender_backlog.log 2>&1 < /dev/null & echo PID=$!")
try:
    out, err = run(launch, t=20)
    print("  ", out.strip() or err[-300:])
except Exception:
    print("   (啟動指令已送出;channel 回傳逾時無妨,worker 已在背景跑)")

# 確認有跑起來
import time
time.sleep(3)
head, _ = run(f"head -5 {root}/logs/rerender_backlog.log 2>/dev/null")
print("---- log 開頭 ----"); print(head.strip() or "(log 還沒寫,稍等)")
cli.close()
print("\n已在雲端背景重渲,跑完會 ntfy 推你手機。不卡你終端。")
print("查進度(任何時候,唯讀): 我可以幫你 tail,或你按:")
print(f"  ssh 進去 tail -f {root}/logs/rerender_backlog.log")
