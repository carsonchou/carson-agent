# -*- coding: utf-8 -*-
"""
tw_arena.py — 真實數據競技場（Python 當裁判，免 LLM 互評）

competition = 參數候選互比「真實回測」分數。裁判=Python，免費 compute。

兩組標的池分開優化（前面發現 0050 跟正2 要不同 trail 鬆緊）：
  A. 指數多空組（會雙向）：^TWII（大盤）+ 00632R（反1）。allow_short=True。
  B. 槓桿純多組（單向趨勢）：00631L（正2）、006208、0050。allow_short=False。

Fitness = 該組標的的「平均 Return/MaxDD」（已驗證這指標才對；不用會獎勵不交易的 PF/獲利比例），
         加最低活躍度護欄：平均每檔交易數 < MIN_AVG_TRADES 就線性重罰。

搜尋：coordinate descent，掃
  erThr, adxOn, minVotes, baseLen, chandMult, trailMidR, trailTightR, tp2R, peakArmK。

成本 tw_real；資料 yfinance period max。

輸出 twdata\arena_result.md：兩組最佳參數 + 每標的 淨利%/PF/交易數/Ret-DD（優化前 vs 後）。

執行：使用指定的 Python 3.9 解譯器執行本檔。
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

OUT_MD = os.path.join(tw_data.DATA_DIR, "arena_result_v2.md")
COST = "tw_real"
CAPITAL = 10000.0
# v2：護欄大幅拉高到 25，逼出能實戰、樣本夠的穩健參數。
# 9 筆交易的 PF 5.17 是統計幻象，跟「不交易假象」同病——逼 minVotes 回 2、每標的 ~25-40 筆才有信賴度。
MIN_AVG_TRADES = 25.0

# 兩組標的池
POOL_INDEX = ["^TWII", "00632R.TW"]      # 指數多空組（allow_short=True）
POOL_LEVER = ["00631L.TW", "006208.TW", "0050.TW"]  # 槓桿純多組（allow_short=False）

# 起點 = crypto 原生 v5 預設（乾淨基準，非被汙染的 minVotes=3）
START = dict(erThr=0.36, adxOn=25.0, minVotes=2, baseLen=10, chandMult=3.0,
             trailMidR=2.8, trailTightR=2.5, tp2R=4.5, peakArmK=2.5)

# 搜尋網格（coordinate descent 每參數獨立掃）
SWEEP = [
    ("minVotes",    [2, 3]),
    ("erThr",       [0.26, 0.30, 0.36, 0.42]),
    ("adxOn",       [22.0, 25.0, 28.0]),
    ("baseLen",     [7, 10, 14]),
    ("chandMult",   [2.5, 3.0, 3.5]),
    ("trailMidR",   [2.5, 2.8, 3.2]),
    ("trailTightR", [2.2, 2.5, 3.0, 3.5]),
    ("tp2R",        [3.5, 4.5, 6.0]),
    ("peakArmK",    [2.0, 2.5, 3.0]),
]


def make_params(overrides):
    p = strategy.Params()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def load_pool(symbols):
    out = []
    for t in symbols:
        df = tw_data.load_ohlcv(t, period="max", sleep=0.4)
        if df is not None and len(df) >= 500:
            out.append((t, df))
    return out


def backtest_one(df, overrides, allow_short):
    p = make_params(overrides)
    m, trades, _ = strategy.backtest(df, cost_model=COST, initial_capital=CAPITAL,
                                     p=p, allow_short=allow_short)
    return m


def evaluate(pool, overrides, allow_short):
    """Fitness = 平均 Return/MaxDD（含活躍度護欄）。回傳 dict + 每標的明細。"""
    retdds = []
    trades = []
    detail = []
    for t, df in pool:
        m = backtest_one(df, overrides, allow_short)
        rdd = m["return_over_maxdd"]
        if not np.isfinite(rdd):
            rdd = 5.0 if m["net_profit_pct"] > 0 else -1.0
        retdds.append(rdd)
        trades.append(m["n_trades"])
        detail.append((t, m))
    mean_retdd = float(np.mean(retdds)) if retdds else 0.0
    avg_trades = float(np.mean(trades)) if trades else 0.0
    min_trades = float(np.min(trades)) if trades else 0.0
    score = mean_retdd
    # v2 護欄：以「最弱標的的交易數」為準（任一標的 <25 就視為樣本不足）。
    # 罰則用 5.0 係數，遠大於 Ret/MaxDD 的量級（~3），確保低交易配置真的被淘汰、不只是扣一點。
    guard_ref = min(min_trades, avg_trades)
    if guard_ref < MIN_AVG_TRADES:
        score -= 5.0 * (1.0 - guard_ref / MIN_AVG_TRADES)
    return dict(score=score, mean_retdd=mean_retdd, avg_trades=avg_trades,
                min_trades=min_trades, detail=detail)


def _fmt(d):
    return (f"score={d['score']:.4f} meanRetDD={d['mean_retdd']:.3f} "
            f"avgTrades={d['avg_trades']:.1f} minTrades={d.get('min_trades',0):.0f}")


def coordinate_descent(pool, allow_short, rounds, label):
    current = dict(START)
    start = evaluate(pool, current, allow_short)
    print(f"\n[{label}] 起點 {current}")
    print(f"   {_fmt(start)}")
    best_score = start["score"]
    traj = [dict(step="起點", param="-", value="-",
                 **{k: start[k] for k in ("score", "mean_retdd", "avg_trades", "min_trades")})]

    for rnd in range(1, rounds + 1):
        print(f"  --- {label} 第 {rnd} 輪 ---")
        for name, values in SWEEP:
            cur_val = current[name]
            best_val = cur_val
            best_local = best_score
            best_m = None
            for v in values:
                if v == cur_val:
                    continue
                trial = dict(current); trial[name] = v
                t0 = time.time()
                r = evaluate(pool, trial, allow_short)
                dt = time.time() - t0
                flag = ""
                if r["score"] > best_local + 1e-9:
                    best_local = r["score"]; best_val = v; best_m = r; flag = "  <=="
                print(f"    {name}={v:<6} {_fmt(r)} ({dt:.0f}s){flag}")
            if best_val != cur_val and best_m is not None:
                current[name] = best_val
                best_score = best_local
                traj.append(dict(step=f"R{rnd}", param=name, value=best_val,
                                 score=best_m["score"], mean_retdd=best_m["mean_retdd"],
                                 avg_trades=best_m["avg_trades"], min_trades=best_m["min_trades"]))
                print(f"    -> {name} 採用 {best_val}（score {best_score:.4f}）")
            else:
                traj.append(dict(step=f"R{rnd}", param=name, value=f"{cur_val}(不變)",
                                 score=best_score, mean_retdd=np.nan, avg_trades=np.nan,
                                 min_trades=np.nan))
                print(f"    -> {name} 維持 {cur_val}")
    final = evaluate(pool, current, allow_short)
    return current, final, traj


def detail_table(L, pool, allow_short, base_over, best_over):
    """每標的：優化前(START) vs 後(best) 的 淨利%/PF/交易數/Ret-DD。"""
    L.append("| 標的 | 參數 | 淨利% | PF | 交易數 | MaxDD% | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|---|")
    for t, df in pool:
        for tag, ov in [("前(START)", base_over), ("**後(best)**", best_over)]:
            m = backtest_one(df, ov, allow_short)
            pf = "inf" if not np.isfinite(m["profit_factor"]) else f"{m['profit_factor']:.2f}"
            rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else f"{m['return_over_maxdd']:.2f}"
            L.append(f"| {t} | {tag} | {m['net_profit_pct']:.1f} | {pf} | "
                     f"{m['n_trades']} | {m['max_dd_pct']:.1f} | {rdd} |")
    L.append("")


def traj_table(L, traj):
    L.append("| 步驟 | 參數 | 採用值 | score | 平均Ret/DD | 平均交易數 | 最少交易數 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in traj:
        def g(k, f="{:.3f}"):
            v = t.get(k, np.nan)
            return "-" if (isinstance(v, float) and np.isnan(v)) else f.format(v)
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | {t['score']:.4f} | "
                 f"{g('mean_retdd')} | {g('avg_trades','{:.1f}')} | {g('min_trades','{:.0f}')} |")
    L.append("")


def param_table(L, keys):
    L.append("| 參數 | 起點(START) | 指數多空組 best | 槓桿純多組 best |")
    L.append("|---|---|---|---|")
    for k in keys:
        L.append(f"| {k} | {START[k]} | **{BEST_IDX[k]}** | **{BEST_LEV[k]}** |")
    L.append("")


BEST_IDX = {}
BEST_LEV = {}


def main():
    print("=" * 80)
    print("真實數據競技場 tw_arena（Python 裁判，免 LLM）")
    print("=" * 80)
    t0 = time.time()
    rounds = 2

    print("載入標的池…")
    pool_idx = load_pool(POOL_INDEX)
    pool_lev = load_pool(POOL_LEVER)
    print(f"  指數多空組: {[t for t,_ in pool_idx]}")
    print(f"  槓桿純多組: {[t for t,_ in pool_lev]}")

    print("\n##### A. 指數多空組（allow_short=True）#####")
    best_idx, final_idx, traj_idx = coordinate_descent(pool_idx, True, rounds, "指數多空")
    print("\n##### B. 槓桿純多組（allow_short=False）#####")
    best_lev, final_lev, traj_lev = coordinate_descent(pool_lev, False, rounds, "槓桿純多")

    global BEST_IDX, BEST_LEV
    BEST_IDX, BEST_LEV = best_idx, best_lev

    # 報告
    L = []
    L.append("# 真實數據競技場結果 v2 — 高活躍度護欄（逼出能實戰的穩健參數）\n")
    L.append("> v2 修正：把活躍度護欄從 12 拉到 **25**，淘汰「9 筆交易 PF 5.17」這種統計幻象。")
    L.append("> 護欄以「最弱標的的交易數」為準（任一標的 <25 即視為樣本不足、重罰）。\n")
    L.append(f"- 裁判：Python 真實回測（免 LLM 互評）；成本 `{COST}`；資料 yfinance period max。")
    L.append(f"- Fitness = 該組「平均 Return/MaxDD」− 護欄罰則（最弱標的交易數 < {MIN_AVG_TRADES:.0f} 時重罰）。")
    L.append("- 兩組分開優化（指數會雙向→多空；槓桿單向→純多）。\n")

    L.append("## 兩組最佳參數\n")
    param_table(L, list(START.keys()))
    L.append(f"- 指數多空組 best score（含護欄）：**{final_idx['score']:.4f}**"
             f"（平均交易數 {final_idx['avg_trades']:.1f}、最少 {final_idx['min_trades']:.0f}）")
    L.append(f"- 槓桿純多組 best score：**{final_lev['score']:.4f}**"
             f"（平均交易數 {final_lev['avg_trades']:.1f}、最少 {final_lev['min_trades']:.0f}）\n")

    L.append("## A. 指數多空組（allow_short=True）— 每標的 優化前 vs 後\n")
    detail_table(L, pool_idx, True, START, best_idx)
    L.append("### 軌跡\n")
    traj_table(L, traj_idx)

    L.append("## B. 槓桿純多組（allow_short=False）— 每標的 優化前 vs 後\n")
    detail_table(L, pool_lev, False, START, best_lev)
    L.append("### 軌跡\n")
    traj_table(L, traj_lev)

    L.append("## 重點檢核\n")
    # 正2 PF
    lev_best = {t: backtest_one(df, best_lev, False) for t, df in pool_lev}
    p2 = lev_best.get("00631L.TW")
    if p2:
        pfv = "inf" if not np.isfinite(p2["profit_factor"]) else f"{p2['profit_factor']:.2f}"
        L.append(f"- **正2(00631L) 純多 best**：淨利 {p2['net_profit_pct']:.1f}%、PF {pfv}、"
                 f"交易 {p2['n_trades']}、Ret/MaxDD {p2['return_over_maxdd']:.2f}。")
    idx_best = {t: backtest_one(df, best_idx, True) for t, df in pool_idx}
    tw = idx_best.get("^TWII")
    if tw:
        L.append(f"- **指數多空(^TWII) best**：淨利 {tw['net_profit_pct']:.1f}%、"
                 f"Ret/MaxDD {tw['return_over_maxdd']:.2f}、交易 {tw['n_trades']}。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("\n" + "=" * 80)
    print(f"指數多空 best: {best_idx}")
    print(f"槓桿純多 best: {best_lev}")
    print(f"報告已存: {OUT_MD}  總耗時 {time.time()-t0:.0f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
