# -*- coding: utf-8 -*-
"""_traffic_why.py — 診斷「觀看數為何突然變高」：流量來源 + 每日趨勢 + 近7天爆量片。"""
import sys, json
sys.path.insert(0, "scripts")
from pathlib import Path
from datetime import date, timedelta
import yt_analytics as ya

svc = ya._service()
if svc is None:
    print("NO_TOKEN"); sys.exit(0)

end = date.today()

def q(**kw):
    try:
        return svc.reports().query(ids="channel==MINE", **kw).execute().get("rows", [])
    except Exception as e:
        return [("ERR", str(e))]

# 1) 每日觀看趨勢（近14天）
print("=== 每日觀看(近14天) ===")
for r in q(startDate=(end-timedelta(days=14)).isoformat(), endDate=end.isoformat(),
           dimensions="day", metrics="views,estimatedMinutesWatched,subscribersGained", sort="day"):
    print(r)

# 2) 流量來源(近7天) —— 回答「為什麼」的關鍵
print("\n=== 流量來源(近7天) views ===")
for r in q(startDate=(end-timedelta(days=7)).isoformat(), endDate=end.isoformat(),
           dimensions="insightTrafficSourceType", metrics="views,averageViewPercentage", sort="-views"):
    print(r)

# 3) 近7天爆量片 + 留存
print("\n=== 近7天 top 影片 ===")
vids = q(startDate=(end-timedelta(days=7)).isoformat(), endDate=end.isoformat(),
         dimensions="video", metrics="views,averageViewPercentage,subscribersGained", sort="-views", maxResults=8)
# 對照標題
titles = {}
p = Path("STUDIO/channel_videos.json")
if p.exists():
    try:
        cv = json.loads(p.read_text(encoding="utf-8"))
        items = cv if isinstance(cv, list) else cv.get("videos", cv.get("items", []))
        for it in items:
            vid = it.get("video_id") or it.get("id") or it.get("videoId")
            t = it.get("title") or it.get("name")
            if vid and t: titles[vid] = t
    except Exception: pass
for r in vids:
    vid = r[0]
    print(r, "|", titles.get(vid, "?")[:30])

# 4) 對照:近7天 vs 前7天總量
print("\n=== 週對週 ===")
cur = q(startDate=(end-timedelta(days=7)).isoformat(), endDate=end.isoformat(), metrics="views")
prev = q(startDate=(end-timedelta(days=14)).isoformat(), endDate=(end-timedelta(days=7)).isoformat(), metrics="views")
print("近7天:", cur, " 前7天:", prev)
