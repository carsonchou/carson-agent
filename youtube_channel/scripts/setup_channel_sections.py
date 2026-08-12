#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup_channel_sections.py — 頻道首頁排架(channelSections)。

## 為什麼(2026-08-12 成長包裝)
頻道首頁 0 個區塊=陌生訪客看完預告片後只剩無序上傳牆。首頁是「訂閱決策頁」:
排架=告訴訪客「訂了會固定拿到什麼」(連載感=訂閱理由,同 EP0 的轉化邏輯)。

## 版位設計(由上而下)
1. 熱門上傳(popularUploads)——社會證明,最高觀看的片打頭
2. 個股體檢連載——旗艦系列(70+支)
3. 新手避雷·迷思拆穿——受眾最廣
4. 0050/ETF 定期定額實驗——搜尋磁鐵(190+支)
5. 台股真相實驗室——franchise
播放清單 ID 於 2026-08-12 用 playlists().list(mine=True) 線上驗證存在且有片。

## 安全設計
- 預設 dry-run;--apply 才動。冪等:已有同型區塊就跳過不重建。
- 全部是「新增」,可隨時在 Studio 刪除或重排(可逆)。
- 每個 insert 50 units,共 ~250 units。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SECTIONS = [
    {"type": "popularUploads", "title": "", "playlist": None},
    {"type": "singlePlaylist", "title": "個股體檢｜台股個股歷史數據連載", "playlist": "PLUYgyV8FsN5c"},
    {"type": "singlePlaylist", "title": "新手避雷·迷思拆穿", "playlist": "PLRzEVFXw1kT8"},
    {"type": "singlePlaylist", "title": "0050/ETF 定期定額實驗", "playlist": "PLJp7y2jl2p64"},
    {"type": "singlePlaylist", "title": "台股真相實驗室｜真回測連載", "playlist": "PLVsS_a65Tqfw"},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的建立(預設 dry-run)")
    args = ap.parse_args()

    from update_channel import get_service
    yt = get_service()
    cur = yt.channelSections().list(part="snippet,contentDetails", mine=True).execute()
    have = set()
    for it in cur.get("items", []):
        sn, cd = it["snippet"], it.get("contentDetails", {})
        if sn.get("type") == "popularUploads":
            have.add("popularUploads")
        for p in (cd.get("playlists") or []):
            have.add(p)

    made = 0
    for i, s in enumerate(SECTIONS):
        key = s["playlist"] or s["type"]
        if key in have:
            print(f"[skip] 已存在:{s['title'] or s['type']}")
            continue
        body = {"snippet": {"type": s["type"], "position": i}}
        if s["playlist"]:
            body["contentDetails"] = {"playlists": [s["playlist"]]}
        if not args.apply:
            print(f"[dry] 將建立 #{i} {s['type']} {s['title'] or ''}")
            made += 1
            continue
        yt.channelSections().insert(part="snippet,contentDetails", body=body).execute()
        made += 1
        print(f"[ok] 已建立 #{i} {s['title'] or s['type']}")
    print(f"{'建立' if args.apply else '將建立'} {made} 個區塊")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
