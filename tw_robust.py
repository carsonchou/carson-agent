# -*- coding: utf-8 -*-
"""
tw_robust.py — 最終參數穩健性驗證（確認不是對全期間過擬合）

三部分：
  1. 時間切分 walk-forward：每標的依日期中點切前半/後半，最終參數在兩段各跑一次，
     看績效是否「兩段都成立」（重點：後半較近期、較少被優化看到，會不會崩）。
  2. 跨標的泛化：把「正2純多組」參數套到其他台股正2 ETF（00675L/00663L/00637L/00650L），
     看 edge 是普遍還是只在 00631L。
  3. 0050 單獨 coordinate-descent：它像權值盤整、需更挑/更緊，fitness=Ret/MaxDD+護欄(≥30筆)，
     看能不能讓 0050 也回到正的 Ret/MaxDD。

輸出 twdata\robust_result.md。成本 tw_real，資料 yfinance period max。
執行：使用指定的 Python 3.9 解譯器。
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

import tw_data
import strategy

OUT_MD = os.path.join(tw_data.DATA_DIR, "robust_result.md")
COST = "tw_real"
CAPITAL = 10000.0

# 最終參數（competition v2 定案）
PARAM_LEVER = dict(erThr=0.26, adxOn=25.0, minVotes=2, trailMidR=2.5,
                   trailTightR=3.5, tp2R=3.5, peakArmK=2.0, chandMult=3.5, baseLen=10)
PARAM_INDEX = dict(erThr=0.30, adxOn=28.0, minVotes=2, trailMidR=2.8,
                   trailTightR=3.0, tp2R=3.5, peakArmK=2.5, chandMult=3.0, baseLen=10)

LEVER_SYMBOLS = ["00631L.TW", "006208.TW"]
INDEX_SYMBOLS = ["^TWII", "00632R.TW"]
OTHER_LEVER = ["00675L.TW", "00663L.TW", "00637L.TW", "00650L.TW"]


def make_params(overrides):
    p = strategy.Params()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def bt(df, overrides, allow_short):
    p = make_params(overrides)
    m, _, _ = strategy.backtest(df, cost_model=COST, initial_capital=CAPITAL,
                                p=p, allow_short=allow_short)
    return m


def mline(m):
    pf = "inf" if not np.isfinite(m["profit_factor"]) else f"{m['profit_factor']:.2f}"
    rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else f"{m['return_over_maxdd']:.2f}"
    return (m["net_profit_pct"], pf, m["n_trades"], m["max_dd_pct"], rdd)


def split_half(df):
    mid = df.index[len(df) // 2]
    return df[df.index < mid], df[df.index >= mid]


# ----------------------------------------------------------------------------
# Part 1: walk-forward 前半/後半
# ----------------------------------------------------------------------------
def part_walkforward(L):
    L.append("## 1. 時間切分 walk-forward（前半 / 後半）\n")
    L.append("重點：**後半段**（較近期、較少被優化看到）有沒有崩。若只有前半好，就是過擬合前期。\n")

    def block(title, symbols, overrides, allow_short):
        L.append(f"### {title}\n")
        L.append("| 標的 | 區段 | 期間 | 淨利% | PF | 交易數 | MaxDD% | Ret/MaxDD |")
        L.append("|---|---|---|---|---|---|---|---|")
        print(f"\n[walk-forward] {title}")
        for sym in symbols:
            df = tw_data.load_ohlcv(sym, period="max", sleep=0.4)
            if df is None or len(df) < 500:
                L.append(f"| {sym} | - | 資料不足 | - | - | - | - | - |")
                continue
            full = bt(df, overrides, allow_short)
            d1, d2 = split_half(df)
            for tag, seg in [("全期", df), ("前半", d1), ("後半", d2)]:
                if len(seg) < 250:
                    L.append(f"| {sym} | {tag} | 太短 | - | - | - | - | - |")
                    continue
                m = bt(seg, overrides, allow_short)
                npct, pf, nt, dd, rdd = mline(m)
                per = f"{seg.index[0].date()}~{seg.index[-1].date()}"
                bold = "**" if tag == "後半" else ""
                L.append(f"| {sym} | {bold}{tag}{bold} | {per} | {npct:.1f} | {pf} | {nt} | {dd:.1f} | {rdd} |")
                print(f"  {sym:<11} {tag} 淨利={npct:6.1f}% PF={pf:>5} 交易={nt:>3} RetDD={rdd}")
        L.append("")

    block("正2純多組（allow_short=False）", LEVER_SYMBOLS, PARAM_LEVER, False)
    block("指數多空組（allow_short=True）", INDEX_SYMBOLS, PARAM_INDEX, True)


# ----------------------------------------------------------------------------
# Part 2: 跨標的泛化（正2參數 → 其他正2 ETF）
# ----------------------------------------------------------------------------
def part_generalize(L):
    L.append("## 2. 跨標的泛化：正2純多參數套到其他正2 ETF\n")
    L.append("看正2上的 edge 是**普遍**還是**只在 00631L**。\n")
    L.append("| 標的 | 名稱 | 全期間 | 淨利% | PF | 交易數 | MaxDD% | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    names = {"00631L.TW": "元大台灣50正2(基準)", "00675L.TW": "富邦臺灣加權正2",
             "00663L.TW": "國泰臺灣加權正2", "00637L.TW": "元大滬深300正2",
             "00650L.TW": "復華香港正2"}
    print("\n[泛化] 正2參數套其他正2 ETF")
    rows = []
    for sym in ["00631L.TW"] + OTHER_LEVER:
        df = tw_data.load_ohlcv(sym, period="max", sleep=0.4)
        if df is None or len(df) < 500:
            L.append(f"| {sym} | {names.get(sym,'')} | 資料不足 | - | - | - | - | - |")
            continue
        m = bt(df, PARAM_LEVER, False)
        npct, pf, nt, dd, rdd = mline(m)
        per = f"{df.index[0].date()}~{df.index[-1].date()}"
        L.append(f"| {sym} | {names.get(sym,'')} | {per} | {npct:.1f} | {pf} | {nt} | {dd:.1f} | {rdd} |")
        rows.append((sym, m))
        print(f"  {sym:<11} 淨利={npct:6.1f}% PF={pf:>5} 交易={nt:>3} RetDD={rdd}")
    L.append("")
    return rows


# ----------------------------------------------------------------------------
# Part 3: 0050 單獨 coordinate-descent
# ----------------------------------------------------------------------------
START_0050 = dict(erThr=0.36, adxOn=25.0, minVotes=2, baseLen=10, chandMult=3.0,
                  trailMidR=2.8, trailTightR=2.5, tp2R=4.5, peakArmK=2.5)
SWEEP_0050 = [
    ("minVotes",    [2, 3]),
    ("erThr",       [0.30, 0.36, 0.42, 0.48]),
    ("adxOn",       [22.0, 25.0, 28.0, 32.0]),
    ("baseLen",     [7, 10, 14, 20]),
    ("chandMult",   [2.5, 3.0, 3.5, 4.0]),
    ("trailMidR",   [2.2, 2.5, 2.8]),
    ("trailTightR", [1.8, 2.2, 2.5]),
    ("tp2R",        [3.0, 4.5, 6.0]),
    ("peakArmK",    [2.0, 2.5, 3.0]),
]
MIN_TRADES_0050 = 30.0


def eval_0050(df, overrides):
    m = bt(df, overrides, False)
    rdd = m["return_over_maxdd"]
    if not np.isfinite(rdd):
        rdd = 5.0 if m["net_profit_pct"] > 0 else -1.0
    score = rdd
    nt = m["n_trades"]
    if nt < MIN_TRADES_0050:
        score -= 5.0 * (1.0 - nt / MIN_TRADES_0050)
    return score, m


def part_0050(L):
    L.append("## 3. 0050 單獨 coordinate-descent（它像權值盤整、需更挑/更緊）\n")
    L.append(f"fitness = Return/MaxDD + 活躍度護欄（交易數 < {MIN_TRADES_0050:.0f} 重罰）。\n")
    print("\n[0050 單獨優化]")
    df = tw_data.load_ohlcv("0050.TW", period="max", sleep=0.4)
    current = dict(START_0050)
    best_score, best_m = eval_0050(df, current)
    print(f"  起點 score={best_score:.3f} 淨利={best_m['net_profit_pct']:.1f}% 交易={best_m['n_trades']}")
    for rnd in range(1, 3):
        for name, values in SWEEP_0050:
            cur = current[name]; bv = cur; bl = best_score; bm = None
            for v in values:
                if v == cur:
                    continue
                trial = dict(current); trial[name] = v
                s, m = eval_0050(df, trial)
                if s > bl + 1e-9:
                    bl = s; bv = v; bm = m
            if bv != cur:
                current[name] = bv; best_score = bl; best_m = bm
    # 對照：套「正2組」參數 vs 0050 自己的最佳 vs START
    L.append("| 參數來源 | 淨利% | PF | 交易數 | MaxDD% | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|")
    for tag, ov in [("START(crypto原生)", START_0050),
                    ("套正2組參數", PARAM_LEVER),
                    ("**0050 自己最佳**", current)]:
        m = bt(df, ov, False)
        npct, pf, nt, dd, rdd = mline(m)
        L.append(f"| {tag} | {npct:.1f} | {pf} | {nt} | {dd:.1f} | {rdd} |")
    L.append("")
    L.append("**0050 自己的最佳參數**：")
    L.append("```")
    L.append(str(current))
    L.append("```\n")
    print(f"  0050 best: {current}")
    print(f"  0050 best metrics: 淨利={best_m['net_profit_pct']:.1f}% PF={best_m['profit_factor']} "
          f"交易={best_m['n_trades']} RetDD={best_m['return_over_maxdd']}")
    return current, best_m


def main():
    print("=" * 80)
    print("最終參數穩健性驗證 tw_robust")
    print("=" * 80)
    t0 = time.time()
    L = []
    L.append("# 最終參數穩健性驗證（過擬合檢查）\n")
    L.append(f"- 成本 `{COST}`；資料 yfinance period max；初始資金 {CAPITAL:.0f}。")
    L.append(f"- 正2純多參數：`{PARAM_LEVER}`（allow_short=False）")
    L.append(f"- 指數多空參數：`{PARAM_INDEX}`（allow_short=True）\n")

    part_walkforward(L)
    gen_rows = part_generalize(L)
    o50_params, o50_m = part_0050(L)

    # 自動結論
    L.append("## 誠實結論（自動彙整）\n")
    # 泛化 edge：除 00631L 外有幾檔 Ret/MaxDD>0 且 PF>1
    others = [m for s, m in gen_rows if s != "00631L.TW"]
    pos_gen = sum(1 for m in others if m["return_over_maxdd"] > 0 and m["profit_factor"] > 1)
    L.append(f"- 跨正2泛化：除 00631L 外 {len(others)} 檔中，有 **{pos_gen}** 檔 Ret/MaxDD>0 且 PF>1。")
    if pos_gen >= max(1, len(others) - 1):
        L.append("  → edge 在正2上**大致普遍**，非 00631L 獨有。")
    elif pos_gen == 0:
        L.append("  → **edge 只在 00631L！其他正2 都失效，正2好表現恐為 00631L 特例。**")
    else:
        L.append("  → edge **部分泛化**（有檔成立有檔失效），謹慎看待。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n" + "=" * 80)
    print(f"報告已存: {OUT_MD}  耗時 {time.time()-t0:.0f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
