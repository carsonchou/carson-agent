# -*- coding: utf-8 -*-
"""
多標的真實回測：驗證「每個標的都自動做單」是否可行
策略：UT Bot(key2) + EMA200 過濾（前一輪 BTC 最佳策略）
數據：幣安真實日線
"""
import sys
from backtest_engine import fetch_klines, ut_bot_signals, ema, backtest, fmt
import numpy as np

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT"]
CAP_EACH = 60.0  # 假設每個標的各放 60u（單獨衡量策略在該標的的表現）

def run_symbol(sym):
    df = fetch_klines(sym, "1d", total=4000)
    d = ut_bot_signals(df, key=2.0, atr_period=10)
    e200 = ema(d["close"], 200)
    d["ut_long"]  = d["ut_long"]  & (d["close"] > e200)
    d["ut_short"] = d["ut_short"] & (d["close"] < e200)
    r = backtest(d, "ut_long", "ut_short", leverage=1.0, tp_pct=None, sl_pct=None, capital=CAP_EACH)
    r["start"] = df["date"].iloc[0]
    r["bars"] = len(df)
    return r

if __name__ == "__main__":
    print("多標的回測：UT Bot(key2)+EMA200 無槓桿，各標的獨立 60u 起始")
    print("="*140)
    rows = []
    for s in SYMBOLS:
        try:
            r = run_symbol(s)
            rows.append((s, r))
            pf = "∞" if r['profit_factor']==float('inf') else f"{r['profit_factor']:.2f}"
            print(f"{s:<10} 起{str(r['start'])[:10]} {r['bars']:>4}根 | "
                  f"終值 ${r['final']:>7.1f} | 報酬 {r['total_return_pct']:>8.1f}% | "
                  f"勝率 {r['winrate']:>5.1f}% | 交易 {r['trades']:>3d} | "
                  f"回撤 {r['max_dd_pct']:>5.1f}% | 盈虧比 {pf:>5}")
        except Exception as e:
            print(f"{s:<10} 失敗: {e}")
    print("="*140)
    # 統計：賺錢標的比例、平均報酬
    profits = [r["total_return_pct"] for _,r in rows]
    wins = [p for p in profits if p > 0]
    print(f"\n【結論】{len(rows)} 個標的中，{len(wins)} 個賺錢、{len(rows)-len(wins)} 個虧錢")
    print(f"   平均報酬 {np.mean(profits):>7.1f}% | 中位數 {np.median(profits):>7.1f}% | "
          f"最好 {max(profits):>7.1f}% | 最差 {min(profits):>7.1f}%")
    print(f"   勝率最高: {max(rows,key=lambda x:x[1]['winrate'])[0]} "
          f"({max(r['winrate'] for _,r in rows):.1f}%)")
