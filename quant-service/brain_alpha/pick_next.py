#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick_next.py — 挑今天該交哪幾條：**用實測 self-correlation 排序，不是用分數**。

## 為什麼（2026-08-28）
選片標準演化了三次，每次都是被打臉才改：

1. 「挑 fitness 最高的」
   → 撞牆：`QP7vPrEr` self-corr **0.9653** 被擋。它跟同日已交的只差一個外層變換。
2. 「挑不同 base（比率）的」
   → 還是撞：`operating_income/close` vs 已交的 `operating_income/cap` → **0.9732**。
     換分母沒用，`close` 與 `cap` 本身高度相關。
3. 「挑不同**分子**的」
   → 有效：`cashflow_op/close` → **0.6168** 通過。

但第 3 條仍是**代理指標**。真正決定能不能交的是平台實測的 self-correlation，
而那個只有跑 `/check` 才知道。而且它是**遞減的資源** —— 交越多，後面越難不相關
（08-28 第二條已經 0.6168，門檻 0.7）。

→ 所以：**先花模擬額度跑 check 拿實測值，再挑最低的交。**
   挑錯的成本（提交被擋、浪費當天名額）遠高於多跑幾次 check。

## 官方 Quality Factor（決定當天拿幾分）
    Universe（越小越好）· SelfCorrelation（越低越好）· Fitness（越高越好）· Delay（D1>D0）
且**跨當天所有提交者正規化** —— 所以分數不是固定的，昨天拿滿不代表今天拿滿。

## 用法
    python pick_next.py --check 8      # 對前 8 個候選跑 check,依實測 self-corr 排序
"""
from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402


def numerator(expr: str) -> str:
    m = re.findall(r"ts_backfill\(([^,)]+)", expr)
    return m[0].split("/")[0].strip() if m else "?"


def submitted_ids(s):
    """已提交的 alpha id（status != UNSUBMITTED）。"""
    out = set()
    r = s.get(f"{B.API}/users/self/alphas?limit=100&status=ACTIVE", timeout=40)
    if r.ok and r.text.strip():
        for a in (r.json().get("results") or []):
            out.add(a.get("id"))
    return out


# poll_check / checks_of 已合併進 brain_auto —— 這裡只留別名。
# 🔴 2026-09-05:原本這支、submit_alpha、brain_daily_pick 各有一份 /check 的
#    輪詢與判讀,三份各壞各的(而修好其中兩份的那一版,正是靠沒同步改第三份
#    造成一次 cron 全掛的迴歸)。同一條規則只能有一份實作。
poll_check = B.poll_check


def checks_of(data):
    """`{name: (result, value)}`,拿不到 checks 回 None。薄包裝,判讀在 brain_auto。"""
    ck = B.parse_checks(data)
    if ck is None:
        return None
    return {k: (c.get("result"), c.get("value")) for k, c in ck.items()}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    n = 8
    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        if len(sys.argv) > i + 1:
            n = int(sys.argv[i + 1])

    s = B.auth()
    done = submitted_ids(s)
    led = B.load_ledger()
    cand = [r for r in led.values()
            if r.get("ok") and r.get("result", {}).get("evaluable_pass")
            and r.get("alpha_id") not in done]

    # 每個分子只留最好的一條（同分子必然高度相關，多測沒意義）
    by = defaultdict(list)
    for r in cand:
        by[numerator(r["expr"])].append(r)
    done_nums = {numerator(r["expr"]) for r in led.values() if r.get("alpha_id") in done}
    picks = []
    for num, v in by.items():
        if num in done_nums:            # 分子交過了，同分子的一定撞
            continue
        v.sort(key=lambda r: -(r["result"].get("fitness") or 0))
        picks.append(v[0])
    # 先用「最後一年 sharpe」粗排（官方分數每週依樣本外更新，近年撐得住才會持續加分）
    picks.sort(key=lambda r: -((r.get("year_quality") or {}).get("last_year_sharpe") or -9))
    picks = picks[:n]

    print(f"已交分子 {len(done_nums)} 種 | 未交分子候選 {len(by) - len(done_nums)} 種")
    print(f"對前 {len(picks)} 個跑實測 check（每個約 30~60 秒）\n")
    rows = []
    for r in picks:
        aid = r["alpha_id"]
        d, why = poll_check(s, aid)
        if d is None:
            print(f"  {numerator(r['expr'])[:26]:<28} {aid}  ✗ {why}")
            # 認證死掉的話後面每一條都會同樣死。不 abort 的話這一輪會印出一整排
            # 失敗、最後給一張空的建議表 —— 而「沒有候選」和「沒問到」
            # 在那張表上長得一樣。
            if why.startswith("HTTP 401") or why.startswith("HTTP 403"):
                print("\n✗ 認證失效，中止本輪(不是沒有候選，是沒問到)。請重新取得 token。")
                return 2
            continue
        if why:
            print(f"  {numerator(r['expr'])[:26]:<28} {aid}  ⚠️ {why}")
        ck = checks_of(d)
        if ck is None:
            print(f"  {numerator(r['expr'])[:26]:<28} {aid}  ✗ 回 200 但沒有可判讀的 checks（不是全過）")
            continue
        sc = ck.get("SELF_CORRELATION", ("?", None))
        bad = B.non_pass(ck)      # 唯一規則。原本是 == "FAIL",會放行 PENDING/WARNING
        y = (r.get("year_quality") or {}).get("last_year_sharpe")
        rows.append((sc[1] if sc[1] is not None else 9, numerator(r["expr"]), aid,
                     r["result"].get("sharpe"), r["result"].get("fitness"), y, bad))
        print(f"  {numerator(r['expr'])[:26]:<28} {aid}  self_corr={sc[1]}  {'FAIL:' + ','.join(bad) if bad else 'OK'}")

    # ── 排序邏輯（2026-08-28 修正）──
    # 原本純按 self-corr 由低到高排。但實測 8 條全在 0.42~0.52，**遠低於門檻 0.7**，
    # 彼此只差 0.06 —— 拿 0.06 的差距去換掉 Sharpe 2.03、最後一年 2.90 的候選，不划算。
    # → self-corr 當**篩選條件**（<SAFE 就算安全），不當排序依據；
    #   排序改用官方 Quality Factor 真正在意的東西：fitness、以及近年是否撐得住
    #   （官方分數每週依樣本外表現更新 → 最後一年 sharpe 決定交完之後還會不會漲）。
    SAFE = 0.60
    ok = [x for x in rows if not x[6]]
    safe = [x for x in ok if x[0] < SAFE]
    risky = [x for x in ok if x[0] >= SAFE]

    def quality(x):
        _sc, _num, _aid, sh, fi, ly, _ = x
        return -((fi or 0) * 1.0 + (ly or 0) * 0.5 + (sh or 0) * 0.3)
    safe.sort(key=quality)
    risky.sort(key=lambda x: x[0])

    print(f"\n建議提交順序（self-corr < {SAFE} 視為安全，之後按品質排）")
    print(f"{'分子':<28}{'id':<11}{'selfCorr':>9}{'sh':>6}{'fit':>6}{'最後年':>8}")
    print("-" * 72)
    for sc, num, aid, sh, fi, ly, _ in safe + risky:
        flag = "" if sc < SAFE else "  ⚠️相關偏高"
        print(f"{num[:26]:<28}{aid:<11}{sc:>9.4f}{(sh or 0):>6.2f}{(fi or 0):>6.2f}"
              f"{(ly if ly is not None else 0):>8.2f}{flag}")
    best = safe + risky
    if len(best) >= 2:
        print(f"\n→ 交這兩條：{best[0][2]}（{best[0][1][:22]}）、{best[1][2]}（{best[1][1][:22]}）")
        print("  （一天 2 條吃滿每日 2,000 分上限；必須是**不同分子**否則會撞 self-correlation）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
