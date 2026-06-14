# -*- coding: utf-8 -*-
"""
tw_optimize_adaptive2.py — 優化自適應策略「沒調過」的部分（均值回歸半 + regime 切換）

前一輪只調了趨勢半。本輪聚焦：regime 切換門檻 + 均值回歸進出場。

1. 標的池 = screener 濾網篩後的「可交易池」（trend_frac≥0.25 + 年化≥0 + 流動性≥2000萬），
   依代碼末位 偶=train / 奇=test。只在 train 搜，test 報 OOS。修分割、tw_real。
2. 搜（coordinate descent）：
   - regime 切換：adxTrend 18/20/25、erTrend 0.26/0.30/0.36
   - MR 進場：bbLen 15/20/30、bbK 1.5/2.0/2.5、rsiBuy 25/30/35
   - MR 出場：rsiSell 50/55/60、mrMaxBars 10/20/30、mrStopK 1.5/2.0/2.5
   趨勢半固定：trendExposure=0.95、wideMult=11、baseLen=10。
3. Fitness = 篩後池 中位 Return/MaxDD + 獲利檔比例 + 活躍護欄（最弱標的交易數太少重罰）。
4. 輸出 twdata\optimize_adaptive2_result.md：最佳參數 + OOS 新 vs 現行 vs baseline + 軌跡。

執行：使用指定的 Python 3.9 解譯器。可選 --train-sample 200。
"""
import argparse
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
import tw_adaptive as ad
import tw_optimize_adaptive as oa   # trend_fraction / annual_return / avg_dollar_vol
import tw_trendride as tr           # adjust_splits

OUT_MD = os.path.join(tw_data.DATA_DIR, "optimize_adaptive2_result.md")
COST = "tw_real"
CAPITAL = 10000.0

# screener 濾網（滾動可實作版：用前 3 年算 trend_frac；年化/流動性用近 5 年）
SCREEN_TREND = 0.25
SCREEN_RET = 0.0
SCREEN_TURNOVER = 20_000_000.0
LOOKBACK_YEARS = 5.0
WARMUP_YEARS = 3.0
MIN_BARS = 1000
MIN_TRADES = 15.0          # 活躍護欄（篩後池標的、自適應交易數通常數十筆）

# 趨勢半固定（前一輪最佳）
TREND_FIXED = dict(trendExposure=0.95, wideMult=11.0, baseLen=10)

# 「現行 adaptive」= adaptive 預設（對照組之一）
CURRENT = dict(adxTrend=25.0, erTrend=0.30, bbLen=20, bbK=2.0, rsiBuy=30.0,
               rsiSell=55.0, mrMaxBars=20, mrStopK=1.5)
# baseline = 完全未調（同 CURRENT，但這裡 baseline 指「全市場未篩 + 預設參數」對照）

# 搜尋起點 = 現行預設
START = dict(CURRENT)
SWEEP = [
    ("adxTrend", [18.0, 20.0, 25.0]),
    ("erTrend",  [0.26, 0.30, 0.36]),
    ("bbLen",    [15, 20, 30]),
    ("bbK",      [1.5, 2.0, 2.5]),
    ("rsiBuy",   [25.0, 30.0, 35.0]),
    ("rsiSell",  [50.0, 55.0, 60.0]),
    ("mrMaxBars", [10, 20, 30]),
    ("mrStopK",  [1.5, 2.0, 2.5]),
]


# ----------------------------------------------------------------------------
# 載入 + screener 篩選（滾動，不看未來）
# ----------------------------------------------------------------------------
def recent_window(df, years):
    cutoff = df.index[-1] - pd.Timedelta(days=int(years * 365.25))
    return df[df.index >= cutoff]


def turnover_60d(df):
    if "Volume" not in df.columns:
        return 0.0
    dv = (df["Close"] * df["Volume"]).dropna()
    return float(dv.tail(60).median()) if len(dv) else 0.0


def build_pool():
    """回傳通過 screener 的 [(code, name, df, last_digit), ...]（df 已修分割）。"""
    uni = tw_data.get_universe()
    pool = []
    t0 = time.time()
    for k, (code, ticker, market, name) in enumerate(uni, 1):
        raw = tw_data.load_ohlcv(ticker, period="max", use_cache=True)
        if raw is None or len(raw) < MIN_BARS:
            continue
        df, _ = tr.adjust_splits(raw)
        # 滾動可實作：trend_frac 用前 WARMUP 年算；年化/流動性用近 LOOKBACK
        cut = df.index[0] + pd.Timedelta(days=int(WARMUP_YEARS * 365.25))
        warm = df[df.index <= cut]
        tf = oa.trend_fraction(warm) if len(warm) > 250 else 0.0
        win = recent_window(df, LOOKBACK_YEARS)
        if len(win) < 250:
            continue
        ar = oa.annual_return(win)
        to = turnover_60d(df)
        if tf >= SCREEN_TREND and ar >= SCREEN_RET and to >= SCREEN_TURNOVER:
            last = int(code[-1]) if code[-1].isdigit() else 0
            # 自適應只交易 warmup 之後（避免用到濾網期間；與可實作一致）
            tradedf = df[df.index > cut]
            if len(tradedf) >= 250:
                pool.append((code, name, tradedf, last))
        if k % 400 == 0:
            print(f"  篩選 {k}/{len(uni)}（已收池 {len(pool)}，{time.time()-t0:.0f}s）")
    print(f"  可交易池：{len(pool)} 檔（{time.time()-t0:.0f}s）")
    return pool


# ----------------------------------------------------------------------------
# 回測 + fitness（含 cache：MR/regime 參數變、趨勢半固定）
# ----------------------------------------------------------------------------
_CACHE = {}


def make_ap(over):
    p = ad.AdaptiveParams()
    for k, v in TREND_FIXED.items():
        setattr(p, k, v)
    for k, v in over.items():
        setattr(p, k, v)
    return p


def _key(over):
    return tuple(sorted((k, round(v, 6) if isinstance(v, float) else v) for k, v in over.items()))


def bt(code, df, over):
    key = (code, _key(over))
    if key in _CACHE:
        return _CACHE[key]
    p = make_ap(over)
    m, _, _, _ = ad.backtest_adaptive(df, COST, CAPITAL, p)
    _CACHE[key] = m
    return m


def evaluate(pool, over):
    prof = 0
    pfs, rdds, trades = [], [], []
    for code, name, df, _ in pool:
        m = bt(code, df, over)
        pf = m["profit_factor"]
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
        pfs.append(pf if np.isfinite(pf) else 5.0)
        rdd = m["return_over_maxdd"]
        rdds.append(rdd if np.isfinite(rdd) else (5.0 if m["net_profit_pct"] > 0 else -1.0))
        trades.append(m["n_trades"])
    n = len(pfs)
    if n == 0:
        return dict(score=-99, prof_ratio=0, med_pf=0, med_rdd=0, med_tr=0, n=0)
    prof_ratio = prof / n
    med_rdd = float(np.median(rdds))
    med_pf = float(np.median(pfs))
    med_tr = float(np.median(trades))
    # fitness = 中位Ret/MaxDD（clip）+ 獲利比例 + 活躍護欄（中位交易數 < MIN_TRADES 重罰）
    score = min(med_rdd, 5.0) + prof_ratio
    if med_tr < MIN_TRADES:
        score -= 3.0 * (1.0 - med_tr / MIN_TRADES)
    return dict(score=score, prof_ratio=prof_ratio, med_pf=med_pf,
                med_rdd=med_rdd, med_tr=med_tr, n=n)


def _fmt(d):
    return (f"score={d['score']:.3f} 獲利比={d['prof_ratio']*100:.0f}% "
            f"medPF={d['med_pf']:.2f} medRetDD={d['med_rdd']:.2f} medTr={d['med_tr']:.0f} n={d['n']}")


def coordinate_descent(pool, rounds=2):
    cur = dict(START)
    e = evaluate(pool, cur)
    print(f"[起點] {_fmt(e)}")
    best = e["score"]
    traj = [dict(step="起點", param="-", value="-", **{k: e[k] for k in
                ("score", "prof_ratio", "med_rdd", "med_tr")})]
    for rnd in range(1, rounds + 1):
        print(f"--- 第 {rnd} 輪 ---")
        for name, values in SWEEP:
            cv = cur[name]; bv = cv; bl = best; bm = None
            for v in values:
                if v == cv:
                    continue
                trial = dict(cur); trial[name] = v
                r = evaluate(pool, trial)
                flag = "  <==" if r["score"] > bl + 1e-9 else ""
                if r["score"] > bl + 1e-9:
                    bl = r["score"]; bv = v; bm = r
                print(f"  {name}={v} {_fmt(r)}{flag}")
            if bv != cv and bm is not None:
                cur[name] = bv; best = bl
                traj.append(dict(step=f"R{rnd}", param=name, value=bv, score=bm["score"],
                                 prof_ratio=bm["prof_ratio"], med_rdd=bm["med_rdd"], med_tr=bm["med_tr"]))
                print(f"  -> {name} 採用 {bv}（score {best:.3f}）")
            else:
                traj.append(dict(step=f"R{rnd}", param=name, value=f"{cv}(不變)", score=best,
                                 prof_ratio=np.nan, med_rdd=np.nan, med_tr=np.nan))
    return cur, evaluate(pool, cur), traj


def main():
    apg = argparse.ArgumentParser()
    apg.add_argument("--train-sample", type=int, default=0, help="0=用全 train 池")
    apg.add_argument("--seed", type=int, default=42)
    args = apg.parse_args()

    print("=" * 80)
    print("優化自適應 v2：均值回歸半 + regime 切換（screener 池、train/test）")
    print("=" * 80)
    t0 = time.time()
    pool = build_pool()
    train = [r for r in pool if r[3] % 2 == 0]
    test = [r for r in pool if r[3] % 2 == 1]
    print(f"切分：train {len(train)}、test {len(test)}")

    train_search = train
    if args.train_sample and len(train) > args.train_sample:
        rng = np.random.RandomState(args.seed)
        idx = sorted(rng.choice(len(train), args.train_sample, replace=False))
        train_search = [train[i] for i in idx]
        print(f"train 搜尋子樣本：{len(train_search)}")

    best, train_eval, traj = coordinate_descent(train_search, rounds=2)
    print(f"\n最佳: {best}")
    print(f"train(篩後): {_fmt(train_eval)}")

    print("\n===== OOS（test）=====")
    oos_new = evaluate(test, best)
    oos_cur = evaluate(test, CURRENT)
    print("  新參數:", _fmt(oos_new))
    print("  現行adaptive:", _fmt(oos_cur))

    write_report(best, train_eval, oos_new, oos_cur, traj, len(train), len(test))
    print(f"\n報告: {OUT_MD}  總耗時 {time.time()-t0:.0f}s")


def write_report(best, train_eval, oos_new, oos_cur, traj, n_tr, n_te):
    L = []
    L.append("# 自適應策略 v2 優化 — 均值回歸半 + regime 切換（screener 池、OOS）\n")
    L.append(f"- 標的池 = screener 濾後可交易池（trend_frac≥{SCREEN_TREND} 滾動 + 年化≥{SCREEN_RET*100:.0f}% "
             f"+ 近60日均額≥{SCREEN_TURNOVER:,.0f}）；修分割、tw_real。")
    L.append(f"- 切分：代碼末位 偶=train({n_tr}) / 奇=test({n_te})；只在 train 搜、test 報 OOS。")
    L.append("- 趨勢半固定（前輪最佳）：trendExposure=0.95、wideMult=11、baseLen=10。")
    L.append(f"- Fitness = 中位Ret/MaxDD + 獲利比例 + 活躍護欄（中位交易<{MIN_TRADES:.0f} 重罰）。\n")

    L.append("## 最佳參數（均值回歸 + regime）vs 現行\n")
    L.append("| 參數 | 現行adaptive | **v2 最佳** |")
    L.append("|---|---|---|")
    for k in START:
        L.append(f"| {k} | {CURRENT[k]} | **{best[k]}** |")
    L.append("")

    L.append("## ★ OOS（test）對照\n")
    L.append("| 設定 | 獲利檔比例 | 中位PF | 中位Ret/MaxDD | 中位交易 | 池 |")
    L.append("|---|---|---|---|---|---|")
    L.append(f"| 現行 adaptive（未調MR） | {oos_cur['prof_ratio']*100:.1f}% | {oos_cur['med_pf']:.3f} | {oos_cur['med_rdd']:.3f} | {oos_cur['med_tr']:.0f} | {oos_cur['n']} |")
    L.append(f"| **v2 最佳（調MR+regime）** | **{oos_new['prof_ratio']*100:.1f}%** | {oos_new['med_pf']:.3f} | {oos_new['med_rdd']:.3f} | {oos_new['med_tr']:.0f} | {oos_new['n']} |")
    L.append("")
    dprof = (oos_new['prof_ratio'] - oos_cur['prof_ratio']) * 100
    drdd = oos_new['med_rdd'] - oos_cur['med_rdd']
    L.append(f"- train(篩後) 獲利比 {train_eval['prof_ratio']*100:.1f}%、中位Ret/DD {train_eval['med_rdd']:.2f}。")
    overfit = (oos_new['prof_ratio']*100 < train_eval['prof_ratio']*100 - 12) or (oos_new['med_rdd'] < train_eval['med_rdd'] - 1.0)
    if overfit:
        L.append(f"- ⚠ **OOS 明顯比 train 差（獲利比 {train_eval['prof_ratio']*100:.0f}%→{oos_new['prof_ratio']*100:.0f}%、"
                 f"Ret/DD {train_eval['med_rdd']:.2f}→{oos_new['med_rdd']:.2f}）→ 有過擬合疑慮**。")
    else:
        L.append(f"- OOS 與 train 接近 → 非過擬合。")
    L.append("")

    L.append("## Coordinate Descent 軌跡（train）\n")
    L.append("| 步驟 | 參數 | 採用值 | score | 獲利比 | 中位Ret/DD | 中位交易 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in traj:
        def g(k, f="{:.3f}"):
            v = t.get(k, np.nan)
            return "-" if (isinstance(v, float) and np.isnan(v)) else f.format(v)
        pr = "-" if (isinstance(t.get("prof_ratio"), float) and np.isnan(t.get("prof_ratio"))) else f"{t['prof_ratio']*100:.0f}%"
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | {t['score']:.3f} | {pr} | {g('med_rdd')} | {g('med_tr','{:.0f}')} |")
    L.append("")

    L.append("## 誠實結論\n")
    if overfit:
        L.append("- ⚠ 過擬合：OOS 明顯低於 train。**建議退回現行 adaptive 參數**，本輪 MR/regime 調整未泛化。")
        L.append(f"- 最終建議：沿用現行（adxTrend=25, erTrend=0.30, bbLen=20, bbK=2.0, rsiBuy=30, rsiSell=55, mrMaxBars=20, mrStopK=1.5）。")
    elif dprof >= 3 or drdd >= 0.1:
        L.append(f"- v2 在 OOS 上改善：獲利比 {dprof:+.1f}、中位Ret/DD {drdd:+.3f}。MR/regime 調整有泛化價值，採用 v2。")
    else:
        L.append(f"- v2 在 OOS 上與現行差不多（獲利比 {dprof:+.1f}、Ret/DD {drdd:+.3f}）。"
                 "MR/regime 已接近最佳，調整空間有限——維持現行即可，不必換。")
    L.append("- 註：池為 screener 篩後子集，非全台股；數字反映「對的標的上」的表現。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
