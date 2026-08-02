#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_fundamentals_backfill.py — 回補「斷料期間算出來、基本面全缺」的個股體檢事實。

## 為什麼需要(2026-08-03)
FinMind API 於 2026-07-18 起連不上,直到今天才接上 yfinance 備援(見 fundamentals_yf.py)。
那 16 天裡每天照常算事實、照常種題,只是**五組基本面全部略過**——事實庫裡留下 117 檔
只有價格面 8 組事實的殘缺紀錄。

已經產成影片的補不回來(片已發布)。但**題目已種、影片還沒產**的那些,只要現在把事實
重算一次,之後產出的片就會有完整的營收/EPS/毛利/股利/估值,而且新的概念圖
(_fundamentals / _valuation,見 concept_visuals.py)也才畫得出來——沒有事實那兩張圖
會回 None,該段又會退回跟別段一樣的圖。

實測待補:45 檔,而且都是有搜尋量的名字(國巨2327、華邦電2344、大立光3008、緯創3231、
南亞1303…)。搜尋是本頻道唯一在成長的流量來源。

## 判斷條件
「skipped 有 5 組(=基本面全缺) 且 沒有成品 mp4 且 未發布」。
已產/已發的不碰——重算也改不了已經渲染好的影片,只會白燒時間。

## 冪等性
補成功的檔 skipped 會少於 5 組,下次就不符合條件。可以安全重跑。

用法:
  python scripts/checkup_fundamentals_backfill.py            # 只列出(預設)
  python scripts/checkup_fundamentals_backfill.py --apply    # 真的重算並寫回
  python scripts/checkup_fundamentals_backfill.py --apply --max 5   # 小量先驗
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
FACTS = STUDIO / "stock_checkup_facts.json"
BANK = STUDIO / "topic_bank.json"


def _targets():
    """回傳待補代號清單(缺基本面 且 沒成品 且 未發布)。"""
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    by = facts.get("by_code") or {}
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    mp4 = [p.stem for p in OUT.glob("*.mp4")]
    import daily_publish as dp
    led = dp.load_ledger()

    out, seen = [], set()
    for t in bank:
        if not isinstance(t, dict):
            continue
        fk = str(t.get("fact_key", ""))
        if "checkup" not in fk.lower():
            continue
        m = re.findall(r"\d{4,6}", fk)
        if not m:
            continue
        code = m[0]
        if code in seen:
            continue
        d = by.get(code) or {}
        if len(d.get("skipped") or []) < 5:      # 已經有基本面 → 不缺
            continue
        if any(code in s for s in mp4) or any(code in s for s in led):
            continue                              # 已產/已發 → 重算也救不回那支片
        seen.add(code)
        out.append((code, (d.get("name") or code)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的重算並寫回(預設只列出)")
    ap.add_argument("--max", type=int, default=0, dest="mx", help="本次最多補幾檔(0=不限)")
    args = ap.parse_args()

    todo = _targets()
    print("缺基本面 且 還沒產片:**%d 檔**" % len(todo))
    if not todo:
        print("→ 沒有可回補的。")
        return 0
    if args.mx > 0:
        todo = todo[: args.mx]
    for code, name in todo[:15]:
        print("   %-6s %s" % (code, name))
    if len(todo) > 15:
        print("   ...(本次共 %d 檔)" % len(todo))

    if not args.apply:
        print()
        print("[dry-run] 未改動。要真的回補:--apply  (建議先 --apply --max 3)")
        return 0

    import stock_checkup_facts as CF
    ok = fail = 0
    for i, (code, name) in enumerate(todo, 1):
        t0 = time.time()
        try:
            facts = CF.build_checkup(code)
            if isinstance(facts, tuple):
                facts = facts[0]
            n_fund = sum(1 for k in (facts.get("results") or {})
                         if any(s in k for s in ("revenue_trend", "eps_trend", "gross_margin",
                                                 "dividend_history", "valuation_position")))
            CF.merge_and_write(facts)
            ok += 1
            print("[%d/%d] %-6s %-8s 基本面 %d/5 組  %.0fs"
                  % (i, len(todo), code, name[:8], n_fund, time.time() - t0))
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print("[%d/%d] %-6s ❌ %s: %s" % (i, len(todo), code, type(exc).__name__, str(exc)[:60]),
                  file=sys.stderr)
    print()
    print("完成:成功 %d 檔 / 失敗 %d 檔" % (ok, fail))
    try:
        from ops import log_ops
        log_ops("體檢基本面回補", "重算 %d 檔(FinMind 斷料 16 天的殘缺紀錄),失敗 %d" % (ok, fail))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
