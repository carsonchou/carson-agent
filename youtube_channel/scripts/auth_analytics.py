#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auth_analytics.py — 加開 YouTube Analytics 權限（一次性，需在瀏覽器按同意）。

會開啟瀏覽器讓你登入並『允許』查看 YouTube Analytics 報表。
成功後寫出 token_analytics.json（含 force-ssl + yt-analytics.readonly），
數據/CTR/回顧檢討部門就能讀到真實 CTR、留存、流量來源。

⚠️ 另需在 Google Cloud Console 啟用「YouTube Analytics API」(若尚未啟用)。
   執行：右下角會印出測試查詢結果；若 403 提示 API 未啟用，去 Console 開啟即可。
"""
from __future__ import annotations
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRETS = ROOT / "client_secrets.json"
TOKEN = ROOT / "token_analytics.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> int:
    if not CLIENT_SECRETS.exists():
        print(f"[FATAL] 找不到 {CLIENT_SECRETS}", file=sys.stderr)
        return 2
    creds = None
    if TOKEN.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            print("即將開啟瀏覽器，請登入你的 YouTube 帳號並按『允許/Allow』授權 Analytics 唯讀權限…")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"[ok] 授權完成，已寫出 {TOKEN.name}")

    # 測試查詢：近 28 天 CTR / 觀看 / 平均觀看時長
    try:
        ya = build("youtubeAnalytics", "v2", credentials=creds)
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=28)
        r = ya.reports().query(
            ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
            metrics="views,estimatedMinutesWatched,averageViewPercentage,annotationClickThroughRate",
        ).execute()
        rows = r.get("rows", [])
        if rows:
            v = rows[0]
            print(f"[測試] 近28天 觀看 {v[0]}、總觀看分鐘 {v[1]}、平均觀看% {v[2]}、（部分指標需流量才有值）")
        else:
            print("[測試] Analytics 連上了，但近 28 天尚無足夠數據（頻道剛起步，正常）。")
        print("✅ YouTube Analytics 權限已就緒。數據/CTR/回顧檢討部門之後就能讀真實指標。")
    except Exception as e:
        print(f"[注意] 授權成功，但測試查詢失敗：{e}", file=sys.stderr)
        print("  → 多半是『YouTube Analytics API』在 Google Cloud Console 尚未啟用。"
              "請到 Console 搜尋並啟用後再重跑本腳本即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
