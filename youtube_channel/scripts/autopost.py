#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""autopost.py — 【多平台全自動發布】用 Upload-Post 聚合 API 把短片自動發到 TikTok + IG Reels。

Upload-Post API（已查證 2026）：
  POST https://api.upload-post.com/api/upload  (multipart/form-data，直接傳檔，不需公開網址)
  認證：Authorization: Apikey <key>
  參數：user(後台連好的 profile) / platform[]=tiktok&instagram / video=<檔> / title / description
  免費方案：每月 10 支（衝量需升級付費，仍比 Ayrshare 便宜）。

設定（環境變數，setx 設好即可，背景行程記得內聯帶入）：
  UPLOADPOST_API_KEY   你的 Upload-Post API 金鑰
  UPLOADPOST_USER      你在 Upload-Post 後台連好 TikTok/IG 的 profile 名稱
無金鑰時：優雅跳過（印提示、不報錯），等你設好金鑰就會自動發。

發布對象：已成片、尚未自動發過的 Shorts（S_*.mp4）。已發記入 ledger 去重。
用法：python scripts/autopost.py [--max 5] [--platforms tiktok,instagram]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
CFG = ROOT / "channel_config.json"
LEDGER = STUDIO / "autopost_ledger.json"

API_KEY = os.environ.get("UPLOADPOST_API_KEY", "").strip()
USER = os.environ.get("UPLOADPOST_USER", "").strip()
API_URL = "https://api.upload-post.com/api/upload"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

HASHTAGS = "#量化交易 #網格交易 #定投 #被動收入 #加密貨幣 #理財 #Pionex #派網"


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def aff_link():
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
        return (c.get("affiliate", {}) or {}).get("pionex_url",
                "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna")
    except Exception:
        return "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna"


def parse_md(slug):
    md = OUT / f"{slug}.md"
    title, hook = slug, ""
    if md.exists():
        txt = md.read_text(encoding="utf-8")
        m = re.search(r"^#\s*🎬?\s*(.+)$", txt, re.M)
        if m:
            title = m.group(1).strip()
        m2 = re.search(r"\*\*旁白[：:]\*\*\s*(.+)$", txt, re.M)
        if m2:
            hook = m2.group(1).strip()[:60]
    return title, hook


def load_ledger():
    if LEDGER.exists():
        try:
            return set(json.loads(LEDGER.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_ledger(s):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")


def post_one(mp4: Path, title: str, desc: str, platforms) -> bool:
    import requests
    files = {"video": (mp4.name, mp4.open("rb"), "video/mp4")}
    data = [("user", USER), ("title", title[:150]), ("description", desc)]
    for p in platforms:
        data.append(("platform[]", p))
    try:
        r = requests.post(API_URL, headers={"Authorization": f"Apikey {API_KEY}"},
                          data=data, files=files, timeout=300)
        ok = r.status_code < 300
        if not ok:
            print(f"[warn] 發布失敗 {mp4.stem}：HTTP {r.status_code} {r.text[:160]}", file=sys.stderr)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 發布例外 {mp4.stem}：{e}", file=sys.stderr)
        return False
    finally:
        try:
            files["video"][1].close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5, help="本輪最多發幾支（顧及免費額度/quota）")
    ap.add_argument("--platforms", default="tiktok,instagram")
    args = ap.parse_args()
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]

    if not API_KEY or not USER:
        print("[info] 尚未設定 UPLOADPOST_API_KEY / UPLOADPOST_USER —— 跳過自動發布。"
              "（去 upload-post.com 註冊、連好 TikTok/IG、把金鑰與 profile 名稱設成環境變數即可啟用。）")
        return 0

    posted = load_ledger()
    shorts = [p for p in OUT.glob("S_*.mp4") if p.stem not in posted]
    shorts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    shorts = shorts[: args.max]
    if not shorts:
        print("[info] 沒有待自動發布的新短片。")
        return 0

    link = aff_link()
    done = 0
    for p in shorts:
        title, hook = parse_md(p.stem)
        desc = f"{hook}\n📈 工具：Pionex 派網 {link}（邀請碼 08NAcfvcWna）\n⚠️ 投資有風險，非投資建議。\n{HASHTAGS}"
        if post_one(p, title, desc, platforms):
            posted.add(p.stem)
            done += 1
            save_ledger(posted)
    log_ops("多平台自動發布", f"自動發 {done}/{len(shorts)} 支到 {'/'.join(platforms)}")
    print(f"[ok] 多平台自動發布完成：{done}/{len(shorts)} 支 → {'/'.join(platforms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
