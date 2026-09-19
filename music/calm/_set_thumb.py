#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_set_thumb.py — 補設縮圖(給上傳中途被砍、縮圖那步沒跑到的影片)。

用法:python _set_thumb.py <KEY> <videoId>
會先輪詢到 processed 才設(處理中設縮圖有機率被之後的處理覆蓋),
設完回讀確認,並檢查 selfDeclaredMadeForKids 沒有被動到。
"""
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def main():
    if len(sys.argv) < 3:
        print("用法:python _set_thumb.py <KEY> <videoId>")
        return 1
    key, vid = sys.argv[1], sys.argv[2]
    thumb = ROOT / f"thumb_{key}.png"
    if not thumb.exists():
        print(f"縮圖不存在:{thumb}")
        return 1
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}"); return 1

    for i in range(160):                      # 最多等 40 分鐘
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"[X] 查不到影片 {vid}"); return 1
        us = items[0]["status"].get("uploadStatus")
        if us == "rejected":
            print(f"[X] 被拒:{items[0]['status'].get('rejectionReason')}"); return 1
        if us == "processed":
            break
        if i % 8 == 0:
            print(f"  等待處理中({us})… {i*15//60} 分")
        time.sleep(15)

    yt.thumbnails().set(videoId=vid, media_body=str(thumb)).execute()
    got = yt.videos().list(part="snippet,status,contentDetails",
                           id=vid).execute()["items"][0]
    st, sn = got["status"], got["snippet"]
    print(f"縮圖已設 {thumb.name} → {vid}")
    print(f"  時長 {got['contentDetails']['duration']}  隱私 {st['privacyStatus']}"
          f"  狀態 {st.get('uploadStatus')}")
    print(f"  兒童內容自我宣告 {st.get('selfDeclaredMadeForKids')} "
          f"{'✓' if st.get('selfDeclaredMadeForKids') is False else '⚠️ 被動到了'}")
    print(f"  縮圖 URL {sn['thumbnails'].get('high', {}).get('url', '(無)')}")
    print(f"  https://youtu.be/{vid}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
