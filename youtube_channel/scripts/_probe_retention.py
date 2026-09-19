#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A3 探針:測 YouTube Analytics API 的 audienceRetention(逐段留存)本頻道拿不拿得到。
拿得到→值得建 retention_dept;拿不到(Studio 限定)→誠實跳過。只讀不改。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import yt_analytics as ya
from datetime import date, timedelta

ya_svc = ya._service()
if ya_svc is None:
    print("[probe] analytics service 不可用(token_analytics.json 缺?)")
    raise SystemExit(0)

# 拿一支有觀看的影片 id
vid = "U-9oBiQLmJA"  # ALL IN 0050 那支 829 觀看
end = date.today(); start = end - timedelta(days=90)
try:
    r = ya_svc.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio,relativeRetentionPerformance",
        filters=f"video=={vid}",
    ).execute()
    rows = r.get("rows", [])
    print(f"[probe] ✓ 拿得到! elapsedVideoTimeRatio 段數={len(rows)}")
    if rows:
        print("  前3段(時間比例, 觀看比例, 相對表現):", rows[:3])
        print("  → A3 可行,值得建 retention_dept 找 drop-off 段")
    else:
        print("  回應成功但無資料列(該片可能觀看太少)")
except Exception as e:
    print(f"[probe] ✗ 拿不到:{str(e)[:180]}")
    print("  → A3 不可行(API Studio 限定),誠實跳過,不假裝")
