# -*- coding: utf-8 -*-
"""
alerts_monitor.py — 伺服器端到價警示監控（鎖屏也收）

看板的到價警示(dh_alerts)本來只在瀏覽器開著才檢查。此模組在背景(app.py 盤中每輪)讀
prefs.json 裡同步上來的 dh_alerts，用即時價判斷是否觸價 → 推 ntfy(手機鎖屏也收)，
並標 done 寫回 prefs(SSE 推回瀏覽器同步移除)。→ 看板沒開、手機鎖屏都收得到。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREFS_FILE = HERE / "prefs.json"


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"data": {}, "ts": 0}


def _save_prefs(obj: dict) -> None:
    try:
        tmp = PREFS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PREFS_FILE)
    except Exception:
        pass


def check_and_push() -> int:
    """讀 prefs 的 dh_alerts，觸價的推 ntfy 並標 done 寫回。回推播筆數。"""
    pf = _load_prefs()
    data = pf.get("data", {})
    raw = data.get("dh_alerts")
    # prefs 的值來自 localStorage → 多為 JSON 字串；容錯吃 str 或 list
    if isinstance(raw, str):
        try:
            alerts = json.loads(raw)
        except Exception:
            return 0
    elif isinstance(raw, list):
        alerts = raw
    else:
        return 0
    if not alerts:
        return 0
    pending = [a for a in alerts if not a.get("done")]
    if not pending:
        return 0
    codes = sorted({a.get("code") for a in pending if a.get("code")})
    if not codes:
        return 0
    try:
        import realtime_quote as rq
        quotes = rq.fetch_quotes_batch(codes)
    except Exception:
        return 0
    try:
        import notify
    except Exception:
        notify = None
    pushed = 0
    for a in pending:
        q = quotes.get(a.get("code"))
        px = q.get("price") if q else None
        if px is None:
            continue
        op = a.get("op"); target = a.get("price")
        try:
            target = float(target)
        except (TypeError, ValueError):
            continue
        hit = (op == "above" and px >= target) or (op == "below" and px <= target)
        if not hit:
            continue
        arrow = "▲" if op == "above" else "▼"
        msg = (f"🔔 到價警示｜{a.get('code')} {a.get('name', '')}\n"
               f"{arrow} 觸及 {target}（現價 {px}）")
        if notify:
            try:
                notify.broadcast(msg, title=f"到價警示｜{a.get('code')} {a.get('name','')}", priority="high")
            except Exception:
                pass
        a["done"] = True
        pushed += 1
    if pushed:
        data["dh_alerts"] = json.dumps(alerts, ensure_ascii=False)   # 存回原格式(字串)
        pf["data"] = data
        pf["ts"] = int(pf.get("ts", 0)) + 1        # 遞增 ts → SSE 推回瀏覽器同步移除
        _save_prefs(pf)
    return pushed


if __name__ == "__main__":
    print(f"[alerts_monitor] 推播 {check_and_push()} 筆")
