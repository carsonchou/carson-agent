#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_titles.py — 一次性：把指定影片的 YouTube 線上標題換成 CTR 重寫版。

安全做法：videos().update(part=snippet) 會覆蓋整個 snippet，所以先抓現有 snippet、
只改 title、保留 categoryId/description/tags，再送出。比對用「原標題字串」→ 經
dist_queue.json 找 slug → uploaded_ledger.json 找 videoId。找不到的略過並回報。

用法：python scripts/update_titles.py [--dry]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import re
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
LEDGER = STUDIO / "uploaded_ledger.json"
DISTQ = STUDIO / "dist_queue.json"

# 原標題 → CTR 重寫版（copywriting + marketing-psychology，去重＋多樣化，守誠實鐵則）
RENAMES = {
    "幣圈漲 10%，你的網格上限被掃空了——急漲時該重設還是放著？":
        "凌晨幣價暴衝10%，我的網格全踏空——該追設還是按兵不動？",
    "6億爆倉、11萬人被清算，你的網格該停還是跑？一個參數決定生死":
        "6億一夜爆倉、11萬人歸零，我的網格只做對1件事就活下來",
    "比特幣單日暴衝 6.5 萬，你的網格上限設對了嗎？一個參數決定踏空還是清倉":
        "比特幣衝上6.5萬那晚，設錯網格上限的人全踏空了",
    "你的網格機器人在賠錢？其實是『這個陷阱』吃掉你 90% 利潤":
        "網格在賠錢？90%的人栽在這個沒人講的參數陷阱",
    "你的網格機器人在加碼，卻沒算過馬丁格爾死亡螺旋——一個公式看破真相":
        "網格自動加碼聽起來很爽，直到馬丁格爾把本金清零",
    "你的網格回測贏了，為什麼實盤一直虧？樣本外測試一秒戳破過擬合":
        "回測贏麻、實盤狂虧——這就是過擬合在騙你",
    "你的網格間距設太寬，虧爆了還不知道——一張表格看懂參數陷阱":
        "網格間距設太寬＝把利潤送人，一張表看懂甜蜜點",
    "你的網格上下限差 0.5%，實盤虧 40%？一個表格看懂參數陷阱":
        "上下限只差0.5%，實盤虧掉40%——參數差距的真實代價",
    "你的網格上下限設錯了，虧損其實早就寫好了":
        "網格上下限設錯的那一刻，這筆虧損就已經注定了",
    "你的網格回測贏了，實盤卻虧 30%？一個數字暴露過擬合真兇":
        "回測勝率漂亮、實盤虧30%？這個數字一秒拆穿假象",
    "你的網格回測贏了，實盤卻虧？前向測試一秒戳破過擬合":
        "為什麼網格回測無敵、實盤被打爆？前向測試見真章",
    "你的網格回測贏了，實盤虧爆？其實是『這個陷阱』在吃你":
        "實盤一直虧不是你衰，是回測時就被這陷阱埋好了",
    "你的網格勝率 70%，為什麼還在虧？期望值才是真兇手":
        "網格勝率70%還是賠，因為你只看勝率沒看期望值",
    "你的網格間距設太寬，虧 50%？一張表格看懂參數陷阱":
        "網格間距抓錯，50%獲利就蒸發——新手最常踩",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只比對、不真的改")
    ap.add_argument("--source", action="store_true",
                    help="改『未發布』庫存的 .md 來源標題（上架時自動帶新標題）")
    args = ap.parse_args()

    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    dq = json.loads(DISTQ.read_text(encoding="utf-8")) if DISTQ.exists() else {"items": []}
    title2slug = {i["title"]: i["slug"] for i in dq.get("items", [])}

    if args.source:
        # 只處理「尚未發布」的庫存：改 {slug}.md 第一行標題（# 🎬 <title>）
        done = 0
        for old, new in RENAMES.items():
            slug = title2slug.get(old)
            if not slug or slug in ledger:
                continue  # 找不到、或已發布的不在這處理
            md = OUT / f"{slug}.md"
            if not md.exists():
                print(f"[skip] 無 .md：{slug[:24]}…"); continue
            txt = md.read_text(encoding="utf-8")
            new_txt, n = re.subn(r"^#\s*.+$", f"# 🎬 {new}", txt, count=1, flags=re.M)
            if not n:
                print(f"[skip] 找不到標題行：{slug[:24]}…"); continue
            if args.dry:
                print(f"  [dry] {slug[:18]}… → {new}")
            else:
                md.write_text(new_txt, encoding="utf-8")
                done += 1
                print(f"[ok] 來源標題已改：{new}")
        print(f"\n== 來源標題：處理 {done} 支未發布庫存 ==")
        try:
            from ops import log_ops
            log_ops("標題優化", f"CTR 重寫未發布庫存來源標題 {done} 支")
        except Exception:
            pass
        return 0

    # 建 (videoId, new_title) 工作清單
    jobs = []
    for old, new in RENAMES.items():
        slug = title2slug.get(old)
        if not slug:
            print(f"[skip] dist_queue 找不到原標題：{old[:24]}…")
            continue
        vid = ledger.get(slug)
        if not vid:
            print(f"[skip] 尚未發布（ledger 無 videoId）：{slug[:24]}…")
            continue
        jobs.append((vid, slug, new))

    print(f"== 可更新 {len(jobs)} 支 ==")
    if args.dry:
        for vid, slug, new in jobs:
            print(f"  {vid}  →  {new}")
        return 0
    if not jobs:
        print("沒有可更新的影片。")
        return 0

    from daily_publish import get_service
    yt = get_service()
    ok = 0
    for vid, slug, new in jobs:
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items", [])
            if not items:
                print(f"[warn] 抓不到 {vid}（可能已刪）")
                continue
            sn = items[0]["snippet"]
            old_title = sn.get("title", "")
            sn["title"] = new  # 只換標題，其餘保留
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            ok += 1
            print(f"[ok] {vid}\n      舊：{old_title}\n      新：{new}")
        except Exception as e:
            print(f"[err] {vid}：{e}")
    print(f"\n== 完成：成功更新 {ok}/{len(jobs)} 支線上標題 ==")
    try:
        from ops import log_ops
        log_ops("標題優化", f"CTR 重寫線上標題 {ok}/{len(jobs)} 支")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
