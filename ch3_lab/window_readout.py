#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""window_readout.py — 窗口讀數,**資料不完整就拒絕輸出**。唯讀。

🔴 為什麼需要這一支:Analytics 有 2~4 天延遲,而**缺的那幾天不是回 0,是那幾列
   根本不存在**。所以「查一個 14 天窗」和「拿到 14 天資料」是兩件事,
   而它們的輸出長得一模一樣(memory `yt-analytics-lag-false-alarm`)。

延遲會從**兩邊**咬人,方向相反:
· **對照窗**(發布前)讀太晚 ⇒ 尾巴幾天沒進來 ⇒ 分母偏小 ⇒ **門檻偏鬆**
· **量測窗**(發布後)讀太早 ⇒ 尾巴幾天沒進來 ⇒ 新片被低估 ⇒ **測試假性失敗**
兩個都是**儀器**造成的,不是內容造成的,而且都不會報錯。

⇒ 判準是**資料視界**:往今天查一段,最後一個有列的日期就是視界。
  視界 >= 窗結束日 ⇒ 這個窗已經完全落地。不足就 `SystemExit`,不印任何讀數。
  **印一個不完整的數字,比不印更糟** —— 它會被當成結論用下去。

⚠️ **不是數列數。** 本檔第一版寫的是「回的列數必須等於窗長」,而實測
  (2026-09-09)那條會把一個**完整**的窗判成不完整:零觀看日**根本不回列**,
  08-15~08-18 連續四天都沒有列。**那個設計已經被放棄,不要照這段話重建它。**

⚠️ `LAG_DAYS = 4` 只是名目值,昨天實測延遲是 **3 天** —— 它貼得很近。
  **真正 fail-closed 的是視界檢查,不要把 +4 當保護,也不要在別處引用它當常數。**

用法:
  python window_readout.py --start 2026-08-24 --end 2026-09-06
  python window_readout.py --start ... --end ... --allow-incomplete   # 只用於陽性對照
"""
import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
LAG_DAYS = 4          # 讀數不得早於「窗結束日 + 4 天」


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


def q(y, **kw):
    r = y.reports().query(ids=f"channel=={CHANNEL}", **kw).execute()
    return ([c["name"] for c in r.get("columnHeaders", [])], r.get("rows", []))


def expected_days(start, end):
    a = datetime.strptime(start, "%Y-%m-%d").date()
    b = datetime.strptime(end, "%Y-%m-%d").date()
    return (b - a).days + 1


def assert_complete(y, start, end, allow_incomplete=False):
    """🔴 這一格的判準是**列數**,不是「查詢成功」也不是「有資料」。

    「查詢成功 + 有回結果」證不了篩選/範圍有生效
    (memory `filter-accepted-is-not-filter-applied`)。
    缺的日子不會回 0,它們**不存在** —— 所以只有數列數看得見。
    """
    want = expected_days(start, end)
    _, rows = q(y, startDate=start, endDate=end, metrics='views',
                dimensions='day')
    days = {r[0] for r in rows}
    a = datetime.strptime(start, '%Y-%m-%d').date()
    absent = [(a + timedelta(days=i)).isoformat() for i in range(want)
              if (a + timedelta(days=i)).isoformat() not in days]

    # 🔴 **列數不是判準。** 2026-09-09 實測撞到:窗 08-24~09-06 只回 12 列,
    #    而缺的是 **08-24 / 08-25 —— 開頭**,可是延遲只會咬結尾。
    #    那兩天缺的真正原因是**觀看數是 0,所以那一列根本不存在**;
    #    在這個量級的頻道上零觀看日是常態(08-15~08-18 連續四天都沒有列)。
    #    ⇒ 「列數 == 窗長」會把一個**完整**的窗判成不完整然後拒絕輸出,
    #      而它的訊息會說「資料還沒進來」—— 一個很有說服力的錯誤診斷。
    #    分得開兩者的是**資料視界**:往今天查一段,最後一個有列的日期。
    #    視界 >= 窗結束日 ⇒ 這個窗已經完全落地,內部的洞是真的零。
    _, hz = q(y, startDate=(date.today() - timedelta(days=45)).isoformat(),
              endDate=date.today().isoformat(), metrics='views',
              dimensions='day')
    horizon = max((r[0] for r in hz), default=None)
    end_iso = datetime.strptime(end, '%Y-%m-%d').date().isoformat()
    truncated = (horizon is None) or (horizon < end_iso)
    if truncated and not allow_incomplete:
        raise SystemExit(
            f'⛔ 資料視界只到 {horizon},而這個窗要到 {end_iso} —— '
            f'窗的尾巴還沒落地。現在讀會拿到一個分母偏小、'
            f'但看起來完全正常的數字。不輸出任何讀數。')
    # 🔴 `rows_returned` / `expected_days` **不放進輸出**。它們會被抄進讀數紀錄,
    #    而讀的人會拿 12 對 14 得出「少了兩天」的結論 —— 那個結論是錯的,
    #    而且它比沒有數字更有說服力。判準是視界,紀錄裡就只留視界。
    return {'data_horizon': horizon, 'truncated_by_lag': truncated,
            'zero_view_days': absent,
            'note': ('內部缺的日子是**真的零觀看**(那一列不存在),'
                     '不是資料沒進來;分辨兩者的是資料視界,不是列數。')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--measurement", action="store_true",
                    help="這是發布後的量測窗:日期規則升為硬閘門(明示,不從窗長推論)")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="只給陽性對照用:證明不完整時它真的會拒絕")
    ap.add_argument("--out")
    a = ap.parse_args()

    end_d = datetime.strptime(a.end, "%Y-%m-%d").date()
    ready = end_d + timedelta(days=LAG_DAYS)
    early = date.today() < ready
    # 🔴 兩道檢查的關係要講清楚,不然會互相否決:
    #    **列數檢查是直接量測**(這個窗到底拿到幾天),
    #    **日期規則只是它的代理**(延遲通常 2~4 天)。代理不該否決量測。
    #    ⇒ 量測窗(`--measurement`)兩道都要過 —— 那是對外結論用的數字,
    #      寧可晚讀也不要在邊緣搶讀;
    #      其餘窗以列數為準,提早讀但列數齊全時放行,並把這件事記進輸出。
    if early and a.measurement and not a.allow_incomplete:
        raise SystemExit(
            f"⛔ 現在是 {date.today()},而量測窗要到 {ready} 之後才讀"
            f"(窗結束 {a.end} + {LAG_DAYS} 天)。不輸出讀數。")

    y = svc()
    comp = assert_complete(y, a.start, a.end, a.allow_incomplete)
    comp["read_before_nominal_lag"] = early
    comp["nominal_ready_date"] = ready.isoformat()
    if early:
        print(f"⚠️ 比名目延遲({ready})早讀,但視界檢查通過"
              f"(資料視界 {comp['data_horizon']} >= 窗結束 {a.end})——"
              f"以列數為準,並記進輸出。")
    cols, rows = q(y, startDate=a.start, endDate=a.end,
                   metrics="views,estimatedMinutesWatched",
                   dimensions="insightTrafficSourceType")
    by = {r[cols.index("insightTrafficSourceType")]: r[cols.index("views")]
          for r in rows}
    out = {"window": [a.start, a.end], "completeness": comp,
           "by_source": by, "total_views": sum(by.values()),
           "read_at": datetime.now().astimezone().isoformat()}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.out:
        p = pathlib.Path(a.out)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        import os
        os.replace(tmp, p)
        print(f"落檔 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
