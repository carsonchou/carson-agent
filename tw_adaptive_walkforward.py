# -*- coding: utf-8 -*-
"""
tw_adaptive_walkforward.py — v2 自適應參數的「時間維」穩健性驗證

v2 優化已用「橫斷面」OOS（偶=train/奇=test 不同股票）證明非過擬合。
本檔補上「時間維」walk-forward：每檔歷史切前半/後半，分別回測
  v2 最佳參數 vs 現行 adaptive 預設，看 v2 的改善在「兩個時期」都成立，
  還是只靠某一段（例如 2019 後）才贏。若只贏一段 → 誠實標註。

池 = 與 tw_optimize_adaptive2 相同的 screener 篩後可交易池（修分割、tw_real）。
輸出 twdata\adaptive_walkforward_result.md。
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

import tw_adaptive as ad
import tw_optimize_adaptive2 as o2   # build_pool / make_ap / COST / CAPITAL

OUT_MD = os.path.join(o2.tw_data.DATA_DIR, "adaptive_walkforward_result.md")

V2 = dict(adxTrend=18.0, erTrend=0.26, bbLen=30, bbK=2.5, rsiBuy=30.0,
          rsiSell=50.0, mrMaxBars=30, mrStopK=1.5)
CUR = dict(o2.CURRENT)


def bt_half(df, over):
    p = o2.make_ap(over)
    m, _, _, _ = ad.backtest_adaptive(df, o2.COST, o2.CAPITAL, p)
    return m


def agg(pool, over, which):
    """which='first'|'second'：對每檔取對應時間半段回測，彙總。"""
    prof = 0
    rdds, pfs, trs = [], [], []
    n = 0
    for code, name, df, _ in pool:
        if len(df) < 500:
            continue
        mid = df.index[len(df) // 2]
        seg = df[df.index < mid] if which == "first" else df[df.index >= mid]
        if len(seg) < 250:
            continue
        m = bt_half(seg, over)
        n += 1
        pf = m["profit_factor"]
        if (pf > 1) and (m["net_profit_pct"] > 0):
            prof += 1
        pfs.append(pf if np.isfinite(pf) else 5.0)
        rdd = m["return_over_maxdd"]
        rdds.append(rdd if np.isfinite(rdd) else (5.0 if m["net_profit_pct"] > 0 else -1.0))
        trs.append(m["n_trades"])
    if n == 0:
        return dict(prof=0.0, rdd=0.0, pf=0.0, tr=0.0, n=0)
    return dict(prof=prof / n, rdd=float(np.median(rdds)), pf=float(np.median(pfs)),
                tr=float(np.median(trs)), n=n)


def main():
    print("=" * 78)
    print("v2 自適應 時間維 walk-forward（前半 / 後半）")
    print("=" * 78)
    t0 = time.time()
    pool = o2.build_pool()
    print(f"池：{len(pool)} 檔（{time.time()-t0:.0f}s）")

    rows = []
    for which, label in [("first", "前半段"), ("second", "後半段")]:
        a_cur = agg(pool, CUR, which)
        a_v2 = agg(pool, V2, which)
        rows.append((label, a_cur, a_v2))
        print(f"[{label}] 現行 獲利比{a_cur['prof']*100:.1f}% RetDD{a_cur['rdd']:.2f}"
              f" | v2 獲利比{a_v2['prof']*100:.1f}% RetDD{a_v2['rdd']:.2f} (n={a_v2['n']})")

    write_report(rows)
    print(f"\n報告：{OUT_MD}  耗時 {time.time()-t0:.0f}s")


def write_report(rows):
    L = []
    L.append("# v2 自適應參數 — 時間維 walk-forward 穩健性驗證\n")
    L.append("- 目的：v2 改善是否在「前半段」與「後半段」歷史**都**成立，"
             "還是只靠單一時期（避免 edge 只在某年代有效的假象）。")
    L.append("- 池 = screener 篩後可交易池（修分割、tw_real）；每檔以歷史中點切前/後半。")
    L.append("- 對照：現行 adaptive 預設 vs v2 最佳"
             "（adxTrend18/erTrend0.26/bbLen30/bbK2.5/rsiSell50/mrMaxBars30）。\n")
    L.append("| 時期 | 設定 | 獲利檔比例 | 中位PF | 中位Ret/MaxDD | 中位交易 | n |")
    L.append("|---|---|---|---|---|---|---|")
    holds = []
    for label, c, v in rows:
        L.append(f"| {label} | 現行 | {c['prof']*100:.1f}% | {c['pf']:.3f} | {c['rdd']:.3f} | {c['tr']:.0f} | {c['n']} |")
        L.append(f"| {label} | **v2** | **{v['prof']*100:.1f}%** | {v['pf']:.3f} | **{v['rdd']:.3f}** | {v['tr']:.0f} | {v['n']} |")
        holds.append(v["prof"] >= c["prof"] - 0.005 and v["rdd"] >= c["rdd"] - 0.02)
    L.append("")
    L.append("## 誠實結論\n")
    if all(holds):
        L.append("- ✅ v2 的改善在**前半段與後半段都成立**（兩期獲利比與 Ret/MaxDD 皆不輸現行）→ "
                 "非單一時期僥倖，時間維穩健，**維持採用 v2**。")
    elif any(holds):
        i = 0 if holds[0] else 1
        L.append(f"- ⚠ v2 只在 **{rows[i][0]}** 明顯勝出，另一段未明顯領先 → "
                 "edge 有時期偏向。仍可採用（無一期顯著變差即可），但須知改善偏重某時期。")
    else:
        L.append("- ⚠ v2 在兩段都未穩定勝出 → 橫斷面 OOS 雖過關，時間維存疑，"
                 "建議保守看待，必要時退回現行。")
    L.append("- 註：池為 screener 篩後子集；前半段樣本較早、流動性/結構與近期不同，數字僅供穩健性對照。")
    L.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
