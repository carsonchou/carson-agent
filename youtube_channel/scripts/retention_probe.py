#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retention_probe.py — 【留存調查】10 分鐘的長片為什麼只被看 100 秒?

## 為什麼要查這個
2026-08-16 實測:YPP 只算長片時數,本頻道 430/4000 小時(10.8%)。
長片 Top15 的平均觀看時長只有 62~142 秒,而片長約 10 分鐘 → 留存率約 17%。
缺口 8.6 倍,純靠拉產量會同時撞上「發布量+41%→觸及-67%」與 YPP inauthentic 風險,
所以**先把每支片的分鐘做大**是唯一不增加風險的槓桿。

要動它就得先知道:**觀眾在第幾秒走掉、走掉的地方有什麼共同點。**

## 方法
1. 取近 365 天所有長片(>=180 秒)的分鐘/觀看/平均秒數
2. 同題材內分高分鐘組與低分鐘組(控制題材變因——不同題材比較是沒意義的)
3. 逐支拉 audienceRetention 曲線(elapsedVideoTimeRatio × audienceWatchRatio)
4. 對齊到百分位,比較兩組在哪一段拉開差距
5. 併看流量來源(搜尋/推薦/瀏覽),因為來源會決定觀眾的預期與耐心

## 誠實限制
- audienceRetention 需要 `video==ID` 逐支查,無法批次;樣本要控成本
- 觀看數太少的片曲線是雜訊,設 MIN_VIEWS 門檻
- **同題材內比較**才有意義;跨題材差異已知(個股體檢 272 vs 其他 22 分鐘/支)

用法:
  python scripts/retention_probe.py --probe 16      # 抓曲線(寫 STUDIO/retention_probe.json)
  python scripts/retention_probe.py --report        # 只看已抓結果
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

# 配額計量(全域 patch HttpRequest.execute,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
OUT = STUDIO / "retention_probe.json"
TOKEN = ROOT / "token_analytics.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
MIN_VIEWS = 120        # 低於這個數的曲線是雜訊
MIN_DUR = 180          # 長片門檻(秒)


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
    return (build("youtubeAnalytics", "v2", credentials=cr, cache_discovery=False),
            build("youtube", "v3", credentials=cr, cache_discovery=False))


def _dur(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def kind(t):
    if re.search(r"【\d{4}", t) or "個股體檢" in t:
        return "個股體檢"
    if re.search(r"00\d{2,3}|0050|0056", t):
        return "ETF對決"
    if "流言終結者" in t or "真相實驗室" in t:
        return "流言終結者"
    return "其他"


def fetch_videos(ya, yt, start, end):
    r = ya.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="estimatedMinutesWatched,views,averageViewDuration,subscribersGained",
        dimensions="video", sort="-estimatedMinutesWatched", maxResults=200).execute()
    rows = r.get("rows", [])
    out = []
    for i in range(0, len(rows), 50):
        chunk = rows[i:i + 50]
        meta = yt.videos().list(part="snippet,contentDetails",
                                id=",".join(x[0] for x in chunk)).execute()
        mm = {it["id"]: it for it in meta.get("items", [])}
        for x in chunk:
            it = mm.get(x[0])
            if not it:
                continue
            d = _dur(it["contentDetails"]["duration"])
            if d < MIN_DUR:
                continue
            title = it["snippet"]["title"]
            out.append({"id": x[0], "title": title, "kind": kind(title), "dur": d,
                        "minutes": x[1], "views": x[2], "avd": x[3], "subs": x[4],
                        "retention_pct": round(x[3] / d * 100, 1) if d else None,
                        "published": it["snippet"]["publishedAt"][:10]})
    return out


def fetch_curve(ya, vid, start, end):
    """回 [(位置比例, 觀看比率)]。ORGANIC 只算自然流量,排除廣告/外部嵌入的雜訊。"""
    try:
        r = ya.reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
            filters=f"video=={vid};audienceType==ORGANIC").execute()
        return [(row[0], row[1]) for row in r.get("rows", [])]
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:110]}"}


def at(curve, x):
    """曲線在位置 x 的觀看比率(取最接近的點)。"""
    if not curve:
        return None
    return min(curve, key=lambda p: abs(p[0] - x))[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0, help="抓幾支的曲線")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    end = date.today().isoformat()
    start = (date.today() - timedelta(days=365)).isoformat()

    if a.probe:
        ya, yt = svc()
        vids = fetch_videos(ya, yt, start, end)
        print(f"長片(>={MIN_DUR}秒)共 {len(vids)} 支")
        pool = [v for v in vids if v["views"] >= MIN_VIEWS and v["kind"] == "個股體檢"]
        pool.sort(key=lambda v: -v["minutes"])
        n = min(a.probe // 2, len(pool) // 2)
        picks = pool[:n] + pool[-n:]
        print(f"個股體檢且觀看>={MIN_VIEWS} 的有 {len(pool)} 支,取高分鐘 {n} + 低分鐘 {n} = {len(picks)} 支\n")
        data = {"generated": end, "window": [start, end], "videos": vids, "curves": {}}
        for i, v in enumerate(picks, 1):
            c = fetch_curve(ya, v["id"], start, end)
            data["curves"][v["id"]] = c
            ok = "曲線 %d 點" % len(c) if isinstance(c, list) else c.get("error", "?")
            print(f"  {i:2d}/{len(picks)} {v['minutes']:>6,}分 {v['views']:>5}觀看 "
                  f"留存{v['retention_pct']:>5}% {ok}  {v['title'][:34]}")
        STUDIO.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"\n已寫 {OUT}")

    if a.report:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        vids = {v["id"]: v for v in d["videos"]}
        curves = {k: v for k, v in d["curves"].items() if isinstance(v, list) and v}
        if not curves:
            print("沒有可用曲線")
            return 0
        got = sorted(curves, key=lambda i: -vids[i]["minutes"])
        half = len(got) // 2
        hi, lo = got[:half], got[half:]

        def agg(ids, x):
            vals = [at(curves[i], x) for i in ids]
            vals = [v for v in vals if v is not None]
            return statistics.median(vals) if vals else None

        print(f"\n=== 留存曲線對比(個股體檢,同題材內比) ===")
        print(f"高分鐘組 {len(hi)} 支(中位 {statistics.median(vids[i]['minutes'] for i in hi):,.0f} 分鐘)")
        print(f"低分鐘組 {len(lo)} 支(中位 {statistics.median(vids[i]['minutes'] for i in lo):,.0f} 分鐘)")
        print(f"\n{'播放位置':>8s}{'高分鐘組':>10s}{'低分鐘組':>10s}{'差距':>9s}")
        print("-" * 40)
        prev = None
        for x in [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.70, 0.90, 1.0]:
            h, l = agg(hi, x), agg(lo, x)
            if h is None or l is None:
                continue
            gap = h - l
            mark = ""
            if prev is not None and prev[0] - h > 0.12:
                mark = "  ← 高分鐘組在這段掉最兇"
            print(f"{x*100:>7.0f}%{h:>10.3f}{l:>10.3f}{gap:>+9.3f}{mark}")
            prev = (h, l)
        # 逐支列出前 15% 的留存(開場是決定生死的一段)
        print(f"\n{'分鐘':>7s}{'觀看':>6s}{'留存%':>7s}{'@5%':>7s}{'@15%':>7s}{'@50%':>7s}  標題")
        for i in got:
            v = vids[i]
            print(f"{v['minutes']:>7,}{v['views']:>6}{v['retention_pct']:>7}"
                  f"{(at(curves[i],0.05) or 0):>7.2f}{(at(curves[i],0.15) or 0):>7.2f}"
                  f"{(at(curves[i],0.5) or 0):>7.2f}  {v['title'][:32]}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
