#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_thumbnails.py — 把 assets/thumbnails/<slug>.jpg 設為各影片的自訂縮圖。

需 youtube.force-ssl（沿用 token_manage.json）。注意：YouTube 帳號必須先完成
「電話驗證」(youtube.com/verify) 才能用自訂縮圖，否則 API 會回權限錯誤。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MANAGE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"
THUMB_DIR = PROJECT_ROOT / "assets" / "thumbnails"

# slug -> videoId
VIDEOS = {
    "網格機器人能不能賺錢_原理風險與誰適合": "fO-ZyxHI_xY",
    "自動交易機器人實測企劃_規則先講死_EP0": "ijCNjwEDRnc",
    "玩網格90趴賠錢的關鍵參數_區間設定": "Qf-xkKw4kGQ",
    "派網Pionex是什麼_新手搞懂自動交易平台": "_I82uMc__HM",
    "DCA定投機器人vs網格機器人_哪個適合你": "K4x90FeqZSo",
    "什麼是回測_沒回測別拿真錢碰": "wZyBaJJ7A40",
}


def get_service():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), MANAGE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), MANAGE_SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def main() -> int:
    yt = get_service()
    ok = 0
    verify_hint = False
    for slug, vid in VIDEOS.items():
        thumb = THUMB_DIR / f"{slug}.jpg"
        if not thumb.exists():
            print(f"[warn] 縮圖不存在：{thumb}")
            continue
        try:
            yt.thumbnails().set(
                videoId=vid,
                media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
            ).execute()
            ok += 1
            print(f"[ok] 縮圖已設定：{slug} -> {vid}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            print(f"[FAIL] {slug} ({vid})：{msg[:160]}")
            if "thumbnail" in msg.lower() or "permission" in msg.lower() or "forbidden" in msg.lower():
                verify_hint = True

    print(f"\n完成：{ok}/{len(VIDEOS)} 支已設縮圖。")
    if verify_hint:
        print("⚠️ 若失敗為權限問題：請先到 https://www.youtube.com/verify 完成電話驗證，"
              "才能使用自訂縮圖，然後重跑本程式。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
