"""
參數網格掃描 — 對 SuperTrend 做 ATR×mult×停損 網格優化，跨標的/週期驗證穩健度。

效率重點：每個 (symbol, interval) 只抓一次資料，之後在記憶體裡重複跑所有參數組合。
排名用複合分數（穩健性導向）：Sharpe 為主，懲罰交易數過少與 MaxDD 過大。

用法：
    python sweep.py
    python sweep.py --symbols BTC_USDT,ETH_USDT --intervals 1H,4H --bars 1000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_PARENT = _ROOT.parent
for _p in (str(_ROOT), str(_PARENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data.pionex_feed import PionexFeed
from strategy.supertrend import SuperTrendStrategy
from backtest.engine import BacktestEngine

ATR_GRID = [7, 10, 14]
MULT_GRID = [2.0, 2.5, 3.0, 3.5]
STOP_GRID = [1.5, 2.0, 3.0]


def composite_score(r):
    """穩健性導向複合分數。

    - Sharpe 為核心。
    - 交易數 < 10 視為樣本不足，線性折扣（避免少數幸運單造成的假高 Sharpe）。
    - MaxDD 超過 25% 額外懲罰。
    - 負報酬直接判負。
    """
    sharpe = float(r.sharpe)
    n = int(r.num_trades)
    mdd = float(r.max_drawdown)
    tr = float(r.total_return)
    if tr <= 0:
        return -abs(sharpe) - 1.0
    sample_factor = min(1.0, n / 10.0)
    dd_pen = max(0.0, mdd - 0.25) * 4.0
    return sharpe * sample_factor - dd_pen


def run_combo(df, interval, symbol, atr, mult, stop):
    strategy = SuperTrendStrategy(atr_length=atr, multiplier=mult, symbol=symbol)
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=10_000.0,
        fee_rate=0.0005,
        stop_loss_pct=stop,
        slippage_pct=0.02,
        allow_short=True,
    )
    return engine.run(df, interval=interval, print_summary=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SuperTrend 參數網格掃描")
    parser.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT")
    parser.add_argument("--intervals", default="1H,4H")
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--out", default="sweep_report.json")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    intervals = [s.strip() for s in args.intervals.split(",") if s.strip()]
    feed = PionexFeed(base_url="https://api.pionex.com")

    all_rows = []
    for symbol in symbols:
        for interval in intervals:
            try:
                df = feed.get_historical(symbol, interval, args.bars)
            except Exception as exc:
                print(f"!! 抓不到 {symbol} {interval}: {exc!r}")
                continue
            if df is None or len(df) == 0:
                print(f"!! {symbol} {interval} 空資料")
                continue
            df.attrs["symbol"] = symbol
            print(f"\n### {symbol} {interval}  ({len(df)} 根, {df.index[0]} ~ {df.index[-1]})")
            for atr in ATR_GRID:
                for mult in MULT_GRID:
                    for stop in STOP_GRID:
                        try:
                            r = run_combo(df, interval, symbol, atr, mult, stop)
                        except Exception as exc:
                            print(f"   x ATR{atr} m{mult} s{stop}: {exc!r}")
                            continue
                        row = {
                            "symbol": symbol,
                            "interval": interval,
                            "atr": atr,
                            "mult": mult,
                            "stop": stop,
                            "total_return": round(float(r.total_return), 6),
                            "sharpe": round(float(r.sharpe), 4),
                            "calmar": round(float(r.calmar), 4),
                            "max_drawdown": round(float(r.max_drawdown), 6),
                            "win_rate": round(float(r.win_rate), 4),
                            "profit_factor": (
                                None if r.profit_factor == float("inf")
                                else round(float(r.profit_factor), 4)
                            ),
                            "num_trades": int(r.num_trades),
                            "score": round(composite_score(r), 4),
                        }
                        all_rows.append(row)

    # 每個 (symbol, interval) 取最佳，並算各參數組合的「跨組合平均分數」找最穩健的全域參數
    from collections import defaultdict

    best_per_market = {}
    for row in all_rows:
        key = f"{row['symbol']} {row['interval']}"
        if key not in best_per_market or row["score"] > best_per_market[key]["score"]:
            best_per_market[key] = row

    param_scores = defaultdict(list)
    for row in all_rows:
        param_scores[(row["atr"], row["mult"], row["stop"])].append(row["score"])
    robust = sorted(
        ((p, sum(v) / len(v), len(v)) for p, v in param_scores.items()),
        key=lambda x: x[1],
        reverse=True,
    )

    report = {
        "grid": {"atr": ATR_GRID, "mult": MULT_GRID, "stop": STOP_GRID},
        "markets": list(best_per_market.keys()),
        "best_per_market": best_per_market,
        "robust_global_params": [
            {"atr": p[0], "mult": p[1], "stop": p[2], "avg_score": round(s, 4), "n_markets": n}
            for p, s, n in robust[:5]
        ],
        "all_rows": all_rows,
    }
    out_path = _ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print(" 各市場最佳參數")
    print("=" * 78)
    print(f"{'市場':<16}{'ATR':>4}{'mult':>6}{'stop':>6}{'報酬':>10}{'Sharpe':>9}{'MaxDD':>8}{'筆數':>6}{'分數':>8}")
    print("-" * 78)
    for key, r in best_per_market.items():
        print(
            f"{key:<16}{r['atr']:>4}{r['mult']:>6}{r['stop']:>6}"
            f"{r['total_return']*100:>9.2f}%{r['sharpe']:>9.3f}{r['max_drawdown']*100:>7.1f}%"
            f"{r['num_trades']:>6}{r['score']:>8.3f}"
        )
    print("\n" + "=" * 78)
    print(" 最穩健的全域參數（跨所有市場平均分數）")
    print("=" * 78)
    for item in report["robust_global_params"]:
        print(
            f"  ATR={item['atr']:>3}  mult={item['mult']:<4}  stop={item['stop']:<4}"
            f"  平均分數={item['avg_score']:>7.3f}  (n={item['n_markets']})"
        )
    print(f"\n報告已存至：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
