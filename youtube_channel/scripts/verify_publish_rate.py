#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""驗收「11 支/天到底划不划算」—— 2026-09-15 之後才有資料可跑。

## 這支存在的理由

2026-09-01 把發布量從 8 推到 11 支/天,而 memory `yt-search-entry-decides-views` 有一張表
暗示發布量與每支觀看是負相關(1-8支→118、9-20支→73,n=14),若成立則總觀看反而少 15%。

當天用全樣本查證的結論是:**假設沒被證實也沒被推翻,因為新時代從來沒跑過 9+ 支/日** ——
那一格 37 支 100% 發布於 2026-06-23~06-30(頻道起飛前)。09-01 是第一次跑 11 支。

所以答案只能等資料長出來。這支把當天的分析設計固定下來,免得到時重推一次
(而且重推很可能又踩同一個坑,見下)。

## 三個必須遵守的方法約束(當天各踩過一次)

1. **用 `videos.list part=statistics` 取全樣本,不用 Analytics 的
   `dimensions=video&sort=-views&maxResults=200`** —— 後者是 Top-200 硬截斷
   (`limit` 調到 1200 仍只回 200),而 r(觀看數,留存) = -0.406,
   截斷樣本會偏向「看起來像輸家」那端。本專案已在這上面錯過三次。
2. **必須控制片齡**。不控制的話 9+ 支那格看起來崩到 2 次觀看,
   而那是**時代差異**(六月舊片)不是產量效應。同一個陷阱 09-01 當天踩了兩次。
3. **只取成熟片**(發布滿 14 天)。memory `yt-video-lifespan-4days` 說本頻道片約 4 天停止成長,
   但體檢片是常青(`yt-search-capture-engine`),14 天是保守值。

## 目標函數

不是「支/日」,是 **每日總觀看 = 當日支數 × 該支數區間的觀看中位數**。
再乘每次秒數換成小時。找讓這個乘積最大的支數。

用法:
  python scripts/verify_publish_rate.py              # 完整報告
  python scripts/verify_publish_rate.py --min-age 21 # 改成熟門檻
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
TW = ZoneInfo("Asia/Taipei")


def bucket(n: int) -> str:
    return "1-2" if n <= 2 else "3-5" if n <= 5 else "6-8" if n <= 8 else \
        "9-11" if n <= 11 else "12+"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-age", type=int, default=14, help="成熟門檻(天)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import daily_publish as dp
    yt = dp.get_service()
    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    rev = {v: k for k, v in led.items()}
    ids = list(led.values())

    info = {}
    for i in range(0, len(ids), 50):        # 50 支 1 unit,全樣本約 21 units
        r = yt.videos().list(part="snippet,statistics", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            u = dt.datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00"))
            info[it["id"]] = {"day": u.astimezone(TW).date(),
                              "views": int(it.get("statistics", {}).get("viewCount", 0)),
                              "slug": rev.get(it["id"], "")}

    today = dt.date.today()
    long_by_day = collections.Counter(v["day"] for v in info.values()
                                      if v["slug"].startswith("L_"))
    mature = [v for v in info.values()
              if v["slug"].startswith("L_") and (today - v["day"]).days >= a.min_age]
    print(f"全樣本 {len(info)} 支;已成熟長片(>= {a.min_age} 天){len(mature)} 支\n")

    # ── 表一:控制片齡(不控制會得到假崩塌)────────────────────────────────
    print("【表一】控制片齡 — 每格 = 觀看中位(n)")
    bands = [(a.min_age, 30, f"{a.min_age}~30天"), (31, 60, "31~60天"), (61, 999, "61天以上")]
    cols = ["1-2", "3-5", "6-8", "9-11", "12+"]
    print("  " + "片齡".ljust(10) + "".join(c.rjust(11) for c in cols))
    for lo, hi, lab in bands:
        row = collections.defaultdict(list)
        for v in mature:
            age = (today - v["day"]).days
            if lo <= age <= hi:
                row[bucket(long_by_day[v["day"]])].append(v["views"])
        cells = []
        for c in cols:
            x = row.get(c) or []
            cells.append(f"{statistics.median(x):.0f}(n={len(x)})" if len(x) >= 5
                         else f"n={len(x)}")
        print("  " + lab.ljust(10) + "".join(s.rjust(11) for s in cells))

    # ── 表二:每格的片齡分布(用來看有沒有「某一格全是舊片」)──────────────
    print("\n【表二】每個支數區間的片齡中位 — 若某格明顯偏老,那格的低觀看是時代不是產量")
    for c in cols:
        ages = [(today - v["day"]).days for v in mature
                if bucket(long_by_day[v["day"]]) == c]
        if len(ages) >= 5:
            print(f"  {c:<6}n={len(ages):<4}片齡中位 {statistics.median(ages):.0f} 天"
                  f"(最小 {min(ages)} / 最大 {max(ages)})")

    # ── 表三:目標函數 ────────────────────────────────────────────────
    print("\n【表三】每日總觀看 = 支數 × 該區間觀看中位(只用最成熟且 n>=10 的片齡帶)")
    best = None
    for lo, hi, lab in bands:
        row = collections.defaultdict(list)
        for v in mature:
            age = (today - v["day"]).days
            if lo <= age <= hi:
                row[bucket(long_by_day[v["day"]])].append(v["views"])
        if not any(len(x) >= 10 for x in row.values()):
            continue
        print(f"  片齡 {lab}:")
        mid = {"1-2": 2, "3-5": 4, "6-8": 7, "9-11": 10, "12+": 13}
        for c in cols:
            x = row.get(c) or []
            if len(x) < 5:
                continue
            tot = mid[c] * statistics.median(x)
            print(f"    {c:<6}{mid[c]:>3} 支 × {statistics.median(x):>6.0f} = {tot:>8.0f}"
                  f"   (n={len(x)})")
            if best is None or tot > best[1]:
                best = (c, tot, lab, len(x))
    if best:
        print(f"\n  → 峰值落在 {best[0]} 支區間(片齡 {best[2]},n={best[3]})")
        print("  ⚠️ 要看 n:n<20 的差距撐不起結論;不同片齡帶排序不一致代表雜訊大於訊號。")
    print("\n判讀:峰值明顯低於 11 → 發得更少但更好,配額壓力同時解掉。"
          "\n      峰值 >= 11 或各帶排序不一致 → 維持,不要用感覺調參數。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
