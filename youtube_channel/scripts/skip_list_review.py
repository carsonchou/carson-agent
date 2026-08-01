#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skip_list_review.py — 回頭複查 publish_skip 名單:哪些「擋人的理由」已經過期了?

## 為什麼需要這支(2026-08-02 實際踩到)
`publish_skip.json` 是**只進不出**的名單:片子有缺陷就加進去,但**缺陷修好之後
沒有任何機制回頭複查**。實際後果:

  5 支高分片(94/89/86/84/79)被「渲染期把派網機器人假數字燒進畫面」的理由擋著。
  那個理由**在當時是真的**(附 ffmpeg 抽幀鐵證)。但:
    · 造成它的 bug 在 **07-17 09:56**(commit 5466bc2)就修好了
    · 這些檔案在 **07-29 01:31~01:52** 已經重新渲染過
    · 沒有人回頭更新名單 → **白白躺了四天**,其中含中華電、鴻海這種搜尋量最大的權值股
  而搜尋是這個頻道唯一在成長的流量來源(+95%),每支個股體檢都是永久的搜尋入口。

## 判準(刻意保守,只找「一定過期」的)
只挑同時滿足下列三項的:
  ①理由文字提到的是**渲染期/畫面層**的缺陷(渲染期/HUD/畫面/抽幀/假數字/首幀)
  ②該片的 mp4 **修改時間晚於**對應的修正時間(預設 2026-07-17 09:56,可用 --since 改)
  ③尚未發布、mp4 還在
**不自動解鎖**——只列出來給人看。誠信類的擋(捏數、禁用骨架)一律不碰,那些跟渲染無關。

## 用法
  python scripts/skip_list_review.py              # 列出可能過期的
  python scripts/skip_list_review.py --verbose    # 連理由全文一起印
  python scripts/skip_list_review.py --since "2026-07-17 09:56"
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"

# 只認「畫面/渲染層」的缺陷理由。誠信類(捏數/禁語/洗版骨架)不在此列——
# 那些是內容本身的問題,重新渲染並不會讓它變乾淨,不可用本工具的邏輯放行。
RENDER_DEFECT_KW = ("渲染期", "HUD", "畫面", "抽幀", "假數字", "首幀", "亂數樣本外", "賽跑條")
INTEGRITY_KW = ("捏數", "編造", "信口", "禁語", "洗版骨架", "is_banned_skeleton", "無憑據")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-17 09:56",
                    help="修正時間;mp4 晚於此時間才算『已重渲』")
    ap.add_argument("--verbose", action="store_true", help="印出理由全文")
    args = ap.parse_args()
    try:
        fix_at = datetime.datetime.strptime(args.since, "%Y-%m-%d %H:%M")
    except ValueError:
        print("[fatal] --since 格式應為 'YYYY-MM-DD HH:MM'", file=sys.stderr)
        return 2

    p = STUDIO / "publish_skip.json"
    if not p.exists():
        print("[skip] 沒有 publish_skip.json,無事可做。")
        return 0
    d = json.loads(p.read_text(encoding="utf-8"))
    sl = d.get("slugs") or {}
    if not isinstance(sl, dict):
        print("[skip] slugs 不是 dict,格式不符,不處理。")
        return 0

    import daily_publish as dp
    led = dp.load_ledger()
    qmap, qmin = dp.load_quality()

    stale, integrity_skipped = [], 0
    for slug, reason in sl.items():
        r = str(reason)
        if slug in led:
            continue
        f = OUT / f"{slug}.mp4"
        if not f.exists():
            continue
        if any(k in r for k in INTEGRITY_KW):
            integrity_skipped += 1
            continue          # 誠信類不碰:重渲不會讓假數字變真
        if not any(k in r for k in RENDER_DEFECT_KW):
            continue
        mt = datetime.datetime.fromtimestamp(f.stat().st_mtime)
        if mt <= fix_at:
            continue          # 還沒重渲過,理由仍然有效
        stale.append((slug, qmap.get(slug), mt, r))

    print("跳過名單 %d 支;誠信類(不適用本工具)%d 支" % (len(sl), integrity_skipped))
    print("『理由是渲染期缺陷、但檔案已在 %s 之後重渲』:**%d 支**"
          % (fix_at.strftime("%Y-%m-%d %H:%M"), len(stale)))
    if not stale:
        print("→ 沒有過期的擋人理由,名單是乾淨的。")
        return 0

    print()
    pub_ready = 0
    for slug, sc, mt, r in sorted(stale, key=lambda x: -(x[1] or 0)):
        ok = isinstance(sc, (int, float)) and (not qmin or sc >= qmin)
        pub_ready += ok
        print("  %s %3s 分  重渲於 %s  %s"
              % ("★" if ok else " ", sc, mt.strftime("%m-%d %H:%M"), slug[:44]))
        if args.verbose:
            print("      理由:%s" % r[:200])
    print()
    print("其中 %d 支分數已達門檻(%s)——★ 標記者解鎖後即可發布。" % (pub_ready, qmin))
    print()
    print("⚠️ 本工具**不自動解鎖**。放行前請自己驗,不要只信這裡的判斷:")
    print("   ①確認現行碼不會再產生同一個缺陷(例如 make_video._hud_applies 對該片回 False)")
    print("   ②用 ffmpeg 抽出**理由指控的那個時間點**的幀,親眼看缺陷真的不見了")
    print("   ③原始缺陷片先另存備份(保留證據),再從 publish_skip.json 的 slugs 移除")
    try:
        from ops import log_ops
        log_ops("跳過名單複查", "發現 %d 支擋人理由可能已過期(%d 支已達門檻)" % (len(stale), pub_ready))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
