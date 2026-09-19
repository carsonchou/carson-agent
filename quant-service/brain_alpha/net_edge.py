#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""net_edge.py — 用**期望淨報酬**排序 alpha，不是用過閘指標。

## 為什麼要這支（2026-09-03）
這條線既有的判準全部是**過閘判準**：sharpe/fitness/turnover 門檻、self-corr、
八項檢查全過 —— 衡量的都是「會不會被擋下來」。目標是 Challenge 10,000 分時
這是對的，因為分數本身就是過閘（`pick_next.py` 明講依實測 self-correlation 排序）。

但顧問報酬是 performance-based，量的是 OS 的實際 PnL。過閘判準與賺錢判準
在這個帳號上**已經分岔過一次**：`LL7rbXY6` fitness 1.04（只高過門檻 4%）、
turnover 50.42%（其餘 12 條 2.4%~32.6%）、margin 3.9bp（中位數 10.4bp）。
過閘判準看它合格所以送出，賺錢判準看它是最脆的一條。

**本檔只做排序，不做決策，不改任何閘門門檻。**

## 公式（零自由參數，只有成本 c 是外生假設）
平台 `is` 欄位裡三個數字不是獨立的，實測恆等式（13 條全部吻合到 0.8%）：

    margin = returns / (500 * turnover)      # 500 = 2 邊 * 250 交易日

驗證：ret/(2*252*turn) 對 margin 的比值 13 條全落在 1.006~1.009，
即 252/250 = 1.008 —— 平台用 **250** 交易日。

由此：
    年成交量（倍於 book） = 500 * turnover
    毛報酬               = margin * 500 * turnover = returns      （恆等，可自檢）
    淨報酬(c)            = (margin - c) * 500 * turnover
                         = returns * (1 - c / margin)
    損益兩平成本          = margin 本身

`margin` 是每一塊錢**成交量**的毛利，`c` 是每一塊錢成交量的成本，
所以 c > margin 的 alpha 在成本後為負 —— 與 returns 多高無關。

## c 取多少
**不調 c 去湊排名。** 預設 5bp，並同時印 2/5/10bp 三檔敏感度。
排名在這三檔之間若會翻轉，那個翻轉本身就是要回報的東西。

## 用法
    python net_edge.py              # 抓線上 ACTIVE alpha
    python net_edge.py --file active13.json
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TRADING_DAYS = 250          # 由恆等式反推，非猜測
SIDES = 2
VOL_MULT = SIDES * TRADING_DAYS      # 500
COSTS_BP = (2.0, 5.0, 10.0)
DEFAULT_C_BP = 5.0


def load_online() -> list[dict]:
    import brain_auto as B
    s = B.auth()
    r = s.get(f"{B.API}/users/self/alphas?limit=100&status=ACTIVE", timeout=60)
    if not r.ok:
        raise SystemExit(f"問不到 HTTP {r.status_code}")
    return r.json().get("results") or []


def net_return(returns: float, margin: float, c_bp: float) -> float:
    """淨報酬 = returns * (1 - c/margin)。margin 是每元成交量毛利。"""
    return returns * (1.0 - (c_bp * 1e-4) / margin)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    if "--file" in sys.argv:
        rows = json.loads(Path(sys.argv[sys.argv.index("--file") + 1]).read_text(encoding="utf-8"))
    else:
        rows = load_online()

    good, missing = [], []
    for a in rows:
        b = a.get("is") or {}
        rec = {k: b.get(k) for k in ("returns", "turnover", "margin", "fitness", "sharpe", "drawdown")}
        rec["id"] = a.get("id")
        # 缺值不補 0、不丟棄 —— 單獨列出（`docs/ops/failsafe.md`：讀不到本身就是證據）
        if any(rec[k] is None for k in ("returns", "turnover", "margin")) or not rec["turnover"]:
            missing.append(rec)
        else:
            good.append(rec)

    # 恆等式自檢：算不出 returns 就代表我對欄位的理解錯了，直接喊出來
    for r in good:
        implied = r["margin"] * VOL_MULT * r["turnover"]
        r["identity_err"] = abs(implied - r["returns"]) / r["returns"]

    for r in good:
        r["traded"] = VOL_MULT * r["turnover"]
        for c in COSTS_BP:
            r[f"net{c}"] = net_return(r["returns"], r["margin"], c)

    key = f"net{DEFAULT_C_BP}"
    good.sort(key=lambda r: r[key], reverse=True)
    for i, r in enumerate(good, 1):
        r["rank_net"] = i
    by_fit = sorted(good, key=lambda r: r["fitness"] or -9, reverse=True)
    for i, r in enumerate(by_fit, 1):
        r["rank_fit"] = i

    w = max((r["identity_err"] for r in good), default=0)
    print(f"恆等式自檢：margin*{VOL_MULT}*turnover vs returns，最大誤差 {w*100:.2f}%")
    print(f"成本假設 c = {DEFAULT_C_BP}bp（每元成交量）。損益兩平成本 = 該條的 margin。\n")

    hdr = (f"{'#':>2} {'alpha_id':<10} {'fitness':>7} {'turnover':>8} {'margin':>8} "
           f"{'returns':>8} {'成交量/年':>9} {'淨報酬@5bp':>11} {'名次':>4} {'fit名次':>7} {'差':>4}")
    print(hdr); print("-" * len(hdr))
    for r in good:
        d = r["rank_fit"] - r["rank_net"]
        print(f"{r['rank_net']:>2} {r['id']:<10} {r['fitness']:7.2f} {r['turnover']*100:7.2f}% "
              f"{r['margin']*1e4:7.2f}bp {r['returns']*100:7.2f}% {r['traded']:8.1f}x "
              f"{r[key]*100:10.2f}% {r['rank_net']:>4} {r['rank_fit']:>7} {d:+4d}")

    print(f"\n成本敏感度（淨報酬 %）：")
    print(f"{'alpha_id':<10} " + " ".join(f"{'c='+str(c)+'bp':>10}" for c in COSTS_BP) + "   兩平成本")
    for r in good:
        print(f"{r['id']:<10} " + " ".join(f"{r[f'net{c}']*100:9.2f}%" for c in COSTS_BP)
              + f"   {r['margin']*1e4:6.2f}bp")

    if missing:
        print(f"\n缺值 {len(missing)} 條（未補 0、未丟棄）：")
        for r in missing:
            print(f"  {r['id']}  returns={r['returns']} turnover={r['turnover']} margin={r['margin']}")
    else:
        print("\n缺值 0 條")

    # 兩種判準可不可分辨：Spearman（自己算，不引入 scipy）
    n = len(good)
    if n > 2:
        d2 = sum((r["rank_net"] - r["rank_fit"]) ** 2 for r in good)
        rho = 1 - 6 * d2 / (n * (n * n - 1))
        print(f"\n淨報酬名次 vs fitness 名次 Spearman ρ = {rho:.3f}（n={n}）")
        print("  ρ 接近 1 = 在這個樣本上兩種判準不可分辨（負面結果，照實回報）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
