# -*- coding: utf-8 -*-
"""
tw_optimize_v2.py — 修正版參數優化（修掉「獎勵不交易」的 fitness）

問題：v1 fitness = 獲利檔比例 + 0.1*(平均PF-1)，會獎勵「幾乎不交易」——
       minVotes=3 讓 0050 等 17 年只交易十幾次、大多空手、實際報酬極低
      （0050 PF 2.09 但只賺 +6.4%）。PF/獲利檔比例高 ≠ 真的賺到錢。

修正：
  1. Fitness 改以「真正賺到錢」為主：
       fitness = 中位數(Return/MaxDD)（train 樣本）
     並加「最低活躍度護欄」：若 train 平均每檔交易數 < MIN_AVG_TRADES(=20)，
     重罰（線性扣分），避免又收斂到不交易。
     同時記錄 平均淨利%、獲利檔比例、平均交易數 供對照。成本 tw_real。
  2. 搜尋方向改往「抓得住趨勢/讓利潤奔跑」：
       minVotes 2 vs 3、erThr 0.26/0.30/0.36、adxOn 22/25/28、
       trailMidR 2.5/2.8/3.2、trailTightR 2.2/2.5/3.0、tp2R 3.5/4.5/6.0、
       baseLen 7/10/14。
  3. train 找最佳 → test OOS 驗證；對照「舊優化(minVotes3那組)」vs「新參數」。
     另外把最佳新參數在 0050/00631L/006208 三個趨勢 ETF 各跑一次（tw_real）。
  4. 輸出 twdata\optimize_result_v2.md。

執行：使用指定的 Python 3.9 解譯器執行本檔。
可選：--n-train 150 --n-test 150 --rounds 2 --seed 42
"""
import argparse
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
OUT_MD = os.path.join(DATA_DIR, "optimize_result_v2.md")

MIN_YEARS = 5
MIN_BARS = 1000
COST = "tw_real"
CAPITAL = 10000.0
MIN_AVG_TRADES = 20.0          # 活躍度護欄：train 平均每檔交易數下限

# 起點 = 「冠軍 v5 原生 crypto 預設」而非目前被汙染的 minVotes=3。
# 明確指定起點，避免從上一輪壞參數出發。
START = dict(minVotes=2, erThr=0.36, adxOn=25.0, trailMidR=2.8,
             trailTightR=2.5, tp2R=4.5, baseLen=10, chandMult=3.0)

# 舊優化參數（minVotes=3 那組，要被對照打臉的對象）
OLD_OPT = dict(minVotes=3, erThr=0.30, adxOn=28.0, trailMidR=2.8,
               trailTightR=2.5, tp2R=4.5, baseLen=7, chandMult=3.5)

# 搜尋方向：往「多交易/讓利潤奔跑」掃
SWEEP = [
    ("minVotes",    [2, 3]),
    ("erThr",       [0.26, 0.30, 0.36]),
    ("adxOn",       [22.0, 25.0, 28.0]),
    ("trailMidR",   [2.5, 2.8, 3.2]),
    ("trailTightR", [2.2, 2.5, 3.0]),
    ("tp2R",        [3.5, 4.5, 6.0]),
    ("baseLen",     [7, 10, 14]),
]


# ----------------------------------------------------------------------------
# 資料
# ----------------------------------------------------------------------------
def _ticker_from_cache(path):
    name = os.path.basename(path).rsplit(".", 1)[0]
    return name.replace("_", ".")


def load_eligible():
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
        if not {"Open", "High", "Low", "Close"}.issubset(df.columns):
            continue
        ticker = _ticker_from_cache(f)
        out.append((ticker.split(".")[0], ticker, df))
    return out


def split_train_test(eligible, n_train, n_test, seed):
    train_pool, test_pool = [], []
    for code, ticker, df in eligible:
        try:
            last = int(code[-1])
        except ValueError:
            continue
        (train_pool if last % 2 == 0 else test_pool).append((code, ticker, df))
    rng = np.random.RandomState(seed)

    def sample(pool, n):
        if len(pool) <= n:
            return pool
        idx = sorted(rng.choice(len(pool), size=n, replace=False))
        return [pool[i] for i in idx]

    return sample(train_pool, n_train), sample(test_pool, n_test), len(train_pool), len(test_pool)


# ----------------------------------------------------------------------------
# 參數 / 評估
# ----------------------------------------------------------------------------
def make_params(overrides: dict) -> strategy.Params:
    p = strategy.Params()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def evaluate(sample, overrides: dict):
    """回傳 dict: score, med_retdd, mean_net, prof_ratio, avg_trades, n。

    fitness（score）= 中位數(Return/MaxDD)，但若平均交易數 < MIN_AVG_TRADES
    則線性重罰：score -= 2.0 * (1 - avg_trades/MIN_AVG_TRADES)。
    """
    p = make_params(overrides)
    retdds = []
    nets = []
    trades_list = []
    prof = 0
    n = 0
    for code, ticker, df in sample:
        try:
            m, _, _ = strategy.backtest_long_only(
                df, cost_model=COST, initial_capital=CAPITAL, p=p)
        except Exception:
            continue
        n += 1
        nets.append(m["net_profit_pct"])
        trades_list.append(m["n_trades"])
        rdd = m["return_over_maxdd"]
        # inf（有獲利但 0 回撤）clip 成合理上界，避免拉爆中位數附近
        if np.isfinite(rdd):
            retdds.append(rdd)
        else:
            retdds.append(5.0 if m["net_profit_pct"] > 0 else -1.0)
        pf = m["profit_factor"]
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
    if n == 0:
        return dict(score=-99, med_retdd=0.0, mean_net=0.0,
                    prof_ratio=0.0, avg_trades=0.0, n=0)
    med_retdd = float(np.median(retdds))
    mean_net = float(np.mean(nets))
    avg_trades = float(np.mean(trades_list))
    prof_ratio = prof / n
    score = med_retdd
    if avg_trades < MIN_AVG_TRADES:
        score -= 2.0 * (1.0 - avg_trades / MIN_AVG_TRADES)
    return dict(score=score, med_retdd=med_retdd, mean_net=mean_net,
                prof_ratio=prof_ratio, avg_trades=avg_trades, n=n)


def _fmt(d):
    return (f"score={d['score']:.4f} medRetDD={d['med_retdd']:.3f} "
            f"meanNet={d['mean_net']:.2f}% 獲利比={d['prof_ratio']:.3f} "
            f"avgTrades={d['avg_trades']:.1f}")


# ----------------------------------------------------------------------------
# Coordinate descent
# ----------------------------------------------------------------------------
def coordinate_descent(train, rounds):
    current = dict(START)
    trajectory = []

    start = evaluate(train, current)
    print(f"[起點] {current}")
    print(f"        {_fmt(start)}")
    trajectory.append(dict(step="起點", param="-", value="-", **start))
    best_score = start["score"]

    for rnd in range(1, rounds + 1):
        print(f"\n===== 第 {rnd} 輪 =====")
        for name, values in SWEEP:
            cur_val = current[name]
            best_val = cur_val
            best_local = best_score
            best_metrics = None
            for v in values:
                if v == cur_val:
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
                print(f"  {name}={v:<6} {_fmt(r)} ({dt:.0f}s){flag}")
            if best_val != cur_val and best_metrics is not None:
                current[name] = best_val
                best_score = best_local
                trajectory.append(dict(step=f"R{rnd}", param=name,
                                       value=best_val, **best_metrics))
                print(f"  -> {name} 採用 {best_val}（score {best_score:.4f}）")
            else:
                trajectory.append(dict(step=f"R{rnd}", param=name,
                                       value=f"{cur_val}(不變)", score=best_score,
                                       med_retdd=np.nan, mean_net=np.nan,
                                       prof_ratio=np.nan, avg_trades=np.nan, n=0))
                print(f"  -> {name} 維持 {cur_val}")
    return current, best_score, trajectory


# ----------------------------------------------------------------------------
# ETF 單檔驗證
# ----------------------------------------------------------------------------
def run_etfs(overrides):
    p = make_params(overrides)
    rows = []
    for t in ["0050.TW", "00631L.TW", "006208.TW"]:
        df = tw_data.load_ohlcv(t, period="max", sleep=0.4)
        if df is None or len(df) < 250:
            rows.append((t, None))
            continue
        m, _, _ = strategy.backtest_long_only(df, cost_model=COST,
                                              initial_capital=CAPITAL, p=p)
        rows.append((t, m))
    return rows


# ----------------------------------------------------------------------------
# 報告
# ----------------------------------------------------------------------------
def write_report(best, best_score, trajectory, test_new, test_old,
                 etf_new, etf_old, n_train, n_test, train_pool, test_pool, args):
    L = []
    L.append("# 台股參數優化 v2 — 修正「獎勵不交易」的 fitness\n")
    L.append("## 問題與修正")
    L.append("- **v1 的錯**：fitness = 獲利檔比例 + 0.1*(平均PF−1)，獎勵了「幾乎不交易」。")
    L.append("  minVotes=3 讓 0050 等 17 年只交易十幾次、大多空手，PF 漂亮但實際只賺 +6.4%。")
    L.append("- **v2 修正**：`fitness = 中位數(Return/MaxDD)`，並加活躍度護欄——")
    L.append(f"  train 平均每檔交易數 < {MIN_AVG_TRADES:.0f} 就線性重罰，逼策略真的去交易。")
    L.append(f"- 成本 `{COST}`；資料 ≥{MIN_YEARS} 年；train/test 依代碼末位偶/奇切分。")
    L.append(f"- Train {n_train} 檔（母體 {train_pool}）、Test {n_test} 檔（母體 {test_pool}），seed={args.seed}。\n")

    L.append("## 最佳新參數（train coordinate descent）\n")
    L.append("| 參數 | 起點(crypto原生) | 舊優化(minVotes3) | **新優化v2** |")
    L.append("|---|---|---|---|")
    allkeys = ["minVotes", "erThr", "adxOn", "trailMidR", "trailTightR", "tp2R", "baseLen"]
    for k in allkeys:
        L.append(f"| {k} | {START.get(k,'-')} | {OLD_OPT.get(k,'-')} | **{best.get(k,'-')}** |")
    L.append(f"\n- Train 最佳 score（中位Ret/MaxDD，含護欄）：**{best_score:.4f}**\n")

    L.append("## ★ Test（OOS）對照：舊優化(minVotes3) vs 新優化v2\n")
    L.append("| 指標 | 舊優化(minVotes3) | 新優化v2 | 變化 |")
    L.append("|---|---|---|---|")

    def row(label, key, fmt="{:.3f}"):
        a, b = test_old[key], test_new[key]
        d = b - a
        return f"| {label} | {fmt.format(a)} | {fmt.format(b)} | {'+' if d>=0 else ''}{fmt.format(d)} |"
    L.append(row("中位數 Return/MaxDD", "med_retdd"))
    L.append(row("平均淨利 %", "mean_net", "{:.2f}"))
    L.append(row("平均交易數", "avg_trades", "{:.1f}"))
    L.append(row("獲利檔比例", "prof_ratio"))
    L.append(f"| 測試檔數 | {test_old['n']} | {test_new['n']} | - |")
    L.append("")

    L.append("## ★ 趨勢 ETF 實測（策略真正該套的地方，tw_real，period max）\n")
    L.append("策略設計就是吃趨勢，這幾檔長多 ETF 才是檢驗「報酬有沒有變大」的關鍵。\n")
    L.append("| ETF | 參數 | 淨利% | PF | 交易數 | MaxDD% | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|---|")

    def etf_rows(rows, tag):
        for t, m in rows:
            if m is None:
                L.append(f"| {t} | {tag} | - | - | - | - | - |")
                continue
            pf = "inf" if not np.isfinite(m["profit_factor"]) else f"{m['profit_factor']:.2f}"
            rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else f"{m['return_over_maxdd']:.2f}"
            L.append(f"| {t} | {tag} | {m['net_profit_pct']:.1f} | {pf} | "
                     f"{m['n_trades']} | {m['max_dd_pct']:.1f} | {rdd} |")
    etf_rows(etf_old, "舊(mv3)")
    etf_rows(etf_new, "**新v2**")
    L.append("")

    L.append("## Coordinate Descent 軌跡（train）\n")
    L.append("| 步驟 | 參數 | 採用值 | score | 中位Ret/DD | 平均淨利% | 獲利比 | 平均交易數 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for t in trajectory:
        def g(k, f="{:.3f}"):
            v = t[k]
            return "-" if (isinstance(v, float) and np.isnan(v)) else f.format(v)
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | {t['score']:.4f} | "
                 f"{g('med_retdd')} | {g('mean_net','{:.2f}')} | {g('prof_ratio')} | {g('avg_trades','{:.1f}')} |")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-train", type=int, default=150)
    ap.add_argument("--n-test", type=int, default=150)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("=" * 70)
    print("台股參數優化 v2（修正 fitness：中位Ret/MaxDD + 活躍度護欄）")
    print("=" * 70)
    t0 = time.time()
    print("載入快取資料…")
    eligible = load_eligible()
    print(f"符合 ≥{MIN_YEARS} 年：{len(eligible)} 檔")
    train, test, trp, tep = split_train_test(eligible, args.n_train, args.n_test, args.seed)
    print(f"Train {len(train)}（母體 {trp}）；Test {len(test)}（母體 {tep}）")

    best, best_score, traj = coordinate_descent(train, args.rounds)

    print("\n===== Test（OOS）驗證 =====")
    print("新參數v2 …")
    test_new = evaluate(test, best)
    print("  ", _fmt(test_new))
    print("舊優化(minVotes3) …")
    test_old = evaluate(test, OLD_OPT)
    print("  ", _fmt(test_old))

    print("\n===== 趨勢 ETF 實測 =====")
    print("新參數v2 ETF …")
    etf_new = run_etfs(best)
    for t, m in etf_new:
        if m: print(f"  {t}: 淨利{m['net_profit_pct']:.1f}% PF={m['profit_factor']} "
                    f"交易{m['n_trades']} RetDD={m['return_over_maxdd']}")
    print("舊優化(minVotes3) ETF …")
    etf_old = run_etfs(OLD_OPT)
    for t, m in etf_old:
        if m: print(f"  {t}: 淨利{m['net_profit_pct']:.1f}% PF={m['profit_factor']} "
                    f"交易{m['n_trades']} RetDD={m['return_over_maxdd']}")

    write_report(best, best_score, traj, test_new, test_old,
                 etf_new, etf_old, len(train), len(test), trp, tep, args)
    print("\n" + "=" * 70)
    print(f"最佳新參數: {best}")
    print(f"報告已存: {OUT_MD}")
    print(f"總耗時: {time.time()-t0:.0f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
