#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""northstar.py — 北極星整合(C2)。一頁看清:訂閱/觀看/各源進帳/YPP 缺口/飛輪贏家。

聚合現成資料(全唯讀):
  - 觀看/訂閱:yt_analytics.channel_summary(退回 analytics_cache 的 days=28 快取)
  - 各源收入:STUDIO/finance.json(type: affiliate=Pionex返佣 / adsense=YT廣告 / cost=支出)
  - YPP 四門檻缺口:STUDIO/ypp_progress.json(ypp_tracker 產)
  - 飛輪贏家詞:STUDIO/traffic_signals.json(weekly_winners 產)

輸出:STUDIO/northstar.json(決策中心可讀顯示)+ 終端摘要 + --notify 推 ntfy。
用法:python scripts/northstar.py [--notify]
"""
from __future__ import annotations
import glob
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"

import studio_common as sc


def _reach():
    """近28天觀看/新增訂閱:優先 analytics,退回快取。"""
    try:
        import yt_analytics as ya
        if ya.available():
            s = ya.channel_summary(days=28) or {}
            if s.get("views"):
                return {"views28": s.get("views"), "subs28": s.get("subs_gained"), "avg_pct": s.get("avg_pct")}
    except Exception:  # noqa: BLE001
        pass
    # 退回 analytics_cache 的 days=28 快取(取最新)
    best = None
    for f in glob.glob(str(STUDIO / "analytics_cache" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("days") == 28 and d.get("views"):
            if best is None or (d.get("views", 0) > best.get("views", 0)):
                best = d
    if best:
        return {"views28": best.get("views"), "subs28": best.get("subs_gained"), "avg_pct": best.get("avg_pct")}
    return {"views28": None, "subs28": None, "avg_pct": None}


def _revenue():
    """各源進帳彙總(finance.json)。回 {source: 累計金額} + 淨額。"""
    d = sc.load_json_safe(STUDIO / "finance.json", {}) or {}
    entries = d.get("entries") if isinstance(d, dict) else []
    label = {"affiliate": "Pionex 返佣", "adsense": "YouTube 廣告"}
    income, cost = {}, 0.0
    for e in entries or []:
        t = e.get("type")
        amt = float(e.get("amount", 0) or 0)
        if t == "cost":
            cost += amt
        elif t:
            income[label.get(t, t)] = income.get(label.get(t, t), 0.0) + amt
    total_income = sum(income.values())
    return {"by_source": income, "total_income": total_income, "total_cost": cost, "net": total_income - cost}


def _ypp():
    yp = sc.load_json_safe(STUDIO / "ypp_progress.json", {}) or {}
    out = {}
    for tier in ("early", "standard"):
        t = yp.get(tier) or {}
        s = t.get("subs") or {}
        h = t.get("hours") or {}
        out[tier] = {"name": t.get("name"), "subs_cur": s.get("cur"), "subs_need": s.get("need"),
                     "hours_cur": h.get("cur"), "hours_need": h.get("need"), "met": t.get("met")}
    return out


def _winners():
    ts = sc.load_json_safe(STUDIO / "traffic_signals.json", {}) or {}
    return {"win": ts.get("win_keywords") or [], "weak": ts.get("weak_keywords") or []}


def main() -> int:
    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "reach": _reach(),
        "revenue": _revenue(),
        "ypp": _ypp(),
        "winners": _winners(),
    }
    sc.save_json_atomic(STUDIO / "northstar.json", data)

    r, rev, yp, w = data["reach"], data["revenue"], data["ypp"], data["winners"]
    lines = ["★ 量化阿森 北極星 · " + data["updated"], ""]
    lines.append(f"觸及: 近28天觀看 {r['views28']}｜新增訂閱 {r['subs28']}｜完播 {r['avg_pct']}%")
    src = "、".join(f"{k} NT${int(v)}" for k, v in rev["by_source"].items()) or "尚無進帳"
    lines.append(f"變現: 收入源[{src}]｜累計收入 NT${int(rev['total_income'])}｜成本 NT${int(rev['total_cost'])}｜淨 NT${int(rev['net'])}")
    e = yp.get("early", {})
    lines.append(f"YPP 提前級: 訂閱 {e.get('subs_cur')}/{e.get('subs_need')}｜時數 {e.get('hours_cur')}/{e.get('hours_need')}h"
                 + ("（誠實:還很遠）" if not e.get("met") else "（達標✓）"))
    lines.append(f"飛輪贏家詞: {'、'.join(map(str, w['win'][:6])) or '待累積'}")
    summary = "\n".join(lines)
    print(summary)
    print(f"[ok] 已寫入 {STUDIO / 'northstar.json'}(決策中心可讀)")

    if "--notify" in sys.argv:
        try:
            import notify
            notify.push("量化阿森｜北極星", summary, tag="star")
        except Exception as ex:  # noqa: BLE001
            print(f"[warn] ntfy 失敗:{ex}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
