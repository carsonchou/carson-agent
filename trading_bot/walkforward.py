"""
Walk-forward 樣本外驗證 — 檢驗網格優化是否過擬合。

做法：每個市場資料切 70% 樣本內(IS) / 30% 樣本外(OOS)。
  1. 在 IS 上跑同一組參數網格，用複合分數選最佳參數。
  2. 把該「IS 最佳參數」原封不動套到 OOS 上回測。
  3. 比較 IS vs OOS 績效：若 OOS 仍正且 Sharpe 不崩 → 穩健；若 OOS 崩盤 → 過擬合。

對照組：同時把全域 robust 參數 (14/3.5/3.0) 也套到 OOS，看「不調參的固定參數」OOS 表現。

用法：
    python walkforward.py
    python walkforward.py --symbols BTC_USDT,ETH_USDT --intervals 1H,4H --bars 1000
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
ROBUST = (14, 3.5, 3.0)  # 上一輪全域最穩健參數


def composite_score(r):
    sharpe = float(r.sharpe)
    n = int(r.num_trades)
    mdd = float(r.max_drawdown)
    tr = float(r.total_return)
    if tr <= 0:
        return -abs(sharpe) - 1.0
    return sharpe * min(1.0, n / 10.0) - max(0.0, mdd - 0.25) * 4.0


def bt(df, interval, symbol, atr, mult, stop):
    strategy = SuperTrendStrategy(atr_length=atr, multiplier=mult, symbol=symbol)
    engine = BacktestEngine(
        strategy=strategy, initial_capital=10_000.0, fee_rate=0.0005,
        stop_loss_pct=stop, slippage_pct=0.02, allow_short=True,
    )
    return engine.run(df, interval=interval, print_summary=False)


def summarize(r):
    return {
        "total_return": round(float(r.total_return), 6),
        "sharpe": round(float(r.sharpe), 4),
        "max_drawdown": round(float(r.max_drawdown), 6),
        "win_rate": round(float(r.win_rate), 4),
        "num_trades": int(r.num_trades),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Walk-forward 樣本外驗證")
    parser.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT")
    parser.add_argument("--intervals", default="1H,4H")
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--split", type=float, default=0.7)
    parser.add_argument("--out", default="walkforward_report.json")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    intervals = [s.strip() for s in args.intervals.split(",") if s.strip()]
    feed = PionexFeed(base_url="https://api.pionex.com")

    out = {}
    for symbol in symbols:
        for interval in intervals:
            key = f"{symbol} {interval}"
            try:
                df = feed.get_historical(symbol, interval, args.bars)
            except Exception as exc:
                print(f"!! {key} 抓不到: {exc!r}")
                continue
            if df is None or len(df) < 100:
                print(f"!! {key} 資料不足")
                continue
            df.attrs["symbol"] = symbol
            cut = int(len(df) * args.split)
            is_df, oos_df = df.iloc[:cut].copy(), df.iloc[cut:].copy()
            is_df.attrs["symbol"] = symbol
            oos_df.attrs["symbol"] = symbol

            # 1) IS 網格優化
            best = None
            for atr in ATR_GRID:
                for mult in MULT_GRID:
                    for stop in STOP_GRID:
                        try:
                            r = bt(is_df, interval, symbol, atr, mult, stop)
                        except Exception:
                            continue
                        sc = composite_score(r)
                        if best is None or sc > best["score"]:
                            best = {"atr": atr, "mult": mult, "stop": stop,
                                    "score": round(sc, 4), "is": summarize(r)}
            if best is None:
                continue

            # 2) IS 最佳參數 → OOS
            r_oos = bt(oos_df, interval, symbol, best["atr"], best["mult"], best["stop"])
            # 3) 對照：固定 robust 參數 → OOS
            r_rob = bt(oos_df, interval, symbol, *ROBUST)

            out[key] = {
                "is_best_params": {"atr": best["atr"], "mult": best["mult"], "stop": best["stop"]},
                "is_perf": best["is"],
                "oos_perf_tuned": summarize(r_oos),
                "oos_perf_robust_fixed": summarize(r_rob),
                "is_bars": len(is_df),
                "oos_bars": len(oos_df),
            }
            print(f"\n### {key}  IS最佳={best['atr']}/{best['mult']}/{best['stop']}")
            print(f"    IS : ret {best['is']['total_return']*100:+6.2f}%  Sh {best['is']['sharpe']:5.2f}  n{best['is']['num_trades']}")
            print(f"    OOS(調參): ret {summarize(r_oos)['total_return']*100:+6.2f}%  Sh {summarize(r_oos)['sharpe']:5.2f}  n{summarize(r_oos)['num_trades']}")
            print(f"    OOS(固定14/3.5/3): ret {summarize(r_rob)['total_return']*100:+6.2f}%  Sh {summarize(r_rob)['sharpe']:5.2f}  n{summarize(r_rob)['num_trades']}")

    (_ROOT / args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 彙總
    print("\n" + "=" * 82)
    print(" Walk-forward 彙總：IS 調參 → OOS 表現 (檢驗過擬合)")
    print("=" * 82)
    print(f"{'市場':<16}{'IS最佳':>12}{'IS報酬':>9}{'OOS調參':>10}{'OOS固定':>10}")
    print("-" * 82)
    n_pos_tuned = n_pos_robust = n = 0
    sum_t = sum_r = 0.0
    for key, v in out.items():
        p = v["is_best_params"]
        ist = v["is_perf"]["total_return"] * 100
        ot = v["oos_perf_tuned"]["total_return"] * 100
        orr = v["oos_perf_robust_fixed"]["total_return"] * 100
        print(f"{key:<16}{p['atr']}/{p['mult']}/{p['stop']:<6}{ist:>8.2f}%{ot:>9.2f}%{orr:>9.2f}%")
        n += 1
        sum_t += ot; sum_r += orr
        n_pos_tuned += ot > 0
        n_pos_robust += orr > 0
    if n:
        print("-" * 82)
        print(f"{'OOS 平均':<28}{'':>9}{sum_t/n:>9.2f}%{sum_r/n:>9.2f}%")
        print(f"OOS 正報酬市場數：調參 {n_pos_tuned}/{n}  固定robust {n_pos_robust}/{n}")
    print("=" * 82)
    print("解讀：OOS 調參若大幅低於 IS → IS 過擬合；固定 robust 的 OOS 越穩 → 越可實盤。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
