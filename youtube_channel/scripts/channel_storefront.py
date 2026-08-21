#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_storefront.py — 頻道門面:預告片 + 首頁系列櫥窗。

## 解的是「看到就想訂閱」
1. **頻道預告片**(unsubscribedTrailer):非訂閱者進頻道頁會自動播放的那支。
   目前**沒設**。用數據選:EP0 開播預告轉化率 5.8%(全頻道最高,是平均的 ~10 倍),
   它觀看少(86 次)純粹因為沒有版位曝光——預告片正是它該在的位置。
2. **首頁櫥窗**(channelSections):把「這頻道有好幾條可以追的系列」在首頁攤開。
   訪客當下就看懂「訂閱會得到什麼」,而不是一牆沒有結構的影片。

## 版位設計(順序有理由)
  熱門影片(社會證明)→ ETF定投對決(訂閱轉化最強系列)→ 個股體檢·依產業
  (9 條清單一個櫥窗,展示規模)→ 避雷拆穿 → 真相實驗室 → EP實測

## API 事實
- unsubscribedTrailer 在 channels.update 的 brandingSettings.channel(**可 API 設**);
  brandingSettings 是整包覆寫,必須先讀回再改(channel_brand.py 踩過)。
- channelSections:list 1 單位、insert/delete 各 50。全部重建約 500 單位。

用法:
  python scripts/channel_storefront.py --dry-run
  python scripts/channel_storefront.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TRAILER_VID = "Zm5zLEAs30Y"     # EP0 開播預告:訂閱轉化 5.8%,全頻道最高(2026-08-21 Analytics)


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def plan_sections():
    ind = (load(STUDIO / "industry_playlists.json") or {}).get("playlists", {})
    pe = load(STUDIO / "playlist_engine.json") or {}
    ind_ids = [v["id"] for k, v in sorted(ind.items(), key=lambda kv: -kv[1].get("n", 0))]
    secs = [
        {"type": "popularUploads", "title": None, "playlists": None},
        {"type": "singlePlaylist", "title": "ETF 定投對決",
         "playlists": [pe.get("etf_dca", {}).get("playlist_id")]},
        {"type": "multiplePlaylists", "title": "個股體檢・依產業",
         "playlists": ind_ids},
        {"type": "singlePlaylist", "title": "新手避雷・迷思拆穿",
         "playlists": [pe.get("beginner_debunk", {}).get("playlist_id")]},
        {"type": "singlePlaylist", "title": "台股真相實驗室",
         "playlists": [pe.get("truth_lab", {}).get("playlist_id")]},
        {"type": "singlePlaylist", "title": "EP 自動交易實測",
         "playlists": [pe.get("ep_live_test", {}).get("playlist_id")]},
    ]
    return [s for s in secs
            if s["type"] == "popularUploads" or (s["playlists"] and s["playlists"][0])]


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="同預設(明確乾跑)")
    a = ap.parse_args()

    secs = plan_sections()
    print("計畫的首頁櫥窗(由上而下):")
    for i, s in enumerate(secs, 1):
        pls = s["playlists"]
        print(f"  {i}. {s['type']:18s} {s['title'] or '(系統標題)':16s} "
              f"{len(pls) if pls else 0} 條清單")
    print(f"\n預告片:{TRAILER_VID}(EP0,轉化 5.8%)")

    if not a.apply:
        print("\n--dry-run:未連網。")
        return 0

    yt = svc()

    # ── 預告片(讀-改-寫,整包保留) ──
    ch = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    bs = ch["brandingSettings"]
    bs.setdefault("channel", {})["unsubscribedTrailer"] = TRAILER_VID
    yt.channels().update(part="brandingSettings",
                         body={"id": ch["id"], "brandingSettings": bs}).execute()
    got = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    tv = got["brandingSettings"]["channel"].get("unsubscribedTrailer")
    print(f"預告片回讀:{tv} {'✓' if tv == TRAILER_VID else '⚠️ 不符'}")

    # ── 櫥窗:先列出既有 → 刪掉可重建的類型 → 依序建立 ──
    existing = yt.channelSections().list(part="snippet,contentDetails",
                                         mine=True).execute().get("items", [])
    # 🔴 驗證員必修:刪掉的版位無從回復,先整包備份(含 Shorts 架等系統版位設定)
    import time as _t
    bpath = STUDIO / ("channel_sections_backup_" + _t.strftime("%Y%m%d_%H%M%S") + ".json")
    bpath.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"既有櫥窗 {len(existing)} 個(已備份 {bpath.name}),重建中…")
    for it in existing:
        try:
            yt.channelSections().delete(id=it["id"]).execute()
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ 刪除 {it['id']} 失敗:{str(e)[:60]}")
    created = 0
    for pos, s in enumerate(secs):
        body = {"snippet": {"type": s["type"], "position": pos}}
        if s["title"]:
            body["snippet"]["title"] = s["title"]
        if s["playlists"]:
            body["contentDetails"] = {"playlists": [p for p in s["playlists"] if p]}
        try:
            yt.channelSections().insert(
                part="snippet,contentDetails" if s["playlists"] else "snippet",
                body=body).execute()
            created += 1
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ 建立「{s['title'] or s['type']}」失敗:{str(e)[:80]}")
    back = yt.channelSections().list(part="snippet", mine=True).execute().get("items", [])
    print(f"完成:建立 {created} 個櫥窗,API 回讀 {len(back)} 個。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
