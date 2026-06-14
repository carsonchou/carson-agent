"""
技術指標（純函式）。

設計原則：
- 全部以 pandas / numpy 自行實作，不依賴會「重繪」(repaint) 的寫法。
- 函式皆為純函式：相同輸入永遠得到相同輸出，不持有狀態。
- 只使用「過去到當下」的資料計算，不引用未來 K 棒，避免前視偏誤(look-ahead bias)。

對外提供：
- atr(df, length)                  → 平均真實波幅 (Series)
- supertrend(df, length, mult)     → (方向 Series[1/-1], 軌道線 Series)
- ema(series, length)              → 指數移動平均 (Series)
"""
from __future__ import annotations

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover - 缺套件時給清楚錯誤
    raise ImportError(
        "indicators 需要 pandas 與 numpy，請先安裝：pip install pandas numpy"
    ) from exc


# ────────────────────────────────────────────────────────────
# 內部工具
# ────────────────────────────────────────────────────────────
def _require_columns(df: "pd.DataFrame", cols: tuple[str, ...]) -> None:
    """檢查 DataFrame 是否含有指定欄位，缺欄位時給清楚錯誤。"""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(
            f"DataFrame 缺少必要欄位 {missing}；現有欄位：{list(df.columns)}"
        )


def true_range(df: "pd.DataFrame") -> "pd.Series":
    """
    真實波幅 (True Range)。

    TR = max(
        high - low,
        |high - prev_close|,
        |low  - prev_close|,
    )

    第一根 K 棒沒有前收盤，TR 退化為 high - low。
    """
    _require_columns(df, ("high", "low", "close"))

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)

    range1 = high - low
    range2 = (high - prev_close).abs()
    range3 = (low - prev_close).abs()

    tr = pd.concat([range1, range2, range3], axis=1).max(axis=1)
    # 首根以 high-low 補上
    tr.iloc[0] = range1.iloc[0]
    return tr.rename("tr")


# ────────────────────────────────────────────────────────────
# ATR
# ────────────────────────────────────────────────────────────
def atr(df: "pd.DataFrame", length: int = 14) -> "pd.Series":
    """
    平均真實波幅 (Average True Range)。

    採用 Wilder 平滑法（即 RMA / 等同 alpha=1/length 的 EMA），
    這是 SuperTrend 標準作法，可避免簡單 SMA 在窗口邊界造成的跳動。

    參數
    ----
    df     : 含 high / low / close 欄位的 DataFrame
    length : 平滑週期（預設 14）

    回傳
    ----
    與 df 等長的 ATR Series（前段暖機期為 NaN）
    """
    if length < 1:
        raise ValueError(f"atr length 必須 >= 1，收到 {length}")

    tr = true_range(df)
    # Wilder 平滑：RMA = EMA(alpha = 1/length)，min_periods 確保暖機足夠才出值
    atr_series = tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    return atr_series.rename(f"atr_{length}")


# ────────────────────────────────────────────────────────────
# EMA
# ────────────────────────────────────────────────────────────
def ema(series: "pd.Series", length: int) -> "pd.Series":
    """
    指數移動平均 (Exponential Moving Average)。

    參數
    ----
    series : 輸入序列（通常為收盤價）
    length : 週期

    回傳
    ----
    等長 EMA Series（前 length-1 根為 NaN 暖機）
    """
    if length < 1:
        raise ValueError(f"ema length 必須 >= 1，收到 {length}")
    s = series.astype(float)
    return s.ewm(span=length, adjust=False, min_periods=length).mean().rename(
        f"ema_{length}"
    )


# ────────────────────────────────────────────────────────────
# SuperTrend
# ────────────────────────────────────────────────────────────
def supertrend(
    df: "pd.DataFrame",
    length: int = 10,
    mult: float = 3.0,
) -> "tuple[pd.Series, pd.Series]":
    """
    SuperTrend 指標（非重繪版本）。

    計算邏輯
    --------
    1. hl2 = (high + low) / 2
    2. 基本上下軌：
         upper_basic = hl2 + mult * ATR
         lower_basic = hl2 - mult * ATR
    3. 最終軌道（帶記憶、單向收斂，避免抖動）：
         final_upper[i] = min(upper_basic[i], final_upper[i-1])  若 close[i-1] <= final_upper[i-1]
                          否則 upper_basic[i]
         final_lower[i] = max(lower_basic[i], final_lower[i-1])  若 close[i-1] >= final_lower[i-1]
                          否則 lower_basic[i]
    4. 趨勢方向：
         - 收盤突破上軌 → 轉多 (direction = 1)，軌道線取 final_lower
         - 收盤跌破下軌 → 轉空 (direction = -1)，軌道線取 final_upper
         - 否則延續前一根方向

    非重繪保證
    ----------
    方向只依「已收盤」的 close 與「前一根」軌道決定；
    每根 K 棒收盤後其方向就固定，不會因後續資料而改變。
    呼叫端應只取倒數第二根（最後一根『已收盤』）作為訊號依據。

    參數
    ----
    df     : 含 high / low / close 欄位的 DataFrame（index 建議為時間）
    length : ATR 週期（預設 10）
    mult   : ATR 倍數（預設 3.0）

    回傳
    ----
    (direction, trend_line)
      direction  : Series[int]，1 = 多頭趨勢、-1 = 空頭趨勢（暖機期為 NaN）
      trend_line : Series[float]，當前生效的 SuperTrend 軌道線
    """
    if length < 1:
        raise ValueError(f"supertrend length 必須 >= 1，收到 {length}")
    if mult <= 0:
        raise ValueError(f"supertrend mult 必須 > 0，收到 {mult}")

    _require_columns(df, ("high", "low", "close"))

    n = len(df)
    close = df["close"].astype(float).to_numpy()
    hl2 = (df["high"].astype(float) + df["low"].astype(float)).to_numpy() / 2.0

    atr_vals = atr(df, length).to_numpy()

    upper_basic = hl2 + mult * atr_vals
    lower_basic = hl2 - mult * atr_vals

    final_upper = np.full(n, np.nan, dtype=float)
    final_lower = np.full(n, np.nan, dtype=float)
    direction = np.full(n, np.nan, dtype=float)
    trend_line = np.full(n, np.nan, dtype=float)

    # 第一根「ATR 有效」的位置作為起點（length-1，因 min_periods=length）
    start = length - 1
    if start >= n:
        # 資料量不足以暖機，全部回傳 NaN
        idx = df.index
        return (
            pd.Series(direction, index=idx, name="st_direction"),
            pd.Series(trend_line, index=idx, name="st_line"),
        )

    # 初始化起點：預設視為多頭，軌道取下軌
    final_upper[start] = upper_basic[start]
    final_lower[start] = lower_basic[start]
    direction[start] = 1.0
    trend_line[start] = final_lower[start]

    for i in range(start + 1, n):
        # ── 最終上軌：單向收斂 ──
        if (not np.isnan(upper_basic[i])) and (
            upper_basic[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]
        ):
            final_upper[i] = upper_basic[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # ── 最終下軌：單向收斂 ──
        if (not np.isnan(lower_basic[i])) and (
            lower_basic[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]
        ):
            final_lower[i] = lower_basic[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # ── 方向判定（依前一根方向與當前收盤突破狀況）──
        prev_dir = direction[i - 1]
        if prev_dir == 1.0:
            # 前一根多頭：收盤跌破下軌 → 轉空
            if close[i] < final_lower[i]:
                direction[i] = -1.0
            else:
                direction[i] = 1.0
        else:
            # 前一根空頭：收盤突破上軌 → 轉多
            if close[i] > final_upper[i]:
                direction[i] = 1.0
            else:
                direction[i] = -1.0

        # 軌道線：多頭看下軌、空頭看上軌
        trend_line[i] = final_lower[i] if direction[i] == 1.0 else final_upper[i]

    idx = df.index
    return (
        pd.Series(direction, index=idx, name="st_direction"),
        pd.Series(trend_line, index=idx, name="st_line"),
    )
