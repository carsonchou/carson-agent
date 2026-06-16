# -*- coding: utf-8 -*-
"""yt_analytics.py — YouTube Analytics 查詢小工具（給數據/CTR/回顧檢討部門用）。

需先跑 auth_analytics.py 產 token_analytics.json。沒 token 時所有函式回 None（優雅降級，
呼叫端就退回原本的「無 CTR」行為，不報錯、不假裝有數字）。
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
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
        return {"days": days, "views": v[0], "minutes": v[1], "avg_pct": v[2],
                "avg_dur": v[3], "subs_gained": v[4]}
    except Exception:
        return None


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
            out.append({"video_id": row[0], "views": row[1], "avg_pct": row[2]})
        return out
    except Exception:
        return None


def video_stats(days=180, limit=200):
    """近 N 天每支影片的 觀看／留存%／CTR。回 {videoId: {views, retention, ctr}} 或 None。
    先試含 CTR（impressionClickThroughRate，部分帳號/維度不支援），失敗退回只取觀看+留存。"""
    ya = _service()
    if ya is None:
        return None
    end = date.today(); start = end - timedelta(days=days)
    for metrics in ("views,averageViewPercentage,impressionClickThroughRate",
                    "views,averageViewPercentage"):
        try:
            r = ya.reports().query(
                ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                dimensions="video", metrics=metrics, sort="-views", maxResults=limit,
            ).execute()
            mlist = metrics.split(",")
            out = {}
            for row in r.get("rows", []):
                vid = row[0]
                vals = {mlist[i]: row[i + 1] for i in range(len(mlist))}
                out[vid] = {"views": vals.get("views"),
                            "retention": vals.get("averageViewPercentage"),
                            "ctr": vals.get("impressionClickThroughRate")}
            return out
        except Exception:
            continue
    return None


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
