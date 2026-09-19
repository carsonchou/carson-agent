#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_rerender_worker.py — 在雲端重渲「未發布庫存」(舊 b-roll → 新主題對映 b-roll + 會動的數據卡)。
由 _rerender_backlog.py 經 run.sh nohup 背景啟動(已載 .env,帶 PEXELS)。
只重渲「有 mp3+mp4、且不在 uploaded_ledger(未發布)」的 S_ 短片;已發布的不動(YouTube 換不了)。
跑完用 notify.push 推手機。可選環境變數 RERENDER_LIMIT 限數量(測試用)。"""
import glob
import json
import os
import subprocess
import sys
import time

os.chdir("/root/yt")
sys.path.insert(0, "scripts")

try:
    led = set(json.load(open("STUDIO/uploaded_ledger.json", encoding="utf-8")).keys())
except Exception:
    led = set()

mds = [os.path.basename(p)[:-3] for p in glob.glob("output/S_*.md")]
stale = [s for s in mds
         if os.path.exists("output/" + s + ".mp3")
         and os.path.exists("output/" + s + ".mp4")
         and s not in led]
stale.sort()

limit = int(os.environ.get("RERENDER_LIMIT", "0") or "0")
if limit > 0:
    stale = stale[:limit]

print(f"[重渲] 目標未發布庫存 {len(stale)} 支", flush=True)
ok = fail = 0
t0 = time.time()
for i, s in enumerate(stale):
    try:
        r = subprocess.run(
            [".venv/bin/python", "scripts/render_ffmpeg.py", "--slug", s,
             "--width", "1080", "--height", "1920", "--fps", "15"],
            capture_output=True, text=True, timeout=900)
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {s}\n{r.stderr[-300:]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        fail += 1
        print(f"  EXC {s}: {exc}", flush=True)
    print(f"[{i+1}/{len(stale)}] {s} -> ok={ok} fail={fail}  ({time.time()-t0:.0f}s)", flush=True)

mins = (time.time() - t0) / 60.0
body = (f"未發布庫存重渲完成：{ok} 成功 / {fail} 失敗 / 共 {len(stale)} 支\n"
        f"耗時 {mins:.0f} 分。新片＝主題對映 b-roll(鎖金融加密)＋會動的數據卡。\n"
        f"這批之後發布出去就是新畫面了。")
print("[重渲] " + body.replace("\n", " "), flush=True)
try:
    import notify
    notify.push("Carson Quant 庫存重渲", body, tag="movie_camera")
except Exception as exc:  # noqa: BLE001
    print("ntfy 失敗:", exc, flush=True)
print("DONE", flush=True)
