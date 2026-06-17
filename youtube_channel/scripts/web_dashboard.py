#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_dashboard.py — 量化阿森工廠手機儀表板。

用法：python scripts/web_dashboard.py [--port 8080] [--key mytoken]
瀏覽器開 http://<伺服器IP>:8080/?key=mytoken

功能：
  - 即時顯示庫存/今日產量/累計上架/正在跑的腳本
  - 最新 ops_log + cron.log（自動刷新）
  - 快速操作按鈕（補產/上傳/決策）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
LOGS = ROOT / "logs"
LEDGER = STUDIO / "uploaded_ledger.json"
BUFFER = STUDIO / "scheduled_buffer.json"
TW = timezone(timedelta(hours=8))

ACCESS_KEY = os.environ.get("DASHBOARD_KEY", "carson2026")


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
    n = 0
    for p in glob.glob(str(OUT / "*.mp4")):
        try:
            if datetime.fromtimestamp(Path(p).stat().st_mtime, TW).strftime("%Y-%m-%d") == today:
                n += 1
        except Exception:
            pass
    return n


def _published_total():
    return len(_load(LEDGER, {}))


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
    return out or ["⏳ 待排程"]


def _tail(path, n=30):
    p = Path(path)
    if not p.exists():
        return "（尚無記錄）"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "（讀取失敗）"


def _cron_ok():
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return r.returncode == 0 and "run.sh" in r.stdout
    except Exception:
        return False


def _buffer_count():
    items = _load(BUFFER, [])
    now = datetime.now(timezone.utc)
    return sum(1 for b in items if _parse_dt(b.get("publishAt", "")) and _parse_dt(b.get("publishAt", "")) > now)


def _parse_dt(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def run_cmd(script, args=None):
    cmd = [str(ROOT / "run.sh"), f"scripts/{script}.py"] + (args or [])
    subprocess.Popen(cmd, stdout=open(LOGS / f"{script}.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))


HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化阿森 工廠</title>
<meta http-equiv="refresh" content="60">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0b1224;color:#eef2ff;font-family:-apple-system,sans-serif;padding:12px;font-size:15px}}
h1{{color:#ffd23f;font-size:20px;margin-bottom:12px;text-align:center}}
.ts{{color:#8da3c4;font-size:12px;text-align:center;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}}
.card{{background:#182543;border-radius:10px;padding:14px;text-align:center}}
.num{{font-size:32px;font-weight:bold;color:#ffd23f}}
.lbl{{color:#8da3c4;font-size:12px;margin-top:4px}}
.status{{background:#182543;border-radius:10px;padding:12px;margin-bottom:12px}}
.status h3{{color:#5b8cff;margin-bottom:8px;font-size:14px}}
.tag{{display:inline-block;background:#28395f;border-radius:6px;padding:3px 8px;margin:2px;font-size:13px}}
.ok{{color:#46d98a}}.warn{{color:#ffd23f}}.err{{color:#ff6b6b}}
.log{{background:#111a31;border-radius:8px;padding:10px;font-family:monospace;font-size:11px;
      white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;color:#8da3c4}}
.btns{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px}}
.btn{{background:#ffd23f;color:#0b1224;border:none;border-radius:8px;padding:12px;
      font-size:14px;font-weight:bold;cursor:pointer;text-decoration:none;display:block;text-align:center}}
.btn2{{background:#28395f;color:#eef2ff}}
section{{margin-bottom:14px}}
section h3{{color:#5b8cff;font-size:13px;margin-bottom:6px}}
</style>
</head>
<body>
<h1>⚙️ 量化阿森 工廠儀表板</h1>
<div class="ts">更新：{ts}（每 60 秒自動刷新）</div>

<div class="grid">
  <div class="card"><div class="num">{queue}</div><div class="lbl">📦 庫存待上傳</div></div>
  <div class="card"><div class="num">{today}</div><div class="lbl">🎬 今日已產</div></div>
  <div class="card"><div class="num">{total}</div><div class="lbl">✅ 累計上架</div></div>
  <div class="card"><div class="num">{buf}</div><div class="lbl">📅 排程囤片</div></div>
</div>

<div class="status">
  <h3>⚡ 目前狀態</h3>
  <div>{running_tags}</div>
  <div style="margin-top:8px;font-size:12px">
    排程：<span class="{cron_cls}">{cron_txt}</span>
  </div>
</div>

<div class="btns">
  <a href="?key={key}&action=produce" class="btn" onclick="return confirm('確定補產 13 支？')">🎬 立即補產</a>
  <a href="?key={key}&action=publish" class="btn" onclick="return confirm('確定上傳最多 6 支？')">🚀 立即上傳</a>
  <a href="?key={key}&action=decision" class="btn btn2">🧠 跑決策</a>
  <a href="?key={key}&action=check" class="btn btn2">🩺 大檢查</a>
</div>

<section>
  <h3>📋 工廠日誌（最新 30 行）</h3>
  <div class="log">{ops_log}</div>
</section>

<section>
  <h3>📜 Cron 日誌（最新 30 行）</h3>
  <div class="log">{cron_log}</div>
</section>

</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _check_key(self):
        q = parse_qs(urlparse(self.path).query)
        return q.get("key", [""])[0] == ACCESS_KEY

    def do_GET(self):
        if not self._check_key():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"<h1>403 Forbidden</h1><p>?key= \xe9\x8c\xaf\xe8\xaa\xa4</p>")
            return

        q = parse_qs(urlparse(self.path).query)
        action = q.get("action", [""])[0]
        if action == "produce":
            LOGS.mkdir(exist_ok=True)
            run_cmd("produce_batch", ["--shorts", "13", "--long", "0", "--target", "300"])
        elif action == "publish":
            LOGS.mkdir(exist_ok=True)
            run_cmd("daily_publish", ["--max", "6"])
        elif action == "decision":
            LOGS.mkdir(exist_ok=True)
            run_cmd("decision_dept")
        elif action == "check":
            LOGS.mkdir(exist_ok=True)
            run_cmd("daily_check")

        running = _running()
        tags = "".join(f'<span class="tag">{r}</span>' for r in running)
        cron_ok = _cron_ok()

        html = HTML.format(
            ts=tw_now(),
            queue=_queue(),
            today=_produced_today(),
            total=_published_total(),
            buf=_buffer_count(),
            running_tags=tags,
            cron_cls="ok" if cron_ok else "err",
            cron_txt="✅ 已安裝" if cron_ok else "❌ 未安裝",
            ops_log=_tail(STUDIO / "ops_log.txt"),
            cron_log=_tail(LOGS / "cron.log"),
            key=ACCESS_KEY,
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global ACCESS_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--key", default=ACCESS_KEY)
    args = parser.parse_args()
    ACCESS_KEY = args.key
    LOGS.mkdir(exist_ok=True)
    print(f"儀表板啟動：http://0.0.0.0:{args.port}/?key={ACCESS_KEY}")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
