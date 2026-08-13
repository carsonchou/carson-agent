#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""beachhead_tracker.py — 外部分發灘頭指標:每日記錄「非訂閱者來源」觀看。

## 為什麼(2026-08-13,memory yt-subscriber-feed-pollution)
解剖實測:頻道「爆款」觀看 88~96% 來自訂閱者 feed(157 人重複看)——外部分發≈0。
總觀看/總訂閱這類指標全被老訂戶污染;**頻道成長的唯一北極星=非訂閱者來源的觀看**
(搜尋+推薦+首頁+Shorts feed+外部)。本工具每日把它拆出來寫進 ops_log 與
STUDIO/beachhead_history.jsonl,讓每個 session/report 都看得到灘頭有沒有動。

唯讀 Analytics;fail-open(API 失敗只記警告,不影響任何產線)。
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "STUDIO" / "beachhead_history.jsonl"

import yt_analytics as ya  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):
        pass


def main() -> int:
    svc = ya._service()
    if svc is None:
        print("[warn] analytics 不可用,跳過")
        return 0
    # Analytics 延遲 2~4 天:取「4 天前」單日做定錨(數據已穩),避免假警報(memory 教訓)
    day = (date.today() - timedelta(days=4)).isoformat()
    try:
        r = svc.reports().query(ids="channel==MINE", startDate=day, endDate=day,
                                dimensions="insightTrafficSourceType",
                                metrics="views,estimatedMinutesWatched",
                                sort="-views", maxResults=15).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 查詢失敗:{str(exc)[:100]}")
        return 0
    rows = r.get("rows") or []
    total = sum(x[1] for x in rows)
    sub = next((x[1] for x in rows if x[0] == "SUBSCRIBER"), 0)
    ext = total - sub
    detail = {x[0]: x[1] for x in rows if x[0] != "SUBSCRIBER"}
    rec = {"date": day, "total": total, "subscriber": sub, "external": ext,
           "external_pct": round(ext / total * 100, 1) if total else 0.0,
           "sources": detail}
    HIST.parent.mkdir(parents=True, exist_ok=True)
    # 冪等:同一天已記過就跳過(cron 重跑/補跑不會重覆)
    if HIST.exists():
        for ln in HIST.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(ln).get("date") == day:
                    print(f"[skip] {day} 已記錄")
                    return 0
            except Exception:  # noqa: BLE001
                continue
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    top = "、".join(f"{k}:{v}" for k, v in sorted(detail.items(), key=lambda kv: -kv[1])[:3])
    log_ops("灘頭指標", f"{day} 非訂閱者觀看 {ext}/{total}({rec['external_pct']}%)｜{top}")
    print(f"[ok] {day} 外部觀看 {ext}/{total} ({rec['external_pct']}%) → {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
