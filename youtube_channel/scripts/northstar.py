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


# E1:YouTube Studio 官方自承「2026/6/30–7/7 觀看資料低於實際數據,官方正修」(Carson 給的官方截圖)。
# 這段窗口內我方 metrics_history.json 記到的是被 YouTube 少報的假低值,若原樣灌進趨勢計算
# 會把「其實沒跌」算成「下滑」。這裡先把該窗標記為不可靠並在趨勢計算跳過,YouTube 修好、
# 且該窗完全滾出 7d/28d 視窗後(約 2026-08-04 起)這段常數與跳過邏輯即可整段移除。
UNRELIABLE_WINDOW_START = "2026-06-30"
UNRELIABLE_WINDOW_END = "2026-07-07"
UNRELIABLE_WINDOW_NOTE = (
    f"YouTube 官方自承 {UNRELIABLE_WINDOW_START}~{UNRELIABLE_WINDOW_END} 觀看資料低報(官方承認·修復中),"
    "該窗快照已從趨勢計算排除,不代表真下滑"
)


def _mmdd(label):
    """把 metrics_history 兩種 schema 的 label 統一取出 'MM-DD' 供跟不可靠窗比對。
    'YYYY-MM-DD...'(date schema)或 'MM-DD HH:MM'(t schema,同年 2026,不跨年安全)。"""
    s = str(label)
    if len(s) >= 10 and s[4] == "-":
        return s[5:10]
    if len(s) >= 5 and s[2] == "-":
        return s[:5]
    return None


def _in_unreliable_window(label) -> bool:
    mmdd = _mmdd(label)
    if mmdd is None:
        return False
    start, end = UNRELIABLE_WINDOW_START[5:], UNRELIABLE_WINDOW_END[5:]
    return start <= mmdd <= end


def _nearest_reliable_idx(points, target):
    """從 target 索引往外擴散找最近的「非不可靠窗」點(先近後遠,同距離先看較新的一邊)。
    整段都不可靠時回 None——寧可不算趨勢,也別讓假低值當錨點算出假趨勢。"""
    n = len(points)
    if n == 0:
        return None
    for radius in range(0, n):
        for cand in (target + radius, target - radius):
            if 0 <= cand < n and not points[cand]["unreliable"]:
                return cand
    return None


def _rolling_trend():
    """P0-a 認知校正:metrics_history.json 混雜兩種歷史快照 schema——
    {date,total_views,...} 每日快照 / {t,subs,views} 即時快照——兩者記的其實是同一個
    「近28天滾動觀看」數字在不同時間點的值。單看「今日單日增量」會忽高忽低(鋸齒),
    但把這些快照連成線,滾動趨勢是向上的。這裡重建趨勢線 + 7日/28日方向,別重抓 API。

    E1:series 仍保留 UNRELIABLE_WINDOW 內的快照供顯示(標 unreliable),但算
    trend_7d_pct/trend_28d_pct/today_delta_noisy 的錨點(latest/base7/base28)一律
    跳過落在該窗內的點、改用最近的乾淨點,避免被 YouTube 官方低報的假低值拖成假下滑。
    """
    hist = sc.load_json_safe(STUDIO / "metrics_history.json", []) or []
    if not isinstance(hist, list) or not hist:
        return {"series": [], "trend_7d_pct": None, "trend_28d_pct": None,
                "trend_direction": None, "today_delta_noisy": None,
                "unreliable_window_excluded": 0, "unreliable_window_note": None}
    by_key = {}
    for e in hist:
        if not isinstance(e, dict):
            continue
        if "views" in e and e.get("t"):
            label, v = e.get("t"), e.get("views")
        elif "total_views" in e and e.get("date"):
            label, v = e.get("date"), e.get("total_views")
        else:
            continue
        if not v:  # 0/None＝壞快照(非真的歸零)，別畫進趨勢線誤導
            continue
        by_key[label] = v  # 同 key 後者覆蓋前者，保留較新快照
    all_points = [{"t": k, "views28_snapshot": v, "unreliable": _in_unreliable_window(k)}
                  for k, v in by_key.items()]
    series = all_points[-28:]  # 供顯示用,含 unreliable 旗標,筆數/涵蓋天數行為不變
    excluded = sum(1 for p in series if p["unreliable"])
    note = UNRELIABLE_WINDOW_NOTE if excluded else None
    n = len(series)
    if n < 2:
        return {"series": series, "trend_7d_pct": None, "trend_28d_pct": None,
                "trend_direction": None, "today_delta_noisy": None,
                "unreliable_window_excluded": excluded, "unreliable_window_note": note}
    latest_idx = _nearest_reliable_idx(series, n - 1)
    base7_idx = _nearest_reliable_idx(series, max(0, n - 8))
    base28_idx = _nearest_reliable_idx(series, 0)
    if latest_idx is None or base7_idx is None or base28_idx is None:
        # 整段 series 都落在不可靠窗內,沒有乾淨錨點可用——寧可不算,也別算出假趨勢
        return {"series": series, "trend_7d_pct": None, "trend_28d_pct": None,
                "trend_direction": None, "today_delta_noisy": None,
                "unreliable_window_excluded": excluded, "unreliable_window_note": note}
    latest = series[latest_idx]["views28_snapshot"]
    base7 = series[base7_idx]["views28_snapshot"]
    base28 = series[base28_idx]["views28_snapshot"]
    pct7 = round((latest - base7) / base7 * 100, 1) if base7 else None
    pct28 = round((latest - base28) / base28 * 100, 1) if base28 else None
    direction = "up" if (pct7 or 0) > 1 else ("down" if (pct7 or 0) < -1 else "flat")
    prev_idx = _nearest_reliable_idx(series, latest_idx - 1) if latest_idx > 0 else None
    today_delta_noisy = (latest - series[prev_idx]["views28_snapshot"]) if prev_idx is not None else None
    return {"series": series, "trend_7d_pct": pct7, "trend_28d_pct": pct28,
            "trend_direction": direction, "today_delta_noisy": today_delta_noisy,
            "unreliable_window_excluded": excluded, "unreliable_window_note": note}


def main() -> int:
    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "reach": _reach(),
        "trend": _rolling_trend(),
        "revenue": _revenue(),
        "ypp": _ypp(),
        "winners": _winners(),
    }
    sc.save_json_atomic(STUDIO / "northstar.json", data)

    r, tr, rev, yp, w = data["reach"], data["trend"], data["revenue"], data["ypp"], data["winners"]
    lines = ["★ 量化阿森 北極星 · " + data["updated"], ""]
    if tr.get("trend_direction"):
        arrow = {"up": "📈 上升中", "down": "📉 下降中", "flat": "➡ 持平"}.get(tr["trend_direction"], "")
        lines.append(f"【滾動趨勢 · 最重要】近7日 {tr.get('trend_7d_pct')}%｜近28日 {tr.get('trend_28d_pct')}% {arrow}")
        lines.append(f"（單日增量僅供參考,忽高忽低不代表趨勢:今日 {tr.get('today_delta_noisy')}）")
        if tr.get("unreliable_window_note"):
            lines.append(f"（{tr['unreliable_window_note']},已排除 {tr.get('unreliable_window_excluded')} 筆)")
        lines.append("")
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
