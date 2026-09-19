#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hybrid_miner.py — 混合兩個**資料領域**造出真正低相關的 alpha。

## 為什麼（2026-08-29，跑道剩 1 天時建的）
`runway.py` 量出真相：fitness 前 50 的候選裡 **48 條確定撞、0 條安全**。
四千多次模擬其實只做出**一個 alpha**：

    group_rank( <某種排序> (ts_backfill(某個財報比率)) , subindustry)

換了 153 個財報科目，得到 153 個幾乎一樣的東西。
這跟 08-28 那次是同一個病，只是搬高了一層：
當時是「同一個 base 換外層變換」生雙胞胎，我改成「換 base」——
但**外層那個骨架本身才是訊號主體**，換 base 只是換了一點雜訊。

## 實測：什麼能降相關、什麼不能（這是整條線最貴的一組數字）

    換分子（operating_income → cashflow_op）        0.97
    換外層變換（ts_rank → ts_quantile/spow）        0.92
    換分母（/close → /cap）                         0.97
    **混進第二個資料領域（價量 + 財報）**           **0.34**  ← 唯一有效

    對照(CMB 家族，價格反轉 × 財報排名):
      0.5*rank(-ts_delta(close,3)) + 0.5*rank(ts_rank(ts_backfill(operating_income,120),252))
      → 對現有 7 條的最大相關 0.3361

**降相關靠的是換資料來源，不是換數學。**

## 為什麼 CMB 那 4 條彼此還是撞（0.85~0.98）
因為它們的**價格項和分子都一樣**，只有線性配重不同（0.3/0.5/0.7/乘法）。
配重是「換數學」，一樣沒用。
→ 所以這支的變化維度是：**價格側訊號 × 財報側分子**，配重只留兩種。

## 設計
價格側刻意選**機制互不相同**的（不是同一個東西換參數）：
  · 短期反轉 —— 3/10 日，機制是流動性提供
  · 中期動量 —— 60 日，機制與反轉相反
  · 低波動   —— 機制是風險溢酬異常
  · 量價背離 —— 機制是資訊流
財報側直接用 `field_miner` 已驗證有訊號的分子（不用重新探索）。

## 用法
    python hybrid_miner.py --plan
    python hybrid_miner.py --run 300
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

# ── 價格側：機制互不相同的訊號，不是同一個東西換參數 ──
# 每一個的經濟機制都不一樣，所以彼此天生就該低相關；
# 若只是把 ts_delta 的窗口從 3 換成 5，那又是「換數學」，會回到 0.9。
# ⚠️ 正負號一律**兩個方向都跑**，不要照教科書先驗挑一邊（2026-08-29 實測）。
# 第一版我照先驗選了單一方向（反轉取負、動量取正、低波動取負、流動性取負），
# 前 11 條的結果是：
#     rev3   fit  0.57  turnover 60.0%   ← 方向對,週轉率太高
#     rev10  fit  0.58  turnover 34.4%   ← 方向對,週轉率太高
#     mom60  fit -0.64  turnover 13.8%   ← 週轉率漂亮,**方向反了**
#     lowvol fit -0.16  turnover  9.0%   ← 同上
#     pvcorr fit  0.07  turnover 20.0%   ← 同上
#     illiq  fit -0.33  turnover  3.1%   ← 同上
# **四個裡四個反了。** 教科書先驗是在「單獨、無中性化、全市場」的設定下講的，
# 而這裡是 TOP3000 + delay 1 + 產業中性化 + 跟財報混合 —— 條件全不一樣。
# 正負號翻一下是零成本的，用猜的沒有任何道理。
_MECH = {
    "rev3":   "ts_delta(close, 3)",          # 短期反轉／動量
    "rev10":  "ts_delta(close, 10)",         # 兩週
    "mom60":  "ts_delta(close, 60)",         # 中期
    "lowvol": "ts_std_dev(returns, 20)",     # 波動
    "pvcorr": "ts_corr(close, volume, 20)",  # 量價關係
    "illiq":  "ts_mean(volume, 20)",         # 流動性
}
PRICE = {}
for _k, _v in _MECH.items():
    PRICE[f"{_k}+"] = f"rank({_v})"
    PRICE[f"{_k}-"] = f"rank(-{_v})"

# ── 財報側：直接用一階已驗證有訊號的分子 ──
FUND = "rank(ts_rank(ts_backfill({F}, 120), 252))"

# 配重只留兩種：實測 0.3/0.5/0.7 三種線性配重彼此 0.85~0.98，多留是浪費。
# 乘法跟線性的機制不同（乘法要求兩邊同時強），所以留著。
BLEND = {
    "lin": "0.5 * {P} + 0.5 * {Q}",
    "mul": "{P} * {Q}",
}

SETTINGS = dict(B.BASE)
SETTINGS.update(decay=0, truncation=0.1, nanHandling="ON", universe="TOP3000")

# 財報側取幾個分子。取太多會讓價格側的變化被稀釋（同價格項下的不同分子仍有一定相關），
# 取太少則組合數不夠。先取 fitness 前 N 個，跑完看 runway 再決定要不要加。
N_FUND = 25


# 分子的實作只有 `brain_auto.numerator` 一份(2026-09-08 收斂,原本四份)。
# 舊版只認 `ts_backfill(`,認不出的共用一個 `?` 桶 —— 那個桶幾乎只砍平台側。
numerator = B.numerator


def top_numerators(led, n=N_FUND):
    """一階已驗證有訊號的分子，依 fitness 排序。

    只取**原始欄位名**（不帶 /close、/cap）—— 這裡的分母交給 rank 去處理，
    再帶一層比率會讓兩邊的規模處理重複。
    """
    best = {}
    for r in led.values():
        if not (r.get("ok") and (r.get("result") or {}).get("evaluable_pass")):
            continue
        num = numerator(r["expr"])
        if num == "?" or "/" in num:
            continue
        f = r["result"].get("fitness") or 0
        if num not in best or f > best[num]:
            best[num] = f
    return [k for k, _ in sorted(best.items(), key=lambda kv: -kv[1])][:n]


def build(led):
    nums = top_numerators(led)
    todo = []
    # 排序刻意是「價格側外圈、分子內圈」：
    # 先把 6 種價格機制各配上一個分子跑完，才進第二個分子。
    # 這樣最早拿到的結果就是**機制最分散**的一批 —— 跑道只剩 1 天，
    # 要的是趕快拿到彼此獨立的幾條，不是把某個機制窮舉完。
    for f in nums:
        for pk, p in PRICE.items():
            for bk, b in BLEND.items():
                expr = b.format(P=p, Q=FUND.format(F=f))
                st = dict(SETTINGS)
                if B._key(expr, st) in led:
                    continue
                todo.append((f"HY|{pk}|{bk}|{f}", expr, st))
    # 重排成「同一輪各價格機制各一條」。
    # 分組的 key 必須是**價格機制**（要輪流的那個維度），不是分子 ——
    # 一開始寫成照分子分組，跑出來是「illiq 配 25 個分子」，
    # 也就是先把最不重要的維度窮舉完，正好是我想避免的。
    per = {}
    for t in todo:
        pk = t[0].split("|")[1]
        per.setdefault(pk, []).append(t)
    order = []
    i = 0
    while any(v for v in per.values()):
        for pk in PRICE:                      # 照 PRICE 宣告順序輪
            if per.get(pk):
                order.append(per[pk].pop(0))
        i += 1
    return order


def cmd_plan():
    led = B.load_ledger()
    nums = top_numerators(led)
    todo = build(led)
    print(f"價格側 {len(PRICE)} 種機制 × 財報側 {len(nums)} 個分子 × 配重 {len(BLEND)} 種")
    print(f"= 待跑 {len(todo)} 條\n")
    print("價格側（機制互不相同）：")
    for k, v in PRICE.items():
        print(f"  {k:<8} {v}")
    print(f"\n財報側前 10 個分子：")
    for f in nums[:10]:
        print(f"  {f}")
    print(f"\n前 6 條會跑：")
    for lab, expr, _ in todo[:6]:
        print(f"  {lab}")
        print(f"    {expr}")


def cmd_run(n):
    led = B.load_ledger()
    todo = build(led)[:n]
    if not todo:
        print("都跑過了。")
        return
    print(f"混合挖礦：{len(todo)} 條，2 worker 併發")
    print(f"  首條：{todo[0][0]}")
    print(f"        {todo[0][1]}")
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
