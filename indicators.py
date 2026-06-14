# -*- coding: utf-8 -*-
"""
indicators.py — Pine v5 相容的技術指標（ta.* 對應）

忠實重現 TradingView Pine Script 的計算慣例：
- ta.atr      : RMA(True Range, len)，RMA = Wilder's smoothing (alpha=1/len)
- ta.supertrend(factor, atrPeriod): 標準 SuperTrend，上下軌 + 方向翻轉，dir<0 = 多頭
- ta.dmi(diLen, adxLen): +DI/-DI/ADX，全部用 RMA 平滑
- Kaufman ER : |close-close[n]| / sum(|close-close[1]|, n)
- ta.stdev   : 母體標準差（ddof=0），與 Pine 一致
- ta.median / ta.percentile_linear_interpolation : 滾動視窗

所有函式輸入 pandas Series / DataFrame，輸出對齊原 index 的 Series。
"""
import numpy as np
import pandas as pd


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's RMA (Pine ta.rma)。alpha = 1/length，種子用前 length 個值的 SMA。

    Pine 的 ta.rma 第一個有效值 = SMA(length)，之後遞迴。
    用 ewm(alpha=1/length, adjust=False) 並以 SMA 種子起算可精確重現。
    """
    length = int(length)
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    alpha = 1.0 / length
    # 找第一個非 NaN
    valid = ~np.isnan(arr)
    if valid.sum() < length:
        return pd.Series(out, index=series.index)
    # 第一個可計算 SMA 的位置
    first = np.argmax(valid)  # 第一個 True 的 index
    # 累積到湊滿 length 個有效值
    start = None
    cnt = 0
    s = 0.0
    for i in range(first, n):
        if not np.isnan(arr[i]):
            s += arr[i]
            cnt += 1
            if cnt == length:
                start = i
                out[i] = s / length
                break
    if start is None:
        return pd.Series(out, index=series.index)
    prev = out[start]
    for i in range(start + 1, n):
        x = arr[i]
        if np.isnan(x):
            out[i] = prev  # Pine 對 NaN 通常沿用；資料已清過故罕見
            continue
        prev = alpha * x + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=series.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    """Pine ta.tr(true): max(high-low, |high-close[1]|, |low-close[1]|)。
    第一根用 high-low。"""
    high = df["High"]
    low = df["Low"]
    close_prev = df["Close"].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    tr.iloc[0] = (high.iloc[0] - low.iloc[0])
    return tr


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    """Pine ta.atr(length) = rma(tr, length)。"""
    return rma(true_range(df), length)


def supertrend(df: pd.DataFrame, factor: float, atr_period: int):
    """Pine ta.supertrend(factor, atrPeriod) 的忠實重現。

    回傳 (supertrend_line, direction)；direction < 0 代表多頭（與 Pine 一致）。

    Pine 演算法（v5 內建）：
      atr = ta.atr(atrPeriod)
      hl2 = (high+low)/2
      upperBasic = hl2 + factor*atr ; lowerBasic = hl2 - factor*atr
      lowerBand = lowerBasic > lowerBand[1] or close[1] < lowerBand[1] ? lowerBasic : lowerBand[1]
      upperBand = upperBasic < upperBand[1] or close[1] > upperBand[1] ? upperBasic : upperBand[1]
      方向判定：
        if prevSuperTrend == prevUpperBand:
            dir = close > upperBand ? -1 : 1
        else:
            dir = close < lowerBand ? 1 : -1
      superTrend = dir == -1 ? lowerBand : upperBand
    """
    a = atr(df, atr_period).to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    hl2 = ((df["High"] + df["Low"]) / 2.0).to_numpy(dtype=float)
    n = len(close)

    upper_basic = hl2 + factor * a
    lower_basic = hl2 - factor * a

    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(a[i]):
            continue
        if np.isnan(lower_band[i - 1]) if i > 0 else True:
            lower_band[i] = lower_basic[i]
            upper_band[i] = upper_basic[i]
            direction[i] = 1  # Pine: 初始 dir = 1（空），首根 superTrend = upperBand
            st[i] = upper_band[i]
            continue
        # lowerBand
        if lower_basic[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
            lower_band[i] = lower_basic[i]
        else:
            lower_band[i] = lower_band[i - 1]
        # upperBand
        if upper_basic[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
            upper_band[i] = upper_basic[i]
        else:
            upper_band[i] = upper_band[i - 1]
        # direction
        prev_st = st[i - 1]
        prev_upper = upper_band[i - 1]
        if prev_st == prev_upper:
            direction[i] = -1 if close[i] > upper_band[i] else 1
        else:
            direction[i] = 1 if close[i] < lower_band[i] else -1
        st[i] = lower_band[i] if direction[i] == -1 else upper_band[i]

    return (pd.Series(st, index=df.index), pd.Series(direction, index=df.index))


def dmi(df: pd.DataFrame, di_len: int, adx_len: int):
    """Pine ta.dmi(diLen, adxLen) → (+DI, -DI, ADX)。全部 Wilder RMA 平滑。"""
    high = df["High"]
    low = df["Low"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    tr = true_range(df)
    tr_rma = rma(tr, di_len)
    plus_di = 100.0 * rma(plus_dm, di_len) / tr_rma
    minus_di = 100.0 * rma(minus_dm, di_len) / tr_rma

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = rma(dx.fillna(0.0), adx_len)
    return plus_di, minus_di, adx


def kaufman_er(close: pd.Series, length: int) -> pd.Series:
    """Kaufman 效率比 = |close-close[n]| / sum(|close-close[1]|, n)。"""
    change = (close - close.shift(length)).abs()
    vol = close.diff().abs().rolling(length).sum()
    er = change / vol.replace(0, np.nan)
    return er.fillna(0.0)


def rolling_stdev(series: pd.Series, length: int) -> pd.Series:
    """Pine ta.stdev = 母體標準差（ddof=0）。"""
    return series.rolling(length).std(ddof=0)


def rolling_median(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).median()


def rolling_percentile(series: pd.Series, length: int, pct: float) -> pd.Series:
    """Pine ta.percentile_linear_interpolation(src, length, percentage)。
    線性插值百分位（numpy 'linear' 對應 Pine 慣例）。"""
    return series.rolling(length).quantile(pct / 100.0, interpolation="linear")
