#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""second_order.py — 二階組合爆炸：在已知有礦的欄位上做全面變化。

## 為什麼（2026-08-27）
一階全欄位掃描（`field_miner.py`）的命中率約 **1%**（939 條出 10 條可提交）。
但看帳本，命中不是均勻分布的 —— **最高分的兩條（Sharpe 2.32 / 2.28）都來自
二階變化**（`N8` 那批：在已知有效的 `est_eps/close` 上換 `signed_power` /
`ts_quantile`），不是來自盲掃新欄位。

結論：**一階負責找礦脈，二階負責把礦挖乾淨。** 兩者要並行，但擴充火力該放二階。

## 這支做什麼
拿已實測有效的 base 訊號，跟五個維度做**完整交叉**：

    base 欄位 (6) × 外層變換 (8) × universe (3) × truncation (2) × 中性化 (2)

其中每個維度的選項都有實測依據，不是憑空列的：
· 外層變換：`ts_quantile`/`signed_power` 是實測最高分那兩條用的；
  `ts_zscore`/`ts_rank` 是 baseline；`days_from_last_change` 是時間維度（正交性高）。
· universe：官方 Quality Factor 明寫 **smaller universes get more score**，
  而 `U|esteps|TOP1000` 實測 Sharpe 1.85、最後一年 1.52（比總分還高）。
· truncation：官方對 weight test 的建議區間是 0.05~0.1。

## 用法
    python second_order.py --plan
    python second_order.py --run 300
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

# ── 已實測有礦的 base（都出過雙門檻達標的 alpha）──
BASES = {
    "esteps":  "est_eps/close",
    "opinc":   "operating_income/equity",
    "fcf":     "free_cash_flow_reported_value/equity",
    "buzz":    "scl12_buzz",
    "sales_eq": "sales/equity",
    "assets_eq": "assets/equity",
}

# ── 系統化生成的比率 base（2026-08-27）──
# 觀察：所有雙門檻達標的 alpha 都是**「獲利項 / 規模項」的比率**
#   est_eps/close（預估盈餘殖利率）、operating_income/equity（股東權益報酬）
# 比率的作用是**把規模除掉** —— 這正是官方點名的 sub-universe 殺手
#   （教材原文警告避免 size 乘數如 rank(-assets)、1-rank(cap)）。
# 而我手挑了 2 個，財報資料集裡光是乾淨可用的組合就有 60 個。
NUMERATORS = ("cashflow_op", "operating_income", "income", "ebit", "ebitda",
              "pretax_income", "income_beforeextra", "retained_earnings",
              "cashflow", "cash")
DENOMINATORS = ("equity", "assets", "sales", "cap", "close", "debt")
for _n in NUMERATORS:
    for _d in DENOMINATORS:
        BASES[f"{_n[:9]}_{_d[:5]}"] = f"{_n}/{_d}"

# 探勘用：新比率先只跑三個已驗證最強的變換 × 單一設定，
# 便宜地找出「哪些比率本身有訊號」，再讓它們進完整交叉。
EXPLORE_TRANSFORMS = ("golden", "spow", "tsquant")

# 外層變換。{X} 會填入已 winsorize+backfill 的欄位。
TRANSFORMS = {
    "golden":  "group_rank(ts_rank({X}, 126), subindustry)",          # Sharpe 2.25 那條
    "spow":    "group_rank(signed_power(ts_zscore({X}, 63), 0.5), subindustry)",  # 2.32
    "tsquant": "group_rank(ts_quantile({X}, 126), subindustry)",       # 2.28
    "zs63":    "ts_zscore({X}, 63)",
    "zs63n":   "-ts_zscore({X}, 63)",
    "gzs":     "group_zscore(ts_rank({X}, 126), subindustry)",
    "dflc":    "group_rank(days_from_last_change({X}), subindustry)",  # 時間維度,正交性高
    "avdiff":  "group_rank(ts_av_diff({X}, 63), subindustry)",
}

UNIVERSES = ("TOP3000", "TOP1000", "TOP500")
TRUNCS = (0.1, 0.05)
NEUTS = ("SUBINDUSTRY", "INDUSTRY")


PROVEN_BASES = ("esteps", "opinc", "fcf", "buzz", "sales_eq", "assets_eq")


def build():
    """回傳候選，**探勘在前、深挖在後**。

    Tier A 探勘：新比率 × 3 個最強變換 × 單一最佳設定（每個比率只花 3 條）
    Tier B 深挖：已知有礦的 base × 全部變換 × 全部設定（完整交叉）

    這樣排的理由：算力先用來回答「哪些比率有訊號」（便宜、資訊量大），
    再把火力集中到有礦的地方。跟一階/二階同一個邏輯，只是往下再切一層。
    """
    best = dict(B.BASE)
    best.update(decay=0, truncation=0.1, nanHandling="ON",
                universe="TOP1000", neutralization="SUBINDUSTRY")

    tierA, tierB = [], []
    for bn, field in BASES.items():
        X = f"winsorize(ts_backfill({field}, 120), std=4)"
        if bn in PROVEN_BASES:
            for tn, tmpl in TRANSFORMS.items():
                expr = tmpl.format(X=X)
                for u in UNIVERSES:
                    for tr in TRUNCS:
                        for nz in NEUTS:
                            s = dict(B.BASE)
                            s.update(decay=0, truncation=tr, nanHandling="ON",
                                     universe=u, neutralization=nz)
                            tierB.append((f"S2|{bn}|{tn}|{u}|t{tr}|{nz[:3]}", expr, s))
        else:
            for tn in EXPLORE_TRANSFORMS:
                tierA.append((f"S2A|{bn}|{tn}", TRANSFORMS[tn].format(X=X), dict(best)))
    return tierA + tierB


def cmd_plan():
    c = build()
    print(f"二階候選總數：{len(c)}")
    print(f"  = {len(BASES)} base × {len(TRANSFORMS)} 變換 × {len(UNIVERSES)} universe "
          f"× {len(TRUNCS)} trunc × {len(NEUTS)} 中性化")
    led = B.load_ledger()
    todo = [x for x in c if B._key(x[1], x[2]) not in led]
    print(f"  其中未跑過：{len(todo)}")
    for l, e, s in todo[:4]:
        print(f"\n[{l}]\n  {e}")


def cmd_run(n):
    led = B.load_ledger()
    todo = [x for x in build() if B._key(x[1], x[2]) not in led][:n]
    if not todo:
        print("二階候選都跑過了。")
        return
    print(f"二階：{len(todo)} 條待跑")
    B.candidates = lambda: todo      # noqa: E731
    B.cmd_run(len(todo))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    if "--plan" in a:
        cmd_plan()
    elif "--run" in a:
        i = a.index("--run")
        cmd_run(int(a[i + 1]) if len(a) > i + 1 else 200)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
