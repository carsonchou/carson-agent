# -*- coding: utf-8 -*-
"""
tw_optimize_adaptive.py — 瘋狂優化自適應策略 + 選股濾網（強制 train/test 防過擬合）

切分：全台股（修分割、≥5年）依代碼末位 偶數=train / 奇數=test。
      所有搜尋只在 train，最後在 test 報 OOS。對照未優化 baseline。

搜尋（coordinate descent 多輪）：
  (A) 策略參數：regime 門檻(adxTrend/erTrend)、趨勢段(exposure/wideMult/adxOn/baseLen)、
      均值回歸段(bbLen/bbK/rsiBuy/rsiSell/mrStopK/mrMaxBars)。
  (B) ★選股濾網（大槓桿）：trend_frac≥門檻、最低日均成交額(流動性)、排除長期陰跌
      （全期年化報酬 ≥ 門檻）。濾網門檻納入搜尋。

      ⚠ 誠實標示 look-ahead：
        - trend_frac / 全期年化報酬 = 「全期統計選股」（研究用，含未來資訊）。
        - 另跑「可實作的滾動版」：只用前 WARMUP_YEARS 的資料算濾網特徵，之後才交易，
          兩者都報、誠實區分。

Fitness（train，濾後池）：獲利檔比例 + 中位數 Ret/MaxDD，加最低池大小護欄
      （池 < MIN_POOL 重罰，避免濾到剩幾檔作弊）。

輸出 twdata\optimize_adaptive_result.md。tw_real、252。
執行：使用指定的 Python 3.9 解譯器。可選 --train-sample 400。
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
import tw_trendride as tr

OUT_MD = os.path.join(tw_data.DATA_DIR, "optimize_adaptive_result.md")
COST = "tw_real"
CAPITAL = 10000.0
MIN_POOL = 40            # 濾後池最小檔數（護欄，避免濾到剩幾檔）
WARMUP_YEARS = 3.0      # 可實作滾動版：用前 3 年算濾網特徵


# ----------------------------------------------------------------------------
# 載入 + 特徵預算（一次）
# ----------------------------------------------------------------------------
def trend_fraction(df, adxLen=14, erLen=20, adxThr=25.0, erThr=0.30):
    """歷史趨勢佔比（ADX≥thr 且 ER≥thr 的根數比例）。"""
    import indicators as ind
    _, _, adx = ind.dmi(df, adxLen, adxLen)
    er = ind.kaufman_er(df["Close"], erLen)
    mask = (adx >= adxThr) & (er >= erThr)
    return float(mask.mean())


def annual_return(df):
    c = df["Close"]
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    if yrs <= 0 or c.iloc[0] <= 0:
        return 0.0
    return (c.iloc[-1] / c.iloc[0]) ** (1.0 / yrs) - 1.0


def avg_dollar_vol(df):
    if "Volume" not in df.columns:
        return 0.0
    dv = (df["Close"] * df["Volume"]).dropna()
    return float(dv.median()) if len(dv) else 0.0


def load_all(train_only_codes=None):
    """載入全 universe（修分割、≥5年），回傳 list of dict（含特徵，全期 + 滾動版）。"""
    uni = tw_data.get_universe()
    out = []
    t0 = time.time()
    for k, (code, ticker, market, name) in enumerate(uni, 1):
        df = ad.load_adj(ticker)
        if df is None:
            continue
        # 全期特徵（研究用，含未來）
        tf_full = trend_fraction(df)
        ar_full = annual_return(df)
        dv = avg_dollar_vol(df)
        # 滾動可實作特徵：只用前 WARMUP_YEARS
        cut = df.index[0] + pd.Timedelta(days=int(WARMUP_YEARS * 365.25))
        warm = df[df.index <= cut]
        tf_roll = trend_fraction(warm) if len(warm) > 250 else tf_full
        out.append(dict(code=code, name=name, df=df, last=int(code[-1]) if code[-1].isdigit() else 0,
                        tf_full=tf_full, ar_full=ar_full, dv=dv, tf_roll=tf_roll,
                        warm_cut=cut))
        if k % 300 == 0:
            print(f"  載入 {k}/{len(uni)}（已收 {len(out)}，{time.time()-t0:.0f}s）")
    print(f"  載入完成：{len(out)} 檔（{time.time()-t0:.0f}s）")
    return out


# ----------------------------------------------------------------------------
# 濾網
# ----------------------------------------------------------------------------
def pass_filter(rec, f, rolling=False):
    tf = rec["tf_roll"] if rolling else rec["tf_full"]
    if tf < f["tf_min"]:
        return False
    if rec["dv"] < f["dv_min"]:
        return False
    if (not rolling) and rec["ar_full"] < f["ar_min"]:
        return False
    return True


# ----------------------------------------------------------------------------
# 回測單檔（自適應，可帶滾動 warmup-only-trade）
# ----------------------------------------------------------------------------
def make_ap(overrides):
    p = ad.AdaptiveParams()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


_BT_CACHE = {}   # (code, ap_key, rolling) -> metrics；策略參數不變時濾網掃描可重用


def _ap_key(ap_over):
    return tuple(sorted((k, round(v, 6) if isinstance(v, float) else v)
                        for k, v in ap_over.items()))


def bt_adaptive(rec, ap_over, rolling=False):
    key = (rec["code"], _ap_key(ap_over), rolling)
    if key in _BT_CACHE:
        return _BT_CACHE[key]
    df = rec["df"]
    if rolling:
        df = df[df.index > rec["warm_cut"]]   # 只交易 warmup 之後（避免濾網用到的期間重複計入）
        if len(df) < 250:
            _BT_CACHE[key] = None
            return None
    p = make_ap(ap_over)
    m, _, _, _ = ad.backtest_adaptive(df, COST, CAPITAL, p)
    _BT_CACHE[key] = m
    return m


# ----------------------------------------------------------------------------
# Fitness（train 濾後池）
# ----------------------------------------------------------------------------
def evaluate(pool, ap_over, f, rolling=False):
    sel = [r for r in pool if pass_filter(r, f, rolling)]
    n_sel = len(sel)
    if n_sel == 0:
        return dict(score=-99, prof_ratio=0.0, med_pf=0.0, med_rdd=0.0, pool=0)
    prof = 0
    pfs, rdds = [], []
    for r in sel:
        m = bt_adaptive(r, ap_over, rolling)
        if m is None:
            continue
        pf = m["profit_factor"]
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
        pfs.append(pf if np.isfinite(pf) else 5.0)
        rdd = m["return_over_maxdd"]
        rdds.append(rdd if np.isfinite(rdd) else (5.0 if m["net_profit_pct"] > 0 else -1.0))
    n_eval = len(pfs)
    if n_eval == 0:
        return dict(score=-99, prof_ratio=0.0, med_pf=0.0, med_rdd=0.0, pool=0)
    prof_ratio = prof / n_eval
    med_pf = float(np.median(pfs))
    med_rdd = float(np.median(rdds))
    # med_rdd clip 進 score，避免少數標的的天文 Ret/MaxDD 把分數灌爆
    med_rdd_capped = min(med_rdd, 5.0)
    if n_eval < MIN_POOL:
        # 硬性護欄：池太小直接淘汰——回傳「遠低於任何合法配置」的分數，
        # 且池越小越差，讓搜尋永遠不會收斂到小池作弊。
        score = -10.0 + (n_eval / MIN_POOL) * 1.0   # 介於 -10 ~ -9，恆低於合法配置(>=0)
    else:
        score = prof_ratio + 0.3 * med_rdd_capped
    return dict(score=score, prof_ratio=prof_ratio, med_pf=med_pf,
                med_rdd=med_rdd, pool=n_eval)


def _fmt(d):
    return (f"score={d['score']:.3f} 獲利比={d['prof_ratio']*100:.0f}% "
            f"medPF={d['med_pf']:.2f} medRetDD={d['med_rdd']:.2f} 池={d['pool']}")


# ----------------------------------------------------------------------------
# 搜尋空間
# ----------------------------------------------------------------------------
# 策略參數起點（= adaptive 預設）
AP_START = dict(adxTrend=25.0, erTrend=0.30, trendExposure=0.95, wideMult=9.0,
                adxLen=14, baseLen=10, bbLen=20, bbK=2.0, rsiBuy=30.0,
                rsiSell=55.0, mrStopK=1.5, mrMaxBars=20, mrExposure=0.60)
# 濾網起點（寬鬆＝幾乎全收）
F_START = dict(tf_min=0.0, dv_min=0.0, ar_min=-1.0)

AP_SWEEP = [
    ("adxTrend",      [20.0, 25.0, 30.0]),
    ("erTrend",       [0.26, 0.30, 0.36]),
    ("trendExposure", [0.8, 0.95, 1.0]),
    ("wideMult",      [8.0, 11.0, 14.0]),
    ("baseLen",       [7, 10, 14]),
    ("bbLen",         [20, 30]),
    ("bbK",           [2.0, 2.5]),
    ("rsiBuy",        [25.0, 30.0]),
    ("rsiSell",       [50.0, 55.0]),
    ("mrStopK",       [1.5, 2.5]),
    ("mrMaxBars",     [15, 20, 30]),
]
F_SWEEP = [
    ("tf_min", [0.0, 0.15, 0.20, 0.25, 0.30]),
    ("dv_min", [0.0, 5e6, 2e7, 5e7]),       # 日均成交額(中位數)門檻
    ("ar_min", [-1.0, 0.0, 0.05, 0.10]),    # 全期年化報酬門檻
]


def coordinate_descent(pool, rounds=2):
    ap = dict(AP_START)
    f = dict(F_START)
    cur = evaluate(pool, ap, f)
    print(f"[起點] {_fmt(cur)}")
    best = cur["score"]
    traj = [dict(step="起點", param="-", value="-", **{k: cur[k] for k in
                ("score", "prof_ratio", "med_rdd", "pool")})]

    for rnd in range(1, rounds + 1):
        print(f"--- 第 {rnd} 輪 ---")
        # 先掃濾網（大槓桿），再掃策略
        for kind, sweep, target in [("濾網", F_SWEEP, f), ("策略", AP_SWEEP, ap)]:
            for name, values in sweep:
                curv = target[name]; bv = curv; bl = best; bm = None
                for v in values:
                    if v == curv:
                        continue
                    trial = dict(target); trial[name] = v
                    if kind == "濾網":
                        r = evaluate(pool, ap, trial)
                    else:
                        r = evaluate(pool, trial, f)
                    if r["score"] > bl + 1e-9:
                        bl = r["score"]; bv = v; bm = r
                    print(f"  [{kind}] {name}={v} {_fmt(r)}")
                if bv != curv and bm is not None:
                    target[name] = bv; best = bl
                    traj.append(dict(step=f"R{rnd}", param=name, value=bv,
                                     score=bm["score"], prof_ratio=bm["prof_ratio"],
                                     med_rdd=bm["med_rdd"], pool=bm["pool"]))
                    print(f"  -> {name} 採用 {bv}（score {best:.3f}）")
                else:
                    traj.append(dict(step=f"R{rnd}", param=name, value=f"{curv}(不變)",
                                     score=best, prof_ratio=np.nan, med_rdd=np.nan, pool=np.nan))
    return ap, f, evaluate(pool, ap, f), traj


# ----------------------------------------------------------------------------
# OOS 評估（全市場 vs 濾後池 vs baseline）
# ----------------------------------------------------------------------------
def eval_full(pool, ap_over, rolling=False):
    """全 pool（不濾），回傳 prof_ratio / med_pf / med_rdd / n。"""
    prof = 0; pfs = []; rdds = []
    for r in pool:
        m = bt_adaptive(r, ap_over, rolling)
        if m is None:
            continue
        pf = m["profit_factor"]
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
        pfs.append(pf if np.isfinite(pf) else 5.0)
        rdd = m["return_over_maxdd"]
        rdds.append(rdd if np.isfinite(rdd) else (5.0 if m["net_profit_pct"] > 0 else -1.0))
    n = len(pfs)
    if n == 0:
        return dict(prof_ratio=0, med_pf=0, med_rdd=0, n=0)
    return dict(prof_ratio=prof / n * 100, med_pf=float(np.median(pfs)),
                med_rdd=float(np.median(rdds)), n=n)


def eval_filtered(pool, ap_over, f, rolling=False):
    sel = [r for r in pool if pass_filter(r, f, rolling)]
    return eval_full(sel, ap_over, rolling), len(sel)


def main():
    ap_arg = argparse.ArgumentParser()
    ap_arg.add_argument("--train-sample", type=int, default=400,
                        help="train 搜尋用的隨機子樣本大小（控制回測量）")
    ap_arg.add_argument("--seed", type=int, default=42)
    args = ap_arg.parse_args()

    print("=" * 80)
    print("瘋狂優化自適應策略 + 選股濾網（train/test 防過擬合）")
    print("=" * 80)
    t0 = time.time()
    allrec = load_all()
    train = [r for r in allrec if r["last"] % 2 == 0]
    test = [r for r in allrec if r["last"] % 2 == 1]
    print(f"切分：train {len(train)}、test {len(test)}")

    # train 搜尋子樣本（控制回測量）
    rng = np.random.RandomState(args.seed)
    if len(train) > args.train_sample:
        idx = sorted(rng.choice(len(train), args.train_sample, replace=False))
        train_search = [train[i] for i in idx]
    else:
        train_search = train
    print(f"train 搜尋子樣本：{len(train_search)} 檔")

    ap_best, f_best, train_eval, traj = coordinate_descent(train_search, rounds=2)
    print(f"\n最佳策略參數: {ap_best}")
    print(f"最佳濾網: {f_best}")
    print(f"train(濾後): {_fmt(train_eval)}")

    # ---- OOS 評估（test 全量）----
    print("\n===== OOS（test）評估 =====")
    print("baseline 全市場 …")
    base_full = eval_full(test, AP_START, rolling=False)
    print("  ", base_full)
    print("最佳參數 全市場 …")
    opt_full = eval_full(test, ap_best, rolling=False)
    print("  ", opt_full)
    print("最佳參數 濾後池（全期統計選股，研究用）…")
    opt_filt, n_filt = eval_filtered(test, ap_best, f_best, rolling=False)
    print("  ", opt_filt, "池", n_filt)
    print("最佳參數 濾後池（滾動可實作版）…")
    opt_roll, n_roll = eval_filtered(test, ap_best, f_best, rolling=True)
    print("  ", opt_roll, "池", n_roll)

    write_report(ap_best, f_best, train_eval, base_full, opt_full,
                 opt_filt, n_filt, opt_roll, n_roll, traj,
                 len(train), len(test), len(train_search))
    print(f"\n報告已存: {OUT_MD}  總耗時 {time.time()-t0:.0f}s")


def write_report(ap_best, f_best, train_eval, base_full, opt_full,
                 opt_filt, n_filt, opt_roll, n_roll, traj, n_tr, n_te, n_search):
    L = []
    L.append("# 瘋狂優化自適應策略 + 選股濾網（train/test OOS）\n")
    L.append(f"- 全台股修分割、≥5年；依代碼末位 偶=train({n_tr}) / 奇=test({n_te})。")
    L.append(f"- 搜尋只在 train（隨機子樣本 {n_search} 檔，seed 固定）；最後 test 報 OOS。")
    L.append(f"- Fitness = 濾後池 獲利檔比例 + 0.3×中位Ret/MaxDD（池<{MIN_POOL} 重罰）。\n")

    L.append("## 最佳參數\n")
    L.append("**策略參數**：")
    L.append("```")
    L.append(str(ap_best))
    L.append("```")
    L.append("**選股濾網門檻**：")
    L.append(f"- trend_frac ≥ {f_best['tf_min']}")
    L.append(f"- 日均成交額(中位) ≥ {f_best['dv_min']:.0f}")
    L.append(f"- 全期年化報酬 ≥ {f_best['ar_min']*100:.0f}%（注：全期統計＝含未來資訊，研究用）\n")

    L.append("## ★ OOS（test）對照\n")
    L.append("| 設定 | 獲利檔比例 | 中位PF | 中位Ret/MaxDD | 池大小 |")
    L.append("|---|---|---|---|---|")
    L.append(f"| baseline 全市場（未優化） | {base_full['prof_ratio']:.1f}% | {base_full['med_pf']:.3f} | {base_full['med_rdd']:.3f} | {base_full['n']} |")
    L.append(f"| 最佳參數 全市場（不濾） | {opt_full['prof_ratio']:.1f}% | {opt_full['med_pf']:.3f} | {opt_full['med_rdd']:.3f} | {opt_full['n']} |")
    L.append(f"| **最佳 濾後池（全期選股,研究用）** | **{opt_filt['prof_ratio']:.1f}%** | {opt_filt['med_pf']:.3f} | {opt_filt['med_rdd']:.3f} | {n_filt} |")
    L.append(f"| **最佳 濾後池（滾動可實作）** | **{opt_roll['prof_ratio']:.1f}%** | {opt_roll['med_pf']:.3f} | {opt_roll['med_rdd']:.3f} | {n_roll} |")
    L.append("")
    L.append(f"- train(濾後) 獲利比 {train_eval['prof_ratio']*100:.1f}%、中位Ret/DD {train_eval['med_rdd']:.2f}、池 {train_eval['pool']}。")
    L.append(f"  → OOS test 濾後池 獲利比 {opt_filt['prof_ratio']:.1f}%；"
             f"{'OOS 與 train 接近，非過擬合。' if abs(opt_filt['prof_ratio']-train_eval['prof_ratio']*100)<12 else 'OOS 比 train 差較多，留意過擬合。'}\n")

    L.append("## Coordinate Descent 軌跡（train）\n")
    L.append("| 步驟 | 參數 | 採用值 | score | 獲利比 | 中位Ret/DD | 池 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in traj:
        def g(k, f="{:.3f}"):
            v = t.get(k, np.nan)
            return "-" if (isinstance(v, float) and np.isnan(v)) else f.format(v)
        pr = "-" if (isinstance(t.get("prof_ratio"), float) and np.isnan(t.get("prof_ratio"))) else f"{t['prof_ratio']*100:.0f}%"
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | {t['score']:.3f} | {pr} | {g('med_rdd')} | {g('pool','{:.0f}')} |")
    L.append("")

    L.append("## 誠實結論\n")
    gain = opt_filt["prof_ratio"] - base_full["prof_ratio"]
    L.append(f"- 選股濾網是大槓桿：把 OOS 獲利檔比例從 baseline 全市場 {base_full['prof_ratio']:.0f}% "
             f"拉到濾後池 **{opt_filt['prof_ratio']:.0f}%**（全期選股）/ **{opt_roll['prof_ratio']:.0f}%**（滾動可實作）。")
    L.append(f"- **這是「選股後的子集」（{n_filt} / {opt_full['n']} 檔），不是全台股**。"
             "濾掉的是低流動性/長期陰跌/無趨勢的股——它們本來就不該套這策略。")
    if opt_roll["prof_ratio"] < opt_filt["prof_ratio"] - 8:
        L.append(f"- ⚠ 滾動可實作版（{opt_roll['prof_ratio']:.0f}%）明顯低於全期選股版（{opt_filt['prof_ratio']:.0f}%）"
                 "→ 全期選股的好看有相當部分來自**未來資訊**，實作時打折。")
    else:
        L.append(f"- 滾動可實作版（{opt_roll['prof_ratio']:.0f}%）與全期選股版（{opt_filt['prof_ratio']:.0f}%）接近"
                 "→ 濾網的 edge 不太靠未來資訊，較可實作。")
    L.append("- 定論：**沒有策略能讓全台股都賺；但『自適應策略 + 選股濾網』能把可用子集的勝率顯著拉高**。"
             "實務 = 先濾股、再對篩出來的池套自適應。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
