#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_dashboard.py — 量化阿森工廠手機儀表板（Flask 版）。

用法：python scripts/web_dashboard.py [--port 8080] [--key mytoken]
手機瀏覽器開：http://<伺服器IP>:8080/?key=mytoken
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, request, redirect, url_for

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
LOGS = ROOT / "logs"
LEDGER = STUDIO / "uploaded_ledger.json"
BUFFER = STUDIO / "scheduled_buffer.json"
TW = timezone(timedelta(hours=8))
ACCESS_KEY = os.environ.get("DASHBOARD_KEY", "carson2026")

app = Flask(__name__)


# ── 資料函式 ──────────────────────────────────────────────
def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S")


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else d
    except Exception:
        return d


def _queue():
    led = set(_load(LEDGER, {}).keys())
    mp4s = set(Path(p).stem for p in glob.glob(str(OUT / "*.mp4")))
    return len(mp4s - led)


def _produced_today():
    today = datetime.now(TW).strftime("%Y-%m-%d")
    return sum(
        1 for p in glob.glob(str(OUT / "*.mp4"))
        if datetime.fromtimestamp(Path(p).stat().st_mtime, TW).strftime("%Y-%m-%d") == today
    )


def _published_total():
    return len(_load(LEDGER, {}))


def _buffer_count():
    items = _load(BUFFER, [])
    now = datetime.now(timezone.utc)
    count = 0
    for b in items:
        try:
            dt = datetime.strptime(b.get("publishAt", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if dt > now:
                count += 1
        except Exception:
            pass
    return count


def _running():
    MAP = [
        ("produce_batch", "🎬 補產中"), ("daily_publish", "🚀 上傳中"),
        ("decision_dept", "🧠 決策中"), ("daily_check", "🩺 大檢查"),
        ("intel_dept", "🔍 競品情報"), ("news_dept", "📰 時事"),
        ("quality_score", "🎯 品質評分"), ("train_depts", "📚 部門進修"),
        ("traffic_dept", "📊 流量分析"),
    ]
    out = []
    for key, label in MAP:
        try:
            r = subprocess.run(["pgrep", "-f", key], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                out.append(label)
        except Exception:
            pass
    return out


def _cron_ok():
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return r.returncode == 0 and "run.sh" in r.stdout
    except Exception:
        return False


def _tail(path, n=40):
    p = Path(path)
    if not p.exists():
        return "（尚無記錄）"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "（讀取失敗）"


def _run_bg(script, args=None):
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{script}.log", "a", encoding="utf-8")
    subprocess.Popen(
        [str(ROOT / "run.sh"), f"scripts/{script}.py"] + (args or []),
        stdout=log, stderr=log, cwd=str(ROOT),
    )


# ── 路由 ──────────────────────────────────────────────────
def _check_key():
    return request.args.get("key", "") == ACCESS_KEY


@app.route("/")
def index():
    if not _check_key():
        return "<h2>403 — 請在網址加 ?key=你的密碼</h2>", 403

    action = request.args.get("action", "")
    msg = ""
    if action == "produce":
        _run_bg("produce_batch", ["--shorts", "13", "--long", "0", "--target", "300"])
        msg = "✅ 補產已在背景啟動！"
    elif action == "publish":
        _run_bg("daily_publish", ["--max", "6"])
        msg = "✅ 上傳已在背景啟動！"
    elif action == "decision":
        _run_bg("decision_dept")
        msg = "✅ 決策部門已啟動！"
    elif action == "check":
        _run_bg("daily_check")
        msg = "✅ 大檢查已啟動！"
    elif action == "quality":
        _run_bg("quality_score")
        msg = "✅ 品質評分已啟動！"

    running = _running()
    cron_ok = _cron_ok()
    key = ACCESS_KEY

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化阿森 工廠</title>
<meta http-equiv="refresh" content="60">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0b1224;color:#eef2ff;font-family:-apple-system,sans-serif;padding:12px;font-size:15px}}
h1{{color:#ffd23f;font-size:22px;margin-bottom:6px;text-align:center}}
.ts{{color:#8da3c4;font-size:12px;text-align:center;margin-bottom:14px}}
.msg{{background:#46d98a22;color:#46d98a;border-radius:8px;padding:10px;margin-bottom:12px;text-align:center;font-weight:bold}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}}
.card{{background:#182543;border-radius:10px;padding:14px;text-align:center}}
.num{{font-size:34px;font-weight:bold;color:#ffd23f}}
.lbl{{color:#8da3c4;font-size:12px;margin-top:4px}}
.box{{background:#182543;border-radius:10px;padding:12px;margin-bottom:12px}}
.box h3{{color:#5b8cff;margin-bottom:8px;font-size:14px}}
.tag{{display:inline-block;background:#28395f;border-radius:6px;padding:4px 10px;margin:2px;font-size:13px}}
.ok{{color:#46d98a}}.err{{color:#ff6b6b}}
.log{{background:#111a31;border-radius:8px;padding:10px;font-family:monospace;font-size:11px;
      white-space:pre-wrap;word-break:break-all;max-height:220px;overflow-y:auto;color:#8da3c4;margin-top:6px}}
.btns{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}}
a.btn{{background:#ffd23f;color:#0b1224;border-radius:8px;padding:13px;font-size:14px;
       font-weight:bold;text-decoration:none;display:block;text-align:center}}
a.btn2{{background:#28395f;color:#eef2ff}}
</style>
</head>
<body>
<h1>⚙️ 量化阿森 工廠</h1>
<div class="ts">⏱ {tw_now()} · 每 60 秒自動刷新</div>

{"<div class='msg'>" + msg + "</div>" if msg else ""}

<div class="grid">
  <div class="card"><div class="num">{_queue()}</div><div class="lbl">📦 庫存待上傳</div></div>
  <div class="card"><div class="num">{_produced_today()}</div><div class="lbl">🎬 今日已產</div></div>
  <div class="card"><div class="num">{_published_total()}</div><div class="lbl">✅ 累計上架</div></div>
  <div class="card"><div class="num">{_buffer_count()}</div><div class="lbl">📅 排程囤片</div></div>
</div>

<div class="box">
  <h3>⚡ 目前狀態</h3>
  {"".join(f'<span class="tag">{r}</span>' for r in running) or '<span class="tag">⏳ 待排程</span>'}
  <div style="margin-top:8px;font-size:12px">
    排程：<span class="{"ok" if cron_ok else "err"}">{"✅ 已安裝" if cron_ok else "❌ 未安裝"}</span>
  </div>
</div>

<div class="btns">
  <a href="/?key={key}&action=produce" class="btn" onclick="return confirm('確定補產 13 支？')">🎬 立即補產</a>
  <a href="/?key={key}&action=publish" class="btn" onclick="return confirm('確定上傳最多 6 支？')">🚀 立即上傳</a>
  <a href="/?key={key}&action=decision" class="btn btn2">🧠 跑決策</a>
  <a href="/?key={key}&action=quality" class="btn btn2">🎯 品質評分</a>
</div>

<div class="box">
  <h3>📋 工廠日誌</h3>
  <div class="log">{_tail(STUDIO / "ops_log.txt")}</div>
</div>

<div class="box">
  <h3>📜 Cron 日誌</h3>
  <div class="log">{_tail(LOGS / "cron.log")}</div>
</div>

</body></html>"""


def main():
    global ACCESS_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--key", default=ACCESS_KEY)
    args = parser.parse_args()
    ACCESS_KEY = args.key
    LOGS.mkdir(exist_ok=True)
    print(f"儀表板啟動：http://0.0.0.0:{args.port}/?key={ACCESS_KEY}")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
