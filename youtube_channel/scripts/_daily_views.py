#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""診斷:近 28 天每日觀看曲線(day 維度 API 可用),判斷流量是真跌還是即時圖尖峰回落。只讀。"""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import yt_analytics as ya

svc = ya._service()
if svc is None:
    print("analytics 不可用"); raise SystemExit(0)
end = date.today(); start = end - timedelta(days=28)
r = svc.reports().query(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                        dimensions="day", metrics="views,estimatedMinutesWatched,subscribersGained",
                        sort="day").execute()
rows = r.get("rows", [])
print("日期        觀看   分鐘   訂閱")
vals = []
for d, v, m, s in rows:
    print(f"{d}  {v:>5}  {m:>5}  {s:>3}")
    vals.append(v)
if len(vals) >= 14:
    first14 = sum(vals[:14]); last14 = sum(vals[-14:])
    print(f"\n前14天觀看合計 {first14} → 後14天 {last14}  變化 {round((last14-first14)/max(first14,1)*100)}%")
    print(f"近7天日均 {round(sum(vals[-7:])/7)} vs 前7天日均 {round(sum(vals[-14:-7])/7)}")
