#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retention_dept.py — 逐段留存分析(A3,已驗 API 可行)。

用 YouTube Analytics audienceRetention(dimension=elapsedVideoTimeRatio)抓每支片的留存曲線,
找觀眾在「影片幾成處」流失最兇,聚合判斷是:
  - 開頭就掉(前 15%)= 鉤子問題 → 該加強 HOOK 前 3 秒
  - 中段掉 = 拖沓 → 該加快節奏/每 3-4 秒一個衝擊點
把結論寫進 STUDIO/retention_insights.json,可餵決策/寫稿參考。全唯讀不改產線。

用法:python scripts/retention_dept.py [--top N] [--notify]
"""
from __future__ import annotations
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"

import studio_common as sc


def _top_video_ids(n=8):
    """取觀看最高的 n 支已發布 videoId(從 quality_scores + analytics_cache)。"""
    q = sc.load_json_safe(STUDIO / "quality_scores.json", {}) or {}
    ids = [x.get("videoId") for x in (q.get("published") or []) if x.get("videoId")]
    # 用 analytics_cache 的 per-video views 排序
    import glob
    import json
    best = {}
    for f in glob.glob(str(STUDIO / "analytics_cache" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d and all(isinstance(v, dict) and "views" in v for v in d.values()):
            if len(d) > len(best):
                best = d
    ranked = sorted(best.items(), key=lambda kv: -(kv[1].get("views", 0)))
    return [vid for vid, _ in ranked[:n]] or ids[:n]


def _curve(ya_svc, vid):
    end = date.today(); start = end - timedelta(days=90)
    try:
        r = ya_svc.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio",
            filters=f"video=={vid}", sort="elapsedVideoTimeRatio",
        ).execute()
        return [(row[0], row[1]) for row in r.get("rows", [])]
    except Exception:  # noqa: BLE001
        return []


def _biggest_drop(curve):
    """回傳最大單段跌幅發生的時間比例(0-1)與跌幅。"""
    worst_r, worst_d = None, 0.0
    for i in range(1, len(curve)):
        d = curve[i - 1][1] - curve[i][1]  # 前一段 - 這段(正=下跌)
        if d > worst_d:
            worst_d, worst_r = d, curve[i][0]
    return worst_r, worst_d


def main() -> int:
    n = 8
    if "--top" in sys.argv:
        try:
            n = int(sys.argv[sys.argv.index("--top") + 1])
        except Exception:  # noqa: BLE001
            pass
    try:
        import yt_analytics as ya
        svc = ya._service()
    except Exception:  # noqa: BLE001
        svc = None
    if svc is None:
        print("[retention] analytics 不可用,跳過。")
        return 0

    early_drops, mid_drops, samples = 0, 0, []
    for vid in _top_video_ids(n):
        curve = _curve(svc, vid)
        if len(curve) < 5:
            continue
        r, d = _biggest_drop(curve)
        if r is None:
            continue
        where = "開頭(鉤子)" if r <= 0.15 else ("中段(拖沓)" if r <= 0.7 else "結尾")
        if r <= 0.15:
            early_drops += 1
        elif r <= 0.7:
            mid_drops += 1
        samples.append({"video": vid, "drop_at": round(r, 2), "drop_size": round(d, 3), "where": where})

    verdict = "資料不足"
    if samples:
        if early_drops >= mid_drops and early_drops > 0:
            verdict = "最大流失多在【開頭】→ 鉤子是主戰場:強化前 3 秒具體數字+反直覺,別鋪陳"
        elif mid_drops > 0:
            verdict = "最大流失多在【中段】→ 節奏問題:每 3-4 秒一個衝擊點/轉折,砍掉拖沓段"
    data = {"updated": time.strftime("%Y-%m-%d %H:%M"), "analyzed": len(samples),
            "early_drops": early_drops, "mid_drops": mid_drops, "verdict": verdict, "samples": samples[:12]}
    sc.save_json_atomic(STUDIO / "retention_insights.json", data)
    print(f"[retention] 分析 {len(samples)} 支｜開頭掉 {early_drops}、中段掉 {mid_drops}")
    print(f"[retention] 結論:{verdict}")
    print(f"[ok] 已寫入 {STUDIO / 'retention_insights.json'}")
    if "--notify" in sys.argv:
        try:
            import notify
            notify.push("量化阿森｜逐段留存", verdict, tag="chart_with_downwards_trend")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 失敗:{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
