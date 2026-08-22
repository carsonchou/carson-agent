#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""upload3.py — 三支氛圍測試片上傳(ch2)。

繼承 upload.py 的三條教訓:
- selfDeclaredMadeForKids=False 必設(不設=留言/營利腰斬)
- 上傳完成 ≠ 處理完成:輪詢到 processed/rejected 才算數
- 不信 insert 回應,回讀確認

三支片打三個搜尋意圖(deep work / sleep dark screen / rain),
描述誠實揭露:視覺=真實流體物理模擬(非 AI 生成)、音樂=程式原創合成、
音樂每 10 分鐘無縫循環、視覺 60 分鐘連續演化不循環。

用法:python upload3.py [A|B|C|all] [public|unlisted]
"""
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

COMMON_DESC = """
—
About this video (honest notes):
• The visuals are a real fluid-dynamics simulation (Navier-Stokes equations, computed frame by frame). Nothing is AI-generated imagery — every wisp of ink is physics. The simulation runs continuously for the full hour and never loops or repeats.
• The music is original, synthesised note by note in code. It is not from a stock library and not AI-generated audio. The piece loops seamlessly every 10 minutes by design — ambient music should have no destination.
• No mid-roll ads. No voice. No sudden loud moments.
"""

VIDEOS = {
    "A": {
        "file": "final_A.mp4", "thumb": "thumb_A.png",
        "title": "Deep Focus Ambient — Ink Drifting in Water (1 Hour) | Study, Work, Coding",
        "desc": "One hour of calm for deep work. Ink slowly blooming in water — "
                "a real fluid simulation, evolving for the whole hour and never repeating — "
                "with original ambient music in D pentatonic: no clashing notes, "
                "no melody to follow, nothing that asks for your attention.\n"
                "00:00 Begin\n" + COMMON_DESC,
        "tags": ["focus music", "deep work", "study music", "ambient music",
                 "concentration music", "work music", "coding music", "1 hour",
                 "calm music", "background music", "ink in water", "fluid art",
                 "study with me", "pomodoro", "adhd focus"],
    },
    "B": {
        "file": "final_B.mp4", "thumb": "thumb_B.png",
        "title": "Sleep Ambient, Dark Screen — Slow Ink at Night (1 Hour) | Deep Sleep Music",
        "desc": "One hour of near-darkness for sleep. Cool ink — ice blue, pale "
                "aqua, faint violet — drifting through a dark field. A real fluid "
                "simulation, slow enough to fall asleep to, with original low "
                "ambient music: sparse notes, ten-second decays, nothing sudden. "
                "The screen stays dark for the whole hour: no bright flashes, "
                "nothing that will wake you.\n"
                "00:00 Begin\n" + COMMON_DESC,
        "tags": ["sleep music", "dark screen", "deep sleep", "sleep aid",
                 "ambient sleep music", "insomnia relief", "1 hour", "calm music",
                 "relaxing music", "night music", "black screen sleep",
                 "meditation music", "wind down"],
    },
    "C": {
        "file": "final_C.mp4", "thumb": "thumb_C.png",
        "title": "Gentle Rain & Soft Ambient — Ink on Paper (1 Hour) | Rain Sounds for Study, Sleep",
        # 🔴 原文寫雨勢「never repeat exactly」是**假的**:音訊是 10 分鐘循環平鋪 6 次,
        #    一小時內雨聲會重複 6 輪。COMMON_DESC 已誠實揭露循環,這句不可與它打架。
        "desc": "One hour of gentle rain with soft, distant tones. Cool ink "
                "spreading on paper — a real fluid simulation that runs "
                "continuously for the full hour — while synthesised rain rises "
                "and falls in slow waves.\n"
                "00:00 Begin\n" + COMMON_DESC,
        "tags": ["rain sounds", "rain ambience", "study music", "sleep music",
                 "rain for sleeping", "gentle rain", "ambient music", "1 hour",
                 "relaxing rain", "white noise", "rain no thunder", "cozy rain",
                 "reading music"],
    },
}


def svc():
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def upload_one(yt, key, privacy):
    cfg = VIDEOS[key]
    video = ROOT / cfg["file"]
    print(f"\n[{key}] {cfg['title']}")
    print(f"    檔案 {video.name} {video.stat().st_size/1024/1024:.0f}MB  隱私 {privacy}")
    body = {
        "snippet": {"title": cfg["title"], "description": cfg["desc"],
                    "tags": cfg["tags"], "categoryId": "10",
                    "defaultLanguage": "en", "defaultAudioLanguage": "zxx"},
        "status": {"privacyStatus": privacy,
                   "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, last = None, -1
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            p = int(status.progress() * 100)
            if p >= last + 20:
                print(f"    上傳 {p}%"); last = p
    vid = resp["id"]
    print(f"    videoId={vid}  輪詢處理狀態…")
    for i in range(30):
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"    [X] 影片查不到(通常=被拒)。videoId={vid}")
            return None
        us = items[0]["status"].get("uploadStatus")
        if us == "rejected":
            print(f"    [X] 被拒:{items[0]['status'].get('rejectionReason')}")
            return None
        if us == "processed":
            print("    處理完成 ✓")
            break
        time.sleep(15)
    thumb = ROOT / cfg["thumb"]
    if thumb.exists():
        yt.thumbnails().set(videoId=vid, media_body=str(thumb)).execute()
        print("    縮圖已設 ✓")
    got = yt.videos().list(part="snippet,status", id=vid).execute()["items"][0]
    st = got["status"]
    print(f"    回讀:隱私 {st['privacyStatus']}  兒童 {st.get('selfDeclaredMadeForKids')}"
          f"  狀態 {st.get('uploadStatus')}")
    print(f"    https://youtu.be/{vid}")
    return vid


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    privacy = sys.argv[2] if len(sys.argv) > 2 else "public"
    keys = list(VIDEOS) if which == "all" else [which]
    yt = svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    print(f"上傳目標頻道:{me['snippet']['title']} ({me['snippet'].get('customUrl')})")
    if "carson" in (me["snippet"].get("customUrl") or "").lower():
        print("⛔ 這是主頻道!中止。"); return 1
    for k in keys:
        upload_one(yt, k, privacy)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
