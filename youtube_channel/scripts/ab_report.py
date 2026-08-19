#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_report.py — 開場結構 A/B 實驗的結果報告(只報告,不動產線)。

## 為什麼要做實驗(2026-08-19)
長片留存中位 22.3%、平均只看 115 秒,是 BROWSE(首頁推薦)基線為 0 的直接原因。
留存曲線把斷崖定位在第 15~25 秒,逐字對照就是「節目預告+頻道自我介紹」那三句。
因果看起來很清楚——但同一天我用**觀察性數據**驗了四個同樣清楚的假說,三個被推翻,
其中「前 40 秒端出對比數字」還是反向的。真長片彼此的混淆變數(片長、題材、
發布日競爭、股票熱度)比效果本身大,觀察性數據切不出因果,所以改用隨機分組。

## 這支怎麼判讀
· 分組來自 output/<slug>.ab.txt(產片當下寫的,不是事後貼的)。
· 留存用 averageViewPercentage,**只取片長 >5 分鐘的真長片**——留存與片長
  r=-0.675,混進短片會讓兩組的差異完全被片長蓋掉。
· 每組 n<8 一律**不下結論**。這條是硬規:本專案已經有兩次拿 n=2 的樣本下結論的紀錄。
· 差異用 Mann-Whitney U(不假設常態,樣本小時比 t 檢定穩)。p<0.05 才算有訊號。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT = ROOT / "output"
MIN_N = 8
MIN_DUR = 300.0


def _mannwhitney(a, b):
    """回 (U, p 近似)。小樣本用常態近似,夠判斷有沒有訊號。"""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    r1 = sum(ranks[k] for k, (_, g) in enumerate(allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u = min(u1, n1 * n2 - u1)
    mu = n1 * n2 / 2.0
    sd = (n1 * n2 * (n1 + n2 + 1) / 12.0) ** 0.5
    if sd == 0:
        return u, 1.0
    z = abs(u - mu) / sd
    # 常態尾機率近似(雙尾)
    import math
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return u, max(0.0, min(1.0, p))


def main() -> int:
    import statistics as st
    import audit_video as av
    import yt_analytics as ya
    from datetime import date, timedelta

    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    svc = ya._service()
    end = date.today() - timedelta(days=3)
    r = svc.reports().query(
        ids="channel==MINE", startDate=(end - timedelta(days=60)).isoformat(),
        endDate=end.isoformat(), dimensions="video",
        metrics="views,averageViewPercentage,averageViewDuration,estimatedMinutesWatched",
        sort="-views", maxResults=200).execute()
    m = {row[0]: row[1:] for row in (r.get("rows") or [])}

    groups = {"A": [], "B": []}
    for slug, vid in led.items():
        ab = OUT / f"{slug}.ab.txt"
        if not ab.exists() or vid not in m:
            continue
        arm = ab.read_text(encoding="utf-8").strip()
        if arm not in groups:
            continue
        mp4 = OUT / f"{slug}.mp4"
        if not mp4.exists():
            continue
        dur, _, _ = av._probe(mp4)
        if dur < MIN_DUR:
            continue
        views, pct, avd, mins = m[vid]
        groups[arm].append({"slug": slug, "dur": dur, "views": views,
                            "pct": pct, "avd": avd, "mins": mins})

    print("開場結構 A/B 實驗(A=現行規則 / B=鉤子後禁止鋪陳)")
    print(f"只計入片長 >{MIN_DUR:.0f}s 的真長片(留存 vs 片長 r=-0.675,不控制會全錯)\n")
    for arm in ("A", "B"):
        g = groups[arm]
        if not g:
            print(f"  {arm} 組:0 支")
            continue
        print(f"  {arm} 組 n={len(g)}  留存中位 {st.median([x['pct'] for x in g]):.1f}%  "
              f"平均觀看 {st.median([x['avd'] for x in g]):.0f}s  "
              f"觀看中位 {st.median([x['views'] for x in g]):.0f}  "
              f"片長中位 {st.median([x['dur'] for x in g]):.0f}s")

    a = [x["pct"] for x in groups["A"]]
    b = [x["pct"] for x in groups["B"]]
    print()
    if len(a) < MIN_N or len(b) < MIN_N:
        print(f"  ⏳ 樣本不足(需要每組 ≥{MIN_N},目前 A={len(a)} B={len(b)}),**不下結論**。")
        print("     這條是硬規:本專案已經有兩次拿 n=2 的樣本下結論的紀錄。")
        return 0
    u, p = _mannwhitney(a, b)
    diff = st.median(b) - st.median(a)
    print(f"  Mann-Whitney U={u:.1f}  p≈{p:.3f}  B-A 留存中位差 {diff:+.1f} 個百分點")
    if p < 0.05:
        print(f"  ✅ 有訊號:{'B 組(禁止鋪陳)較好' if diff > 0 else 'A 組(現行規則)較好'}")
        print("     → 把勝出那組的規範寫死進 LONG_RULES,並把 AB_OPENING 設為 off 結束實驗。")
    else:
        print("  ➖ 差異不顯著。繼續累積樣本,或換一個變數重做實驗。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
