#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redo_defective_unpublished.py — 把「已產出但過不了現行閘門」的未發布片退回重做。

## 為什麼(2026-08-24 Carson 指示「把產好還沒發的重作」)
未發布長片 35 支裡,**23 支的稿子過不了現行閘門**:
    期間偷換 15 / 長度不足 7 / 資訊密度(灌水) 1
那 15 支期間偷換是在 **2026-08-22 餵料端修好之前**產的
(three_way 的 claim 原文寫著「同期」這個相對詞,被 LLM 連數字抄走 —— 見 memory
yt-period-swap-integrity)。當時拿真模型 A/B 實測:舊 claim 2/3 中招、新 claim 0/3。
所以**現在重寫就會是乾淨的**,不是把同樣的東西再產一次。

擋著不發只是止血(publish_skip 已擋);Carson 要的是把彈藥重做出來——
每一檔股票都是一個搜尋入口,擋著等於那個入口一直空著。

## 做法
1. 用產線本尊的判定函式重掃未發布長片,挑出過不了閘門的
2. 把該 slug 的所有產物移到 `output/_redo/`(mp4/mp3/voice/md/srt/wordtimes/jpg)
   —— **不刪除**,留著可回溯;移走之後 daily_publish 就撿不到了
3. 個股體檢的題目退回題庫(清掉 used) → 產線下批自然重抽,吃到修好的 claim
   (非體檢題同理,退回 topic_bank)

## 安全
- 預設 dry-run。
- 只動**未發布**的(在 uploaded_ledger 裡的一律不碰,已上線的片不會被影響)。
- 移動不刪除;題庫改動前備份 topic_bank.json.bak-redo。

用法:
  python scripts/redo_defective_unpublished.py            # 只列出
  python scripts/redo_defective_unpublished.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REDO = OUT / "_redo"
BANK = STUDIO / "topic_bank.json"
EXTS = (".mp4", ".mp3", ".voice.txt", ".md", ".srt", ".wordtimes.json",
        ".jpg", ".png", ".parent.txt", ".chapters.txt")


def _defect(slug: str):
    """回缺陷原因或 None。用產線本尊的判定,不另造一套。"""
    import produce_batch as pb
    v = OUT / f"{slug}.voice.txt"
    if not v.exists():
        return None
    t = v.read_text(encoding="utf-8", errors="replace")
    title = ""
    md = OUT / f"{slug}.md"
    if md.exists():
        try:
            first = md.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            title = re.sub(r"^#\s*🎬?\s*", "", first).strip()
        except Exception:  # noqa: BLE001
            pass
    if pb._long_mixed_period(t, title or slug):
        return "期間偷換"
    if "【" in t:
        return "【】prompt欄位洩漏"
    if pb._long_content_padding(t):
        return "資訊密度不足(灌水)"
    if pb._long_underlength(t):
        return "長度不足"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    targets = []
    for p in OUT.glob("L_*.mp4"):
        slug = p.stem
        if slug in led or slug.endswith("_ytcta"):
            continue                       # 已發布 / 衍生檔:不碰
        why = _defect(slug)
        if why:
            targets.append((slug, why))
    targets.sort()
    from collections import Counter
    print(f"未發布長片中過不了現行閘門的:**{len(targets)} 支**")
    for w, c in Counter(w for _, w in targets).most_common():
        print(f"   {w:<20}{c:>3} 支")
    print()
    for slug, why in targets[:12]:
        print(f"   [{why}] {slug[:42]}")
    if len(targets) > 12:
        print(f"   …共 {len(targets)} 支")
    if not targets:
        return 0
    if not args.apply:
        print("\n[dry-run] 未改動。要真的退回重做:--apply")
        return 0

    # 1) 移走產物
    REDO.mkdir(parents=True, exist_ok=True)
    moved = 0
    for slug, _ in targets:
        for ext in EXTS:
            f = OUT / f"{slug}{ext}"
            if f.exists():
                try:
                    shutil.move(str(f), str(REDO / f.name))
                    moved += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[warn] 移不動 {f.name}:{str(exc)[:60]}")
    print(f"\n已移走 {moved} 個檔案到 {REDO.name}/(不刪除,可回溯)")

    # 2) 題目退回題庫
    back = 0
    try:
        bank = json.loads(BANK.read_text(encoding="utf-8"))
        if isinstance(bank, list):
            shutil.copy2(BANK, str(BANK) + ".bak-redo")
            slugs_norm = {re.sub(r"[^0-9A-Za-z一-鿿]", "", s) for s, _ in targets}
            for t in bank:
                if not isinstance(t, dict):
                    continue
                used = str(t.get("used", t.get("produced"))).lower() in ("true", "1", "yes")
                if not used:
                    continue
                ti = re.sub(r"[^0-9A-Za-z一-鿿]", "", str(t.get("title", "")))
                if not ti:
                    continue
                if any(ti[:14] and ti[:14] in s for s in slugs_norm):
                    t.pop("used", None)
                    t.pop("produced", None)
                    t["redo_at"] = "2026-08-24"
                    back += 1
            if back:
                import studio_common as sc
                sc.save_json_atomic(BANK, bank)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 題庫退回失敗({str(exc)[:70]});產物已移走,可靠 checkup_recover_lost 補")
    print(f"題庫退回 {back} 題(其餘體檢題靠週日 checkup_recover_lost 回收)")
    try:
        from ops import log_ops
        log_ops("退回重做", f"{len(targets)} 支未發布缺陷片退回(移走產物+退題 {back})")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
