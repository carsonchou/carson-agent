#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redo_published_defective.py — 把「已發布但旁白有缺陷」的片排進產線重做。

## 為什麼(2026-08-25)
六道閘門上線後回頭掃已發布長片,抓到旁白裡有**產製指令被 TTS 唸出來**:
  · 「所有數字一律用中文口語念法(百分之八十二點三…不要寫成 82.3% 或 24.8%)」 = prompt 原文
  · 「鏡頭切到聯詠還原月線圖上那道深不見底的懸崖式暴跌,量化阿森直接甩出關鍵資料」 = 分鏡指示
旁白被寫成了劇本格式,TTS 把台詞和分鏡指示連在一起唸。

處置要看**觀眾實際聽不聽得到**,不是看缺陷長短:
| 影片 | 近28天觀看 | 洩漏位置 | 平均觀看 | 聽得到? |
|---|---|---|---|---|
| 聯詠3034 | 586 | **第 11 秒** | 69s | 幾乎全部 |
| 凱美2375 | 88 | 439~505s | 85s | **沒有人** → 不重做 |
| 台玻1802 | 24 | 20~90s | 65s | 4 段中 3 段 |
| 竑騰7751 | 7 | 多在 413s 後 | 206s | 14 段中 1 段 |
| 立隆電2472 / 昇陽8028 | 0 | — | — | — |

## 順序(重要)
**先產替代片、確認渲好,再決定舊的要不要下架。** 反過來做就是拿確定的東西換不確定的:
替代片萬一產不出來,舊片至少還在。本腳本**只做前半**(排進產線),
下架是對外動作,要 Carson 另外拍板。

## 兩個坑
1. `_fact_dedup` 的窗口是 90 天,而這些片都是近兩個月發的 → 同 fact_key 會被**永久擋住**。
   不偽造 `used_at`(那是竄改紀錄),改在新題上帶 `redo_of` 旗標讓去重放行 ——
   「重做已發布缺陷片」正是刻意要重用同一組事實的情境。
2. 新片的 slug 由標題推導。萬一跟舊片**完全相同**,`daily_publish` 會因為 slug 已在
   ledger 而判定「已發布」直接跳過。產完要驗一次(本腳本 --check 會列出來)。

用法:
  python scripts/redo_published_defective.py            # dry-run,列出會排哪些
  python scripts/redo_published_defective.py --apply
  python scripts/redo_published_defective.py --check    # 產完之後驗新舊 slug 有沒有撞號
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
BANK = STUDIO / "topic_bank.json"
LEDGER = STUDIO / "uploaded_ledger.json"
STATE = STUDIO / "redo_published.json"

# 要重做的:(股名, 代號, 舊 videoId, 重做理由)。凱美2375 刻意不列 —— 洩漏全在沒人
# 看得到的位置(439s 之後,而平均只看 85 秒),重做的代價換不到任何觀眾體驗。
TARGETS = [
    ("聯詠", "3034", "Oy7dux0cBHs", "分鏡指示在第 11 秒,幾乎每個觀眾都聽得到"),
    ("台玻", "1802", "o_W_gtKNY9U", "分鏡指示在 20~90 秒,4 段中 3 段聽得到"),
    ("竑騰", "7751", "O6gzpYZNzjU", "prompt 指令原文,累計唸出 158.5 秒"),
    ("立隆電", "2472", "o_O4N2nsoac", "prompt 指令原文,唸出 32.8 秒"),
    ("昇陽半導體", "8028", "e9Wn7n6MvgY", "prompt 指令原文,唸出 8.6 秒"),
]


def _bank():
    return json.loads(BANK.read_text(encoding="utf-8"))


def _items(d):
    return d if isinstance(d, list) else d.get("items") or d.get("topics") or []


def _check():
    """產完之後驗:新片的 slug 有沒有跟舊片撞號(撞了就永遠發不出去)。"""
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    out = ROOT / "output"
    for name, code, vid, _ in TARGETS:
        old = next((s for s, v in led.items() if v == vid), None)
        new = [p.stem for p in out.glob(f"L_*{name}{code}*.mp4") if p.stem != old]
        print(f"  {name}{code}: 舊 {str(old)[:40]}")
        print(f"      新 {new if new else '(尚未產出)'}")
        if old and old in new:
            print("      🔴 撞號:新片會被當成已發布而跳過")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        return _check()

    d = _bank()
    items = _items(d)
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    existing = {str(t.get("redo_of") or "") for t in items if isinstance(t, dict)}

    add = []
    for name, code, vid, why in TARGETS:
        if vid in existing:
            print(f"[skip] {name}{code} 已排過(冪等)")
            continue
        old_slug = next((s for s, v in led.items() if v == vid), "")
        add.append({
            "id": "t" + uuid.uuid4().hex[:8],
            "title": f"個股體檢{name}{code}:重做版",   # 真標題由產線 LLM 自己寫,這只是佔位
            "angle": f"{name}({code})個股體檢——重做已發布版本({why})",
            "category": "個股體檢",
            "format": "long",
            "used": False,
            "bucket": "tw_stock",
            "source": "redo_published_defective",
            "fact_key": f"checkup_long_horizon__{code}",
            "redo_of": vid,                 # ← _fact_dedup 看到這個就放行
            "redo_reason": why,
            "redo_old_slug": old_slug,
            "keywords": [code, name, "個股體檢", "含息還原", "最大回撤"],
        })
        print(f"[排入] {name}{code}  ({why})")
        print(f"        舊片 youtu.be/{vid}  {old_slug[:44]}")

    if not add:
        print("\n沒有新的要排(冪等)。")
        return 0
    if not args.apply:
        print(f"\n[dry-run] 會排入 {len(add)} 題。要真的排:--apply")
        return 0

    items.extend(add)
    if isinstance(d, list):
        d = items
    else:
        (d.__setitem__("items", items) if "items" in d else d.__setitem__("topics", items))
    try:
        import studio_common as sc
        sc.save_json_atomic(BANK, d)
    except Exception:  # noqa: BLE001
        BANK.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    for t in add:
        st[t["redo_of"]] = {"queued_at": time.strftime("%F %T"), "reason": t["redo_reason"],
                            "old_slug": t["redo_old_slug"], "status": "queued"}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已排入 {len(add)} 題;舊片**維持發布中**,等替代片產好再由 Carson 拍板下架。")
    try:
        from ops import log_ops
        log_ops("重做已發布", f"{len(add)} 支已發布缺陷片排進產線(舊片未動)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
