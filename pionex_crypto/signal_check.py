# -*- coding: utf-8 -*-
"""
訊號一致性驗證:算出 Python 版 Multi v1 的進出場點
之後跟 TradingView 圖表/交易列表逐筆比對
Multi v1 = 標準SuperTrend(10,3.0) + EMA200 + RSI(14,50-75) + 只做多
"""
from backtest_engine import fetch_klines, supertrend_signals, ema
import pandas as pd

df = fetch_klines("BTCUSDT", "1d", total=3000, market="perp")
d = supertrend_signals(df, mult=3.0, atr_period=10)  # 標準公式(已修)
d["ema200"] = ema(d["close"], 200)

# Pine ta.rsi(Wilder RMA)
delta = d["close"].diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
d["rsi"] = 100 - 100/(1 + avg_gain/avg_loss)

# Multi v1 進出場邏輯
d["goLong"]  = d["st_long"] & (d["close"] > d["ema200"]) & (d["rsi"] > 50) & (d["rsi"] < 75)
d["exitLong"] = (d["st_dir"] == -1) | (d["close"] < d["ema200"])

# 持倉狀態機,列出進出場事件
pos = 0
events = []
for i in range(len(d)):
    dt = str(d["date"].iloc[i])[:10]
    px = d["close"].iloc[i]
    if pos == 0 and d["goLong"].iloc[i]:
        pos = 1; events.append((dt, px, "進場做多"))
    elif pos == 1 and d["exitLong"].iloc[i]:
        pos = 0; events.append((dt, px, "出場平倉"))

print(f"數據範圍: {str(d['date'].iloc[0])[:10]} ~ {str(d['date'].iloc[-1])[:10]}  共 {len(d)} 根")
print(f"Python Multi v1 共 {len(events)} 個進出場事件,最近 16 個:")
print("="*60)
for dt, px, act in events[-16:]:
    print(f"  {dt}  {act}  @ ${px:,.1f}")
print("="*60)
print(f"目前持倉狀態: {'持有多單' if pos==1 else '空手'}")
if pos == 1:
    # 找最後進場
    for dt, px, act in reversed(events):
        if act == "進場做多":
            print(f"  最後進場: {dt} @ ${px:,.1f}")
            break
