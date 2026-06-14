#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_videos.py — 就地更新已上傳影片的描述/標題/標籤，並刪除壞的重複。

需要比 upload 更大的權限（youtube.force-ssl），所以用獨立的 token_manage.json，
首次執行會再開一次瀏覽器要你同意（這次包含「管理影片」權限）。

用途：把已上傳的 6 支影片描述換成 channel_config.json 裡的最新聯盟連結，
並刪除那支 0MB 競爭上傳的壞重複。
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
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import upload_youtube as up  # 重用 metadata 組裝邏輯
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

MANAGE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"
OUTPUT_DIR = PROJECT_ROOT / "output"

# 好的 6 支：slug -> videoId
VIDEOS = {
    "網格機器人能不能賺錢_原理風險與誰適合": "fO-ZyxHI_xY",
    "自動交易機器人實測企劃_規則先講死_EP0": "ijCNjwEDRnc",
    "玩網格90趴賠錢的關鍵參數_區間設定": "Qf-xkKw4kGQ",
    "派網Pionex是什麼_新手搞懂自動交易平台": "_I82uMc__HM",
    "DCA定投機器人vs網格機器人_哪個適合你": "K4x90FeqZSo",
    "什麼是回測_沒回測別拿真錢碰": "wZyBaJJ7A40",
}
# 0MB 競爭上傳的壞重複（要刪）
BROKEN_DUP = "m7_5SZPOP3c"


def get_service():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), MANAGE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("[info] 開啟瀏覽器進行授權（這次需要『管理影片』權限）…")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), MANAGE_SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
        print(f"[ok] token 已快取到 {TOKEN}")
    return build("youtube", "v3", credentials=creds)


def main() -> int:
    cfg = up.load_channel_config()
    yt = get_service()

    updated = 0
    for slug, vid in VIDEOS.items():
        md_path = OUTPUT_DIR / f"{slug}.md"
        meta = up.assemble_metadata(slug=slug, md_path=md_path, channel_config=cfg, append_affiliate=True)
        meta = up.enforce_youtube_limits(meta)

        # 取現有 snippet 保留 categoryId / defaultLanguage 等必填欄位
        cur = yt.videos().list(part="snippet", id=vid).execute()
        items = cur.get("items", [])
        if not items:
            print(f"[warn] 找不到影片 {vid}（{slug}），略過。")
            continue
        snip = items[0]["snippet"]
        snip["title"] = meta["title"]
        snip["description"] = meta["description"]
        snip["tags"] = meta.get("tags") or snip.get("tags", [])
        snip.setdefault("categoryId", "28")

        yt.videos().update(part="snippet", body={"id": vid, "snippet": snip}).execute()
        updated += 1
        print(f"[ok] 已更新描述/連結：{slug} -> {vid}")

    # 刪除壞的重複
    try:
        yt.videos().delete(id=BROKEN_DUP).execute()
        print(f"[ok] 已刪除壞的重複影片 {BROKEN_DUP}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 刪除 {BROKEN_DUP} 失敗（可能已不存在或無權限）：{exc}")

    print(f"\n完成：更新 {updated} 支描述。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
