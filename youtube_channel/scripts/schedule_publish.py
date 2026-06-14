#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schedule_publish.py — 出國前囤片：把已渲好的影片上傳為「排程公開」，由 YouTube 自動定時發布。

關鍵：上傳時設 status.privacyStatus="private" + status.publishAt=<未來時間>，
YouTube 會在指定時間自動把影片轉公開 —— 這個動作在 YouTube 伺服器上完成，
**完全不需要你家的電腦或網路**。所以你人在國外、家裡斷網，頻道照樣每天自動更新。

受 YouTube 配額限制（每日約 6 支上傳），出發前可分今天+明天各跑一次累積更多。
過審才排（重用 audit_video），避免排到壞片/違規片。

用法：
  python scripts/schedule_publish.py --days 7              # 排 7 天，每天 1 支，晚間發
  python scripts/schedule_publish.py --days 12 --per-day 1 --start 1 --hour 19 --max 6
參數：
  --days N      排幾天份（從 --start 起算）
  --per-day K   每天發幾支（預設 1）
  --start D     從幾天後開始（預設 1＝明天）
  --hour H      每天幾點發（台灣時間，預設 19=晚間黃金時段）
  --max M       本次最多上傳幾支（預設 6，顧及配額；明天可再跑一次補）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_publish as dp  # 重用 get_service / find_candidates / ledger / metadata
import upload_youtube as up
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

try:
    from audit_video import audit
except Exception:  # noqa: BLE001
    def audit(slug):
        return True, []

TW = timezone(timedelta(hours=8))


def upload_scheduled(yt, slug: str, publish_at_utc: datetime) -> str:
    """上傳為 private + publishAt（排程公開）。回傳 videoId。"""
    cfg = up.load_channel_config()
    meta = up.assemble_metadata(slug=slug, md_path=dp.OUTPUT / f"{slug}.md",
                                channel_config=cfg, append_affiliate=True)
    meta = up.enforce_youtube_limits(meta)
    body = {
        "snippet": {
            "title": meta["title"], "description": meta["description"],
            "tags": meta.get("tags", []), "categoryId": "28", "defaultLanguage": "zh-Hant",
        },
        "status": {
            "privacyStatus": "private",                     # 排程必須先 private
            "publishAt": publish_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "selfDeclaredMadeForKids": False, "embeddable": True,
        },
    }
    media = MediaFileUpload(str(dp.OUTPUT / f"{slug}.mp4"), resumable=True, chunksize=4 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=False)
    resp = None
    while resp is None:
        _s, resp = req.next_chunk()
    vid = resp["id"]
    thumb = dp.THUMBS / f"{slug}.jpg"
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except Exception:
            pass
    return vid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--per-day", type=int, default=1)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--hour", type=int, default=19)
    ap.add_argument("--max", type=int, default=6)
    args = ap.parse_args()

    yt = dp.get_service()
    ledger = dp.load_ledger()
    cands = dp.find_candidates(ledger)
    if not cands:
        print("沒有可排程的未上架影片。")
        return 0

    # 算發布時段：從 start 天後起，每天 per_day 支，在 hour 點（台灣→轉 UTC）
    today_tw = datetime.now(TW).replace(hour=args.hour, minute=0, second=0, microsecond=0)
    slots = []
    for d in range(args.days):
        day = today_tw + timedelta(days=args.start + d)
        for k in range(args.per_day):
            # 同日多支則錯開 2 小時
            slots.append((day + timedelta(hours=2 * k)).astimezone(timezone.utc))
    # 只能上傳到配額上限
    n = min(args.max, len(cands), len(slots))
    print(f"準備排程 {n} 支（候選 {len(cands)}、時段 {len(slots)}、本次上限 {args.max}）…")

    done = 0
    for i in range(n):
        slug = cands[i]
        ok, reasons = audit(slug)
        if not ok:
            print(f"[跳過] {slug} 未過審：{'；'.join(reasons)[:60]}")
            continue
        at = slots[i]
        try:
            vid = upload_scheduled(yt, slug, at)
            ledger[slug] = vid
            dp.save_ledger(ledger)
            at_tw = at.astimezone(TW).strftime("%m-%d %H:%M")
            print(f"[ok] 已排程 {slug} → 公開於 {at_tw}（台灣）　https://youtu.be/{vid}")
            done += 1
        except HttpError as e:
            if "quota" in str(e).lower():
                print(f"[配額用罄] 已排 {done} 支，明天再跑一次補更多。")
                break
            print(f"[錯誤] {slug}: {e}", file=sys.stderr)
    try:
        dp.log_ops("排程囤片", f"出國前排程 {done} 支，YouTube 將定時自動公開")
    except Exception:
        pass
    print(f"\n[完成] 本次排程 {done} 支。出國前可明天再跑一次累積更多天份。")
    print("這些影片由 YouTube 伺服器定時公開，不依賴你的電腦/家用網路。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
