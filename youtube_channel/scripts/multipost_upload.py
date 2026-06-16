#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multipost_upload.py — 【跨平台真上傳】把已渲好的 Shorts 經 upload-post.com 自動發到 TikTok/IG 等。

接 multipost_dept 產的 STUDIO/dist_queue.json（slug＋各平台文案）＋ output/ 的 mp4，
呼叫 upload-post.com API 一次分發到多平台。同支不重傳（multipost_seen.json）。

前置（你要做一次）：
  1) 到 upload-post.com 訂閱含 TikTok+IG 的方案，在後台「Manage Profiles」連好你的 TikTok/IG 帳號
  2) 取得 API Key，放雲端環境變數 UPLOAD_POST_API_KEY（run.sh 會 source .env）
  3) 設定 profile 名稱到 design_system.json 的 "upload_post_user"（預設 'carson'）
沒金鑰時本檔優雅跳過、不報錯（排程可先掛著，金鑰一到就生效）。

API：POST https://api.upload-post.com/api/upload，Header Authorization: Apikey KEY，
     multipart: user / platform[] / video(檔) / title。
用法：python scripts/multipost_upload.py [--max 6] [--platforms tiktok,instagram] [--dry]
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
DISTQ = STUDIO / "dist_queue.json"
SEEN = STUDIO / "multipost_seen.json"
DESIGN = STUDIO / "design_system.json"
API = "https://api.upload-post.com/api/upload"
KEY = (os.environ.get("UPLOAD_POST_API_KEY", "") or os.environ.get("UPLOADPOST_API_KEY", "")).strip()

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass


def _profile():
    try:
        return json.loads(DESIGN.read_text(encoding="utf-8")).get("upload_post_user") or "carson"
    except Exception:
        return "carson"


def _load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:
        return d


def _save_seen(s):
    try:
        SEEN.write_text(json.dumps(sorted(s), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _caption(item):
    """組一則跨平台文案：標題＋（dist_queue 內某平台文案/標籤）。"""
    caps = item.get("captions") or {}
    for k in ("tiktok", "reels", "threads", "fb"):
        if caps.get(k):
            return str(caps[k])[:2000]
    return item.get("title", "")[:150]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--platforms", default="tiktok,instagram")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not KEY and not args.dry:
        print("[info] 未設 UPLOAD_POST_API_KEY → 跨平台上傳先跳過。"
              "（到 upload-post.com 訂閱+連 TikTok/IG+把 API Key 放雲端 .env 即生效）")
        return 0

    dq = _load(DISTQ, {})
    items = dq.get("items", [])
    if not items:
        print("[info] dist_queue.json 沒有待分發項目（multipost_dept 尚未跑？）。"); return 0
    seen = set(_load(SEEN, []))
    plats = [p.strip() for p in args.platforms.split(",") if p.strip()]
    user = _profile()

    todo = [it for it in items if it.get("slug") and it["slug"] not in seen
            and (OUT / f"{it['slug']}.mp4").exists()][:args.max]
    if not todo:
        print("[info] 沒有可上傳的新片（都傳過或無 mp4）。"); return 0

    if args.dry:
        print(f"[dry] 會傳 {len(todo)} 支到 {plats}（user={user}）：")
        for it in todo:
            print(f"   - {it['slug'][:30]}｜{_caption(it)[:40]}")
        return 0

    import requests
    ok = 0
    for it in todo:
        slug = it["slug"]
        mp4 = OUT / f"{slug}.mp4"
        data = [("user", user), ("title", _caption(it))] + [("platform[]", p) for p in plats]
        try:
            with open(mp4, "rb") as fh:
                r = requests.post(API, headers={"Authorization": f"Apikey {KEY}"},
                                  data=data, files={"video": (mp4.name, fh, "video/mp4")}, timeout=300)
            if r.status_code in (200, 201) and (r.json().get("success") if r.headers.get("content-type", "").startswith("application/json") else True):
                ok += 1
                seen.add(slug)
                print(f"[ok] 已分發：{slug[:30]} → {plats}")
            else:
                print(f"[err] {slug[:24]}：HTTP {r.status_code} {r.text[:120]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[err] {slug[:24]}：{str(e)[:90]}", file=sys.stderr)
    _save_seen(seen)
    log_ops("跨平台上傳", f"upload-post 分發 {ok}/{len(todo)} 支 → {'/'.join(plats)}")
    print(f"[ok] 跨平台上傳完成：{ok}/{len(todo)} 支 → {plats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
