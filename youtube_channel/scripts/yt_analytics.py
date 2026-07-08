# -*- coding: utf-8 -*-
"""yt_analytics.py — YouTube Analytics 查詢小工具（給數據/CTR/回顧檢討部門用）。

需先跑 auth_analytics.py 產 token_analytics.json。沒 token 時所有函式回 None（優雅降級，
呼叫端就退回原本的「無 CTR」行為，不報錯、不假裝有數字）。
"""
from __future__ import annotations
import os
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent


def _dailycache(fn):
    """當日磁碟快取:同函式+同參數當天重呼直接讀檔(channel_summary/impressions_ctr 一天被多部門重抓)。
    設 YA_NO_CACHE=1 關閉。None 不快取(降級不落檔)。"""
    import functools, json as _json, hashlib as _h

    @functools.wraps(fn)
    def wrap(*a, **k):
        if os.environ.get("YA_NO_CACHE"):
            return fn(*a, **k)
        try:
            d = ROOT / "STUDIO" / "analytics_cache"; d.mkdir(parents=True, exist_ok=True)
            key = _h.md5(f"{fn.__name__}|{a}|{sorted(k.items())}|{date.today().isoformat()}".encode("utf-8")).hexdigest()[:20]
            cp = d / (key + ".json")
            if cp.exists():
                return _json.loads(cp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return fn(*a, **k)
        r = fn(*a, **k)
        if r is not None:
            try:
                cp.write_text(_json.dumps(r, ensure_ascii=False), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        return r
    return wrap
TOKEN = ROOT / "token_analytics.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]


def _service():
    if not TOKEN.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtubeAnalytics", "v2", credentials=creds)
    except Exception:
        return None


def available():
    return TOKEN.exists()


@_dailycache
def channel_summary(days=28):
    """近 N 天頻道彙總。回傳 dict 或 None。"""
    ya = _service()
    if ya is None:
        return None
    end = date.today(); start = end - timedelta(days=days)
    try:
        r = ya.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            metrics="views,estimatedMinutesWatched,averageViewPercentage,averageViewDuration,subscribersGained",
        ).execute()
        rows = r.get("rows", [])
        if not rows:
            return {"days": days, "views": 0, "minutes": 0, "avg_pct": 0, "avg_dur": 0, "subs_gained": 0}
        v = rows[0]
        return {"days": days, "views": v[0], "minutes": v[1],
                "avg_pct": (min(100.0, v[2]) if v[2] is not None else v[2]),  # 夾回合理上限
                "avg_dur": v[3], "subs_gained": v[4]}
    except Exception:
        return None


@_dailycache
def top_by_ctr(days=28, limit=20):
    """近 N 天各影片的曝光 CTR / 平均觀看%。回傳 list[dict] 或 None。"""
    ya = _service()
    if ya is None:
        return None
    end = date.today(); start = end - timedelta(days=days)
    try:
        r = ya.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            dimensions="video", metrics="views,averageViewPercentage", sort="-views",
            maxResults=limit,
        ).execute()
        out = []
        for row in r.get("rows", []):
            out.append({"video_id": row[0], "views": row[1],
                        "avg_pct": (min(100.0, row[2]) if row[2] is not None else row[2])})  # 夾回合理上限
        return out
    except Exception:
        return None


@_dailycache
def video_stats(days=180, limit=200):
    """近 N 天每支影片的 觀看／留存%／平均觀看秒數／帶來訂閱數。回 {videoId: {...}} 或 None。
    註：YouTube Analytics API 不提供 impressions/CTR（那是 Studio 網頁限定，API 會回 Unknown identifier），
    故改用 subscribersGained（每支帶來幾個訂閱）——對成長更有意義且 API 真的支援。"""
    ya = _service()
    if ya is None:
        return None
    end = date.today(); start = end - timedelta(days=days)
    metrics = "views,averageViewPercentage,averageViewDuration,subscribersGained"
    mlist = metrics.split(",")
    page = max(1, min(200, limit or 200))  # Analytics 單頁上限 200 → 分頁抓齊,別靜默漏抓尾部影片
    out = {}
    try:
        idx = 1
        while idx <= 5000:  # 上限保護
            r = ya.reports().query(
                ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                dimensions="video", metrics=metrics, sort="-views",
                maxResults=page, startIndex=idx,
            ).execute()
            rows = r.get("rows", [])
            for row in rows:
                vid = row[0]
                vals = {mlist[i]: row[i + 1] for i in range(len(mlist))}
                ret = vals.get("averageViewPercentage")
                out[vid] = {"views": vals.get("views"),
                            "retention": (min(100.0, ret) if ret is not None else None),  # loop重播Shorts原生會>100%,夾回
                            "avg_dur": vals.get("averageViewDuration"),
                            "subs": vals.get("subscribersGained")}
            if len(rows) < page:
                break
            idx += page
        return out or None
    except Exception:
        return out or None


@_dailycache
def impressions_ctr(days=28):
    """近 N 天曝光與點閱率（impressions / CTR）。需要此維度的帳號才有，失敗回 None。"""
    ya = _service()
    if ya is None:
        return None
    end = date.today(); start = end - timedelta(days=days)
    try:
        r = ya.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            metrics="impressions,impressionClickThroughRate",
        ).execute()
        rows = r.get("rows", [])
        if not rows:
            return {"impressions": 0, "ctr": 0.0}
        return {"impressions": rows[0][0], "ctr": rows[0][1]}
    except Exception:
        return None
