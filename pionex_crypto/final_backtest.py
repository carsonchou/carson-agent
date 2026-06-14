# -*- coding: utf-8 -*-
"""
最終配置回測：ETH + BNB + SOL @ 1.5x 槓桿，各 20u
策略：UT Bot(key2) + EMA200 過濾
對比：(A) 純 UT 移動止損  vs  (B) 加 15% 災難止損
"""
from backtest_engine import fetch_klines, ut_bot_signals, ema, backtest
import numpy as np

SYMBOLS = ["ETHUSDT","BNBUSDT","SOLUSDT"]
CAP_EACH = 20.0
LEV = 1.5

def prep(sym):
    df = fetch_klines(sym, "1d", total=4000)
    d = ut_bot_signals(df, key=2.0, atr_period=10)
    e200 = ema(d["close"], 200)
    d["ut_long"]  = d["ut_long"]  & (d["close"] > e200)
    d["ut_short"] = d["ut_short"] & (d["close"] < e200)
    return d

def line(sym, tag, r):
    liq = " ⚠️爆倉" if r["liquidated"] else ""
    pf = "∞" if r["profit_factor"]==float('inf') else f"{r['profit_factor']:.2f}"
    return (f"{sym:<8}{tag:<14}| 終值 ${r['final']:>7.1f} | 報酬 {r['total_return_pct']:>8.1f}% | "
            f"勝率 {r['winrate']:>5.1f}% | 交易 {r['trades']:>3d} | 回撤 {r['max_dd_pct']:>6.1f}% | 盈虧比 {pf:>5}{liq}")

print(f"最終配置回測：各 {CAP_EACH:.0f}u @ {LEV}x 槓桿，UT Bot(key2)+EMA200")
print("="*130)
portfolioA = 0.0; portfolioB = 0.0
for s in SYMBOLS:
    d = prep(s)
    rA = backtest(d, "ut_long", "ut_short", leverage=LEV, tp_pct=None, sl_pct=None,  capital=CAP_EACH)
    rB = backtest(d, "ut_long", "ut_short", leverage=LEV, tp_pct=None, sl_pct=15.0, capital=CAP_EACH)
    print(line(s, "純移動止損", rA))
    print(line(s, "+15%災難止損", rB))
    print("-"*130)
    portfolioA += rA["final"]; portfolioB += rB["final"]
print("="*130)
total_cap = CAP_EACH*len(SYMBOLS)
print(f"\n【組合總結】起始 ${total_cap:.0f}u (3標的各{CAP_EACH:.0f}u)")
print(f"  A 純移動止損   : 總終值 ${portfolioA:>7.1f}  ({(portfolioA/total_cap-1)*100:>+7.1f}%)")
print(f"  B +15%災難止損 : 總終值 ${portfolioB:>7.1f}  ({(portfolioB/total_cap-1)*100:>+7.1f}%)")
