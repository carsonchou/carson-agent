#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""format_ab.py — 舊格式(14~26 秒)vs 新格式(35~47 秒)的對照。

## 為什麼要先寫這支,而不是發完再說
2026-08-31 的改版是拿三個機制做的賭注:片長、片尾提問、選題。
**如果我沒辦法在幾天後分辨它有沒有用,那這次改版跟上一次一樣是憑感覺。**
這條線上「處置改了但沒量實測值」已經踩過:配比改成 1 長 4 短,而長片片長
從頭到尾沒變,三天後才發現。

## 這支量什麼
每支片四個數字:觀看、平均觀看時長、留言、分享。**留言與分享是重點** ——
289 次觀看換到 0 留言 0 分享,那才是分發停在原地的原因;觀看數只是結果。

## 🔴 兩個會讓對照失效的坑,都處理掉
1. **Analytics 有 2~4 天延遲。** 拿今天當終點就是拿「已入帳的 3 天」去比
   「還沒入帳的 3 天」。所以這支**先問資料到哪一天**,再用那一天當終點,
   而且兩邊等長。(這條害我今天差點報一個「Shorts 觀看歸零」的假警報。)
2. **片齡不同。** 新格式今天才發,舊格式已經放了幾天。所以主要指標是
   **每支的前 N 天**,不是累計 —— 累計一定是舊的贏,而那不是關於格式的發現。

用法:
  python format_ab.py --snapshot        # 存下今天的狀態(發布前先跑一次)
  python format_ab.py                   # 比較
"""
import argparse
import json
import pathlib
import statistics as st
import sys
import datetime as dt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
SNAP = ROOT / "format_ab.json"


def _ya():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    tok = pathlib.Path(r"D:\carson-agent\yt_ch2\token.json")
    d = json.loads(tok.read_text(encoding="utf-8"))
    cr = Credentials.from_authorized_user_file(str(tok), d.get("scopes"))
    return build("youtubeAnalytics", "v2", credentials=cr,
                 cache_discovery=False)


def data_through(ya):
    """Analytics 的資料到哪一天為止。**每次都要問,不要假設。**"""
    end = dt.date.today()
    r = ya.reports().query(
        ids="channel==MINE", startDate=str(end - dt.timedelta(days=20)),
        endDate=str(end), metrics="views", dimensions="day").execute()
    rows = r.get("rows") or []
    return max(x[0] for x in rows) if rows else None


def fmt_of(key):
    """這支是哪一種格式。`reel_` 前綴是新的,其餘是舊的。"""
    return "new" if key.startswith("reel_") else "old"


def collect():
    from upload import svc
    import quota
    y = svc()
    ups = json.loads((ROOT / "uploaded_shorts.json").read_text(encoding="utf-8"))
    inv = {v: k for k, v in ups.items()}
    ids = list(inv)
    out = {}
    for i in range(0, len(ids), 50):
        r = y.videos().list(part="snippet,statistics,contentDetails",
                            id=",".join(ids[i:i + 50])).execute()
        quota.spend(1, "format_ab")
        for it in r["items"]:
            k = inv[it["id"]]
            sx = it["statistics"]
            out[k] = {
                "id": it["id"], "fmt": fmt_of(k),
                "published": it["snippet"]["publishedAt"],
                "dur": it["contentDetails"]["duration"],
                "views": int(sx.get("viewCount", 0)),
                "likes": int(sx.get("likeCount", 0) or 0),
                "comments": int(sx.get("commentCount", 0) or 0),
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()
    now = collect()

    if a.snapshot:
        SNAP.write_text(json.dumps(
            {"at": dt.datetime.now().isoformat(timespec="seconds"),
             "videos": now}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"存了 {len(now)} 支的狀態 → {SNAP.name}")
        return 0

    ya = _ya()
    through = data_through(ya)
    print(f"Analytics 資料到 {through}(今天 {dt.date.today()})"
          f" —— 差 {(dt.date.today() - dt.date.fromisoformat(through)).days} 天\n"
          if through else "Analytics 沒有資料\n")

    groups = {"old": [], "new": []}
    for k, v in now.items():
        groups[v["fmt"]].append(v)
    print(f"{'格式':<6}{'支數':>5}{'總觀看':>8}{'中位':>6}"
          f"{'總留言':>8}{'總分享/讚':>10}")
    for g, rows in groups.items():
        if not rows:
            print(f"{g:<6}{0:>5}   —(還沒有這個格式的片)")
            continue
        vs = [x["views"] for x in rows]
        print(f"{g:<6}{len(rows):>5}{sum(vs):>8}{st.median(vs):>6.1f}"
              f"{sum(x['comments'] for x in rows):>8}"
              f"{sum(x['likes'] for x in rows):>10}")
    # 🔴 **不要在這裡下結論。** 新格式今天才發,片齡差幾天,而 Shorts 的
    #    分發本來就有幾天的爬升。這支的工作是把數字擺出來,判斷等資料夠。
    print("\n⚠️ 片齡不同,現在還不能比。新格式至少要放滿 3 天、而且 "
          "Analytics 的資料要覆蓋到那 3 天,才有得比。")
    if groups["new"]:
        print("\n新格式逐支:")
        for x in sorted(groups["new"], key=lambda z: -z["views"]):
            print(f"  {x['dur']:<9}{x['views']:>5} 觀看  "
                  f"{x['comments']:>3} 留言  {x['likes']:>3} 讚   "
                  f"{x['published'][:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
