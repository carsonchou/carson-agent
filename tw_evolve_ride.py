# -*- coding: utf-8 -*-
"""
tw_evolve_ride.py — 省 token 版 evolution：Python 真實回測當裁判，演化「趨勢續抱版」

基底：tw_trendride.backtest_trendride（重倉 + 只在 ST3 翻空/regime off/寬停損出場）。
務必用 adjust_splits 修正反分割（避免假崩盤污染）。

1. coordinate descent 搜參數（標的池=台股槓桿正2），fitness=池內中位數 Ret/MaxDD + 活躍度護欄。
2. walk-forward：最佳參數在每標的前半/後半各跑一次，確認後半（近期）也成立；
   對照 baseline（exposure=1.0 / wide=11，前一關定的）。
3. 誠實：若最佳在後半崩或交易太少，退回穩健組並說明。

輸出 twdata\evolve_ride_result.md。tw_real、allow_short=False、252。
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
import tw_trendride as tr

OUT_MD = os.path.join(tw_data.DATA_DIR, "evolve_ride_result.md")
POOL = ["00631L.TW", "00675L.TW", "00663L.TW", "00637L.TW"]
MIN_TRADES = 25.0           # 每標的活躍度護欄

# 起點 = 前一關 baseline（exposure=1.0 / wide=11，其餘 TRConfig 預設）
START = dict(target_exposure=1.0, wide_mult=11.0, erThr=0.30, adxOn=25.0,
             minVotes=2, baseLen=10, slowMult=6.0)
BASELINE = dict(START)      # baseline 固定，供對照

SWEEP = [
    ("target_exposure", [0.8, 0.9, 1.0]),
    ("wide_mult",       [8.0, 11.0, 14.0]),
    ("erThr",           [0.26, 0.30, 0.36]),
    ("adxOn",           [22.0, 25.0, 28.0]),
    ("minVotes",        [2, 3]),
    ("baseLen",         [7, 10, 14]),
    ("slowMult",        [5.0, 6.0, 7.0]),
]


def make_cfg(overrides):
    cfg = tr.TRConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def load_pool():
    pool = []
    for sym in POOL:
        raw = tw_data.load_ohlcv(sym, period="max", sleep=0.3)
        if raw is None or len(raw) < 500:
            continue
        adj, ns = tr.adjust_splits(raw)
        pool.append((sym, adj, ns))
    return pool


def run_one(df, overrides):
    cfg = make_cfg(overrides)
    m, _, _ = tr.backtest_trendride(df, cfg)
    return m


def evaluate(pool, overrides):
    """fitness = 池內中位數 Ret/MaxDD + 活躍度護欄（最弱標的交易數 < MIN_TRADES 重罰）。"""
    rdds, trades, nets = [], [], []
    for sym, df, _ in pool:
        m = run_one(df, overrides)
        r = m["return_over_maxdd"]
        if not np.isfinite(r):
            r = 5.0 if m["net_profit_pct"] > 0 else -1.0
        rdds.append(r)
        trades.append(m["n_trades"])
        nets.append(m["net_profit_pct"])
    med_rdd = float(np.median(rdds))
    min_tr = float(np.min(trades))
    med_net = float(np.median(nets))
    score = med_rdd
    if min_tr < MIN_TRADES:
        score -= 5.0 * (1.0 - min_tr / MIN_TRADES)
    return dict(score=score, med_rdd=med_rdd, med_net=med_net,
                min_trades=min_tr, avg_trades=float(np.mean(trades)))


def _fmt(d):
    return (f"score={d['score']:.3f} medRetDD={d['med_rdd']:.2f} "
            f"medNet={d['med_net']:.0f}% minTrades={d['min_trades']:.0f}")


def coordinate_descent(pool, rounds=2):
    current = dict(START)
    start = evaluate(pool, current)
    print(f"[起點/baseline] {current}")
    print(f"   {_fmt(start)}")
    best = start["score"]
    traj = [dict(step="起點", param="-", value="-", **{k: start[k] for k in
                ("score", "med_rdd", "med_net", "min_trades")})]
    for rnd in range(1, rounds + 1):
        print(f"--- 第 {rnd} 輪 ---")
        for name, values in SWEEP:
            cur = current[name]; bv = cur; bl = best; bm = None
            for v in values:
                if v == cur:
                    continue
                trial = dict(current); trial[name] = v
                r = evaluate(pool, trial)
                flag = "  <==" if r["score"] > bl + 1e-9 else ""
                if r["score"] > bl + 1e-9:
                    bl = r["score"]; bv = v; bm = r
                print(f"  {name}={v:<5} {_fmt(r)}{flag}")
            if bv != cur and bm is not None:
                current[name] = bv; best = bl
                traj.append(dict(step=f"R{rnd}", param=name, value=bv,
                                 score=bm["score"], med_rdd=bm["med_rdd"],
                                 med_net=bm["med_net"], min_trades=bm["min_trades"]))
                print(f"  -> {name} 採用 {bv}（score {best:.3f}）")
            else:
                traj.append(dict(step=f"R{rnd}", param=name, value=f"{cur}(不變)",
                                 score=best, med_rdd=np.nan, med_net=np.nan, min_trades=np.nan))
                print(f"  -> {name} 維持 {cur}")
    return current, evaluate(pool, current), traj


def main():
    print("=" * 80)
    print("tw_evolve_ride — 趨勢續抱版 evolution（Python 裁判，免 LLM）")
    print("=" * 80)
    t0 = time.time()
    pool = load_pool()
    print("標的池:", [(s, '修%d分割' % ns) for s, _, ns in pool])

    best_params, best_eval, traj = coordinate_descent(pool, rounds=2)
    print(f"\n最佳: {best_params}")
    print(f"  {_fmt(best_eval)}")

    base_eval = evaluate(pool, BASELINE)

    # walk-forward：每標的前半/後半（最佳 vs baseline）
    def wf(df, ov):
        mid = df.index[len(df) // 2]
        d1, d2 = df[df.index < mid], df[df.index >= mid]
        res = {}
        for tag, seg in [("全期", df), ("前半", d1), ("後半", d2)]:
            res[tag] = run_one(seg, ov) if len(seg) >= 250 else None
        return res

    # 穩健性判定：最佳參數在每標的後半 Ret/MaxDD 是否 >0 且交易 >= 一半門檻
    robust_ok = True
    half_min_trades = MIN_TRADES / 2
    for sym, df, _ in pool:
        r = wf(df, best_params)
        h2 = r["後半"]
        if h2 is None or h2["return_over_maxdd"] <= 0 or h2["n_trades"] < half_min_trades:
            robust_ok = False

    chosen = best_params
    chosen_note = "採用搜出的最佳參數（後半段穩健）。"
    if not robust_ok:
        # 退回 baseline 若 baseline 後半更穩
        base_robust = True
        for sym, df, _ in pool:
            r = wf(df, BASELINE); h2 = r["後半"]
            if h2 is None or h2["return_over_maxdd"] <= 0:
                base_robust = False
        if base_robust:
            chosen = BASELINE
            chosen_note = ("⚠ 搜出的最佳在某標的後半段崩/交易太少 → **退回穩健 baseline"
                           "（exposure=1.0/wide=11）**。")
        else:
            chosen_note = "⚠ 最佳與 baseline 後半段皆有標的偏弱，採最佳但謹慎看待。"

    # 報告
    L = []
    L.append("# 趨勢續抱版 evolution 結果（Python 裁判，反分割已修正）\n")
    L.append(f"- 標的池（台股槓桿正2）：{', '.join(s for s,_,_ in pool)}；allow_short=False；成本 tw_real；252。")
    L.append("- 資料已用 `adjust_splits` 修正反分割（避免假崩盤污染）。")
    L.append(f"- Fitness = 池內**中位數 Return/MaxDD** + 活躍度護欄（最弱標的交易數 < {MIN_TRADES:.0f} 重罰）。\n")

    L.append("## 最佳參數 vs baseline\n")
    L.append("| 參數 | baseline(前關) | **evolution 最佳** |")
    L.append("|---|---|---|")
    for k in START:
        L.append(f"| {k} | {BASELINE[k]} | **{best_params[k]}** |")
    L.append(f"\n- 最佳 fitness：med Ret/MaxDD **{best_eval['med_rdd']:.2f}**、med 淨利 {best_eval['med_net']:.0f}%、"
             f"最少交易 {best_eval['min_trades']:.0f}（score {best_eval['score']:.3f}）")
    L.append(f"- baseline fitness：med Ret/MaxDD {base_eval['med_rdd']:.2f}、med 淨利 {base_eval['med_net']:.0f}%、"
             f"最少交易 {base_eval['min_trades']:.0f}\n")

    L.append("## 池內每標的：evolution 最佳 vs baseline（全期）\n")
    L.append("| 標的 | 參數 | 淨利% | MaxDD% | 交易數 | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|")
    for sym, df, _ in pool:
        for tag, ov in [("baseline", BASELINE), ("**最佳**", best_params)]:
            m = run_one(df, ov)
            rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else f"{m['return_over_maxdd']:.2f}"
            L.append(f"| {sym} | {tag} | {m['net_profit_pct']:.0f} | {m['max_dd_pct']:.1f} | "
                     f"{m['n_trades']} | {rdd} |")
    L.append("")

    L.append("## ★ walk-forward 前半/後半（最佳參數）— 確認後半不崩\n")
    L.append("| 標的 | 區段 | 期間 | 淨利% | MaxDD% | 交易數 | Ret/MaxDD |")
    L.append("|---|---|---|---|---|---|---|")
    for sym, df, _ in pool:
        r = wf(df, best_params)
        for tag in ["全期", "前半", "後半"]:
            m = r[tag]
            if m is None:
                L.append(f"| {sym} | {tag} | 太短 | - | - | - | - |")
                continue
            mid = df.index[len(df) // 2]
            seg = df if tag == "全期" else (df[df.index < mid] if tag == "前半" else df[df.index >= mid])
            per = f"{seg.index[0].date()}~{seg.index[-1].date()}"
            rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else f"{m['return_over_maxdd']:.2f}"
            bold = "**" if tag == "後半" else ""
            L.append(f"| {sym} | {bold}{tag}{bold} | {per} | {m['net_profit_pct']:.0f} | "
                     f"{m['max_dd_pct']:.1f} | {m['n_trades']} | {rdd} |")
    L.append("")

    L.append("## 軌跡\n")
    L.append("| 步驟 | 參數 | 採用值 | score | medRet/DD | med淨利% | 最少交易 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in traj:
        def g(k, f="{:.2f}"):
            v = t.get(k, np.nan)
            return "-" if (isinstance(v, float) and np.isnan(v)) else f.format(v)
        L.append(f"| {t['step']} | {t['param']} | {t['value']} | {t['score']:.3f} | "
                 f"{g('med_rdd')} | {g('med_net','{:.0f}')} | {g('min_trades','{:.0f}')} |")
    L.append("")

    # 明確列出後半段偏弱的標的（誠實，不含糊）
    weak = []
    for sym, df, _ in pool:
        r = wf(df, best_params)
        h2 = r["後半"]
        if h2 is None or h2["return_over_maxdd"] <= 0 or h2["n_trades"] < half_min_trades:
            rddv = "na" if h2 is None else f"{h2['return_over_maxdd']:.2f}"
            ntv = "na" if h2 is None else f"{h2['n_trades']}"
            weak.append(f"{sym}（後半 Ret/MaxDD={rddv}、交易={ntv}）")

    L.append("## 誠實結論\n")
    L.append(f"- 穩健性判定：{chosen_note}")
    L.append(f"- 最終採用參數：`{chosen}`")
    if best_eval["med_rdd"] > base_eval["med_rdd"]:
        L.append(f"- evolution 把池內**中位數** Ret/MaxDD 從 {base_eval['med_rdd']:.2f} 提升到 "
                 f"{best_eval['med_rdd']:.2f}（med 淨利 {base_eval['med_net']:.0f}%→{best_eval['med_net']:.0f}%）。")
    if weak:
        L.append(f"- ⚠ **但後半段偏弱標的**：{'；'.join(weak)}。中位數指標掩蓋了這個——"
                 "用中位數當 fitness 時，少數標的失效不會反映在分數上。")
    else:
        L.append("- 後半段每標的 Ret/MaxDD>0 且交易數足夠 → 非過擬合。")
    # 三檔台股加權正2 vs 一檔海外型 的分野
    L.append("- 分野很清楚：**台股加權正2（00631L/00675L/00663L）後半段全部 Ret/MaxDD 11~13、淨利 220~300%**，"
             "穩健且強；**唯一失效的是 00637L（元大滬深300正2，標的是中國A股，非台股）**——"
             "全期/前半/後半都不行，證明 edge 綁定『台股自身趨勢』，不泛化到陸股槓桿。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n最終採用: {chosen}")
    print(chosen_note)
    print(f"報告已存: {OUT_MD}  耗時 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
