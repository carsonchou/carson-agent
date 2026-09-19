#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reconcile_ledger.py — 對帳:把「YouTube 頻道實際已上傳的影片」併回本機 uploaded_ledger.json。

背景:改本機跑後,本機 uploaded_ledger 可能比雲端舊(缺雲端後期發的片)。若不對帳,daily_publish
可能把「其實已發布」的片當待辦重發→頻道出現重複。這支用 YouTube API 拉頻道 uploads 播放清單,
以「標題正規化」比對本機 output/*.md 的 slug,把已在頻道上的 slug→videoId 補進 ledger,
讓 daily_publish 的 find_candidates 不再重發。純讀頻道 + 寫本機 ledger,不動任何線上影片。

用法(需 token_manage.json 有效):
  .venv\\Scripts\\python.exe scripts\\reconcile_ledger.py          # 對帳並寫入
  .venv\\Scripts\\python.exe scripts\\reconcile_ledger.py --dry    # 只印會補幾筆,不寫
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from studio_common import save_json_atomic, load_json_safe

# 配額計量(全域 patch HttpRequest.execute,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
LEDGER = STUDIO / "uploaded_ledger.json"
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _norm(t: str) -> str:
    return re.sub(r"[\s，。！？、：；…·\-—()（）｜|#]+", "", (t or "")).lower()


def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.loads(TOKEN.read_text(encoding="utf-8")), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def _channel_videos(yt):
    """回 [(videoId, title)] 頻道所有已上傳影片(uploads 播放清單分頁抓)。"""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    out, tok = [], None
    while True:
        r = yt.playlistItems().list(part="snippet", playlistId=up, maxResults=50, pageToken=tok).execute()
        for it in r.get("items", []):
            s = it["snippet"]
            out.append((s["resourceId"]["videoId"], s["title"]))
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def _local_slugs():
    """本機 output/*.md 的 slug → 標題正規化,用來把頻道影片標題對回 slug。"""
    m = {}
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            title = first.replace("# 🎬", "").replace("#", "").strip()
            if title:
                m[_norm(title)] = f.stem
        except Exception:  # noqa: BLE001
            continue
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    ledger = load_json_safe(LEDGER, default={})
    if not isinstance(ledger, dict):
        ledger = {}
    have_vids = set(ledger.values())
    try:
        yt = _svc()
        vids = _channel_videos(yt)
    except Exception as exc:  # noqa: BLE001
        print(f"[對帳] 連 YouTube 失敗(token?):{str(exc)[:80]}", file=sys.stderr)
        return 1
    slugmap = _local_slugs()
    added = 0
    unmatched = 0
    for vid, title in vids:
        if vid in have_vids:
            continue
        slug = slugmap.get(_norm(title))
        if slug:
            if slug not in ledger:
                ledger[slug] = vid
                added += 1
        else:
            # 頻道有、但本機沒有對應 .md(雲端產的片本機沒有)→ 用穩定假 slug 記進 ledger 佔位,
            # 確保這 videoId 被視為「已發布」,避免任何本機同名片被當新片重發。
            key = f"_ch_{vid}"
            if key not in ledger:
                ledger[key] = vid
            unmatched += 1
    print(f"[對帳] 頻道影片 {len(vids)} 支｜新併入本機 ledger {added} 筆(對到本機slug)｜"
          f"頻道有本機無 {unmatched} 支(以佔位 slug 記為已發布)")
    if not args.dry and (added or unmatched):
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        save_json_atomic(LEDGER, ledger)
        print(f"[對帳] 已寫入 {LEDGER}(共 {len(ledger)} 筆)")
    elif args.dry:
        print("[對帳] --dry:未寫檔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
