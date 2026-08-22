#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_audio_language.py — 把已發布影片的 defaultAudioLanguage 補成 zh-Hant。

## 為什麼(2026-08-22 盤點)
產線上傳時只設了 `defaultLanguage: zh-Hant`(標題/描述的語言),**從來沒設
`defaultAudioLanguage`(音軌語言)**。沒設 YouTube 就自己猜,實測全頻道 946 支:

    en-US    214 支   ← 旁白明明是中文,被標成英語
    (未設)   595 支   ← 空著,隨時可能被猜錯(實測有 12 支從 zh 被改成 en-US)
    zh       131 支
    zh-Hant    6 支

`defaultAudioLanguage` 決定三件事:自動翻譯字幕的來源語言、自動配音(auto-dubbing)
的資格、以及**語言別的推薦對象**。把一支中文台股影片標成英語,等於請 YouTube
把它推給英語觀眾——對一個受眾 100% 在台灣的頻道,這是純粹的浪費。

## 為什麼要分批
videos.update 是 50 units/支,809 支 = 40,450 units,超過單日配額(18,000,還要
跟發布/追劇鏈/加註共用)。預設 --max 60(約 3,000 units),排每日 cron 慢慢補完。

## 安全
- videos.update 是**全欄覆蓋**,所以 title/description/tags/categoryId/defaultLanguage
  全部原樣回填;缺 categoryId 就跳過該支(不猜分類——猜錯會靜默改變影片分類)。
- 已經是 zh-Hant 的直接跳過(冪等,可以天天跑)。
- 只動 defaultAudioLanguage 一欄的值,描述一個字都不碰(實測驗證過)。

用法:
  python scripts/fix_audio_language.py                # dry-run,只列統計
  python scripts/fix_audio_language.py --apply --max 60
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
TARGET = "zh-Hant"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=60, dest="mx")
    args = ap.parse_args()

    import daily_publish as dp
    yt = dp.get_service()
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    vids = [v for v in led.values() if isinstance(v, str) and len(v) == 11]

    todo, ok = [], 0
    snaps = {}
    for i in range(0, len(vids), 50):
        r = yt.videos().list(part="snippet", id=",".join(vids[i:i + 50])).execute()
        for it in r.get("items", []):
            sn = it["snippet"]
            snaps[it["id"]] = sn
            # zh / zh-TW / zh-Hant 都算「已經標成中文」——不為了統一寫法多燒 6,550 units,
            # 真正要修的是被標成**別的語言**(en-US 等)與空著沒設的。
            if (sn.get("defaultAudioLanguage") or "").lower().startswith("zh"):
                ok += 1
            else:
                todo.append(it["id"])
    # 先修「被猜成別的語言」的(那是**主動錯誤**),再修空著的
    todo.sort(key=lambda v: 0 if (snaps[v].get("defaultAudioLanguage") or "") else 1)
    print(f"已正確 {ok} 支;待修 {len(todo)} 支"
          f"(其中被標成別的語言 {sum(1 for v in todo if snaps[v].get('defaultAudioLanguage'))} 支)")
    if not todo:
        return 0
    if not args.apply:
        print(f"[dry-run] 未改動。要真的補:--apply --max {args.mx}"
              f"(約 {min(args.mx, len(todo)) * 50 + (len(vids) + 49) // 50} units)")
        return 0

    n = err = 0
    for vid in todo[:args.mx]:
        sn = snaps[vid]
        if not sn.get("categoryId"):
            print(f"[skip] {vid} 缺 categoryId,不猜分類")
            continue
        body = {"id": vid, "snippet": {
            "title": sn.get("title"), "description": sn.get("description"),
            "categoryId": sn.get("categoryId"), "tags": sn.get("tags"),
            "defaultLanguage": sn.get("defaultLanguage"),
            "defaultAudioLanguage": TARGET,
        }}
        body["snippet"] = {k: v for k, v in body["snippet"].items() if v is not None}
        try:
            yt.videos().update(part="snippet", body=body).execute()
            n += 1
        except Exception as exc:  # noqa: BLE001
            err += 1
            print(f"[err] {vid} {str(exc)[:100]}")
            if "quota" in str(exc).lower():
                print("配額用盡,停止(冪等,下次接著補)")
                break
    print(f"\n本輪補好 {n} 支、失敗 {err} 支;還剩 {len(todo) - n} 支")
    if n:
        try:
            from ops import log_ops
            log_ops("音軌語言修正", f"補 {n} 支 defaultAudioLanguage=zh-Hant(還剩 {len(todo)-n})")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
