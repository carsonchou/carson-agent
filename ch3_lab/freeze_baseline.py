#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""freeze_baseline.py — 復發測試的**發布前基線**。唯讀,走 Analytics 配額池。

🔴 為什麼要在發布之前跑:事後再算基線 = 用結果挑基線。
   這支的輸出要 commit,而那個 commit 的時間戳必須早於任何發布動作。

判準與讀數方法凍結在 `docs/ops/2026-09-09_ch3_criteria_revision.md`:
- **分母一律用「帶 `dimensions=insightTrafficSourceType` 那條的加總」**。
  同一支同一窗,無維度回 102/3、有維度加總 107/4 ⇒ 差 5%/33%,而判準是比值 ⇒ 兩邊要同源。
- 唯一走得通的組合是 `filters=video==<id>` + `dimensions=insightTrafficSourceType`
  (`insightTrafficSourceType` 不能當 filter,也不能和 video 併成雙維度)。

🔴 拉不到就說拉不到,不代換成 0(memory `self-inflated-numbers-to-carson`)。
   0 和「拉不到」在下游是兩件完全不同的事,而它們長得一模一樣。
"""
import json
import pathlib
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
LIFETIME_START = "2026-01-01"
WINDOW_DAYS = 14


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
    try:
        r = y.reports().query(ids=f"channel=={CHANNEL}", **kw).execute()
        return {"ok": True, "rows": r.get("rows", []),
                "cols": [c["name"] for c in r.get("columnHeaders", [])]}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {str(e)[:200]}"}


def video_ids():
    """三本帳合起來,去重。**帳本是我們唯一知道發過什麼的地方。**"""
    ids = {}
    for name in ("uploaded.json", "uploaded_shorts.json", "uploaded_comp.json"):
        p = ROOT / name
        if not p.exists():
            print(f"  ⚠️ 帳本不存在:{name}")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for k, v in d.items():
            vid = v if isinstance(v, str) else (
                v.get("id") or v.get("video_id") or v.get("videoId"))
            if isinstance(vid, str) and len(vid) == 11:
                ids.setdefault(vid, []).append(f"{name}:{k}")
    return ids


def pct(sorted_vals, p):
    """最近秩(nearest-rank)百分位。n 這麼小的時候插值只是裝飾。"""
    if not sorted_vals:
        return None
    import math
    k = max(1, math.ceil(p / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def main():
    today = date.today()
    win_start = today - timedelta(days=WINDOW_DAYS - 1)
    y = svc()
    ids = video_ids()
    print(f"帳本裡的影片 id:{len(ids)} 支")

    metrics = "views,engagedViews,estimatedMinutesWatched"
    per_video, failed = {}, {}
    for i, vid in enumerate(sorted(ids), 1):
        # 🔴 一次暫時性的 HTTP 500 少抓一支,母體從 60 變 59,而
        #    **最近秩 P90 就從 5 跳到 6** —— 門檻被一次網路抖動決定了。
        #    重試三次;仍然缺就 fail-closed(見下),不要拿殘缺母體算基線。
        for _try in range(3):
            res = q(y, startDate=LIFETIME_START, endDate=today.isoformat(),
                    metrics=metrics, dimensions="insightTrafficSourceType",
                    filters=f"video=={vid}")
            if res["ok"]:
                break
            import time
            time.sleep(2 * (_try + 1))
        if not res["ok"]:
            failed[vid] = res["err"]
            continue
        cols = res["cols"]
        agg = {m: 0 for m in metrics.split(",")}
        for row in res["rows"]:
            for m in agg:
                if m in cols:
                    agg[m] += row[cols.index(m)]
        agg["by_source"] = {row[cols.index("insightTrafficSourceType")]:
                            row[cols.index("views")] for row in res["rows"]}
        per_video[vid] = agg
        if i % 10 == 0:
            print(f"  ...{i}/{len(ids)}")

    print(f"拉到 {len(per_video)} 支;拉不到 {len(failed)} 支")
    for vid, err in list(failed.items())[:5]:
        print(f"  ⛔ {vid}: {err}")

    out = {"frozen_at": None, "channel": CHANNEL,
           "lifetime_start": LIFETIME_START, "as_of": today.isoformat(),
           "denominator_rule": ("帶 dimensions=insightTrafficSourceType 那條的加總;"
                                "與分子同源"),
           "ledger_ids": len(ids), "fetched": len(per_video),
           "per_video": per_video,
           "failed": failed}

    for m in ("views", "engagedViews"):
        vals = sorted(v[m] for v in per_video.values())
        out[f"{m}_dist"] = {
            "n": len(vals), "P50": pct(vals, 50), "P75": pct(vals, 75),
            "P90": pct(vals, 90), "max": vals[-1] if vals else None,
            "sum": sum(vals)}
        print(f"\n{m}:n={len(vals)} P50={pct(vals,50)} P75={pct(vals,75)} "
              f"P90={pct(vals,90)} max={vals[-1] if vals else None} "
              f"sum={sum(vals)}")

    # 發布前 14 天窗,頻道層級,按流量來源
    res = q(y, startDate=win_start.isoformat(), endDate=today.isoformat(),
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType")
    pre = {"window": [win_start.isoformat(), today.isoformat()]}
    if res["ok"]:
        c = res["cols"]
        pre["by_source"] = {r[c.index("insightTrafficSourceType")]:
                            r[c.index("views")] for r in res["rows"]}
        pre["total_views"] = sum(pre["by_source"].values())
    else:
        pre["error"] = res["err"]
    out["pre_window"] = pre
    print(f"\n發布前 {WINDOW_DAYS} 天窗 {pre['window']}:")
    print("  " + json.dumps(pre.get("by_source", pre.get("error")),
                            ensure_ascii=False))

    # 🔴 **殘缺的母體不准凍結。** 基線的用途是當門檻,而門檻對 n 敏感:
    #    實測少一支就把 engagedViews 的 P90 從 5 推到 6。允許「少幾支還是寫檔」
    #    等於允許一次網路抖動決定判準,而下游完全看不出來。
    if failed:
        print(f"⛔ 有 {len(failed)} 支拉不到,**不寫基線檔**。"
              f"先把它們拉到,或由督導明示要用殘缺母體並記錄理由。")
        return 1

    import datetime as _dt
    out["frozen_at"] = _dt.datetime.now().astimezone().isoformat()
    p = ROOT / "facts" / "_baseline_frozen_2026-09-09.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    import os
    os.replace(tmp, p)
    print(f"\n凍結 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
