#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed_checkup_backfill.py — 把「事實已經算好、卻從沒種過題」的個股補種進題庫。

## 為什麼(2026-08-29 產線停擺的真根因)
補產從 08-28 18:11 起連續 7 小時零產出,每一輪都 fail-closed。查下來不是閘門太嚴:

    長片題庫 730 題 → 未用只剩 17 題,其中個股體檢未用 **0**
    (剩 17 題有 14 題掛在同兩個 fact_key,正是每輪被事實層去重擋掉的那 14 題)

抽不到題 → `pull_topic` 回 None → 模型自由生題(**沒有任何事實可依據**)→ 只好灌水
→ 密度閘門正確擋下 → fail-closed。**產線沒壞,是題庫見底了。**

而 `stock_checkup_daily.py` 只做「backlog 隊伍最前面的**下一檔新股票**」——它從不回頭看
已經算過事實的股票。實測落差:

    事實庫涵蓋 522 檔 / 題庫已種過題 207 檔
    → **315 檔有事實、沒種題,共 1890 組事實躺著沒用**

那 315 檔的 FinMind 額度與運算成本**早就付過了**,只差一次 LLM 生題。
315 檔 × 2-4 題 ≈ 900 個長片題,夠產線跑一個多月,而且完全不用再打 FinMind。

## 做法
逐檔呼叫 `stock_checkup_daily.seed_topics_for_code()`(它重用 topics_from_facts 的
prompt 組裝/去重/誠信溯源,題目綁 fact_key、標題數字必須是 claim 裡本來就有的)。
不碰 backlog 的 done 旗標、不重算事實、不打 FinMind。

## 用法
  python scripts/seed_checkup_backfill.py                # 只列出缺題的檔,不動
  python scripts/seed_checkup_backfill.py --apply --max 40
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

FACTS = ROOT / "STUDIO" / "stock_checkup_facts.json"
BANK = ROOT / "STUDIO" / "topic_bank.json"
BACKLOG = ROOT / "STUDIO" / "stock_checkup_backlog.json"


def _seeded_codes():
    """題庫裡已經有 checkup 題的股票代號集合。"""
    import produce_batch as pb

    b = json.loads(BANK.read_text(encoding="utf-8"))
    if isinstance(b, dict):
        b = b.get("topics") or b.get("items") or list(b.values())[0]
    out = set()
    for t in b:
        fk = str(t.get("fact_key", ""))
        if fk.startswith("checkup_"):
            c = pb._checkup_extract_code(fk)
            if c:
                out.add(str(c))
    return out


def _names():
    """代號→名稱(拿 backlog 的名單當來源;缺就留空,seed 端會自己補)。"""
    try:
        bl = json.loads(BACKLOG.read_text(encoding="utf-8"))
        return {str(i.get("code")): str(i.get("name") or "") for i in bl.get("items", [])}
    except Exception:  # noqa: BLE001
        return {}


def pending():
    """回 [(code, name, 事實組數)] —— 有事實但題庫沒題的檔,事實多的排前面。"""
    f = json.loads(FACTS.read_text(encoding="utf-8"))
    by = f.get("by_code", {})
    seeded = _seeded_codes()
    nm = _names()
    rows = []
    for code, v in by.items():
        if str(code) in seeded:
            continue
        n = len(v) if hasattr(v, "__len__") else 1
        rows.append((str(code), nm.get(str(code), ""), n))
    rows.sort(key=lambda r: -r[2])  # 事實多的先種,題目切角比較多
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=40, help="一次補幾檔(每檔 1 次 LLM 呼叫)")
    args = ap.parse_args()

    rows = pending()
    print(f"有事實、題庫沒題的個股:{len(rows)} 檔(共 {sum(r[2] for r in rows)} 組事實)")
    for code, name, n in rows[:15]:
        print(f"  {code} {name[:8]:<9} {n} 組事實")
    if not args.apply:
        print(f"\n[dry-run] 未動。要補種:--apply --max {args.max}")
        return 0

    import stock_checkup_daily as scd

    ok = total = 0
    miss_streak = 0
    for code, name, _n in rows[: args.max]:
        t0 = time.time()
        try:
            k = scd.seed_topics_for_code(code, name=name, dry_run=False)
        except Exception as e:  # noqa: BLE001
            print(f"❌ {code} {name[:8]} 例外:{str(e)[:60]}")
            continue
        if k:
            ok += 1
            total += k
            miss_streak = 0
            print(f"✅ {code} {name[:8]:<9} 種 {k} 題  {time.time() - t0:4.1f}s")
        else:
            # 這裡**不要猜原因**。seed_topics_for_code 回 0 有好幾種可能(LLM 全滅 /
            # 事實不足 / 去重擋掉),它自己已經把真正的原因印在上一行了。
            # 原本這句寫死「事實不足/去重擋掉」,結果實測是 LLM 429 全滅——
            # 訊息把人指向完全錯的方向,而且看起來像正常結果。
            miss_streak += 1
            print(f"—  {code} {name[:8]:<9} 沒種出題(原因見上一行)")
            # 連續多檔種不出來 = 系統性問題(通常是 LLM 全滅),不要再往下燒 40 檔。
            if miss_streak >= 5:
                print(f"\n⛔ 連續 {miss_streak} 檔種不出題 = 系統性失敗,提早收手"
                      f"(已成功 {ok} 檔)。先看上面的錯誤原因,別直接重跑。")
                break

    print(f"\n補種 {ok} 檔、共 {total} 題進題庫。")
    try:
        from ops import log_ops

        log_ops("題庫補種", f"{ok} 檔已有事實的個股補種 {total} 題(不打 FinMind,只花 LLM)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
