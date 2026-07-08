#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""threads_upload.py — 把一支 Shorts 發到 Threads(免費直連 Graph API)。

流程：建立 media container(VIDEO, video_url) → 輪詢 status 到 FINISHED → threads_publish 發布。
跟 ig_reels_upload.py 同一顆公開影片網址，Threads 從公開 URL 抓檔。
需 .env：THREADS_USER_ID、THREADS_TOKEN；缺任一則優雅跳過(不阻塞、不報錯)。

用法：python scripts/threads_upload.py <slug>
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
GRAPH = "https://graph.threads.net/v1.0"
UID = os.environ.get("THREADS_USER_ID", "").strip()
TOKEN = os.environ.get("THREADS_TOKEN", "").strip()
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
    """必要 env(USER_ID/TOKEN)+公開影片庫存 base 都到位才算已設定(給 ig_backfill 判斷是否要跳過整個平台)。"""
    return bool(UID and TOKEN and _video_base())


def publish(slug: str) -> str | None:
    if not (UID and TOKEN):
        print("[skip] 缺 THREADS_USER_ID / THREADS_TOKEN，跳過 Threads 跨發"); return None
    base = _video_base()
    if not base:
        print("[skip] 缺公開影片網址(IG_VIDEO_BASE / tunnel_url.json)，跳過 Threads 跨發"); return None
    mp4 = OUT / f"{slug}.mp4"
    if not mp4.exists():
        print(f"[FATAL] 找不到 {mp4}", file=sys.stderr); return None
    video_url = f"{base}/{quote(slug + '.mp4')}"

    # 1) 建 container
    r = requests.post(f"{GRAPH}/{UID}/threads", data={
        "media_type": "VIDEO", "video_url": video_url,
        "text": _caption(slug), "access_token": TOKEN}, timeout=60)
    d = r.json()
    cid = d.get("id")
    if not cid:
        print(f"[FAIL] 建 container 失敗：{str(d)[:200]}", file=sys.stderr)
        log_ops("Threads發布", f"⚠️ container 失敗：{slug[:30]}")
        return None
    print(f"[info] container={cid}，等 Threads 抓影片+處理…")

    # 2) 輪詢處理狀態(限次數，逾時放棄，非致命)
    for i in range(40):
        time.sleep(8)
        s = requests.get(f"{GRAPH}/{cid}", params={"fields": "status", "access_token": TOKEN}, timeout=30).json()
        st = s.get("status")
        if st == "FINISHED":
            break
        if st == "ERROR":
            print(f"[FAIL] Threads 處理失敗：{s}", file=sys.stderr)
            log_ops("Threads發布", f"⚠️ 處理失敗：{slug[:30]}")
            return None
    else:
        print("[FAIL] 處理逾時", file=sys.stderr); return None

    # 3) 發布
    r2 = requests.post(f"{GRAPH}/{UID}/threads_publish", data={
        "creation_id": cid, "access_token": TOKEN}, timeout=60)
    d2 = r2.json()
    if "id" in d2:
        log_ops("Threads發布", f"已發布：{slug[:30]}")
        print(f"[ok] Threads 已發布！id={d2['id']}")
        return d2["id"]
    print(f"[FAIL] 發布失敗：{str(d2)[:200]}", file=sys.stderr)
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：threads_upload.py <slug>"); raise SystemExit(2)
    if not configured():
        # 缺 key/公開網址＝刻意還沒接通，是正常狀態不是錯誤，exit 0 讓 cron 別誤判失敗
        print("[skip] Threads 尚未設定(缺 token 或公開影片網址)，跳過(非錯誤)")
        raise SystemExit(0)
    raise SystemExit(0 if publish(sys.argv[1]) else 1)
