#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""賈維斯儀表板伺服器 — 提供鋼鐵人風前端 + /api/data（讀本機真實狀態檔）。

用法：python jarvis/dashboard/server.py  → 開 http://127.0.0.1:8787
讀的資料都是唯讀，不改任何東西。沒有的檔案就回 None，前端顯示「—」。
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                 # repo 根
TB = ROOT / "trading_bot"
STUDIO = ROOT / "youtube_channel" / "STUDIO"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787


def _load(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def gather() -> dict:
    out = {"trading": {}, "youtube": {}, "paused": False, "focus": ""}

    # ── 交易：回測報告（取 1H 時框當代表，沒有就抓第一個）──
    bt = _load(TB / "backtest_report.json")
    if bt:
        res = bt.get("results") or {}
        r = res.get("1H") or (next(iter(res.values())) if res else {})
        out["trading"] = {
            "symbol": bt.get("symbol"),
            "total_return": r.get("total_return"),
            "sharpe": r.get("sharpe"),
            "win_rate": r.get("win_rate"),
            "max_drawdown": r.get("max_drawdown"),
            "num_trades": r.get("num_trades"),
            "final_equity": r.get("final_equity"),
        }

    # ── 頻道：成效歷史（最新 + 走勢）──
    y = {}
    hist = _load(STUDIO / "metrics_history.json")
    if isinstance(hist, list) and hist:
        last = hist[-1]
        y["subs"] = last.get("subs")
        y["views"] = last.get("views")
        step = max(1, len(hist) // 60)        # 降採樣到 ~60 點給走勢圖
        y["series"] = [{"views": p.get("views", 0)} for p in hist[::step]]

    q = _load(STUDIO / "quality_scores.json")
    if q:
        s = q.get("summary") or {}
        y["pending"] = s.get("pending")
        y["published"] = s.get("published")

    fin = _load(STUDIO / "finance.json")
    if fin:
        y["net"] = (fin.get("summary") or {}).get("net")
        y["roi"] = (fin.get("summary") or {}).get("roi")

    pend = _load(STUDIO / "pending_decisions.json")
    y["decisions"] = len(pend) if isinstance(pend, list) else 0
    out["youtube"] = y

    drc = _load(STUDIO / "boss_directives.json") or {}
    out["paused"] = bool(drc.get("paused"))

    # ── 賈維斯情緒狀態（jarvis.py 即時寫入）──
    jst = _load(HERE / "state.json") or {}
    out["jarvis"] = {"state": jst.get("state", "idle"), "text": jst.get("text", "")}

    # ── 今日焦點（簡單規則）──
    if out["paused"]:
        out["focus"] = "工廠目前<b>已暫停</b>。"
    elif y.get("decisions"):
        out["focus"] = f"有 <b>{y['decisions']}</b> 件等你拍板，其餘我顧著。"
    elif (y.get("pending") or 0) and (y.get("subs") is not None):
        gap = max(0, 1000 - (y.get("subs") or 0))
        out["focus"] = f"倉庫 <b>{y['pending']}</b> 支待發，離 YPP 還差 <b>{gap}</b> 訂閱。全自動衝量中。"
    else:
        out["focus"] = "一切順，沒有要你決定的事，放心去忙。"
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安靜
        pass

    def do_GET(self):
        if self.path.startswith("/api/state"):   # 輕量：只回賈維斯情緒狀態(高頻輪詢)
            jst = _load(HERE / "state.json") or {}
            body = json.dumps({"state": jst.get("state", "idle")}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/data"):
            body = json.dumps(gather(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        # 其餘一律回前端頁
        try:
            html = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
        except Exception as e:  # noqa: BLE001
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))


if __name__ == "__main__":
    print(f"賈維斯儀表板：http://127.0.0.1:{PORT}  (Ctrl-C 結束)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
