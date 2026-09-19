#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report.py — 副頻道 They Ran It Again 的成績單(唯讀,不改任何東西)。

## 這支要回答什麼
「這個題材在一個零訂閱的新頻道上跑不跑得動」。要回答它必須小心三件事,
主頻道全部踩過:

- **Analytics 有 2~4 天延遲**。錨在今天做週對週會拿 4 天比 7 天,我因此
  報過一次假的「流量 −54%」(真值 −14%)。所以這支**先印出資料到哪一天**,
  而且只在等長區間內比較。
- **videos.list 才是真觀看數**,Analytics 的影片排行是 Top-200 截斷。
- **訂閱轉化要扣掉訂閱者來源**。新頻道還沒有訂閱者所以現在不影響,但
  規則先寫在這裡,免得以後有了又忘記(主頻道爆款 88~96% 觀看是自己人重看)。

## 配額
videos.list 每次 1 單位(可批 50 支);Analytics 走**自己的配額池**,
不吃 Data API 的 10,000。所以這支幾乎不花錢,可以常跑。

用法:
  python report.py
  python report.py --days 7
"""
import argparse
import json
import pathlib
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded.json"
META = ROOT / "publish_meta.json"
CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"


def svc(name, ver, token, scopes):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    p = CH2 / token
    cr = Credentials.from_authorized_user_file(str(p), scopes)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        p.write_text(cr.to_json(), encoding="utf-8")
    return build(name, ver, credentials=cr, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()

    led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    if not led:
        print("還沒發過任何一支。")
        return 0
    meta = {(o.get("slug") or o["dir"]): o
            for o in json.loads(META.read_text(encoding="utf-8"))}

    yt = svc("youtube", "v3", "token.json",
             ["https://www.googleapis.com/auth/youtube.readonly"])

    # ── 頻道層 ──
    ch = yt.channels().list(part="statistics,snippet", id=CHANNEL).execute()
    st = ch["items"][0]["statistics"]
    print(f"頻道:{ch['items'][0]['snippet']['title']}")
    print(f"  訂閱 {int(st.get('subscriberCount', 0)):,}  "
          f"總觀看 {int(st.get('viewCount', 0)):,}  "
          f"影片 {int(st.get('videoCount', 0)):,}\n")

    # ── 每支片:videos.list 才是真觀看數(Analytics 排行是 Top-200 截斷)──
    ids = list(led.values())
    rows = []
    for i in range(0, len(ids), 50):
        got = yt.videos().list(part="statistics,snippet,contentDetails",
                               id=",".join(ids[i:i + 50])).execute()
        for v in got.get("items", []):
            key = next((k for k, x in led.items() if x == v["id"]), v["id"])
            s = v["statistics"]
            rows.append({
                "key": key, "id": v["id"],
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
                "published": v["snippet"]["publishedAt"][:16].replace("T", " "),
                "tone": meta.get(key, {}).get("tone", "?"),
                "title": v["snippet"]["title"],
            })
    rows.sort(key=lambda r: -r["views"])
    total = sum(r["views"] for r in rows)
    print(f"已發 {len(rows)} 支,合計 {total:,} 次觀看"
          f"(平均 {total / max(1, len(rows)):.1f})\n")
    print(f"  {'觀看':>5} {'讚':>4} {'留言':>4}  {'定調':<12}{'發布時間':<17}標題")
    for r in rows:
        print(f"  {r['views']:>5} {r['likes']:>4} {r['comments']:>4}  "
              f"{r['tone']:<12}{r['published']:<17}{r['title'][:52]}")

    # ── Analytics:先確認資料到哪一天,再比等長區間 ──
    try:
        an = svc("youtubeAnalytics", "v2", "token_analytics.json",
                 ["https://www.googleapis.com/auth/yt-analytics.readonly"])
        end = date.today() - timedelta(days=1)
        res = an.reports().query(
            ids=f"channel=={CHANNEL}", startDate="2026-08-01",
            endDate=end.isoformat(), metrics="views,estimatedMinutesWatched",
            dimensions="day", sort="day").execute()
        got = res.get("rows") or []
        if not got:
            print("\nAnalytics:尚無資料(新片通常要 1~2 天才會出現)")
        else:
            last = got[-1][0]
            print(f"\nAnalytics 資料到 {last}"
                  f"(⚠️ 延遲 2~4 天,別拿它跟今天比)")
            recent = got[-a.days:]
            v = sum(r[1] for r in recent)
            m = sum(r[2] for r in recent)
            print(f"  最近 {len(recent)} 天:觀看 {v:,}  觀看分鐘 {m:,}")
            if v:
                print(f"  平均每次觀看 {m * 60 / v:.0f} 秒")
    except Exception as e:                                   # noqa: BLE001
        print(f"\nAnalytics 取不到:{str(e)[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
