#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fb_reels_upload.py — 把一支 Shorts 發到 Facebook Page Reels(免費直連 Graph API)。

流程：video_reels(start) 取 video_id+upload_url → rupload 用 file_url 讓 Meta 抓公開檔
     → video_reels(finish) 標記 PUBLISHED。跟 ig_reels_upload.py 同一顆公開影片網址。
需 .env：FB_PAGE_ID、FB_PAGE_TOKEN；缺任一則優雅跳過(不阻塞、不報錯)。

用法：python scripts/fb_reels_upload.py <slug>
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
GRAPH = "https://graph.facebook.com/v21.0"
PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "").strip()
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass
try:
    from ig_reels_upload import _caption  # 同一份文案邏輯(hook+標題+CTA+hashtag)
except Exception:
    def _caption(slug: str) -> str:
        return slug


def _video_base() -> str:
    """公開影片網址前綴：優先讀 IG_VIDEO_BASE，沒有就退讀 STUDIO/tunnel_url.json 的 base。"""
    base = os.environ.get("IG_VIDEO_BASE", "").strip()
    if base:
        return base.rstrip("/")
    tf = ROOT / "STUDIO" / "tunnel_url.json"
    if tf.exists():
        try:
            return json.loads(tf.read_text(encoding="utf-8")).get("base", "").rstrip("/")
        except Exception:
            return ""
    return ""


def configured() -> bool:
    """必要 env(PAGE_ID/PAGE_TOKEN)+公開影片庫存 base 都到位才算已設定(給 ig_backfill 判斷是否要跳過整個平台)。"""
    return bool(PAGE_ID and PAGE_TOKEN and _video_base())


def publish(slug: str) -> str | None:
    if not (PAGE_ID and PAGE_TOKEN):
        print("[skip] 缺 FB_PAGE_ID / FB_PAGE_TOKEN，跳過 FB 跨發"); return None
    base = _video_base()
    if not base:
        print("[skip] 缺公開影片網址(IG_VIDEO_BASE / tunnel_url.json)，跳過 FB 跨發"); return None
    mp4 = OUT / f"{slug}.mp4"
    if not mp4.exists():
        print(f"[FATAL] 找不到 {mp4}", file=sys.stderr); return None
    video_url = f"{base}/{quote(slug + '.mp4')}"

    # 1) 開場：跟 FB 拿 video_id + upload_url
    r = requests.post(f"{GRAPH}/{PAGE_ID}/video_reels", data={
        "upload_phase": "start", "access_token": PAGE_TOKEN}, timeout=60)
    d = r.json()
    video_id = d.get("video_id")
    if not video_id:
        print(f"[FAIL] video_reels(start) 失敗：{str(d)[:200]}", file=sys.stderr)
        log_ops("FB發布", f"⚠️ start 失敗：{slug[:30]}")
        return None
    print(f"[info] FB video_id={video_id}，用公開網址讓 Meta 抓檔…")

    # 2) 讓 Meta 用 file_url 直接抓公開檔(免自己上傳位元組)
    r2 = requests.post(
        f"https://rupload.facebook.com/video-upload/v21.0/{video_id}",
        headers={"Authorization": f"OAuth {PAGE_TOKEN}", "file_url": video_url},
        timeout=120)
    if r2.status_code != 200 or not r2.json().get("success", True):
        print(f"[FAIL] rupload 失敗：{r2.status_code} {r2.text[:200]}", file=sys.stderr)
        log_ops("FB發布", f"⚠️ rupload 失敗：{slug[:30]}")
        return None

    # 3) 收尾發布
    r3 = requests.post(f"{GRAPH}/{PAGE_ID}/video_reels", data={
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "description": _caption(slug), "access_token": PAGE_TOKEN}, timeout=60)
    d3 = r3.json()
    if d3.get("success"):
        log_ops("FB發布", f"Reels 已發布：{slug[:30]}")
        print(f"[ok] FB Reels 已發布！video_id={video_id}")
        return video_id
    print(f"[FAIL] finish 失敗：{str(d3)[:200]}", file=sys.stderr)
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：fb_reels_upload.py <slug>"); raise SystemExit(2)
    if not configured():
        # 缺 key/公開網址＝刻意還沒接通，是正常狀態不是錯誤，exit 0 讓 cron 別誤判失敗
        print("[skip] FB 尚未設定(缺 token 或公開影片網址)，跳過(非錯誤)")
        raise SystemExit(0)
    raise SystemExit(0 if publish(sys.argv[1]) else 1)
