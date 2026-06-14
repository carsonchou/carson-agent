"""
獨立回測 runner — 抓 Pionex 公開真實 K 棒，跑 SuperTrend 策略，輸出績效報告。

用法：
    python run_backtest.py                # 預設 BTC_USDT，多週期掃描
    python run_backtest.py --symbol ETH_USDT --intervals 15M,1H,4H

特色：
- 直接走 Pionex 公開行情端點（不需金鑰、不送任何單，純讀取）。
- 對每個週期跑 SuperTrend(atr=10, mult=3.0) 多空雙向 + 2% 硬停損回測。
- 輸出 Sharpe / Calmar / MaxDD / 勝率 / 獲利因子 / 交易筆數，並存成 JSON 報告。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 讓 core / strategy / data / backtest 可被匯入（同 main.py 的雙路徑策略）。
_ROOT = Path(__file__).resolve().parent
_PARENT = _ROOT.parent
# 先放 _PARENT 再放 _ROOT，確保 _ROOT 在 sys.path 最前面，
# 讓 trading_bot/ 內的 strategy 套件優先於頂層同名的 strategy.py（避免被遮蔽）。
for _p in (str(_PARENT), str(_ROOT)):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

from data.pionex_feed import PionexFeed
from strategy import create_strategy
from backtest.engine import BacktestEngine


def _build_strategy(strategy_name, symbol, atr_length, multiplier):
    """依名稱建立策略；SMC 用預設 SMC 參數，supertrend 用 atr/mult。"""
    name = (strategy_name or "supertrend").strip().lower()
    if name in ("smc", "smart_money"):
        return create_strategy("smc", swing_lookback=3, require_fvg=True,
                               fvg_lookback=10, entry_on="bos", symbol=symbol)
    return create_strategy("supertrend", atr_length=atr_length,
                           multiplier=multiplier, symbol=symbol)


def run_one(feed, symbol, interval, bars, atr_length, multiplier, stop_loss_pct,
            strategy_name="supertrend"):
    """抓資料 + 跑單一週期回測，回傳 (result, df)。"""
    df = feed.get_historical(symbol, interval, bars)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{symbol} {interval} 取不到資料")
    # 帶上 symbol 供策略 / 引擎推斷
    df.attrs["symbol"] = symbol
    strategy = _build_strategy(strategy_name, symbol, atr_length, multiplier)
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=10_000.0,
        fee_rate=0.0005,
        stop_loss_pct=stop_loss_pct,
        slippage_pct=0.02,
        allow_short=True,
    )
    result = engine.run(df, interval=interval, print_summary=True)
    return result, df


def main(argv=None):
    parser = argparse.ArgumentParser(description="SuperTrend 回測 runner（Pionex 真實資料）")
    parser.add_argument("--symbol", default="BTC_USDT")
    parser.add_argument("--intervals", default="15M,1H,4H,1D")
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--atr", type=int, default=10)
    parser.add_argument("--mult", type=float, default=3.0)
    parser.add_argument("--stop", type=float, default=2.0)
    parser.add_argument("--strategy", default="supertrend",
                        choices=["supertrend", "smc"],
                        help="要回測的策略：supertrend（單一 ST）或 smc（Smart Money Concepts）。")
    parser.add_argument("--out", default="backtest_report.json")
    args = parser.parse_args(argv)

    # 介面接受 1H 等寫法，PionexFeed 內部會正規化成 60M
    intervals = [s.strip() for s in args.intervals.split(",") if s.strip()]
    feed = PionexFeed(base_url="https://api.pionex.com")

    report = {
        "symbol": args.symbol,
        "strategy": args.strategy,
        "params": {"atr_length": args.atr, "multiplier": args.mult, "stop_loss_pct": args.stop},
        "results": {},
    }

    label = "SMC(BOS/CHoCH+FVG)" if args.strategy == "smc" else f"SuperTrend({args.atr},{args.mult})"
    for interval in intervals:
        print("\n" + "#" * 60)
        print(f"# {args.symbol}  {interval}  {label}  停損 {args.stop}%")
        print("#" * 60)
        try:
            result, df = run_one(
                feed, args.symbol, interval, args.bars, args.atr, args.mult, args.stop,
                strategy_name=args.strategy,
            )
            report["results"][interval] = {
                "bars": int(len(df)),
                "data_start": str(df.index[0]),
                "data_end": str(df.index[-1]),
                "total_return": round(float(result.total_return), 6),
                "sharpe": round(float(result.sharpe), 4),
                "calmar": round(float(result.calmar), 4),
                "max_drawdown": round(float(result.max_drawdown), 6),
                "win_rate": round(float(result.win_rate), 4),
                "profit_factor": (
                    None if result.profit_factor == float("inf")
                    else round(float(result.profit_factor), 4)
                ),
                "num_trades": int(result.num_trades),
                "final_equity": round(float(result.metrics.get("final_equity", 0.0)), 2),
            }
        except Exception as exc:  # 單一週期失敗不影響其他週期
            print(f"!! {interval} 回測失敗：{exc!r}")
            report["results"][interval] = {"error": repr(exc)}

    out_path = _ROOT / args.out
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n報告已存至：{out_path}")

    # 彙整表
    print("\n" + "=" * 72)
    print(f" 彙總：{args.symbol}  {label}  停損 {args.stop}%")
    print("=" * 72)
    print(f"{'週期':<6}{'根數':>6}{'總報酬':>11}{'Sharpe':>9}{'Calmar':>9}{'MaxDD':>9}{'勝率':>8}{'筆數':>6}")
    print("-" * 72)
    for interval, r in report["results"].items():
        if "error" in r:
            print(f"{interval:<6}{'—':>6}  {r['error'][:40]}")
            continue
        pf = r["profit_factor"]
        print(
            f"{interval:<6}{r['bars']:>6}{r['total_return']*100:>10.2f}%"
            f"{r['sharpe']:>9.3f}{r['calmar']:>9.3f}{r['max_drawdown']*100:>8.2f}%"
            f"{r['win_rate']*100:>7.1f}%{r['num_trades']:>6}"
        )
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
