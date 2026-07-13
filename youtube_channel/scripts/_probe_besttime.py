#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A7 探針:算「觀眾真實活躍時段」以排最佳發布時間。只讀不寫正式機資料。

背景:YouTube Analytics API 沒有 dimension=hour(Studio『目標對象』分頁限定,API 不開放,
下方仍留探測供未來復查)。改用「本頻道自己的歷史成績」當替代訊號:
  1. 用 Data API videos.list 抓已發布影片的 publishedAt(轉台灣時區→發布時的『小時』)
  2. 用 yt_analytics.video_stats() 抓每支近 180 天的 views/retention/subs(觀眾真實反應)
  3. 用 statistics.viewCount(累積總觀看) / 影片存活天數 = 每日觀看速度,按「發布小時」分桶
     取平均,近似「哪個發布時段的片子長期表現較好」(非即時線上人數,但是本頻道真實成效)
輸出 STUDIO/best_publish_times.json 供 crontab 調度依據 + 之後複查。
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yt_analytics as ya  # noqa: E402

TW = timezone(timedelta(hours=8))


def probe_hour_dimension():
    """先探 Analytics API 是否開放 hour 維度(每次都探,萬一 Google 哪天開放了)。"""
    svc = ya._service()
    if svc is None:
        return {"day": None, "hour": None, "note": "analytics 不可用(無 token)"}
    end = date.today()
    start = end - timedelta(days=28)
    out = {}
    for dim in ("day", "hour"):
        try:
            r = svc.reports().query(
                ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                dimensions=dim, metrics="views",
            ).execute()
            out[dim] = {"ok": True, "rows": len(r.get("rows", []))}
        except Exception as e:  # noqa: BLE001
            out[dim] = {"ok": False, "err": str(e)[:160]}
    return out


def _data_service():
    """借 daily_publish.py 同一組 token_manage.json 讀資料(videos.list 是讀取,不會寫入)。"""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        token = ROOT / "token_manage.json"
        if not token.exists():
            return None
        scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
        creds = Credentials.from_authorized_user_file(str(token), scopes)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)
    except Exception as e:  # noqa: BLE001
        print(f"[probe] data api 服務建立失敗: {str(e)[:160]}")
        return None


def load_ledger():
    p = ROOT / "STUDIO" / "uploaded_ledger.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_video_meta(svc, video_ids):
    """batched videos.list(part=snippet,statistics,contentDetails)。回 {vid: {...}}。"""
    out = {}
    ids = list(video_ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            r = svc.videos().list(part="snippet,statistics,contentDetails", id=",".join(chunk)).execute()
        except Exception as e:  # noqa: BLE001
            print(f"[probe] videos.list 失敗(批{i}): {str(e)[:160]}")
            continue
        for item in r.get("items", []):
            vid = item["id"]
            snip = item.get("snippet", {})
            stats = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            out[vid] = {
                "published_at": snip.get("publishedAt"),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "duration": cd.get("duration", ""),
            }
    return out


def _parse_iso8601_duration_sec(s: str) -> int:
    import re
    if not s:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def analyze():
    probe = probe_hour_dimension()
    print(f"[probe] Analytics dimension 探測: {probe}")

    ledger = load_ledger()
    print(f"[probe] ledger 影片數: {len(ledger)}")
    if not ledger:
        return {"probe": probe, "error": "ledger 空,無法分析"}

    svc = _data_service()
    if svc is None:
        return {"probe": probe, "error": "Data API 服務不可用(無 token_manage.json)"}

    video_ids = list(dict.fromkeys(ledger.values()))
    meta = fetch_video_meta(svc, video_ids)
    print(f"[probe] 成功取回 metadata: {len(meta)} / {len(video_ids)}")

    stats = ya.video_stats(days=180, limit=200) or {}
    print(f"[probe] Analytics video_stats(180d): {len(stats)} 支")

    now_utc = datetime.now(timezone.utc)
    # 只用「成熟片」(發布 >=14 天)算 views_per_day,排除新片剛發的初始推播爆發噪音
    # (新片頭幾天 YouTube 會不分時段給初始曝光,若混進去會讓「最近常發的那個時段」看起來假強)
    MATURE_DAYS = 14
    hour_bucket_short = defaultdict(list)  # hour(TW) -> list of views_per_day(僅成熟片)
    hour_bucket_long = defaultdict(list)
    hour_age_short = defaultdict(list)     # 同桶 debug:平均片齡(檢查是否還有殘留 recency bias)
    dow_bucket_short = defaultdict(list)   # weekday(TW, 0=Mon) -> views_per_day
    dow_bucket_long = defaultdict(list)
    retention_by_hour_short = defaultdict(list)
    retention_by_hour_long = defaultdict(list)
    n_used = 0
    n_immature_skipped = 0

    for vid, m in meta.items():
        pub = m.get("published_at")
        if not pub:
            continue
        try:
            dt_utc = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            continue
        dt_tw = dt_utc.astimezone(TW)
        hour = dt_tw.hour
        dow = dt_tw.weekday()
        age_days = max(1.0, (now_utc - dt_utc).total_seconds() / 86400.0)
        views = m.get("view_count", 0)
        vpd = views / age_days
        dur_sec = _parse_iso8601_duration_sec(m.get("duration", ""))
        is_short = dur_sec > 0 and dur_sec <= 183  # YouTube Shorts 判定門檻(含放寬)

        # retention(intrinsic,較不受片齡影響)不論新舊都收;views_per_day 只收成熟片
        vs = stats.get(vid)
        if vs and vs.get("retention") is not None:
            if is_short:
                retention_by_hour_short[hour].append(vs["retention"])
            else:
                retention_by_hour_long[hour].append(vs["retention"])

        if age_days >= MATURE_DAYS:
            if is_short:
                hour_bucket_short[hour].append(vpd)
                hour_age_short[hour].append(age_days)
                dow_bucket_short[dow].append(vpd)
            else:
                hour_bucket_long[hour].append(vpd)
                dow_bucket_long[dow].append(vpd)
        else:
            n_immature_skipped += 1
        n_used += 1

    def summarize(bucket, age_bucket=None):
        out = {}
        for h, vals in bucket.items():
            if len(vals) >= 3:  # 樣本太少的桶別拿來下結論
                entry = {"avg_views_per_day": round(sum(vals) / len(vals), 2), "n": len(vals)}
                if age_bucket is not None and h in age_bucket:
                    entry["avg_age_days"] = round(sum(age_bucket[h]) / len(age_bucket[h]), 1)
                out[h] = entry
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["avg_views_per_day"]))

    def summarize_ret(bucket):
        out = {}
        for h, vals in bucket.items():
            if len(vals) >= 3:
                out[h] = {"avg_retention": round(sum(vals) / len(vals), 2), "n": len(vals)}
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["avg_retention"]))

    short_by_hour = summarize(hour_bucket_short, hour_age_short)
    long_by_hour = summarize(hour_bucket_long)
    short_by_dow = summarize(dow_bucket_short)
    long_by_dow = summarize(dow_bucket_long)
    short_ret_by_hour = summarize_ret(retention_by_hour_short)
    long_ret_by_hour = summarize_ret(retention_by_hour_long)

    result = {
        "generated_at": datetime.now(TW).isoformat(),
        "method": "Analytics API 無 hour 維度(已探測見 probe 欄);改用本頻道歷史 publishedAt(轉台灣時區)"
                  " × 累積 view_count/存活天數(views_per_day) 分桶,輔以 Analytics retention 交叉驗證。"
                  "views_per_day 會偏favor近期發的片(尚未飽和 vs 舊片已飽和),故只作趨勢參考非絕對值。",
        "probe": probe,
        "n_videos_used": n_used,
        "n_immature_skipped_for_vpd": n_immature_skipped,
        "mature_days_threshold": MATURE_DAYS,
        "shorts": {"views_per_day_by_hour": short_by_hour, "retention_by_hour": short_ret_by_hour,
                   "views_per_day_by_weekday": short_by_dow},
        "long": {"views_per_day_by_hour": long_by_hour, "retention_by_hour": long_ret_by_hour,
                 "views_per_day_by_weekday": long_by_dow},
        "current_schedule": {"shorts": ["12:30", "20:30", "13:40(平日)"], "long": ["12:30/20:30 混排(依隊列)"]},
    }
    return result


if __name__ == "__main__":
    res = analyze()
    out_path = ROOT / "STUDIO" / "best_publish_times.json"
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 已寫入 {out_path}")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
