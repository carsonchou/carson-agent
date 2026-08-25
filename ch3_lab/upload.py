#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""upload.py — 把 publish_meta.json 裡的集數上傳到副頻道 They Ran It Again。

繼承 music/calm/upload3.py 已驗過的教訓,不重新發明:
- **頻道白名單比對 channel ID**,不是比對 handle 字串。舊版 `if "carson" in
  customUrl` 是 fail-open:改名、customUrl 為 None、或第三個頻道都能過關。
- **selfDeclaredMadeForKids=False 必設**(不設 = 留言與營利腰斬)。
- **上傳完成 ≠ 處理完成**:輪詢到 processed 才算數;逾時要明講,不能默默當成功。
- **不信 insert 的回應,回讀確認**。
- 隱私參數**必填**:public 不可逆,不該有預設值。
- 不要設 `defaultAudioLanguage="zxx"`,API 會回 INVALID_REQUEST_METADATA。

## 每支片的配額
videos.insert = 1600 單位。ch2 用獨立的 GCP 專案(quiet-hour-yt),一天 10,000
→ **一天最多 6 支**(6×1600=9,600,再加縮圖與回讀就滿了)。所以預設一次只發
`--limit` 支,而且會先把估算印出來。

用法:
  python upload.py --list
  python upload.py --slug ego_depletion --privacy private
  python upload.py --limit 3 --privacy private
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
COST_INSERT, COST_THUMB, DAILY_QUOTA = 1600, 50, 10000


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def ledger():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:            # noqa: BLE001
        return {}


def key_of(o):
    return o.get("slug") or o["dir"]


def upload_one(yt, o, privacy):
    from googleapiclient.http import MediaFileUpload
    video = ROOT / o["video"]
    print(f"\n[{key_of(o)}] {o['title']}")
    if not video.exists():
        print(f"    ⛔ 影片不存在:{video}")
        return None
    print(f"    {video.name} {video.stat().st_size / 1024 / 1024:.0f}MB  隱私 {privacy}")
    body = {
        "snippet": {"title": o["title"], "description": o["description"],
                    "tags": o["tags"], "categoryId": "27",   # Education
                    "defaultLanguage": "en"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, last = None, -1
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            p = int(status.progress() * 100)
            if p >= last + 25:
                print(f"    上傳 {p}%"); last = p
    vid = resp["id"]
    print(f"    videoId={vid}  輪詢處理狀態…")
    processed = False
    for _ in range(40):                       # 這批片約 80 秒,10 分鐘綽綽有餘
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"    ⛔ 影片查不到(通常=被拒)。videoId={vid}")
            return None
        st = items[0]["status"]
        if st.get("uploadStatus") == "rejected":
            print(f"    ⛔ 被拒:{st.get('rejectionReason')}")
            return None
        if st.get("uploadStatus") == "processed":
            print("    處理完成 ✓"); processed = True
            break
        time.sleep(15)
    if not processed:
        print("    ⚠️ 輪詢 10 分鐘仍未 processed,稍後自行到 Studio 確認")

    thumb = ROOT / o["thumb"] if o.get("thumb") else None
    if thumb and thumb.exists():
        yt.thumbnails().set(videoId=vid, media_body=str(thumb)).execute()
        print("    縮圖已設 ✓")
    else:
        print("    ⚠️ 找不到縮圖,略過")

    got = yt.videos().list(part="snippet,status", id=vid).execute()["items"][0]
    s = got["status"]
    ok_title = got["snippet"]["title"] == o["title"]
    print(f"    回讀:隱私 {s['privacyStatus']}  兒童 {s.get('selfDeclaredMadeForKids')}"
          f"  標題{'✓' if ok_title else ' ⚠️ 不符'}")
    print(f"    https://youtu.be/{vid}")
    return vid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"])
    ap.add_argument("--list", action="store_true", dest="show")
    a = ap.parse_args()

    meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    done = ledger()
    todo = [o for o in meta if key_of(o) not in done]
    if a.slug:
        todo = [o for o in todo if key_of(o) == a.slug or
                pathlib.Path(o["dir"]).name == a.slug]
    if a.show:
        for o in meta:
            mark = f"已上傳 {done[key_of(o)]}" if key_of(o) in done else "未上傳"
            exists = "✓" if (ROOT / o["video"]).exists() else "✗片子不在"
            print(f"  {key_of(o):<26}{o['track']:<6}{exists:<10}{mark}")
        print(f"\n共 {len(meta)} 集,已上傳 {len(done)},待上傳 {len(meta) - len(done)}")
        return 0

    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        print("沒有待上傳的集數"); return 0

    est = len(todo) * (COST_INSERT + COST_THUMB)
    print(f"要上傳 {len(todo)} 集,估算配額 {est:,} / 每日 {DAILY_QUOTA:,}")
    if est > DAILY_QUOTA:
        print(f"⛔ 會超過當日配額(一天最多 "
              f"{DAILY_QUOTA // (COST_INSERT + COST_THUMB)} 支),請用 --limit")
        return 1
    if not a.privacy:
        print("⛔ --privacy 必填(public 不可逆,不設預設值)")
        return 1

    yt = svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    print(f"目標頻道:{me['snippet']['title']} ({me['snippet'].get('customUrl')})")
    if me["id"] != EXPECT_CHANNEL:          # 白名單比對 ID,不是 handle 字串
        print(f"⛔ 頻道不符:{me['id']} != {EXPECT_CHANNEL},中止。")
        return 1

    for o in todo:
        vid = upload_one(yt, o, a.privacy)
        if vid:
            done[key_of(o)] = vid
            LEDGER.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"\n完成。帳本 {LEDGER.name} 共 {len(done)} 支。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
