# -*- coding: utf-8 -*-
"""
真實歷史回測引擎
- 數據來源：幣安(Binance)公開 K 線 API（真實成交數據）
- 標的：BTCUSDT
- 策略：UT Bot、SuperTrend、UT Bot + EMA 趨勢過濾
- 含：槓桿、止盈、止損、手續費、爆倉檢查
- 輸出：總報酬、勝率、最大回撤、交易次數、盈虧比、Sharpe
"""
import requests
import pandas as pd
import numpy as np
import time
import sys

# ============================================================
# 一、抓取真實歷史數據（分頁抓滿）
# ============================================================
def fetch_klines(symbol="BTCUSDT", interval="4h", total=4000, market="perp"):
    # market="perp" 用幣安 USDT 永續合約(跟派網實盤一致)；"spot" 用現貨
    url = "https://fapi.binance.com/fapi/v1/klines" if market=="perp" else "https://api.binance.com/api/v3/klines"
    limit = 1500 if market=="perp" else 1000
    all_rows = []
    end_time = None
    while len(all_rows) < total:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time:
            params["endTime"] = end_time
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if not data:
            break
        all_rows = data + all_rows
        end_time = data[0][0] - 1
        time.sleep(0.25)
        if len(data) < limit:
            break
    df = pd.DataFrame(all_rows, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","tbav","tqav","ignore"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.drop_duplicates("open_time").reset_index(drop=True)
    return df[["date","open","high","low","close","volume"]]

# ============================================================
# 二、技術指標
# ============================================================
def atr(df, period):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

# UT Bot：ATR 移動止損訊號（KIVANC 改良版邏輯）
def ut_bot_signals(df, key=1.0, atr_period=10):
    a = atr(df, atr_period)
    nloss = key * a
    c = df["close"].values
    stop = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0 or np.isnan(nloss.iloc[i]):
            stop[i] = c[i]
            continue
        ps = stop[i-1]
        if c[i] > ps and c[i-1] > ps:
            stop[i] = max(ps, c[i] - nloss.iloc[i])
        elif c[i] < ps and c[i-1] < ps:
            stop[i] = min(ps, c[i] + nloss.iloc[i])
        elif c[i] > ps:
            stop[i] = c[i] - nloss.iloc[i]
        else:
            stop[i] = c[i] + nloss.iloc[i]
    df = df.copy()
    df["ut_stop"] = stop
    df["ut_long"] = (df["close"].shift(1) <= df["ut_stop"].shift(1)) & (df["close"] > df["ut_stop"])
    df["ut_short"] = (df["close"].shift(1) >= df["ut_stop"].shift(1)) & (df["close"] < df["ut_stop"])
    return df

# SuperTrend
def supertrend_signals(df, mult=3.0, atr_period=10):
    a = atr(df, atr_period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_base = hl2 + mult * a
    lower_base = hl2 - mult * a
    upper = upper_base.copy().values
    lower = lower_base.copy().values
    for i in range(1, len(df)):
        if np.isnan(upper[i-1]) or np.isnan(upper_base.iloc[i]):
            continue  # ATR 尚未有效，保持 base 值，避免 NaN 傳播
        upper[i] = upper_base.iloc[i] if (upper_base.iloc[i] < upper[i-1] or df["close"].iloc[i-1] > upper[i-1]) else upper[i-1]
        lower[i] = lower_base.iloc[i] if (lower_base.iloc[i] > lower[i-1] or df["close"].iloc[i-1] < lower[i-1]) else lower[i-1]
    direction = np.ones(len(df), dtype=int)
    for i in range(1, len(df)):
        if np.isnan(lower[i]) or np.isnan(upper[i]):
            continue
        if direction[i-1] == 1:
            direction[i] = -1 if df["close"].iloc[i] < lower[i] else 1
        else:
            direction[i] = 1 if df["close"].iloc[i] > upper[i] else -1
    df = df.copy()
    df["st_dir"] = direction
    df["st_long"] = (df["st_dir"] == 1) & (pd.Series(direction).shift(1).values == -1)
    df["st_short"] = (df["st_dir"] == -1) & (pd.Series(direction).shift(1).values == 1)
    return df

# ============================================================
# 三、回測引擎（含槓桿、止盈止損、手續費、爆倉）
# ============================================================
def backtest(df, long_sig, short_sig, leverage=1.0, tp_pct=None, sl_pct=None,
             fee=0.0005, allow_short=True, capital=60.0):
    equity = capital
    pos = 0          # 1 多 / -1 空 / 0 空手
    entry = 0.0
    peak = capital
    max_dd = 0.0
    trades = []
    eq_curve = []
    liquidated = False

    o = df["open"].values; h = df["high"].values
    l = df["low"].values;  c = df["close"].values
    ls = df[long_sig].values; ss = df[short_sig].values

    for i in range(len(df)):
        # --- 先檢查當前持倉的止盈/止損/爆倉（用 K 線高低點）---
        if pos != 0:
            exit_price = None; reason = None
            if pos == 1:
                sl_price = entry*(1-sl_pct/100) if sl_pct else None
                tp_price = entry*(1+tp_pct/100) if tp_pct else None
                liq_price = entry*(1-1.0/leverage*0.95)  # 約略爆倉價(留5%緩衝)
                if l[i] <= liq_price and leverage > 1:
                    exit_price, reason = liq_price, "爆倉"
                elif sl_price and l[i] <= sl_price:
                    exit_price, reason = sl_price, "止損"
                elif tp_price and h[i] >= tp_price:
                    exit_price, reason = tp_price, "止盈"
            else:
                sl_price = entry*(1+sl_pct/100) if sl_pct else None
                tp_price = entry*(1-tp_pct/100) if tp_pct else None
                liq_price = entry*(1+1.0/leverage*0.95)
                if h[i] >= liq_price and leverage > 1:
                    exit_price, reason = liq_price, "爆倉"
                elif sl_price and h[i] >= sl_price:
                    exit_price, reason = sl_price, "止損"
                elif tp_price and l[i] <= tp_price:
                    exit_price, reason = tp_price, "止盈"
            if exit_price is not None:
                ret = (exit_price-entry)/entry*pos*leverage
                ret -= fee*leverage*2
                equity *= (1+ret)
                trades.append(ret)
                pos = 0
                if reason == "爆倉" or equity <= 0:
                    equity = max(equity, 0)
                    eq_curve.append(equity)
                    liquidated = True
                    break

        # --- 訊號進出場（收盤觸發，次根開盤成交近似用收盤）---
        if pos == 0:
            if ls[i]:
                pos, entry = 1, c[i]
            elif ss[i] and allow_short:
                pos, entry = -1, c[i]
        elif pos == 1 and ss[i]:
            ret = (c[i]-entry)/entry*leverage - fee*leverage*2
            equity *= (1+ret); trades.append(ret)
            if allow_short:
                pos, entry = -1, c[i]
            else:
                pos = 0
        elif pos == -1 and ls[i]:
            ret = (c[i]-entry)/entry*(-1)*leverage - fee*leverage*2
            equity *= (1+ret); trades.append(ret)
            pos, entry = 1, c[i]

        peak = max(peak, equity)
        dd = (peak-equity)/peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        eq_curve.append(equity)

    trades = np.array(trades)
    n = len(trades)
    wins = trades[trades > 0]
    losses = trades[trades < 0]
    winrate = len(wins)/n*100 if n else 0
    avg_win = wins.mean() if len(wins) else 0
    avg_loss = losses.mean() if len(losses) else 0
    pf = abs(wins.sum()/losses.sum()) if losses.sum() != 0 else float('inf')
    eq = np.array(eq_curve)
    rets = np.diff(eq)/eq[:-1] if len(eq) > 1 else np.array([0])
    sharpe = (rets.mean()/rets.std()*np.sqrt(365*6)) if rets.std() > 0 else 0  # 4h≈一年2190根

    return {
        "final": equity,
        "total_return_pct": (equity/capital-1)*100,
        "trades": n,
        "winrate": winrate,
        "max_dd_pct": max_dd*100,
        "profit_factor": pf,
        "avg_win_pct": avg_win*100,
        "avg_loss_pct": avg_loss*100,
        "sharpe": sharpe,
        "liquidated": liquidated,
    }

def fmt(name, r):
    liq = "  ⚠️爆倉歸零" if r["liquidated"] else ""
    pf = "∞" if r["profit_factor"]==float('inf') else f"{r['profit_factor']:.2f}"
    return (f"{name:<34} | 終值 ${r['final']:>8.1f} | 報酬 {r['total_return_pct']:>8.1f}% | "
            f"勝率 {r['winrate']:>5.1f}% | 交易 {r['trades']:>3d} | 最大回撤 {r['max_dd_pct']:>5.1f}% | "
            f"盈虧比 {pf:>5} | Sharpe {r['sharpe']:>5.2f}{liq}")

# ============================================================
# 主程式
# ============================================================
if __name__ == "__main__":
    interval = sys.argv[1] if len(sys.argv) > 1 else "4h"
    print(f"抓取真實數據中... BTCUSDT {interval}")
    df = fetch_klines("BTCUSDT", interval, total=4000)
    print(f"數據範圍：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}  共 {len(df)} 根 K 線")
    print(f"起始價 ${df['close'].iloc[0]:,.0f} → 結束價 ${df['close'].iloc[-1]:,.0f}  "
          f"(買入持有報酬 {(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:.1f}%)")
    print("="*150)

    CAP = 60.0
    df_ut = ut_bot_signals(df, key=1.0, atr_period=10)
    df_ut2 = ut_bot_signals(df, key=2.0, atr_period=10)
    df_st = supertrend_signals(df, mult=3.0, atr_period=10)

    # EMA200 趨勢過濾版（只順大趨勢方向）
    df_utf = df_ut.copy()
    e200 = ema(df_utf["close"], 200)
    df_utf["ut_long"] = df_utf["ut_long"] & (df_utf["close"] > e200)
    df_utf["ut_short"] = df_utf["ut_short"] & (df_utf["close"] < e200)

    configs = [
        ("SuperTrend(3.0) 無槓桿基準", df_st, "st_long", "st_short", 1.0, None, None),
        ("UT Bot(key1) 無槓桿",        df_ut, "ut_long", "ut_short", 1.0, None, None),
        ("UT Bot(key2) 無槓桿",        df_ut2,"ut_long", "ut_short", 1.0, None, None),
        ("UT Bot+EMA200過濾 無槓桿",   df_utf,"ut_long", "ut_short", 1.0, None, None),
        ("UT Bot+EMA200 +TP10/SL5 無槓桿", df_utf,"ut_long","ut_short",1.0, 10, 5),
        ("UT Bot+EMA200 +TP15/SL5 3x槓桿", df_utf,"ut_long","ut_short",3.0, 15, 5),
        ("UT Bot+EMA200 +TP20/SL7 3x槓桿", df_utf,"ut_long","ut_short",3.0, 20, 7),
        ("UT Bot+EMA200 +TP15/SL5 2x槓桿", df_utf,"ut_long","ut_short",2.0, 15, 5),
        ("SuperTrend +TP15/SL5 3x槓桿",    df_st, "st_long","st_short",3.0, 15, 5),
    ]
    results = []
    for name, d, ls, ss, lev, tp, sl in configs:
        r = backtest(d, ls, ss, leverage=lev, tp_pct=tp, sl_pct=sl, capital=CAP)
        results.append((name, r))
        print(fmt(name, r))
    print("="*150)
    # 找最佳(未爆倉、Sharpe 最高)
    valid = [(n,r) for n,r in results if not r["liquidated"]]
    if valid:
        best = max(valid, key=lambda x: x[1]["sharpe"])
        print(f"\n★ 風險調整後最佳(未爆倉, Sharpe最高)：{best[0]}")
        print(f"   {fmt('', best[1])}")
