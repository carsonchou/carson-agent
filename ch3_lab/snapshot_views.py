#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_views.py — 把每支片的觀看數落成一筆帶時間戳的快照。

## 為什麼需要
2026-08-29 早上發現 `ep001` 的 Short 有 107 次觀看(全頻道其餘 0~9)。
那是這條線第一次拿到分發。但我**沒有辦法知道它是什麼時候長出來的**,
也沒辦法知道新發的那幾支是「真的沒人看」還是「才 8 小時還沒開始」——
因為手上只有一個時間點的值。

一個數字不是趨勢。要回答「改版有沒有用」就得有**同一支片在不同時間**
的值,而那必須從今天開始存。

⚠️ 觀看數走 `videos.list`,不要走 Analytics 的影片排行 ——
那個排行是 Top200 截斷,不是真值(memory yt-search-entry-decides-views)。
頻道層級的 `viewCount` 也會落後(現在顯示 3,而逐支加起來是 138),
所以**只信逐支的值**。

配額:videos.list 每 50 支 1 單位。

用法:
  python snapshot_views.py           # 抓一次,附加到 views_history.jsonl
  python snapshot_views.py --report  # 印出每支的成長(需要至少兩筆快照)
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
OUT = ROOT / "views_history.jsonl"
LEDGERS = ["uploaded.json", "uploaded_shorts.json", "uploaded_comp.json"]


def svc():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(
        str(CH2 / "token_manage.json"),
        ["https://www.googleapis.com/auth/youtube.force-ssl",
         "https://www.googleapis.com/auth/youtube.readonly"])
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def all_videos():
    """key → (videoId, 哪一本帳)。key 在不同帳本間可能同名(ep001 長片與
    Short 都叫 ep001),所以帶上帳本名才唯一。"""
    out = {}
    for name in LEDGERS:
        p = ROOT / name
        if not p.exists():
            continue
        kind = {"uploaded.json": "long", "uploaded_shorts.json": "short",
                "uploaded_comp.json": "comp"}[name]
        for k, v in json.loads(p.read_text(encoding="utf-8")).items():
            out[f"{kind}/{k}"] = v
    return out


def grab():
    yt = svc()
    vids = all_videos()
    ids = list(vids.values())
    stats = {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="statistics,snippet",
                                  id=",".join(ids[i:i + 50])).execute()["items"]:
            stats[v["id"]] = v
    row = {"at": datetime.now().isoformat(timespec="seconds"), "v": {}}
    for key, vid in vids.items():
        v = stats.get(vid)
        if not v:
            continue
        row["v"][key] = {
            "id": vid,
            "views": int(v["statistics"].get("viewCount", 0)),
            "likes": int(v["statistics"].get("likeCount", 0)),
            "published": v["snippet"]["publishedAt"],
        }
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tot = sum(x["views"] for x in row["v"].values())
    print(f"快照 {row['at']}:{len(row['v'])} 支,總觀看 {tot}")
    return row


def report():
    if not OUT.exists():
        print("還沒有任何快照"); return 1
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) < 2:
        print(f"只有 {len(rows)} 筆快照 —— **一個數字不是趨勢**,"
              f"至少要兩筆才算得出成長。"); return 1
    a, b = rows[-2], rows[-1]
    print(f"{a['at']} → {b['at']}")
    for key in sorted(b["v"], key=lambda k: -(b["v"][k]["views"]
                                              - a["v"].get(k, {}).get("views", 0))):
        now = b["v"][key]["views"]
        was = a["v"].get(key, {}).get("views")
        d = "(新)" if was is None else f"{now - was:+d}"
        print(f"  {key:28s} {now:>5d}  {d}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    return report() if a.report else (grab() and 0)


if __name__ == "__main__":
    sys.exit(main())
