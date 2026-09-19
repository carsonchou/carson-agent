#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_checkup_thumbs.py — 已發布個股體檢片:用贏家公式重生縮圖。

## 為什麼(2026-08-16)
搜尋是本頻道**唯一在成長**的外部來源(08-11→08-13:331→413→470,+42%),而搜尋詞
Top20 **全部是股票名**(藥華藥 109 觀看/285 分鐘、康舒 92…)——個股體檢片是搜尋磁鐵,
且這些片是常青資產(長尾搜尋持續帶人)。
搜尋結果頁上決定點不點的是**縮圖**。2026-08-13 已把官方 CTR 實證公式(大數字+結果詞,
虧損紅/獲利綠 + 反轉痛點行)寫進 make_thumbnails.derive_cfg,但那只影響之後產的片:
實查 65 支已發布體檢片,**59 支仍是舊縮圖**。

## 安全設計
- `thumbnails.set` 只換圖,**保留 videoId / 觀看數 / 排名 / 留言**(memory yt-video-lifespan-4days
  已確認這是純贏操作,不是重新上傳)。
- 標題取**線上**版本(發布時會掛 EP 號),確保縮圖數字與觀眾看到的標題一致。
- derive_cfg 內建誠信閘 `_numbers_traceable`:縮圖數字必須在標題裡找得到,否則退保底。
- 舊縮圖先備份到 assets/thumbnails/_pre_winner_backup/,可還原。
- 預設 dry-run;每支 50 units,--max 預設 20 控配額。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

THUMBS = ROOT / "assets" / "thumbnails"
BACKUP = THUMBS / "_pre_winner_backup"
DONE = ROOT / "STUDIO" / "winner_thumb_done.json"


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的上傳(預設 dry-run)")
    ap.add_argument("--max", type=int, default=20, help="本輪最多幾支(每支 50 units)")
    ap.add_argument("--only", default="", help="只處理 slug 含此字串者(抽樣用)")
    args = ap.parse_args()

    _load_env()
    import make_thumbnails as mt
    import daily_publish as dp

    led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    cands = [(s, v) for s, v in led.items()
             if s.startswith("L_個股體檢") and v not in done
             and (not args.only or args.only in s)]
    print(f"待更新體檢片:{len(cands)} 支(已完成 {len(done)})")
    if not cands:
        return 0

    yt = dp.get_service()
    n = 0
    for slug, vid in cands:
        if n >= args.max:
            print(f"[quota] 已達本輪上限 {args.max},其餘下次續(冪等)")
            break
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items", [])
            if not items:
                done.add(vid)
                continue
            title = items[0]["snippet"]["title"]
            cfg = mt.derive_cfg(slug, title)          # 內建誠信閘:數字須源自標題
            print(f"  {slug[:34]}\n    標題:{title[:52]}\n    新縮圖:{cfg.get('l1')} / {cfg.get('l2')}")
            if not args.apply:
                n += 1
                continue
            # 備份舊圖後產新圖
            old = THUMBS / f"{slug}.jpg"
            if old.exists():
                BACKUP.mkdir(parents=True, exist_ok=True)
                if not (BACKUP / old.name).exists():
                    shutil.copy2(old, BACKUP / old.name)
            p = mt.make_one(cfg)
            yt.thumbnails().set(videoId=vid, media_body=str(p)).execute()
            done.add(vid)
            n += 1
            print("    ✅ 已上傳")
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {slug[:30]}:{str(exc)[:110]}", file=sys.stderr)
    if args.apply:
        DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
        try:
            from ops import log_ops
            log_ops("縮圖翻新", f"贏家公式重生 {n} 支體檢片縮圖(累計 {len(done)})")
        except Exception:  # noqa: BLE001
            pass
    print(f"{'已更新' if args.apply else '將更新'} {n} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
