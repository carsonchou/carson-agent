# -*- coding: utf-8 -*-
"""
tw_universe_backtest.py — 台股全市場回測 runner + 報告

用法：
  # 先跑權值股 sample（含 2330/2317/2454/2412/2308 等）驗證
  python tw_universe_backtest.py --sample 8

  # 指定代碼
  python tw_universe_backtest.py --symbols 2330,2317

  # 全市場（上市+上櫃所有股票，可中斷續跑）
  python tw_universe_backtest.py --all

  # 切換成本模型（預設 pine；tw_real = 台股實際手續費+證交稅）
  python tw_universe_backtest.py --all --cost tw_real

輸出：
  twdata\per_stock_results.csv   每檔一列
  twdata\summary.md              總體統計（測幾檔/獲利檔數/PF中位數均值/Top20/Bottom20…）
"""
import argparse
import os
import sys
import time

# 讓 Windows 主控台正確顯示中文（cp950 預設會亂碼）
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
RESULTS_CSV = os.path.join(DATA_DIR, "per_stock_results.csv")
SUMMARY_MD = os.path.join(DATA_DIR, "summary.md")

# 權值股優先（sample 驗證用）
PRIORITY = ["2330", "2317", "2454", "2412", "2308", "2881", "2882", "2303",
            "1301", "1303", "2002", "2891", "3008", "2886", "2884"]

MIN_BARS = 750          # < 3 年（約 750 交易日）跳過
MIN_YEARS = 3


def build_symbol_list(args, universe):
    """依 CLI 旗標決定要跑哪些 (code, ticker, market, name)。"""
    by_code = {u[0]: u for u in universe}
    if args.symbols:
        codes = [s.strip() for s in args.symbols.split(",") if s.strip()]
        out = []
        for code in codes:
            if code in by_code:
                out.append(by_code[code])
            else:
                # 嘗試當作完整 ticker
                print(f"  [警告] 代碼 {code} 不在 universe，略過")
        return out
    if args.sample:
        # 權值股優先 + 其餘補滿到 N
        pri = [by_code[c] for c in PRIORITY if c in by_code]
        rest = [u for u in universe if u[0] not in set(PRIORITY)]
        return (pri + rest)[: args.sample]
    # --all
    return universe


def load_existing_results():
    if os.path.exists(RESULTS_CSV):
        try:
            df = pd.read_csv(RESULTS_CSV, dtype={"code": str})
            return df
        except Exception:
            return None
    return None


def run(args):
    # 允許 --out / --results 覆寫輸出路徑（不覆蓋舊報告）
    global SUMMARY_MD, RESULTS_CSV
    if getattr(args, "out", None):
        SUMMARY_MD = (args.out if os.path.isabs(args.out)
                      else os.path.join(DATA_DIR, args.out))
    if getattr(args, "results", None):
        RESULTS_CSV = (args.results if os.path.isabs(args.results)
                       else os.path.join(DATA_DIR, args.results))
    print("=" * 70)
    print("台股全市場回測器 — Triple SuperTrend v4 Champion v5 (LONG-ONLY)")
    print(f"成本模型: {args.cost}   初始資金: {args.capital}")
    print(f"報告輸出: {SUMMARY_MD}")
    print("=" * 70)

    universe = tw_data.get_universe()
    print(f"Universe: {len(universe)} 檔（上市+上櫃 股票）")
    targets = build_symbol_list(args, universe)
    print(f"本次預計回測: {len(targets)} 檔")

    # 續跑：已算過的（同 cost）跳過
    done_codes = set()
    existing = load_existing_results()
    results = []
    if existing is not None and not args.fresh:
        same = existing[existing["cost"] == args.cost]
        done_codes = set(same["code"].astype(str))
        results = existing.to_dict("records")
        if done_codes:
            print(f"續跑：已有 {len(done_codes)} 檔（cost={args.cost}）結果，將跳過")

    p = strategy.Params()
    t0 = time.time()
    n_ok = 0
    n_skip_data = 0
    n_fail = 0

    for k, (code, ticker, market, name) in enumerate(targets, 1):
        if code in done_codes:
            continue
        try:
            df = tw_data.load_ohlcv(ticker, period="max",
                                    sleep=args.sleep, use_cache=not args.refresh)
        except Exception as e:
            n_fail += 1
            print(f"[{k}/{len(targets)}] {code} {ticker} 下載失敗: {e}")
            continue
        if df is None or len(df) < MIN_BARS:
            n_skip_data += 1
            nb = 0 if df is None else len(df)
            print(f"[{k}/{len(targets)}] {code} {ticker} 資料不足({nb} bars)，跳過")
            continue
        span_years = (df.index[-1] - df.index[0]).days / 365.25
        if span_years < MIN_YEARS:
            n_skip_data += 1
            print(f"[{k}/{len(targets)}] {code} {ticker} 期間不足({span_years:.1f}年)，跳過")
            continue
        try:
            m, trades, eq = strategy.backtest_long_only(
                df, cost_model=args.cost, initial_capital=args.capital, p=p)
        except Exception as e:
            n_fail += 1
            print(f"[{k}/{len(targets)}] {code} {ticker} 回測錯誤: {e}")
            continue

        row = dict(code=code, ticker=ticker, market=market, name=name,
                   cost=args.cost, bars=len(df),
                   start=str(df.index[0].date()), end=str(df.index[-1].date()),
                   **m)
        results.append(row)
        n_ok += 1
        pf = m["profit_factor"]
        pf_s = "inf" if not np.isfinite(pf) else f"{pf:.2f}"
        print(f"[{k}/{len(targets)}] {code} {name[:6]:<8} "
              f"net={m['net_profit_pct']:>7.1f}% PF={pf_s:>5} "
              f"DD={m['max_dd_pct']:>5.1f}% trades={m['n_trades']:>3} "
              f"win={m['win_rate_pct']:>4.0f}% Sharpe={m['sharpe']:>5.2f}")

        # 定期存檔（可中斷續跑）
        if n_ok % 25 == 0:
            _save_results(results)

    _save_results(results)
    dt = time.time() - t0
    print("-" * 70)
    print(f"完成：成功 {n_ok}、資料不足 {n_skip_data}、失敗 {n_fail}，耗時 {dt:.0f}s")

    # 報告（只用本次 cost 的結果）
    df_res = pd.DataFrame(results)
    df_res = df_res[df_res["cost"] == args.cost].copy()
    write_summary(df_res, args)
    return df_res


def _save_results(results):
    if not results:
        return
    df = pd.DataFrame(results)
    df.to_csv(RESULTS_CSV, index=False)


def _fmt_pf(x):
    return "inf" if not np.isfinite(x) else f"{x:.3f}"


def write_summary(df: pd.DataFrame, args):
    if len(df) == 0:
        print("無結果可彙整。")
        return
    n = len(df)
    pf = df["profit_factor"].replace([np.inf], np.nan)
    profitable = df[(df["profit_factor"] > 1) & (df["net_profit_pct"] > 0)]
    n_prof = len(profitable)

    lines = []
    lines.append(f"# 台股全市場回測總體統計 — Triple SuperTrend v4 v5 (LONG-ONLY)\n")
    lines.append(f"- 成本模型：`{args.cost}`")
    lines.append(f"- 初始資金：{args.capital}")
    lines.append(f"- 測試檔數：**{n}**")
    lines.append(f"- 獲利檔數（PF>1 且 淨利>0）：**{n_prof}**（{n_prof/n*100:.1f}%）\n")

    lines.append("## 指標總覽（跨所有測試股票）\n")
    lines.append("| 指標 | 中位數 | 平均 |")
    lines.append("|---|---|---|")
    lines.append(f"| 淨利 % | {df['net_profit_pct'].median():.2f} | {df['net_profit_pct'].mean():.2f} |")
    lines.append(f"| Profit Factor | {pf.median():.3f} | {pf.mean():.3f} |")
    lines.append(f"| 最大回撤 % | {df['max_dd_pct'].median():.2f} | {df['max_dd_pct'].mean():.2f} |")
    lines.append(f"| 總交易數 | {df['n_trades'].median():.0f} | {df['n_trades'].mean():.1f} |")
    lines.append(f"| 勝率 % | {df['win_rate_pct'].median():.2f} | {df['win_rate_pct'].mean():.2f} |")
    lines.append(f"| Return/MaxDD | {df['return_over_maxdd'].replace([np.inf],np.nan).median():.3f} | {df['return_over_maxdd'].replace([np.inf],np.nan).mean():.3f} |")
    lines.append(f"| 年化 Sharpe | {df['sharpe'].median():.3f} | {df['sharpe'].mean():.3f} |\n")

    # 淨利分佈
    lines.append("## 淨利 % 分佈\n")
    bins = [(-1e9, -50), (-50, -20), (-20, 0), (0, 20), (20, 50), (50, 100), (100, 1e9)]
    labels = ["< -50%", "-50~-20%", "-20~0%", "0~20%", "20~50%", "50~100%", "> 100%"]
    lines.append("| 區間 | 檔數 |")
    lines.append("|---|---|")
    for (lo, hi), lab in zip(bins, labels):
        cnt = int(((df["net_profit_pct"] > lo) & (df["net_profit_pct"] <= hi)).sum())
        lines.append(f"| {lab} | {cnt} |")
    lines.append("")

    # Top20 / Bottom20（依 Return/MaxDD，inf 排前）
    def sort_key(d):
        d = d.copy()
        d["_rk"] = d["return_over_maxdd"].replace([np.inf], 1e9)
        return d

    ranked = sort_key(df).sort_values("_rk", ascending=False)

    def tbl(sub, title):
        out = [f"## {title}\n",
               "| 代碼 | 名稱 | 淨利% | PF | MaxDD% | 交易數 | 勝率% | Ret/DD | Sharpe |",
               "|---|---|---|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            rdd = "inf" if not np.isfinite(r["return_over_maxdd"]) else f"{r['return_over_maxdd']:.2f}"
            out.append(f"| {r['code']} | {str(r['name'])[:8]} | {r['net_profit_pct']:.1f} | "
                       f"{_fmt_pf(r['profit_factor'])} | {r['max_dd_pct']:.1f} | {int(r['n_trades'])} | "
                       f"{r['win_rate_pct']:.0f} | {rdd} | {r['sharpe']:.2f} |")
        out.append("")
        return out

    lines += tbl(ranked.head(20), "Top 20（依 Return/MaxDD）")
    lines += tbl(ranked.tail(20).iloc[::-1], "Bottom 20（依 Return/MaxDD）")

    text = "\n".join(lines)
    with open(SUMMARY_MD, "w", encoding="utf-8") as f:
        f.write(text)

    # console 摘要
    print("\n" + "=" * 70)
    print(f"總體統計（cost={args.cost}）")
    print(f"  測試檔數: {n}")
    print(f"  獲利檔數(PF>1且淨利>0): {n_prof} ({n_prof/n*100:.1f}%)")
    print(f"  PF 中位數: {pf.median():.3f}  平均: {pf.mean():.3f}")
    print(f"  淨利% 中位數: {df['net_profit_pct'].median():.2f}  平均: {df['net_profit_pct'].mean():.2f}")
    print(f"  Return/MaxDD 中位數: {df['return_over_maxdd'].replace([np.inf],np.nan).median():.3f}")
    print(f"  最大回撤% 中位數: {df['max_dd_pct'].median():.2f}")
    print(f"  報告已存: {SUMMARY_MD}")
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser(description="台股全市場回測器")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, metavar="N", help="跑 N 檔（權值股優先）")
    g.add_argument("--symbols", type=str, help="逗號分隔代碼，如 2330,2317")
    g.add_argument("--all", action="store_true", help="全市場")
    ap.add_argument("--cost", choices=["pine", "tw_real"], default="pine",
                    help="成本模型（預設 pine，給 TradingView 比對）")
    ap.add_argument("--capital", type=float, default=10000.0, help="初始資金")
    ap.add_argument("--sleep", type=float, default=0.4, help="下載間隔秒（避免限流）")
    ap.add_argument("--refresh", action="store_true", help="忽略快取重新下載")
    ap.add_argument("--fresh", action="store_true", help="忽略既有結果，重新計算")
    ap.add_argument("--out", type=str, default=None,
                    help="總體報告輸出檔名（預設 summary.md；可指定如 summary_tw_opt.md 不覆蓋舊報告）")
    ap.add_argument("--results", type=str, default=None,
                    help="每檔結果 CSV 檔名（預設 per_stock_results.csv）")
    args = ap.parse_args()

    if not (args.sample or args.symbols or args.all):
        args.sample = 8
        print("未指定模式，預設 --sample 8")

    run(args)


if __name__ == "__main__":
    main()
