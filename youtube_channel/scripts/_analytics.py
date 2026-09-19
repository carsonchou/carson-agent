# -*- coding: utf-8 -*-
"""抓 YouTube Analytics:整體完播率/留存 + per-video 完播率,找會紅模式。"""
import sys
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# 配額計量(全域 patch HttpRequest.execute,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass

creds = Credentials.from_authorized_user_file(str(ROOT / "token_manage.json"))
ya = build("youtubeAnalytics", "v2", credentials=creds)
yt = build("youtube", "v3", credentials=creds)
end = (date.today() - timedelta(days=1)).isoformat()
start = "2026-06-01"

try:
    # ① 整體
    r = ya.reports().query(ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched,subscribersGained").execute()
    h = r.get("columnHeaders", []); rows = r.get("rows", [[]])
    if rows and rows[0]:
        d = dict(zip([c["name"] for c in h], rows[0]))
        print(f"=== 頻道整體（{start} ~ {end}）===")
        print(f"  觀看:{d.get('views')}  平均觀看秒數:{d.get('averageViewDuration')}s")
        print(f"  ★完播率(averageViewPercentage):{d.get('averageViewPercentage')}%  (Shorts 健康線 >50-60%)")
        print(f"  總觀看分鐘:{d.get('estimatedMinutesWatched')}  新增訂閱:{d.get('subscribersGained')}")

    # ② per-video 完播率(sort by views)
    r2 = ya.reports().query(ids="channel==MINE", startDate=start, endDate=end,
        dimensions="video", metrics="views,averageViewPercentage,averageViewDuration",
        sort="-views", maxResults=25).execute()
    vrows = r2.get("rows", [])
    vids = [row[0] for row in vrows]
    titles = {}
    for i in range(0, len(vids), 50):
        vr = yt.videos().list(part="snippet", id=",".join(vids[i:i+50])).execute()
        for it in vr["items"]:
            titles[it["id"]] = it["snippet"]["title"]
    enriched = [(int(row[1]), float(row[2]), float(row[3]), titles.get(row[0], row[0])) for row in vrows]
    print(f"\n=== 完播率最高的片(看會紅模式) ===")
    for v, pct, dur, t in sorted(enriched, key=lambda x: -x[1])[:8]:
        print(f"  完播{pct:.0f}% {v}觀看 {dur:.0f}s | {t[:42]}")
    print(f"\n=== 完播率最低的片(看流量殺手) ===")
    for v, pct, dur, t in sorted(enriched, key=lambda x: x[1])[:6]:
        print(f"  完播{pct:.0f}% {v}觀看 {dur:.0f}s | {t[:42]}")
except Exception as e:
    msg = str(e)
    if "has not been used" in msg or "not enabled" in msg or "accessNotConfigured" in msg or "SERVICE_DISABLED" in msg:
        print("[需啟用] YouTube Analytics API 在你的 Google Cloud 專案還沒啟用。")
        import re
        m = re.search(r"project[s]?[/=]?\s*(\d{6,})", msg)
        print(f"  專案號:{m.group(1) if m else '見下方連結'}")
        print("  去這裡點 ENABLE(啟用),約 30 秒生效:")
        print("  https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com")
        print("  啟用後跟我說『啟用了』,我再跑一次。")
    else:
        print("[錯誤]", msg[:400])
