# -*- coding: utf-8 -*-
"""
tw_optimize.py — 在台股 universe 上重新優化策略參數（含 train/test 防過擬合）

現行預設參數是加密貨幣調出來的，對台股（多盤整）不一定好。本腳本：
  1. 用快取資料（twdata\cache\），只取 ≥5 年的股票。
  2. 決定性切分 train/test：股票代碼末位數 偶數→train、奇數→test（固定可重現）。
     為速度，train/test 各用固定 seed 隨機抽 ~150 檔。
  3. Fitness（train 上）：score = 獲利檔比例(PF>1且淨利>0) + 0.1*(平均PF-1)
     成本模型 tw_real（真實台股手續費+證交稅）。
  4. Coordinate descent 掃參數（非全網格，控制回測量）：
       erThr 0.30/0.36/0.42/0.48
       adxOn 22/25/28/32
       minVotes 2/3
       baseLen 7/10/14/20
       chandMult 2.5/3.0/3.5
  5. 找到最佳後在 test（OOS）驗證，並與「原始預設」對照。
  6. 輸出 twdata\optimize_result.md。

執行：
  使用指定的 Python 3.9 解譯器執行本檔（tw_optimize.py）。
可選：--n-train 150 --n-test 150 --rounds 2 --seed 42
"""
import argparse
import copy
import glob
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

import tw_data
import strategy

DATA_DIR = tw_data.DATA_DIR
CACHE_DIR = tw_data.CACHE_DIR
OUT_MD = os.path.join(DATA_DIR, "optimize_result.md")

MIN_YEARS = 5
MIN_BARS = 1000
COST = "tw_real"
CAPITAL = 10000.0

# 要掃的參數（coordinate descent；每個參數獨立掃值，取 train 最佳）
SWEEP = [
    ("erThr",     [0.30, 0.36, 0.42, 0.48]),
    ("adxOn",     [22.0, 25.0, 28.0, 32.0]),
    ("minVotes",  [2, 3]),
    ("baseLen",   [7, 10, 14, 20]),
    ("chandMult", [2.5, 3.0, 3.5]),
]


# ----------------------------------------------------------------------------
# 資料載入與切分
# ----------------------------------------------------------------------------
def _ticker_from_cache(path):
    base = os.path.basename(path)
    name = base.rsplit(".", 1)[0]          # 1101_TW
    return name.replace("_", ".")          # 1101.TW


def _code_from_ticker(ticker):
    return ticker.split(".")[0]


def load_eligible():
    """回傳 [(code, ticker, df), ...]，只含 ≥5 年、≥1000 根的股票。"""
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "*.csv")))
    out = []
    for f in files:
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < MIN_BARS:
            continue
        if (df.index[-1] - df.index[0]).days / 365.25 < MIN_YEARS:
            continue
        # 確保欄位齊全
        need = {"Open", "High", "Low", "Close"}
        if not need.issubset(set(df.columns)):
            continue
        ticker = _ticker_from_cache(f)
        out.append((_code_from_ticker(ticker), ticker, df))
    return out


def split_train_test(eligible, n_train, n_test, seed):
    """末位數 偶數→train、奇數→test；各隨機抽 N 檔（固定 seed）。"""
    train_pool, test_pool = [], []
    for code, ticker, df in eligible:
        try:
            last = int(code[-1])
        except ValueError:
            continue
        if last % 2 == 0:
            train_pool.append((code, ticker, df))
        else:
            test_pool.append((code, ticker, df))
    rng = np.random.RandomState(seed)

    def sample(pool, n):
        if len(pool) <= n:
            return pool
        idx = rng.choice(len(pool), size=n, replace=False)
        idx.sort()
        return [pool[i] for i in idx]

    return sample(train_pool, n_train), sample(test_pool, n_test), len(train_pool), len(test_pool)


# ----------------------------------------------------------------------------
# 參數套用 / 評估
# ----------------------------------------------------------------------------
def make_params(overrides: dict) -> strategy.Params:
    p = strategy.Params()                  # 新實例（class 屬性，實例覆寫不影響預設）
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def evaluate(sample, overrides: dict):
    """在 sample（list of (code,ticker,df)）上以 overrides 參數回測，聚合分數。

    回傳 dict: score, prof_ratio, mean_pf, med_retdd, n。
    """
    p = make_params(overrides)
    prof = 0
    pfs = []
    retdds = []
    n = 0
    for code, ticker, df in sample:
        try:
            m, _, _ = strategy.backtest_long_only(
                df, cost_model=COST, initial_capital=CAPITAL, p=p)
        except Exception:
            continue
        n += 1
        pf = m["profit_factor"]
        # PF=inf（全勝無虧）視為大值，clip 避免拉爆平均
        pf_c = pf if np.isfinite(pf) else 5.0
        pfs.append(min(pf_c, 5.0))
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
        rdd = m["return_over_maxdd"]
        if np.isfinite(rdd):
            retdds.append(rdd)
    if n == 0:
        return dict(score=-1, prof_ratio=0.0, mean_pf=0.0, med_retdd=0.0, n=0)
    prof_ratio = prof / n
    mean_pf = float(np.mean(pfs)) if pfs else 0.0
    med_retdd = float(np.median(retdds)) if retdds else 0.0
    score = prof_ratio + 0.1 * (mean_pf - 1.0)
    return dict(score=score, prof_ratio=prof_ratio, mean_pf=mean_pf,
                med_retdd=med_retdd, n=n)


# ----------------------------------------------------------------------------
# Coordinate descent
# ----------------------------------------------------------------------------
def coordinate_descent(train, rounds):
    """從現有預設出發，一次調一個參數取 train 最佳，跑 rounds 輪。"""
    # 預設值（從 Params 取）
    base = strategy.Params()
    current = {name: getattr(base, name) for name, _ in SWEEP}
    trajectory = []

    # 起點分數
    start = evaluate(train, current)
    print(f"[起點] 預設參數 {current}")
    print(f"        score={start['score']:.4f} 獲利比={start['prof_ratio']:.3f} "
          f"meanPF={start['mean_pf']:.3f} medRetDD={start['med_retdd']:.3f}")
    trajectory.append(dict(step="起點(預設)", param="-", value="-", **start, params=dict(current)))

    best_score = start["score"]
    n_bt = start["n"]  # 累計回測檔次計數（粗略）

    for rnd in range(1, rounds + 1):
        print(f"\n===== Coordinate Descent 第 {rnd} 輪 =====")
        for name, values in SWEEP:
            cur_val = current[name]
            best_val = cur_val
            best_local = best_score
            best_metrics = None
            for v in values:
                if v == cur_val:
                    # 已是當前值，沿用 best_score（避免重複跑；但首次需有 metrics）
                    continue
                trial = dict(current)
                trial[name] = v
                t0 = time.time()
                r = evaluate(train, trial)
                dt = time.time() - t0
                flag = ""
                if r["score"] > best_local + 1e-9:
                    best_local = r["score"]
                    best_val = v
                    best_metrics = r
                    flag = "  <== 更佳"
                print(f"  {name}={v:<6} score={r['score']:.4f} "
                      f"獲利比={r['prof_ratio']:.3f} meanPF={r['mean_pf']:.3f} "
                      f"medRetDD={r['med_retdd']:.3f} ({dt:.0f}s){flag}")
            if best_val != cur_val:
                current[name] = best_val
                best_score = best_local
                trajectory.append(dict(step=f"R{rnd}", param=name,
                                       value=best_val, **best_metrics,
                                       params=dict(current)))
                print(f"  -> {name} 採用 {best_val}（score {best_score:.4f}）")
            else:
                trajectory.append(dict(step=f"R{rnd}", param=name,
                                       value=f"{cur_val}(不變)",
                                       score=best_score, prof_ratio=np.nan,
                                       mean_pf=np.nan, med_retdd=np.nan, n=0,
                                       params=dict(current)))
                print(f"  -> {name} 維持 {cur_val}")
    return current, best_score, trajectory


# ----------------------------------------------------------------------------
# 報告
# ----------------------------------------------------------------------------
def write_report(best_overrides, best_train_score, trajectory,
                 test_new, test_old, default_overrides,
                 n_train, n_test, train_pool, test_pool, args):
    L = []
    L.append("# 台股策略參數優化結果（train/test 防過擬合）\n")
    L.append(f"- 成本模型：`{COST}`（真實台股手續費 0.1425%×2 + 證交稅 0.3%）")
    L.append(f"- 資料門檻：≥{MIN_YEARS} 年、≥{MIN_BARS} 根")
    L.append(f"- 切分：股票代碼末位 偶數→train、奇數→test")
    L.append(f"- Train 樣本：{n_train} 檔（母體 {train_pool} 檔，seed={args.seed}）")
    L.append(f"- Test 樣本：{n_test} 檔（母體 {test_pool} 檔，seed={args.seed}，OOS）")
    L.append(f"- Fitness：`score = 獲利檔比例 + 0.1*(平均PF-1)`\n")

    L.append("## 最佳參數（train 上 coordinate descent）\n")
    L.append("| 參數 | 預設值(crypto) | 優化後(台股) |")
    L.append("|---|---|---|")
    for name, _ in SWEEP:
        L.append(f"| {name} | {default_overrides[name]} | **{best_overrides[name]}** |")
    L.append(f"\n- Train 最佳 score：**{best_train_score:.4f}**\n")

    L.append("## ★ Test（OOS）新參數 vs 舊預設 對照\n")
    L.append("| 指標 | 舊預設(crypto) | 新優化(台股) | 變化 |")
    L.append("|---|---|---|---|")

    def row(label, key, fmt="{:.3f}"):
        a = test_old[key]; b = test_new[key]
        d = b - a
        return (f"| {label} | {fmt.format(a)} | {fmt.format(b)} | "
                f"{'+' if d >= 0 else ''}{fmt.format(d)} |")
    L.append(row("獲利檔比例 (PF>1且淨利>0)", "prof_ratio"))
    L.append(row("平均 PF", "mean_pf"))
    L.append(row("中位數 Return/MaxDD", "med_retdd"))
    L.append(f"| 測試檔數 | {test_old['n']} | {test_new['n']} | - |")
    L.append("")

    L.append("## Coordinate Descent 軌跡（train）\n")
    L.append("| 步驟 | 調整參數 | 採用值 | train score | 獲利比 | 平均PF | 中位RetDD |")
    L.append("|---|---|---|---|---|---|---|")
    for t in trajectory:
        pr = "-" if (isinstance(t["prof_ratio"], float) and np.isnan(t["prof_ratio"])) else f"{t['prof_ratio']:.3f}"
        mp = "-" if (isinstance(t["mean_pf"], float) and np.isnan(t["mean_pf"])) else f"{t['mean_pf']:.3f}"
        md = "-" if (isinstance(t["med_retdd"], float) and np.isnan(t["med_retdd"])) else f"{t['med_retdd']:.3f}"
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | "
                 f"{t['score']:.4f} | {pr} | {mp} | {md} |")
    L.append("")

    L.append("## 結論\n")
    improved = test_new["prof_ratio"] >= test_old["prof_ratio"]
    if improved:
        L.append("- OOS（test）上，優化參數的獲利檔比例 **不低於** 舊預設 → 優化有泛化價值，非單純過擬合 train。")
    else:
        L.append("- OOS（test）上優化參數獲利檔比例未超過舊預設 → 該參數空間對台股提升有限，建議保留舊預設或改調出場端。")
    L.append("")

    text = "\n".join(L)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-train", type=int, default=150)
    ap.add_argument("--n-test", type=int, default=150)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("=" * 70)
    print("台股策略參數優化（train/test）")
    print("=" * 70)
    t0 = time.time()
    print("載入快取資料中…")
    eligible = load_eligible()
    print(f"符合 ≥{MIN_YEARS} 年的股票：{len(eligible)} 檔")

    train, test, train_pool, test_pool = split_train_test(
        eligible, args.n_train, args.n_test, args.seed)
    print(f"Train：{len(train)} 檔（母體 {train_pool}）；Test：{len(test)} 檔（母體 {test_pool}）")

    # coordinate descent on train
    best_overrides, best_train_score, trajectory = coordinate_descent(train, args.rounds)

    # 預設 overrides（對照用）
    base = strategy.Params()
    default_overrides = {name: getattr(base, name) for name, _ in SWEEP}

    print("\n===== Test（OOS）驗證 =====")
    print("跑 新參數 …")
    test_new = evaluate(test, best_overrides)
    print(f"  新參數 test: 獲利比={test_new['prof_ratio']:.3f} "
          f"meanPF={test_new['mean_pf']:.3f} medRetDD={test_new['med_retdd']:.3f} (n={test_new['n']})")
    print("跑 舊預設 …")
    test_old = evaluate(test, default_overrides)
    print(f"  舊預設 test: 獲利比={test_old['prof_ratio']:.3f} "
          f"meanPF={test_old['mean_pf']:.3f} medRetDD={test_old['med_retdd']:.3f} (n={test_old['n']})")

    text = write_report(best_overrides, best_train_score, trajectory,
                        test_new, test_old, default_overrides,
                        len(train), len(test), train_pool, test_pool, args)

    print("\n" + "=" * 70)
    print(f"最佳參數: {best_overrides}")
    print(f"報告已存: {OUT_MD}")
    print(f"總耗時: {time.time()-t0:.0f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
