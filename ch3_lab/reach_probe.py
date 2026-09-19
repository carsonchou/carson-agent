#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reach_probe.py — 曝光在哪裡消失的。**唯讀,走 Analytics 配額池。**

## 為什麼
2026-09-01 實測:長片 22 支 / 6 天 / 總共 11 次觀看 / 中位數 **0**;
Shorts 34 支拿到 299。中位數 0 不是「成長慢」,是那些片**沒有被曝光**。
再發 11 支同格式長片不會改變任何事 —— 除非先知道曝光是「低」還是「沒有」。

YouTube Analytics API 和 Data API 是**不同的配額池**,所以這支不吃發布額度。

🔴 這支只讀不寫,而且**拉不到就說拉不到**。用估計值往下推是這條線
   今天已經記過的錯(memory: 我對 Carson 誇大數字)。
"""
import json
import pathlib
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), [
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtubeAnalytics", "v2", credentials=cr,
                 cache_discovery=False)


def q(y, label, **kw):
    """跑一個查詢。失敗就**原樣回報錯誤**,不吞、不代換成 0。"""
    try:
        r = y.reports().query(ids=f"channel=={CHANNEL}", **kw).execute()
        return {"ok": True, "rows": r.get("rows", []),
                "cols": [c["name"] for c in r.get("columnHeaders", [])]}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {str(e)[:220]}"}


def show(label, res):
    print(f"\n=== {label} ===")
    if not res["ok"]:
        print(f"  ⛔ 拉不到:{res['err']}")
        return
    if not res["rows"]:
        print("  (查詢成功,但沒有資料列)")
        return
    print("  " + " | ".join(res["cols"]))
    for row in res["rows"][:25]:
        print("  " + " | ".join(str(x) for x in row))


def main():
    y = svc()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=8)
    s, e = start.isoformat(), end.isoformat()
    print(f"頻道 {CHANNEL}   期間 {s} ~ {e}")
    print("(Analytics 資料延遲 2~4 天,所以最後兩天可能偏低 —— "
          "這是已知的,不要當成下降)")

    out = {}
    # 1) 曝光與點閱率:這兩個 metric 這個頻道先前回過 400,要實測
    out["reach"] = q(y, "reach", startDate=s, endDate=e,
                     metrics="impressions,impressionsClickThroughRate,views")
    show("曝光與點閱率(全頻道)", out["reach"])

    # 2) 分格式:creatorContentType 才分得出長片與 Shorts
    out["by_type"] = q(y, "by_type", startDate=s, endDate=e,
                       dimensions="creatorContentType",
                       metrics="views,estimatedMinutesWatched",
                       sort="-views")
    show("分格式(長片 vs Shorts)", out["by_type"])

    out["by_type_reach"] = q(y, "by_type_reach", startDate=s, endDate=e,
                             dimensions="creatorContentType",
                             metrics="impressions,impressionsClickThroughRate")
    show("分格式的曝光", out["by_type_reach"])

    # 3) 流量來源:曝光從哪裡來的
    out["src"] = q(y, "src", startDate=s, endDate=e,
                   dimensions="insightTrafficSourceType",
                   metrics="views,estimatedMinutesWatched", sort="-views")
    show("流量來源", out["src"])

    # 4) 逐日,看有沒有某一天斷掉
    out["daily"] = q(y, "daily", startDate=s, endDate=e,
                     dimensions="day", metrics="views,estimatedMinutesWatched",
                     sort="day")
    show("逐日", out["daily"])

    (ROOT / "_reach_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n原始結果 → {ROOT / '_reach_probe.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
