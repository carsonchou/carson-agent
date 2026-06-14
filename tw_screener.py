# -*- coding: utf-8 -*-
"""
tw_screener.py — 台股篩選器：輸出當下值得套自適應策略的可交易池

用「滾動、不看未來」的特徵（截至最新一日、只用歷史）篩股：
  - trend_frac（近 LOOKBACK 年 regime 偏多/有趨勢的佔比）≥ --trend（預設 0.25）
  - 近 LOOKBACK 年年化報酬 ≥ --min-ret（預設 0，排除長期陰跌）
  - 近 60 日均成交額（中位）≥ --min-turnover（預設 2000 萬，過濾低流動性雜訊）

全台股 universe（修分割、用快取資料）。輸出：
  - twdata\screener_pool.csv：代碼/名稱/市場/trend_frac/近年年化報酬/均成交額（依 trend_frac 排序）
  - 主控台：通過 X/全部 Y 檔 + Top 30。

⚠ 誠實：這是「當下快照」的可交易池，會隨時間變動，建議定期重跑。

用法：
  python tw_screener.py
  python tw_screener.py --trend 0.25 --min-ret 0 --min-turnover 20000000 --lookback 5
執行：使用指定的 Python 3.9 解譯器。
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
import tw_trendride as tr          # adjust_splits（修分割）
import tw_optimize_adaptive as oa  # trend_fraction / annual_return

DATA_DIR = tw_data.DATA_DIR
OUT_CSV = os.path.join(DATA_DIR, "screener_pool.csv")

MIN_BARS = 750                    # 至少 ~3 年資料才篩（lookback 取得到）


def recent_window(df, years):
    """取最新一日往回 years 年的資料（滾動、不看未來：用的全是已發生的歷史）。"""
    cutoff = df.index[-1] - pd.Timedelta(days=int(years * 365.25))
    return df[df.index >= cutoff]


def turnover_60d(df):
    """近 60 個交易日的『日成交額』中位數（價×量）。"""
    if "Volume" not in df.columns:
        return 0.0
    dv = (df["Close"] * df["Volume"]).dropna()
    if len(dv) == 0:
        return 0.0
    last60 = dv.tail(60)
    return float(last60.median())


def screen(args):
    universe = tw_data.get_universe()
    print(f"全台股 universe：{len(universe)} 檔（上市+上櫃 股票）")
    print(f"門檻：trend_frac≥{args.trend}、近{args.lookback}年年化報酬≥{args.min_ret*100:.0f}%、"
          f"近60日均成交額≥{args.min_turnover:,.0f}")

    rows = []
    n_eval = 0
    n_skip = 0
    t0 = time.time()
    for k, (code, ticker, market, name) in enumerate(universe, 1):
        raw = tw_data.load_ohlcv(ticker, period="max", use_cache=True)
        if raw is None or len(raw) < MIN_BARS:
            n_skip += 1
            continue
        df, _ = tr.adjust_splits(raw)   # 修分割
        n_eval += 1
        win = recent_window(df, args.lookback)
        if len(win) < 250:
            n_skip += 1
            continue
        tf = oa.trend_fraction(win)
        ar = oa.annual_return(win)
        to = turnover_60d(df)
        passed = (tf >= args.trend) and (ar >= args.min_ret) and (to >= args.min_turnover)
        rows.append(dict(code=code, name=name, market=market,
                         trend_frac=round(tf, 4),
                         ann_return=round(ar, 4),
                         turnover_60d=round(to, 0),
                         passed=passed))
        if k % 300 == 0:
            print(f"  進度 {k}/{len(universe)}（已評 {n_eval}，{time.time()-t0:.0f}s）")

    df_all = pd.DataFrame(rows)
    pool = df_all[df_all["passed"]].copy()
    pool = pool.sort_values("trend_frac", ascending=False).reset_index(drop=True)

    # 輸出 CSV（只存通過的池，依 trend_frac 排序）
    pool_out = pool[["code", "name", "market", "trend_frac", "ann_return", "turnover_60d"]]
    pool_out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # 主控台摘要
    print("\n" + "=" * 78)
    print(f"通過 {len(pool)} / 全部 {len(df_all)} 檔（已評估；跳過資料不足 {n_skip} 檔），"
          f"耗時 {time.time()-t0:.0f}s")
    print(f"可交易池 CSV：{OUT_CSV}")
    print("=" * 78)
    print(f"{'排名':>3} {'代碼':<7}{'名稱':<10}{'市場':<5}{'趨勢佔比':>8}{'近年年化':>9}{'近60日均額(億)':>14}")
    print("-" * 78)
    for i, r in pool.head(30).iterrows():
        nm = str(r["name"])
        # 名稱寬度補齊（中文佔位）
        pad = nm + "　" * max(0, 5 - len(nm))
        print(f"{i+1:>3} {r['code']:<7}{pad:<10}{r['market']:<5}"
              f"{r['trend_frac']*100:>7.1f}%{r['ann_return']*100:>8.1f}%"
              f"{r['turnover_60d']/1e8:>13.2f}")
    print("=" * 78)
    print("⚠ 這是『當下快照』的可交易池，會隨時間變動，建議定期重跑。")
    return pool, df_all


def main():
    ap = argparse.ArgumentParser(description="台股篩選器（自適應策略可交易池）")
    ap.add_argument("--trend", type=float, default=0.25, help="trend_frac 門檻")
    ap.add_argument("--min-ret", type=float, default=0.0, help="近年年化報酬門檻（小數，0=0%%）")
    ap.add_argument("--min-turnover", type=float, default=20_000_000.0,
                    help="近60日均成交額門檻（預設 2000 萬）")
    ap.add_argument("--lookback", type=float, default=5.0, help="特徵回看年數（3-5）")
    args = ap.parse_args()
    screen(args)


if __name__ == "__main__":
    main()
