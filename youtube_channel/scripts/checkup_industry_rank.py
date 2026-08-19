#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_industry_rank.py — 從已算好的體檢資料,推出「同產業相對位置」事實。

## 為什麼(2026-08-19)
現在每支個股體檢給的是 13 組**孤立**的數字:總報酬 270%、回撤 -78%、套牢 4.6 年…
觀眾看完不知道「這樣到底算好還算壞」。真觀眾的留言正是打在這一點上:
    「20年才1145%也叫爆賺喔==」
    「0050 相同期間的含息報酬率差不多…結果還不用承受單一個股風險」
vs 0050 的對照已經加進標題規則,但那是跟大盤比;**跟同產業的同儕比**是另一個維度,
而且是我們獨有的——沒有別的頻道手上有 377 檔用同一份體檢表算出來的資料。

## 三個附帶好處
1. **零成本**:全部從 STUDIO/stock_checkup_facts.json 現有欄位算,不打任何 API。
2. **反模板化**:每檔在產業裡的位置都不同,敘事自然分岔
   (memory yt-inauthentic-template-risk-2026-08:「1925檔×13事實模板」正中政策定義,
   緩解方向是「讓每檔最異常的數據決定敘事主軸」——排名正好指出哪裡異常)。
3. **越做越值錢**:體檢檔數越多,排名越有意義,是會複利的資產。

## 誠實設計
· 樣本不足不算:同產業已體檢 <8 檔就跳過(排名沒有意義)。
· claim 裡**寫明母體**(「在已體檢的 N 檔電子工業股中」),不寫成「全台股第幾名」
  ——我們只體檢了 377/1925 檔,講成全市場排名就是灌水。
· 排名是**當下快照**,claim 內含「截至 YYYY-MM-DD、N 檔」;之後重跑會覆蓋更新。
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

FACTS = ROOT / "STUDIO" / "stock_checkup_facts.json"
MIN_PEERS = 8


def _pct(claim: str, pat: str):
    m = re.search(pat, claim or "")
    return float(m.group(1)) if m else None


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="寫回事實庫(預設只印)")
    args = ap.parse_args()

    d = json.loads(FACTS.read_text(encoding="utf-8"))
    res, by_code = d["results"], d.get("by_code", {})

    # 收集每檔的 (總報酬, 年化, 最大回撤) —— 全部從 long_horizon 那組 claim 解析
    stats = {}
    for code, meta in by_code.items():
        c = (res.get(f"checkup_long_horizon__{code}") or {}).get("claim", "")
        tr = _pct(c, r"總報酬\s*([-\d.]+)\s*%")
        cagr = _pct(c, r"年化\s*([-\d.]+)\s*%")
        mdd = _pct(c, r"最大回撤\s*-?([\d.]+)\s*%")
        ind = ((meta.get("profile") or {}).get("industry") or "").strip()
        if tr is None or not ind:
            continue
        stats[code] = {"name": meta.get("name") or code, "ind": ind,
                       "tr": tr, "cagr": cagr, "mdd": mdd}

    groups = defaultdict(list)
    for code, s in stats.items():
        groups[s["ind"]].append(code)

    as_of = d.get("as_of") or ""
    added = 0
    print(f"已體檢 {len(stats)} 檔可用;產業分組:")
    for ind, codes in sorted(groups.items(), key=lambda x: -len(x[1])):
        mark = "✅" if len(codes) >= MIN_PEERS else "⏭ 樣本不足"
        print(f"  {ind:<12} {len(codes):3d} 檔  {mark}")
        if len(codes) < MIN_PEERS:
            continue
        n = len(codes)
        by_tr = sorted(codes, key=lambda c: -(stats[c]["tr"]))
        by_mdd = sorted(codes, key=lambda c: (stats[c]["mdd"] if stats[c]["mdd"] is not None else 1e9))
        for code in codes:
            s = stats[code]
            r_tr = by_tr.index(code) + 1
            r_mdd = by_mdd.index(code) + 1 if s["mdd"] is not None else None
            pctile = 100.0 * r_tr / n
            claim = (f"在已體檢的 {n} 檔「{ind}」股票中（截至 {as_of}，"
                     f"全市場已體檢 {len(stats)} 檔），{s['name']}（{code}）的長期總報酬 "
                     f"{s['tr']:.1f}% 排第 {r_tr} 名（前 {pctile:.0f}%）")
            if r_mdd:
                claim += (f"；最大回撤 -{s['mdd']:.1f}% 在同組裡是第 {r_mdd} 淺"
                          f"（1 = 跌得最少）")
            claim += "。母體是本頻道已體檢的個股，不是全台股。"
            key = f"checkup_industry_rank__{code}"
            res[key] = {
                "key": key, "claim": claim,
                "desc": f"{s['name']} 在同產業已體檢個股中的相對位置",
                "summary": claim,
                "keywords": [code, s["name"], ind, "同業比較", "相對位置"],
                "method": ("拿本頻道已體檢個股的 long_horizon 事實(同一份體檢表、"
                           "同一套含息還原口徑)按產業分組後排序;母體=已體檢者,非全市場"),
                "symbol": f"{s['name']}（{code}）",
                "period": as_of,
                "source": "本頻道 stock_checkup_facts.json 既有資料再計算(不打任何外部 API)",
            }
            added += 1

    print(f"\n{'已寫入' if args.apply else '將寫入'} {added} 組同業排名事實")
    if added:
        ex = res[[k for k in res if k.startswith("checkup_industry_rank__")][0]]
        print(f"\n範例:{ex['claim']}")
    if args.apply and added:
        from studio_common import save_json_atomic
        save_json_atomic(FACTS, d)
        print(f"\n事實庫已更新:{FACTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
