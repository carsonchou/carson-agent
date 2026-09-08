#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""news12_weight_fix.py — 改模板解 CONCENTRATED_WEIGHT（delay=1，36 條）。

## 事前預期寫在別的地方
`docs/ops/2026-09-09_news12_template_prereg.md` —— **跑之前**就落檔了，跑完直接對答案。
本檔只負責跑，不做判讀；判讀不可以在看到結果之後才決定判準。

## 這批在測什麼
`news12` 的 VECTOR 欄位在 delay=1 有 23 條 Sharpe 3.4~6.5 / fitness 1.2~7.3，
但**全部、且只**掛在 `CONCENTRATED_WEIGHT` + `LOW_SUB_UNIVERSE_SHARPE`。
官方把 weight test 拆成兩支（`OFFICIAL_RULES.md:31`）：「被賦權的股票太少」與
「單一股票權重過高」。官方三個修法（`rank` / `truncation 0.1` / `ts_backfill`）
**我們全都已經做了還是掛** ⇒ 掛在「股票太少」那支。
而 `group_backfill(x, group, d, std)` 是唯一能**跨股票**補值的工具
（`ts_backfill` 只能拿這支股票自己的歷史填，對「從來沒有新聞的股票」無效）。

## 2×2 設計（基準格已量過，只跑另外三格）
    基準  ts_backfill    + trunc 0.1    ← 已在帳本裡
    A     group_backfill + trunc 0.1    ← 只動運算式
    B     group_backfill + trunc 0.05   ← 兩個都動
    C     ts_backfill    + trunc 0.05   ← 只動設定
C 是用來**分離設定的效果**：若 C 也解掉了，代表我對失敗成因的判斷錯了。

## 刻意不做的事
- **不跑 `v_per_cap`**：`OFFICIAL_RULES.md` sub-universe 官方建議第 1 條逐字
  "Avoid using multipliers related to the size of the company"，而 `/cap` 正是那個。
  代價是放掉目前 fitness 最高的形式（7.31）—— **選過關不選分數。**
- **每組近別名只留一個欄位**：23 條只有 19 個相異 `(sharpe,fitness,turnover)` 指紋。
- 標籤用 `F2|` 前綴：`field_miner.dataset_yield()` 只統計 `F1|`，
  這批是二階變體，不可以污染一階掃描的產出率排序。

## ⚠️ A 有一個承認的混淆
`group_backfill(x, group, d, std=4)` 自帶 std ⇒ 外層 `winsorize(..., std=4)` 被它吸收。
所以 A 同時改了「補值來源」和「winsorize 的位置」。**若 A 有效，不能斷言是補值來源的功勞。**

## 用法
    python -u news12_weight_fix.py            # 跑 36 條
    python -u news12_weight_fix.py --plan     # 只印要跑什麼，不打 API
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

# 每組近別名各留一個（見 prereg 的部分別名表）
FIELDS = [
    "main_opening_trading_volume",            # ≡ opening_session_volume_count（v_raw/v_per_px 全等）
    "all_sessions_volume_weighted_avg_price",  # ≡ aggregate_session_vwap_2（v_per_px/v_per_cap 全等）
    "closing_session_volume_count",
    "premarket_volume_weighted_avg_price",
    "main_post_session_vwap",
    "after_hours_vwap_value",
]

FORMS = {                       # 不含 v_per_cap，理由見上
    "v_raw": "vec_avg({F})",
    "v_per_px": "vec_avg({F})/close",
}

BASE_INNER = "winsorize(ts_backfill({X}, 120), std=4)"
GRP_INNER = "group_backfill({X}, subindustry, 120, std=4)"
OUTER = "group_rank(ts_rank({INNER}, 126), subindustry)"

# (代號, 內層, truncation)
VARIANTS = [
    ("A", GRP_INNER, 0.1),
    ("B", GRP_INNER, 0.05),
    ("C", BASE_INNER, 0.05),
]

SETTINGS = dict(B.BASE)         # delay=1（BASE 預設），不呼叫 use_delay
SETTINGS.update(decay=0, truncation=0.1, nanHandling="ON", universe="TOP3000")


def build():
    todo, skipped = [], 0
    led = B.load_ledger()
    for code, inner, trunc in VARIANTS:
        st = dict(SETTINGS)
        st["truncation"] = trunc
        for fld in FIELDS:
            for form, pat in FORMS.items():
                expr = OUTER.format(INNER=inner.format(X=pat.format(F=fld)))
                if B._key(expr, st) in led:     # 已跑過就不重跑（去重的唯一真相是 _key）
                    skipped += 1
                    continue
                todo.append((f"F2|news12|{fld}|{form}|{code}", expr, dict(st)))
    return todo, skipped


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    todo, skipped = build()
    print(f"delay={SETTINGS['delay']}  待跑 {len(todo)} 條（已在帳本裡跳過 {skipped} 條）")
    for lab, expr, st in todo[:3]:
        print(f"  {lab}  trunc={st['truncation']}")
        print(f"    {expr}")
    if len(todo) > 3:
        print(f"  …另外 {len(todo) - 3} 條")
    if "--plan" in sys.argv:
        return 0
    if not todo:
        print("沒有要跑的。")
        return 0
    if not B.claim_lock():
        raise SystemExit("有別的挖礦程序在跑 —— 不疊上去（併發上限 2 是帳號層級）")
    try:
        B.candidates = lambda: todo          # noqa: E731  一次性覆寫，同 field_miner.cmd_run
        B.cmd_run(len(todo))
    finally:
        B.release_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
