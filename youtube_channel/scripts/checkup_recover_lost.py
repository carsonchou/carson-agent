#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_recover_lost.py — 回收「題目被消耗、影片卻沒產出來」的個股體檢。

## 為什麼需要(2026-08-02 實測)
題庫的題目一旦標成 used 就不會再被抽到。但**產片失敗不會把 used 退回**——
只要渲染中途掛掉(逾時 / MemoryError / 稿子壞掉),那一檔就**永久消失**,
沒有任何一層會叫。

實測規模:checkup 已消耗題目 115 個,其中 **51 個**既無成品也未發布,而且
**事實檔全部還在**(抽查 8 檔全中)→ 只要把 used 退回就能重產,不必重算資料。
流失名單是台股最有搜尋量的名字:聯發科2454、國泰金2882、南亞科2408、國巨2327、
華邦電2344、旺宏2337、大立光3008、緯創3231、日月光3711…

而搜尋是本頻道**唯一在成長**的流量來源(近28天 +95%),且搜尋詞裡個股名/代號佔 **64%**。
**51 檔 = 51 個永久流失的搜尋入口。**

## 為什麼是「退回 used」而不是「重新種題」
topic_bank.add_topics 會對既有題目與既有影片標題去重,把同一個題再加一次會被擋掉。
直接把既有題目的 used 清掉最乾淨:不產生重複題、保留原本的 fact_key 與 angle。

## 冪等性
偵測條件是「沒有成品 且 未發布」。片子一旦產出來,條件就不成立,不會被重複重置。
所以這支可以安全地排程重跑。

## 比對方式(踩過的坑)
用**代號 or 公司名**雙重比對。只用代號會誤判:聯電那支的 slug 是
`L_聯電20年報酬1344…`,**不含「2303」**,只比代號會把它算成流失(我第一次就算錯,
把 51 誇大成 53)。

用法:
  python scripts/checkup_recover_lost.py           # 只列出(預設)
  python scripts/checkup_recover_lost.py --apply   # 真的退回 used
  python scripts/checkup_recover_lost.py --apply --max 20
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
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
BANK = STUDIO / "topic_bank.json"
FACTS = STUDIO / "stock_checkup_facts.json"
TW = timezone(timedelta(hours=8))


def _is_used(t) -> bool:
    v = t.get("used", t.get("produced"))
    return str(v).lower() in ("true", "1", "yes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的把 used 退回(預設只列出)")
    ap.add_argument("--max", type=int, default=0, dest="mx",
                    help="本次最多回收幾檔(0=不限)。想小量試就設 5")
    args = ap.parse_args()

    if not BANK.exists():
        print("[fatal] 找不到 topic_bank.json", file=sys.stderr)
        return 2
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    if not isinstance(bank, list):
        print("[fatal] topic_bank 不是 list,格式不符,不處理", file=sys.stderr)
        return 2

    import daily_publish as dp
    led = dp.load_ledger()
    mp4s = [p.stem for p in OUT.glob("*.mp4")]
    facts = {}
    try:
        _f = json.loads(FACTS.read_text(encoding="utf-8"))
        facts = _f.get("by_code") or _f
    except Exception:  # noqa: BLE001
        pass

    lost = []
    for t in bank:
        if not isinstance(t, dict):
            continue
        fk = str(t.get("fact_key", ""))
        if "checkup" not in fk.lower() or not _is_used(t):
            continue
        ti = str(t.get("title", ""))
        codes = re.findall(r"\d{4,6}", fk)
        code = codes[0] if codes else None
        m = re.search(r"個股體檢([^\d:：]{1,6})", ti)
        name = (m.group(1).strip().replace("*", "") if m else "")

        def hit(pool):
            return any((code and code in s) or (len(name) >= 2 and name in s) for s in pool)

        if hit(mp4s) or hit(led):
            continue                      # 已有成品或已發布 → 不是流失
        if code and facts and code not in facts:
            continue                      # 事實不在了 → 退回 used 也產不出來,不碰
        lost.append((t, code, name, ti))

    print("題庫 %d 題;checkup 已消耗但**無成品且未發布**且事實仍在:**%d 檔**"
          % (len(bank), len(lost)))
    if not lost:
        print("→ 沒有可回收的,題庫是乾淨的。")
        return 0

    todo = lost[: args.mx] if args.mx > 0 else lost
    print()
    for _t, code, name, ti in todo[:20]:
        print("   %-6s %-8s %s" % (code or "-", name or "-", ti[:34]))
    if len(todo) > 20:
        print("   ...(共 %d 檔)" % len(todo))

    if not args.apply:
        print()
        print("[dry-run] 未改動。要真的回收:--apply  (建議先 --apply --max 5 小量驗證)")
        return 0

    bak = BANK.with_suffix(".json.bak-recover")
    shutil.copy2(BANK, bak)
    n = 0
    ids = {id(t) for t, _, _, _ in todo}
    for t in bank:
        if id(t) in ids:
            t.pop("used", None)
            t.pop("produced", None)
            t["recovered_at"] = datetime.now(TW).strftime("%Y-%m-%d %H:%M")
            n += 1
    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print("[ok] 已把 %d 檔的 used 退回,產線下批會重新抽到。原檔備份:%s" % (n, bak.name))
    try:
        from ops import log_ops
        log_ops("個股體檢回收", "退回 %d 檔流失題目(題目被消耗但沒產出片;事實仍在)" % n)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
