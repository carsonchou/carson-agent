#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_public.py — 把已上傳的 6 支影片隱私改成 public（需 youtube.force-ssl，
沿用 update_videos.py 建立的 token_manage.json，不需再授權）。

用法：python scripts\\set_public.py            # 全部轉 public
      python scripts\\set_public.py --privacy unlisted   # 或轉不公開連結
"""
from __future__ import annotations

import argparse
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

MANAGE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"

VIDEO_IDS = {
    "網格能不能賺錢": "fO-ZyxHI_xY",
    "實測企劃EP0": "ijCNjwEDRnc",
    "90%賠錢關鍵參數": "Qf-xkKw4kGQ",
    "派網Pionex是什麼": "_I82uMc__HM",
    "DCA定投vs網格": "K4x90FeqZSo",
    "什麼是回測": "wZyBaJJ7A40",
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    yt = get_service()
    done = 0
    for name, vid in VIDEO_IDS.items():
        cur = yt.videos().list(part="status", id=vid).execute()
        items = cur.get("items", [])
        if not items:
            print(f"[warn] 找不到 {name} ({vid})，略過。")
            continue
        status = items[0]["status"]
        status["privacyStatus"] = args.privacy
        # madeForKids 必填：沿用現值，預設非兒童向
        status.setdefault("selfDeclaredMadeForKids", False)
        yt.videos().update(part="status", body={"id": vid, "status": status}).execute()
        done += 1
        print(f"[ok] {name} -> {args.privacy}  (https://youtu.be/{vid})")

    print(f"\n完成：{done} 支已設為 {args.privacy}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
