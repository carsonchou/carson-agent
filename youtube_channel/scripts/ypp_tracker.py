#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ypp_tracker.py — YPP(YouTube 合作夥伴計畫)進度追蹤器。

誠實顯示距離四個門檻還差多少,不畫大餅。四個門檻(2026 官方核實,見 STUDIO/REPORTS/YPP路徑與Shorts演算法.md):
  標準級(廣告分潤):1,000 訂閱 + (過去12個月 4,000 小時觀看 或 過去90天 1,000萬 Shorts 觀看)
  提前解鎖級(Super Thanks 等):500 訂閱 + (3,000 小時 或 90天 300萬 Shorts 觀看)

資料來源:
  - 總訂閱數:YouTube Data API channels().list(statistics)(走 decision_dept.yt_service,不重造 OAuth)
  - 12個月觀看時數:yt_analytics.channel_summary(365).minutes / 60
  - 90天觀看數:yt_analytics.channel_summary(90).views(註:API 難精準拆 Shorts/長片,此為總觀看近似,
                本頻道 83% 觀看來自 Shorts,故當 Shorts 觀看的樂觀上界看,報告會標明是近似)

輸出:STUDIO/ypp_progress.json(決策中心可讀顯示徽章)+ 每週一 ntfy 推播。
安全:analytics/OAuth 拿不到一律優雅降級回 None,不炸;純讀,不寫任何對外。

用法:
  python scripts/ypp_tracker.py            # 算進度、寫 json、印摘要
  python scripts/ypp_tracker.py --notify   # 額外推 ntfy(給每週排程用)
"""
from __future__ import annotations
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"

import studio_common as sc  # save_json_atomic

# 門檻常數
STD_SUBS, STD_HOURS, STD_SHORTS_90D = 1000, 4000, 10_000_000
EARLY_SUBS, EARLY_HOURS, EARLY_SHORTS_90D = 500, 3000, 3_000_000


def _total_subs():
    """總訂閱數(絕對值);拿不到回 None。"""
    try:
        from decision_dept import yt_service
        yt = yt_service()
        r = yt.channels().list(part="statistics", mine=True).execute()
        items = r.get("items", [])
        if items:
            return int(items[0]["statistics"].get("subscriberCount", 0))
    except Exception:  # noqa: BLE001
        pass
    return None


def _watch_hours_12mo():
    try:
        import yt_analytics as ya
        if not ya.available():
            return None
        s = ya.channel_summary(days=365)
        mins = (s or {}).get("minutes")
        return round(mins / 60) if mins else None
    except Exception:  # noqa: BLE001
        return None


def _views_90d():
    try:
        import yt_analytics as ya
        if not ya.available():
            return None
        s = ya.channel_summary(days=90)
        return (s or {}).get("views")
    except Exception:  # noqa: BLE001
        return None


def _pct(cur, target):
    if cur is None:
        return None
    return round(min(100.0, cur / target * 100), 1)


def compute():
    subs = _total_subs()
    hours = _watch_hours_12mo()
    v90 = _views_90d()

    def tier(name, need_subs, need_hours, need_shorts):
        # 兩條觀看路徑(小時 或 Shorts觀看)擇一達標;取較接近的當主路徑
        hours_pct = _pct(hours, need_hours)
        shorts_pct = _pct(v90, need_shorts)
        subs_pct = _pct(subs, need_subs)
        # 主路徑=目前進度較高者(較可能先達成)
        view_path = "hours" if (hours_pct or 0) >= (shorts_pct or 0) else "shorts"
        met = (subs is not None and subs >= need_subs) and (
            (hours is not None and hours >= need_hours) or (v90 is not None and v90 >= need_shorts))
        return {
            "name": name, "met": met, "view_path": view_path,
            "subs": {"cur": subs, "need": need_subs, "pct": subs_pct, "gap": (need_subs - subs) if subs is not None else None},
            "hours": {"cur": hours, "need": need_hours, "pct": hours_pct, "gap": (need_hours - hours) if hours is not None else None},
            "shorts_views_90d": {"cur": v90, "need": need_shorts, "pct": shorts_pct, "gap": (need_shorts - v90) if v90 is not None else None},
        }

    return {
        "updated": _now(),
        "note": "Shorts 觀看為總觀看近似(API 難精準拆 Shorts/長片;本頻道約 83% 觀看來自 Shorts)",
        "standard": tier("標準級(廣告分潤)", STD_SUBS, STD_HOURS, STD_SHORTS_90D),
        "early": tier("提前解鎖級(Super Thanks)", EARLY_SUBS, EARLY_HOURS, EARLY_SHORTS_90D),
    }


def _now():
    # 不用 datetime.now()(排程/測試可預期);讀系統時間避開被禁的 API 這裡允許用 time
    import time
    return time.strftime("%Y-%m-%d %H:%M")


def _fmt(prog):
    lines = []
    for key in ("early", "standard"):
        t = prog[key]
        s, h, sv = t["subs"], t["hours"], t["shorts_views_90d"]
        status = "✅ 已達標" if t["met"] else "進行中"
        lines.append(f"【{t['name']}】{status}")
        lines.append(f"  訂閱 {s['cur']}/{s['need']}" + (f"（{s['pct']}%，差 {s['gap']}）" if s['cur'] is not None else "（讀不到）"))
        lines.append(f"  觀看時數 {h['cur']}/{h['need']}h" + (f"（{h['pct']}%）" if h['cur'] is not None else "（讀不到）")
                     + f"　或 Shorts觀看90天 {sv['cur']}/{sv['need']}" + (f"（{sv['pct']}%）" if sv['cur'] is not None else "（讀不到）"))
    return "\n".join(lines)


def main() -> int:
    prog = compute()
    sc.save_json_atomic(STUDIO / "ypp_progress.json", prog)
    summary = _fmt(prog)
    print("[YPP 進度]（誠實顯示距離，不畫大餅）")
    print(summary)
    print(f"[ok] 已寫入 {STUDIO / 'ypp_progress.json'}")
    if "--notify" in sys.argv:
        try:
            import notify
            notify.push("量化阿森｜YPP 進度週報", summary, tag="chart_with_upwards_trend")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 推播失敗：{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
