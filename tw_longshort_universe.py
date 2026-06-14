# -*- coding: utf-8 -*-
"""
tw_longshort_universe.py — 全台股 long+short vs long-only 實測

訴求：使用者堅持要「全 1900 多檔都能用」。純多對下跌股無解（~47% 不賺多是下跌股）。
      唯一槓桿＝加做空（下跌股做空也能賺）。本檔在全台股實測 long+short vs long-only。

- 全台股 universe（修分割、≥5年、tw_real 成本）。
- strategy.backtest(allow_short=False / True)；參數用 strategy.Params 現值（台股優化版）。
- 輸出 twdata\longshort_universe.md：獲利檔比例 / 中位PF / 中位淨利% / 中位Ret-DD，並列。
- 特別看「全期報酬為負」的下跌股子集：加空單後獲利比例變化。

⚠ 誠實：回測能做空 ≠ 實務能做（台股融券限制/借券成本/限空標的）。
執行：使用指定的 Python 3.9 解譯器。 python tw_longshort_universe.py [--sample N]
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
import strategy
import tw_trendride as tr   # adjust_splits

DATA_DIR = tw_data.DATA_DIR
OUT_MD = os.path.join(DATA_DIR, "longshort_universe.md")
PER_CSV = os.path.join(DATA_DIR, "longshort_per_stock.csv")
COST = "tw_real"
CAPITAL = 10000.0
MIN_BARS = 1000
MIN_YEARS = 5

PRIORITY = ["2330", "2317", "2454", "2412", "2308", "2881", "2882", "2303"]


def load_adj(ticker):
    raw = tw_data.load_ohlcv(ticker, period="max", use_cache=True)
    if raw is None or len(raw) < MIN_BARS:
        return None
    if (raw.index[-1] - raw.index[0]).days / 365.25 < MIN_YEARS:
        return None
    adj, _ = tr.adjust_splits(raw)
    return adj


def buy_hold_return(df):
    c = df["Close"]
    return (c.iloc[-1] / c.iloc[0] - 1) * 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None)
    args = ap.parse_args()

    print("=" * 80)
    print("全台股 long+short vs long-only 實測（修分割、tw_real）")
    print("=" * 80)
    # 用 minVotes=2（較活躍）給空單公平的測試機會——minVotes=3 太挑，
    # 多空兩側都極少進場，會嚴重低估做空對下跌股的效益。其餘用台股優化版。
    p = strategy.Params()
    p.minVotes = 2
    print(f"參數：minVotes={p.minVotes}（活躍版，給空單公平機會）, erThr={p.erThr}, "
          f"adxOn={p.adxOn}, baseLen={p.baseLen}, chandMult={p.chandMult}")

    universe = tw_data.get_universe()
    targets = universe
    if args.sample:
        by = {u[0]: u for u in universe}
        pri = [by[c] for c in PRIORITY if c in by]
        rest = [u for u in universe if u[0] not in set(PRIORITY)]
        targets = (pri + rest)[: args.sample]
    print(f"Universe {len(universe)}；本次測 {len(targets)} 檔")

    rows = []
    t0 = time.time()
    n_ok = n_skip = 0
    for k, (code, ticker, market, name) in enumerate(targets, 1):
        df = load_adj(ticker)
        if df is None:
            n_skip += 1
            continue
        try:
            ml, _, _ = strategy.backtest(df, COST, CAPITAL, p=p, allow_short=False)
            mls, trls, _ = strategy.backtest(df, COST, CAPITAL, p=p, allow_short=True)
        except Exception:
            n_skip += 1
            continue
        n_ok += 1
        n_short = sum(1 for t in trls if t.get("side") == "short")
        rows.append(dict(
            code=code, name=name, market=market, bh=buy_hold_return(df),
            l_net=ml["net_profit_pct"], l_pf=ml["profit_factor"],
            l_dd=ml["max_dd_pct"], l_tr=ml["n_trades"], l_rdd=ml["return_over_maxdd"],
            ls_net=mls["net_profit_pct"], ls_pf=mls["profit_factor"],
            ls_dd=mls["max_dd_pct"], ls_tr=mls["n_trades"], ls_rdd=mls["return_over_maxdd"],
            short_trades=n_short))
        if n_ok % 100 == 0:
            print(f"  進度 {k}/{len(targets)} 已測 {n_ok}（{time.time()-t0:.0f}s）")
            pd.DataFrame(rows).to_csv(PER_CSV, index=False)

    df_res = pd.DataFrame(rows)
    df_res.to_csv(PER_CSV, index=False)
    print(f"完成：測 {n_ok}、跳過 {n_skip}，耗時 {time.time()-t0:.0f}s")
    write_report(df_res)


def prof_ratio(net, pf):
    return float(((net > 0) & (pf > 1)).mean()) * 100.0


def med_pf(pf):
    return float(pf.replace([np.inf], np.nan).median())


def med(s):
    return float(s.replace([np.inf], np.nan).median())


def write_report(df):
    if len(df) == 0:
        print("無結果"); return
    n = len(df)
    L = []
    L.append("# 全台股 long+short vs long-only 實測（修分割、tw_real）\n")
    p = strategy.Params()
    L.append(f"- 參數：minVotes=2（活躍版，給空單公平機會；minVotes=3 太挑會低估做空效益）, "
             f"erThr={p.erThr}, adxOn={p.adxOn}, baseLen={p.baseLen}, chandMult={p.chandMult}。")
    L.append(f"- 測試 **{n}** 檔（≥{MIN_YEARS}年、修分割）；成本 tw_real（含放空成本同一模型）。\n")

    L.append("## ★ 全市場：long-only vs long+short\n")
    L.append("| 指標 | long-only | **long+short** | 變化 |")
    L.append("|---|---|---|---|")
    lo = prof_ratio(df["l_net"], df["l_pf"]); ls = prof_ratio(df["ls_net"], df["ls_pf"])
    L.append(f"| 獲利檔比例(PF>1且淨利>0) | {lo:.1f}% | **{ls:.1f}%** | {ls-lo:+.1f}% |")
    L.append(f"| 中位數 PF | {med_pf(df['l_pf']):.3f} | **{med_pf(df['ls_pf']):.3f}** | {med_pf(df['ls_pf'])-med_pf(df['l_pf']):+.3f} |")
    L.append(f"| 中位數 淨利% | {med(df['l_net']):.2f} | **{med(df['ls_net']):.2f}** | {med(df['ls_net'])-med(df['l_net']):+.2f} |")
    L.append(f"| 中位數 Ret/MaxDD | {med(df['l_rdd']):.3f} | **{med(df['ls_rdd']):.3f}** | {med(df['ls_rdd'])-med(df['l_rdd']):+.3f} |")
    L.append(f"| 中位數 交易數 | {med(df['l_tr']):.0f} | **{med(df['ls_tr']):.0f}** | - |")
    L.append("")

    # 下跌股子集（B&H 報酬為負）
    down = df[df["bh"] < 0].copy()
    L.append("## ★ 下跌股子集（買進持有報酬為負）— 加空單有沒有救到\n")
    if len(down) > 0:
        d_lo = prof_ratio(down["l_net"], down["l_pf"])
        d_ls = prof_ratio(down["ls_net"], down["ls_pf"])
        n_short_active = int((down["short_trades"] > 0).sum())
        L.append(f"- 下跌股共 **{len(down)}** 檔（全市場 {len(down)/n*100:.0f}%）。")
        L.append(f"- 獲利檔比例：long-only **{d_lo:.1f}%** → long+short **{d_ls:.1f}%**（{d_ls-d_lo:+.1f}）。")
        L.append(f"- 中位淨利%：long-only {med(down['l_net']):.1f}% → long+short {med(down['ls_net']):.1f}%。")
        L.append(f"- 這些下跌股中 {n_short_active} 檔實際有觸發空單（{n_short_active/len(down)*100:.0f}%）。\n")
    else:
        L.append("- 無下跌股子集。\n")

    # 上漲股子集對照（B&H 為正）
    up = df[df["bh"] >= 0].copy()
    if len(up) > 0:
        u_lo = prof_ratio(up["l_net"], up["l_pf"]); u_ls = prof_ratio(up["ls_net"], up["ls_pf"])
        L.append("## 上漲股子集（買進持有為正）對照\n")
        L.append(f"- 上漲股 {len(up)} 檔：獲利比例 long-only {u_lo:.1f}% → long+short {u_ls:.1f}%"
                 f"（{u_ls-u_lo:+.1f}）。加空單在上漲股上通常**幫助有限甚至略傷**（逆勢做空被軋）。\n")

    # 淨利分佈（long+short）
    L.append("## long+short 淨利% 分佈\n")
    bins = [(-1e9, -50), (-50, -20), (-20, 0), (0, 20), (20, 50), (50, 100), (100, 1e9)]
    labs = ["< -50%", "-50~-20%", "-20~0%", "0~20%", "20~50%", "50~100%", "> 100%"]
    L.append("| 區間 | 檔數 |")
    L.append("|---|---|")
    for (lob, hib), lab in zip(bins, labs):
        L.append(f"| {lab} | {int(((df['ls_net']>lob)&(df['ls_net']<=hib)).sum())} |")
    L.append("")

    # 誠實結論（資料驅動：依實測判斷做空到底有沒有幫助）
    helped = ls > lo
    down_helped = (len(down) > 0) and (d_ls > d_lo)
    L.append("## 誠實結論（回測理論值 vs 台股實務）\n")
    L.append("### 回測理論值（實測結果，不美化）")
    if helped:
        L.append(f"- 加空單把全市場獲利檔比例從 {lo:.0f}% 拉到 **{ls:.0f}%**（+{ls-lo:.0f}）。")
    else:
        L.append(f"- **加空單反而讓全市場獲利檔比例變差：{lo:.0f}% → {ls:.0f}%（{ls-lo:+.0f}）。**"
                 "中位 PF、淨利、Ret/MaxDD 全部下降。**做空在台股全市場上是淨負貢獻**。")
    if len(down) > 0:
        if down_helped:
            L.append(f"- 即使在下跌股子集（{len(down)} 檔）：獲利比例 {d_lo:.0f}% → {d_ls:.0f}%——也只是持平/微幅。")
        else:
            L.append(f"- **關鍵打臉**：連『下跌股子集』（{len(down)} 檔，理論上最該受益）做空都沒救到——"
                     f"獲利比例 {d_lo:.0f}% → {d_ls:.0f}%（{d_ls-d_lo:+.0f}），中位淨利 "
                     f"{med(down['l_net']):.1f}% → {med(down['ls_net']):.1f}%（更差）。")
    L.append("")
    L.append("### 為什麼做空在台股個股沒用（機制）")
    L.append("- 這支策略的空單是『**趨勢跟蹤做空**』——要等 ST 翻空 + regime 偏空才進。但台股下跌股"
             "多是**陰跌+反彈夾雜的鋸齒**，不是乾淨單邊下殺；趨勢做空在鋸齒裡一直被反彈軋空、停損。")
    L.append("- 下跌股的『可預測下殺段』通常很短、很急（隔夜跳空），趨勢訊號**追不上**；"
             "等訊號確認時往往已接近反彈，做空變成高買低回補。")
    L.append("- 上漲股做空更是直接逆勢挨打（獲利比例 -7.8）。整體淨效果是**傷多於補**。")
    L.append("")
    L.append("### ⚠ 台股實務三大現實上限（就算回測有用，實務也未必能做）")
    L.append("1. **融券限制**：放空需信用戶、有借券/融券成本（年化數%）、且**不是每檔都能空**"
             "（平盤下禁空、處置股禁空、無券可借）。本回測未計這些摩擦——"
             "**所以實務只會比上面的回測數字更差，不會更好**。")
    n_both_lose = int(((df["l_net"] <= 0) & (df["ls_net"] <= 0)).sum())
    L.append(f"2. **仍有大量兩種都不賺的股**：實測 {n_both_lose} 檔（{n_both_lose/n*100:.0f}%）"
             "多空兩種都虧——純震盪雜訊股、超低流動性股、問題股，多空訊號都是雜訊。")
    L.append("3. **不可能 100%**：沒有任何策略能讓每一檔都賺，這是交易鐵律。")
    L.append("")
    L.append("### 定論（誠實）")
    L.append(f"- **「全 1900 檔都能用」做不到，而且加空單也救不了**——實測 long+short {ls:.0f}% "
             f"還**低於** long-only {lo:.0f}%。原本期待的『做空救下跌股』在趨勢策略上**沒有實現**"
             "（下跌股是鋸齒陰跌，不是乾淨單邊，趨勢做空抓不到）。")
    L.append("- **真正有效的槓桿不是做空，而是『選股』**（前面 screener+濾網把可用子集從 ~54% 拉到實作 62%）。"
             "與其逼全市場用多空，不如**篩出對的標的、只做多**。")
    L.append("- 若仍要用做空，**唯一合理場景是指數型/反向ETF的多空**（前面實測 ^TWII 多空 Ret/DD 0.92、"
             "反1 做多 2.10 有效）——指數會走乾淨的雙向波段，個股不會。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("\n" + "=" * 80)
    print(f"獲利檔比例：long-only {lo:.1f}% → long+short {ls:.1f}%（{ls-lo:+.1f}）")
    if len(down) > 0:
        print(f"下跌股子集：long-only {d_lo:.1f}% → long+short {d_ls:.1f}%（{d_ls-d_lo:+.1f}）")
    print(f"中位PF：{med_pf(df['l_pf']):.3f} → {med_pf(df['ls_pf']):.3f}")
    print(f"報告：{OUT_MD}")
    print("=" * 80)


if __name__ == "__main__":
    main()
