#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchtime_lever.py — 「每次觀看時長」到底怎麼拉:拿真 Analytics 算,不猜。

## 為什麼要算這個
頻道的引擎是**台股個股名的搜尋佔位**(近 28 天 YT_SEARCH 佔 21.5% 觀看但 **40% 的觀看時數**,
BROWSE 推薦 = 0)。YPP 的門檻是**觀看時數**,而時數 = 觀看次數 × 每次觀看時長。
覆蓋率(多發片)拉的是前者,但前者要靠產能;後者是**同一支片、同樣的曝光**就能改的,
理論上最便宜。問題是「拉時長」有兩種完全相反的做法:
  A. 片拍長一點(分母變大)—— 但實測 >10 分鐘**絕對觀看分鐘數不增反減**
  B. 讓人看久一點(完播率變高)
所以動手之前必須先量:時數到底卡在哪個因子上、以及**哪個片長帶真的最會累積時數**。

## 誠實邊界(先寫在這裡免得自己忘)
- Analytics 的 video 維度是 **Top-200 截斷**,不是全頻道真值(本專案踩過兩次)。
  所以這裡算出來的是「**貢獻絕大多數時數的那批片**」的結構,不能當成全頻道平均。
- Analytics 有 2~4 天延遲,endDate 一律往回抓,不要錨在 today。
- 片長取本機 mp4 的實際長度(ffprobe),不是估的;結果寫進快取,重跑不必重掃。

用法:
  python scripts/watchtime_lever.py              # 近 28 天(自動避開延遲)
  python scripts/watchtime_lever.py --days 90
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
DURCACHE = STUDIO / "video_durations.json"
LAG_DAYS = 4          # Analytics 延遲;錨在 today 會拿 4 天比 7 天(本專案報過假警報)


def _load_dur():
    try:
        return json.loads(DURCACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _probe(slug):
    p = ROOT / "output" / f"{slug}.mp4"
    if not p.exists():
        return slug, None
    try:
        o = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return slug, round(float(o), 1)
    except Exception:  # noqa: BLE001
        return slug, None


def durations(slugs):
    """片長(秒),帶磁碟快取。第一次會慢(ffprobe 每支開一次 process),之後幾乎免費。"""
    cache = _load_dur()
    todo = [s for s in slugs if s not in cache]
    if todo:
        print(f"  (ffprobe 掃 {len(todo)} 支新片長…)", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for slug, d in ex.map(_probe, todo):
                cache[slug] = d
        DURCACHE.parent.mkdir(parents=True, exist_ok=True)
        DURCACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    args = ap.parse_args()

    import yt_analytics as ya
    end = date.today() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=args.days - 1)
    print(f"期間 {start} ~ {end}(已扣 Analytics {LAG_DAYS} 天延遲)")

    s = ya._service()
    r = s.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views,estimatedMinutesWatched,averageViewDuration",
        dimensions="video", sort="-estimatedMinutesWatched", maxResults=200).execute()
    rows = r.get("rows", [])
    if len(rows) >= 200:
        print("⚠️ 回傳滿 200 列 = **Top-200 截斷**,以下是『貢獻最多時數的那批片』的結構,不是全頻道平均。")

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    v2s = {v: k for k, v in led.items() if isinstance(v, str) and len(v) == 11}
    slugs = [v2s[v[0]] for v in rows if v[0] in v2s]
    dur = durations(slugs)

    longs = []
    for vid, views, mins, avg in rows:
        slug = v2s.get(vid)
        d = dur.get(slug) if slug else None
        if not slug or not slug.startswith("L_") or not d:
            continue
        longs.append({"vid": vid, "slug": slug, "views": views, "mins": mins,
                      "avg": avg, "dur": d, "pct": avg / d * 100})

    tv = sum(x["views"] for x in longs)
    tm = sum(x["mins"] for x in longs)
    print(f"\n長片 {len(longs)} 支:觀看 {tv:,}、時數 {tm/60:,.0f} 小時、"
          f"平均每次觀看 {tm*60/max(tv,1):.0f} 秒")

    import statistics as st
    order = ["<6分", "6-8分", "8-10分", "10-12分", ">12分"]

    def bucket(d):
        return ("<6分" if d < 360 else "6-8分" if d < 480 else
                "8-10分" if d < 600 else "10-12分" if d < 720 else ">12分")

    bs = {}
    for x in longs:
        bs.setdefault(bucket(x["dur"]), []).append(x)
    print(f"\n{'片長':>7} {'支數':>4} {'中位觀看':>8} {'中位每次觀看':>12} {'中位完播%':>9} "
          f"{'總時數hr':>9} {'每支平均時數hr':>13}")
    for b in order:
        g = bs.get(b)
        if not g:
            continue
        print(f"{b:>7} {len(g):>4} {st.median(x['views'] for x in g):>8.0f} "
              f"{st.median(x['avg'] for x in g):>11.0f}秒 {st.median(x['pct'] for x in g):>8.1f} "
              f"{sum(x['mins'] for x in g)/60:>9.1f} {sum(x['mins'] for x in g)/60/len(g):>13.2f}")

    # 槓桿試算:時數 = 觀看 × 每次觀看時長。兩條路各自要付什麼代價?
    cur_avg = tm * 60 / max(tv, 1)
    print(f"\n── 槓桿試算(目前每次觀看 {cur_avg:.0f} 秒)──")
    for tgt in (cur_avg * 1.25, cur_avg * 1.5, 210):
        print(f"  每次觀看拉到 {tgt:>3.0f} 秒 → 同樣觀看數,時數 "
              f"{tm/60*tgt/cur_avg:,.0f} 小時(×{tgt/cur_avg:.2f})")
    best = max(((b, sum(x['mins'] for x in g) / 60 / len(g)) for b, g in bs.items() if len(g) >= 5),
               key=lambda kv: kv[1], default=None)
    if best:
        print(f"  每支平均最會累積時數的片長帶:**{best[0]}**({best[1]:.2f} hr/支)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
