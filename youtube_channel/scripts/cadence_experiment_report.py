#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cadence_experiment_report.py — 發布節奏實驗(7→3/天)的前後對照報告。

## 背景(memory yt-cadence-experiment-2026-08)
2026-08-12 起發布量 7→3/天(2長1短),14 天實驗。本工具在評估日自動算前後窗對照,
未來 session/Carson 不用手工重算,也不會忘記評估。

窗口:前窗 07-29~08-11(舊節奏 14 天) vs 後窗 08-12~08-25(新節奏 14 天)。
指標(與實驗備忘一致):
  ①BROWSE(首頁推薦)觀看——基線 0,任何非零都是訊號
  ②單片中位觀看(該窗內發布的長片,取到報告日的累計)
  ③訂閱增量、④觀看分鐘(YPP 資產)
回滾條件(寫在 daily_publish.LONG_PER_CYCLE 註解):三指標全無改善且分鐘掉 >30%。
本工具**只報告不動產線**——要不要回滾由 Carson/當班 session 依報告判斷。
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"

import yt_analytics as ya  # noqa: E402

WIN_A = ("2026-07-29", "2026-08-11")   # 舊節奏
WIN_B = ("2026-08-12", "2026-08-25")   # 新節奏

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass


def _window_stats(svc, start, end):
    out = {}
    r = svc.reports().query(ids="channel==MINE", startDate=start, endDate=end,
                            metrics="views,estimatedMinutesWatched,subscribersGained").execute()
    row = (r.get("rows") or [[0, 0, 0]])[0]
    out["views"], out["minutes"], out["subs"] = row[0], row[1], row[2]
    r = svc.reports().query(ids="channel==MINE", startDate=start, endDate=end,
                            dimensions="insightTrafficSourceType",
                            metrics="views", sort="-views", maxResults=15).execute()
    src = {a: b for a, b in (r.get("rows") or [])}
    out["browse"] = src.get("BROWSE_FEATURES", 0)
    out["search"] = src.get("YT_SEARCH", 0)
    out["suggested"] = src.get("RELATED_VIDEO", 0)
    return out


def _median_views_of_window_longs(svc, yt, start, end, end_report):
    """該窗內發布的長片,截至報告日的累計觀看中位數。"""
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    longs = [(s, v) for s, v in led.items() if s.startswith("L_")]
    ids = [v for _, v in longs]
    pubs = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            pubs[it["id"]] = it["snippet"]["publishedAt"][:10]
    win = [v for v in ids if start <= pubs.get(v, "") <= end]
    if not win:
        return None, 0
    views = {}
    for i in range(0, len(win), 30):
        r = svc.reports().query(ids="channel==MINE", startDate=start, endDate=end_report,
                                dimensions="video", metrics="views",
                                filters="video==" + ",".join(win[i:i + 30]),
                                sort="-views", maxResults=100).execute()
        for vid, vw in (r.get("rows") or []):
            views[vid] = vw
    vals = [views.get(v, 0) for v in win]
    return statistics.median(vals), len(win)


def main() -> int:
    svc = ya._service()
    if svc is None:
        print("[FATAL] analytics 不可用")
        return 1
    import daily_publish as dp
    yt = dp.get_service()
    today = date.today().isoformat()

    a = _window_stats(svc, *WIN_A)
    b = _window_stats(svc, *WIN_B)
    med_a, na = _median_views_of_window_longs(svc, yt, WIN_A[0], WIN_A[1], today)
    med_b, nb = _median_views_of_window_longs(svc, yt, WIN_B[0], WIN_B[1], today)

    def pct(x, y):
        return f"{(y - x) / x * 100:+.0f}%" if x else "n/a"

    lines = [
        f"# 節奏實驗對照報告({today} 產出)",
        "",
        f"前窗(7支/天) {WIN_A[0]}~{WIN_A[1]} vs 後窗(3支/天) {WIN_B[0]}~{WIN_B[1]}",
        "",
        "| 指標 | 前窗 | 後窗 | 變化 |",
        "|---|---|---|---|",
        f"| BROWSE 觀看 | {a['browse']} | {b['browse']} | {pct(a['browse'], b['browse'])} |",
        f"| 搜尋觀看 | {a['search']} | {b['search']} | {pct(a['search'], b['search'])} |",
        f"| 推薦(related) | {a['suggested']} | {b['suggested']} | {pct(a['suggested'], b['suggested'])} |",
        f"| 總觀看 | {a['views']} | {b['views']} | {pct(a['views'], b['views'])} |",
        f"| 觀看分鐘 | {a['minutes']} | {b['minutes']} | {pct(a['minutes'], b['minutes'])} |",
        f"| 訂閱增量 | {a['subs']} | {b['subs']} | {pct(a['subs'], b['subs'])} |",
        f"| 窗內長片中位觀看 | {med_a}(n={na}) | {med_b}(n={nb}) | — |",
        "",
        "## 判讀提醒(誠實條款)",
        "- ⚠️ 前窗片齡較老、累計觀看天生佔優;「窗內長片中位」兩窗都取到報告日,",
        "  後窗片齡短,**中位持平即是進步**。",
        "- ⚠️ Analytics 延遲 2~4 天:評估日跑的話後窗尾端數據不全,兩窗要等長可比",
        "  (memory yt-analytics-lag-false-alarm)。建議 08-28 之後再跑一次定案。",
        "- 回滾條件(見 daily_publish.LONG_PER_CYCLE 註解):三指標全無改善且分鐘掉 >30%。",
        "- 本報告只陳述,不自動動產線。",
    ]
    md = "\n".join(lines)
    outp = STUDIO / "REPORTS" / f"{today}_節奏實驗對照.md"
    outp.write_text(md, encoding="utf-8")
    print(md)
    log_ops("實驗評估", f"節奏實驗對照報告已產出:{outp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
