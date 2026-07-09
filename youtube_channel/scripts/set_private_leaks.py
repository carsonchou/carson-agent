#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_private_leaks.py — 把 STUDIO/weekly_winners_state.json 裡
`leak_titles`（洗版骨架/破產爆倉/低完播老弱片清單，內部 slug 字串）
在 YouTube 精準匹配成 videoId 後設為 private（不公開，可逆，不刪）。

匹配策略（只做精準比對，不模糊猜測；對不上就跳過）：
  1. 優先查 STUDIO/uploaded_ledger.json（studio 產線自己的
     slug -> videoId 對照表，被 cover_redone_ledger / multipost_ledger /
     ig_ledger 等共用，非本腳本自建猜測）。
  2. ledger 沒有的，退而掃描頻道 uploads playlist，找標題完全等於
     「slug」或「slug + ' #Shorts'」且唯一一支的影片（同名多支一律跳過）。

沿用 update_videos.py / set_public.py 的憑證模式：
  token_manage.json + client_secrets.json, scope=youtube.force-ssl。

預設 --dry-run（只列出會怎麼改，不寫入）。要真的執行需明確加 --apply。
每次執行都會做讀回自驗（重新查一次 privacyStatus 確認=private），
並抽查頻道內標題含 --winner-keywords 的影片，確認高觀看數的仍是原本狀態，
報告寫到 output/privacy_reports/<timestamp>.json（不進版控，見 .gitignore 慣例）。

用法：
  python scripts\\set_private_leaks.py --dry-run   # 只看會匹配到誰，不寫入（預設）
  python scripts\\set_private_leaks.py --apply      # 真的執行 videos().update
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STUDIO = PROJECT_ROOT / "STUDIO"
CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
TOKEN = PROJECT_ROOT / "token_manage.json"
REPORT_DIR = PROJECT_ROOT / "output" / "privacy_reports"

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

MANAGE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
DEFAULT_WINNER_KEYWORDS = ["複利", "ETF", "定投", "賓士", "停損"]


def get_service():
    if not TOKEN.exists():
        raise SystemExit("[FATAL] token_manage.json 不存在，無寫入憑證，停止。")
    creds = Credentials.from_authorized_user_file(str(TOKEN), MANAGE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise SystemExit("[FATAL] token 無效且無 refresh_token，需要 Carson 重新授權，停止。")
    return build("youtube", "v3", credentials=creds)


def get_uploads_playlist_id(yt):
    resp = yt.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise SystemExit("[FATAL] channels().list(mine=True) 找不到頻道，憑證可能沒有存取權。")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_all_uploads(yt, playlist_id):
    """回傳 list of dict: {videoId, title}（來自 playlistItems 的 snippet）"""
    out = []
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            vid = it["contentDetails"]["videoId"]
            title = it["snippet"]["title"]
            out.append({"videoId": vid, "title": title})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def get_videos_full(yt, video_ids):
    """回傳 dict videoId -> {title, privacyStatus, viewCount, status(dict)}
    用 videos().list 直查 id（不靠 playlist 列舉，涵蓋 playlist 分頁可能漏掉的項目）。"""
    out = {}
    video_ids = list(dict.fromkeys(video_ids))  # 去重保序
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        if not chunk:
            continue
        resp = yt.videos().list(part="snippet,status,statistics", id=",".join(chunk)).execute()
        for it in resp.get("items", []):
            out[it["id"]] = {
                "title": it["snippet"]["title"],
                "privacyStatus": it["status"]["privacyStatus"],
                "viewCount": int(it.get("statistics", {}).get("viewCount", 0)),
                "status": it["status"],
            }
    return out


def match_leak_titles(leak_titles, ledger, title_map):
    """回傳 (matched: {title: videoId}, match_source: {title: str}, unmatched: [(title, reason)])"""
    matched, match_source, unmatched = {}, {}, []
    for t in leak_titles:
        if t in ledger:
            matched[t] = ledger[t]
            match_source[t] = "uploaded_ledger.json"
            continue
        ids = title_map.get(t)
        if ids and len(ids) == 1:
            matched[t] = ids[0]
            match_source[t] = "uploads_playlist標題完全相符"
            continue
        ids2 = title_map.get(t + " #Shorts")
        if ids2 and len(ids2) == 1:
            matched[t] = ids2[0]
            match_source[t] = "uploads_playlist標題=slug+' #Shorts'完全相符"
            continue
        if ids and len(ids) > 1:
            unmatched.append((t, f"標題重複({len(ids)}支同名，無法精準對上單一 id，跳過): {ids}"))
        else:
            unmatched.append((t, "ledger 與 uploads playlist 皆找不到精準相符，跳過"))
    return matched, match_source, unmatched


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的呼叫 videos().update 寫入；不加則只 dry-run")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"],
                     help="要設成的 privacyStatus（預設 private，可逆用 unlisted/public 轉回）")
    ap.add_argument("--winner-keywords", nargs="*", default=DEFAULT_WINNER_KEYWORDS,
                     help="抽查用的贏家片標題關鍵字")
    args = ap.parse_args()
    dry_run = not args.apply

    leak_titles = json.loads((STUDIO / "weekly_winners_state.json").read_text(encoding="utf-8"))["leak_titles"]
    print(f"[info] leak_titles count = {len(leak_titles)}  mode={'DRY-RUN' if dry_run else 'APPLY'}")

    yt = get_service()
    print("[info] 憑證/服務建立成功 (youtube.force-ssl)")

    uploads_pl = get_uploads_playlist_id(yt)
    all_uploads = list_all_uploads(yt, uploads_pl)
    print(f"[info] 頻道 uploads playlist 條目數 = {len(all_uploads)}")

    ledger_path = STUDIO / "uploaded_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    title_map = {}
    for row in all_uploads:
        title_map.setdefault(row["title"], []).append(row["videoId"])

    matched, match_source, unmatched = match_leak_titles(leak_titles, ledger, title_map)
    print(f"[info] 精準匹配 = {len(matched)} / 未匹配 = {len(unmatched)}")

    full_before = get_videos_full(yt, list(matched.values()))

    results = []
    for t, vid in matched.items():
        info = full_before.get(vid)
        if not info:
            results.append({"title": t, "videoId": vid, "action": "skip",
                             "reason": "videos().list 讀不到（可能已刪除）"})
            continue
        prev_privacy = info["privacyStatus"]
        src = match_source.get(t, "?")
        actual_title = info["title"]
        if dry_run:
            results.append({"title": t, "videoId": vid, "actual_youtube_title": actual_title,
                             "match_source": src, "action": f"dry_run_would_set_{args.privacy}",
                             "prev_privacy": prev_privacy})
            print(f"[dry-run] {prev_privacy} -> {args.privacy}: {t} ({vid}) actual='{actual_title}'")
            continue
        status = dict(info["status"])
        status["privacyStatus"] = args.privacy
        status.setdefault("selfDeclaredMadeForKids", False)
        try:
            yt.videos().update(part="status", body={"id": vid, "status": status}).execute()
            results.append({"title": t, "videoId": vid, "actual_youtube_title": actual_title,
                             "match_source": src, "action": f"set_{args.privacy}",
                             "prev_privacy": prev_privacy, "result": "updated"})
            print(f"[ok] {prev_privacy} -> {args.privacy}: {t} ({vid}) actual='{actual_title}'")
        except Exception as exc:  # noqa: BLE001
            results.append({"title": t, "videoId": vid, "match_source": src, "action": "error", "error": str(exc)})
            print(f"[ERR] {t} ({vid}): {exc}")

    for t, reason in unmatched:
        results.append({"title": t, "videoId": None, "action": "skip", "reason": reason})
        print(f"[skip] {t} -- {reason}")

    # ---- 自驗：讀回 privacyStatus ----
    updated_ids = [r["videoId"] for r in results if r.get("result") == "updated"]
    readback = get_videos_full(yt, updated_ids) if updated_ids else {}
    verify = []
    all_confirmed = True
    for r in results:
        if r.get("result") == "updated":
            vid = r["videoId"]
            got = readback.get(vid, {}).get("privacyStatus")
            ok = (got == args.privacy)
            all_confirmed = all_confirmed and ok
            verify.append({"title": r["title"], "videoId": vid, "readback_privacy": got, "confirmed": ok})

    # ---- 抽查贏家片（標題含指定關鍵字），確認高觀看片沒被誤動 ----
    candidate_ids = [row["videoId"] for row in all_uploads
                      if any(k in row["title"] for k in args.winner_keywords)]
    candidate_full = get_videos_full(yt, candidate_ids) if candidate_ids else {}
    winners_sorted = sorted(candidate_full.items(), key=lambda kv: kv[1]["viewCount"], reverse=True)
    leak_video_ids = set(matched.values())
    winner_check = []
    winners_unaffected = True
    for vid, info in winners_sorted[:10]:
        was_leak = vid in leak_video_ids
        winner_check.append({"videoId": vid, "title": info["title"], "viewCount": info["viewCount"],
                              "privacyStatus": info["privacyStatus"], "was_in_leak_list": was_leak})
        if not was_leak and info["viewCount"] > 100 and info["privacyStatus"] != "public":
            winners_unaffected = False

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "apply" if args.apply else "dry_run",
        "target_privacy": args.privacy,
        "leak_titles_total": len(leak_titles),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "results": results,
        "verify_readback": verify,
        "all_confirmed": all_confirmed,
        "winner_spotcheck": winner_check,
        "winners_unaffected": winners_unaffected,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{'apply' if args.apply else 'dryrun'}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] 報告寫到 {out_path}")
    print(f"[summary] matched={len(matched)} unmatched={len(unmatched)} "
          f"all_confirmed={all_confirmed} winners_unaffected={winners_unaffected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
