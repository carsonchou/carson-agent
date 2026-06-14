# -*- coding: utf-8 -*-
"""
永續合約校準 + SuperTrend 救援測試
1. 復現 TradingView 的 SuperTrend(2%止損) → 對帳 TradingView 實測 -78%
2. 測無止損 / 放寬止損,找能救 100u BTC bot 的配置
數據：幣安 USDT 永續合約 BTCUSDT 日線(跟派網實盤一致)
"""
from backtest_engine import fetch_klines, supertrend_signals, ut_bot_signals, ema, backtest, fmt

print("抓取幣安永續合約 BTCUSDT 日線...")
df = fetch_klines("BTCUSDT", "1d", total=3000, market="perp")
print(f"數據範圍：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}  共 {len(df)} 根")
print(f"買入持有報酬 {(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:.1f}%")
print("="*140)

CAP = 1000.0  # 跟 TradingView initial_capital 一致,比對報酬%
dst = supertrend_signals(df, mult=3.0, atr_period=10)

configs = [
    ("SuperTrend(3.0) +2%止損 [復現TV]", dst, 2.0),
    ("SuperTrend(3.0) 無止損",           dst, None),
    ("SuperTrend(3.0) +5%止損",          dst, 5.0),
    ("SuperTrend(3.0) +8%止損",          dst, 8.0),
    ("SuperTrend(3.0) +12%止損",         dst, 12.0),
]
for name, d, sl in configs:
    r = backtest(d, "st_long", "st_short", leverage=1.0, tp_pct=None, sl_pct=sl, capital=CAP)
    print(fmt(name, r))

print("-"*140)
# 不同 ATR 倍數(無止損,純趨勢翻轉)
for mult in [2.0, 4.0, 5.0]:
    d = supertrend_signals(df, mult=mult, atr_period=10)
    r = backtest(d, "st_long", "st_short", leverage=1.0, tp_pct=None, sl_pct=None, capital=CAP)
    print(fmt(f"SuperTrend({mult}) 無止損", r))

print("-"*140)
# UT Bot 對照(對帳 TV -1.23%)
for key in [1.0, 2.0, 3.0]:
    d = ut_bot_signals(df, key=key, atr_period=10)
    e200 = ema(d["close"], 200)
    d["ut_long"] = d["ut_long"] & (d["close"] > e200)
    d["ut_short"] = d["ut_short"] & (d["close"] < e200)
    r = backtest(d, "ut_long", "ut_short", leverage=1.0, tp_pct=None, sl_pct=None, capital=CAP)
    print(fmt(f"UT Bot(key{key})+EMA200 無止損", r))
print("="*140)
