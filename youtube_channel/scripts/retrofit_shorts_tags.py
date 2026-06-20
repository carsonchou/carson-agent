#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retrofit_shorts_tags.py — 補打 #Shorts 標籤到已上架的 Shorts 影片。

問題：過去上架的 Shorts 描述沒有 #Shorts，YouTube 無法把它們分類進 Shorts shelf。
做法：讀 uploaded_ledger.json，找出所有 S_* slug，批次更新它們的 description + title
加入 #Shorts，讓 YouTube 重新分類並推入 Shorts 推薦流。

每次 videos.update 耗 50 配額單位；預設每日 10000 單位 = 最多可更新 ~200 支。
建議一次跑完，之後每次 daily_publish 新影片已自動加 #Shorts，不需再跑。

用法：
  python scripts/retrofit_shorts_tags.py           # 更新所有缺 #Shorts 的 Shorts
  python scripts/retrofit_shorts_tags.py --dry-run # 只印出，不實際更新
  python scripts/retrofit_shorts_tags.py --limit 30 # 只更新前 30 支
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN = PROJECT_ROOT / "token_manage.json"
LEDGER = PROJECT_ROOT / "STUDIO" / "uploaded_ledger.json"
OUTPUT = PROJECT_ROOT / "output"

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

_SHORTS_HASHTAGS = "\n\n#Shorts #量化交易 #網格交易 #派網 #Pionex #被動收入 #投資理財 #自動交易"
MAX_DESC = 5000
MAX_TITLE = 100


def get_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def fetch_video_meta(yt, video_ids: list[str]) -> dict:
    """批次拉影片現有 snippet（title + description + tags）。回傳 {vid: snippet}。"""
    result = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            resp = yt.videos().list(part="snippet", id=",".join(chunk)).execute()
            for item in resp.get("items", []):
                result[item["id"]] = item["snippet"]
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 拉 snippet 失敗：{exc}", file=sys.stderr)
    return result


def update_video(yt, vid: str, snippet: dict, dry_run: bool) -> bool:
    desc = snippet.get("description") or ""
    title = snippet.get("title") or ""

    needs_desc = "#shorts" not in desc.lower()
    needs_title = "#shorts" not in title.lower() and len(title) <= 90

    if not needs_desc and not needs_title:
        print(f"[skip] {vid} 已有 #Shorts")
        return False

    new_desc = (desc + _SHORTS_HASHTAGS)[:MAX_DESC] if needs_desc else desc
    new_title = (title + " #Shorts") if needs_title else title

    if dry_run:
        print(f"[dry] {vid} | title: {new_title[:60]} | desc 末尾: {new_desc[-30:]}")
        return True

    try:
        snippet["description"] = new_desc
        snippet["title"] = new_title
        yt.videos().update(
            part="snippet",
            body={"id": vid, "snippet": snippet},
        ).execute()
        print(f"[ok] {vid} → 已補 #Shorts")
        return True
    except HttpError as exc:
        if "quota" in str(exc).lower() or "exceeded" in str(exc).lower():
            print(f"[QUOTA] 配額用罄，已停止。已更新上方所有影片。", file=sys.stderr)
            raise
        print(f"[err] {vid}: {str(exc)[:100]}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="補打 #Shorts 到已上架的 Shorts 影片")
    ap.add_argument("--dry-run", action="store_true", help="只印，不實際更新")
    ap.add_argument("--limit", type=int, default=0, help="最多更新幾支（0=不限）")
    args = ap.parse_args()

    if not LEDGER.exists():
        print("[error] 找不到 uploaded_ledger.json", file=sys.stderr)
        return 1

    ledger: dict = json.loads(LEDGER.read_text(encoding="utf-8"))
    # 只處理 S_* (Shorts)
    shorts_items = [(slug, vid) for slug, vid in ledger.items() if slug.startswith("S_")]
    print(f"[info] 台帳中共 {len(shorts_items)} 支 Shorts")

    if not shorts_items:
        print("[info] 沒有 Shorts 需要處理")
        return 0

    yt = get_service()

    # 批次拉現有 snippet
    vid_to_slug = {vid: slug for slug, vid in shorts_items}
    all_vids = list(vid_to_slug.keys())
    print(f"[info] 正在拉 {len(all_vids)} 支影片的 snippet…")
    meta = fetch_video_meta(yt, all_vids)

    # 找出需要更新的
    to_update = []
    for vid, snippet in meta.items():
        desc = snippet.get("description") or ""
        title = snippet.get("title") or ""
        if "#shorts" not in desc.lower() or ("#shorts" not in title.lower() and len(title) <= 90):
            to_update.append((vid, snippet))

    print(f"[info] 需補 #Shorts 的：{len(to_update)} 支")
    if args.limit:
        to_update = to_update[:args.limit]
        print(f"[info] 限制只更新前 {args.limit} 支")

    updated = 0
    for vid, snippet in to_update:
        try:
            if update_video(yt, vid, snippet, args.dry_run):
                updated += 1
            if not args.dry_run:
                time.sleep(0.3)  # 避免 API 短時間爆量
        except HttpError:
            break

    print(f"\n完成：{'模擬' if args.dry_run else '實際'}更新 {updated} 支 Shorts 補入 #Shorts 標籤")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
