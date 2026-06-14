"""
回測績效指標計算（純函式）。

本模組只負責「數學」：吃權益曲線（equity curve）或交易紀錄（trades），
回傳各種績效指標。所有函式皆為純函式、無副作用、可單獨測試。

設計原則：
    - 不依賴 core.interfaces，避免循環匯入；engine 會把結果組裝成 BacktestResult。
    - 輸入退化（空序列、單點、零波動）時回傳合理的預設值（多為 0.0），不丟例外。
    - 年化相關指標需提供 periods_per_year（每年的 K 棒數），由呼叫端依週期換算。
"""
from __future__ import annotations

from typing import Sequence, Union

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover - 缺套件時給清楚錯誤
    raise ImportError(
        "backtest.metrics 需要 numpy 與 pandas，請先安裝：pip install numpy pandas"
    ) from exc


# 型別別名：可接受 pandas.Series 或一般序列
EquityLike = Union["pd.Series", Sequence[float]]


# ────────────────────────────────────────────────────────────
# 內部工具
# ────────────────────────────────────────────────────────────
def _to_series(equity: EquityLike) -> "pd.Series":
    """把任意序列轉成 float 型別的 pandas.Series。"""
    if isinstance(equity, pd.Series):
        return equity.astype(float)
    return pd.Series(list(equity), dtype=float)


def _returns_from_equity(equity: EquityLike) -> "pd.Series":
    """由權益曲線推算每期報酬率（pct_change），去除 NaN/Inf。"""
    s = _to_series(equity)
    if len(s) < 2:
        return pd.Series([], dtype=float)
    rets = s.pct_change().dropna()
    # 權益若出現 0 會產生 inf，這裡濾掉避免污染統計
    rets = rets.replace([np.inf, -np.inf], np.nan).dropna()
    return rets


# ────────────────────────────────────────────────────────────
# 權益曲線類指標
# ────────────────────────────────────────────────────────────
def total_return(equity: EquityLike) -> float:
    """
    總報酬率 = 期末權益 / 期初權益 - 1。

    例如期初 10000、期末 12000，回傳 0.20（即 +20%）。
    期初為 0 或序列過短時回傳 0.0。
    """
    s = _to_series(equity)
    if len(s) < 2:
        return 0.0
    start = float(s.iloc[0])
    end = float(s.iloc[-1])
    if start == 0.0:
        return 0.0
    return end / start - 1.0


def max_drawdown(equity: EquityLike) -> float:
    """
    最大回撤（Maximum Drawdown），以「正的比例」回傳。

    定義：權益曲線從歷史高點回落的最大幅度。
    回傳值範圍 0.0 ~ 1.0，例如 0.25 代表最深曾回落 25%。
    序列過短回傳 0.0。
    """
    s = _to_series(equity)
    if len(s) < 2:
        return 0.0
    running_max = s.cummax()
    # 避免除以 0：running_max 為 0 的位置回撤視為 0
    drawdown = (s - running_max) / running_max.replace(0.0, np.nan)
    drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mdd = float(drawdown.min())  # 最深回撤為負值
    return abs(mdd)


def sharpe(
    equity: EquityLike,
    periods_per_year: int = 365,
    risk_free_rate: float = 0.0,
) -> float:
    """
    年化夏普比率（Sharpe Ratio）。

    參數：
        equity            : 權益曲線。
        periods_per_year  : 每年的 K 棒數（用於年化）。
                            例如日線 365、15 分鐘線 ≈ 365*96。
        risk_free_rate    : 年化無風險利率（預設 0）。

    計算：以每期報酬率的平均/標準差，乘上 sqrt(periods_per_year) 年化。
    報酬無波動（std=0）或樣本不足時回傳 0.0。
    """
    rets = _returns_from_equity(equity)
    if len(rets) < 2:
        return 0.0
    # 把年化無風險利率拆成每期，從報酬中扣除
    per_period_rf = risk_free_rate / periods_per_year
    excess = rets - per_period_rf
    std = float(excess.std(ddof=1))
    if std == 0.0 or np.isnan(std):
        return 0.0
    mean = float(excess.mean())
    return mean / std * np.sqrt(periods_per_year)


def calmar(equity: EquityLike, periods_per_year: int = 365) -> float:
    """
    年化卡瑪比率（Calmar Ratio）= 年化報酬 / 最大回撤。

    年化報酬以複利方式由總報酬換算：
        annual = (1 + total_return) ** (periods_per_year / n_periods) - 1
    最大回撤為 0（無回撤）時回傳 0.0，避免除以 0。
    """
    s = _to_series(equity)
    if len(s) < 2:
        return 0.0
    n_periods = len(s) - 1
    tr = total_return(s)
    base = 1.0 + tr
    if base <= 0.0:
        # 權益歸零/翻負，年化報酬無意義，視為極差
        annual_return = -1.0
    else:
        annual_return = base ** (periods_per_year / n_periods) - 1.0
    mdd = max_drawdown(s)
    if mdd == 0.0:
        return 0.0
    return annual_return / mdd


# ────────────────────────────────────────────────────────────
# 交易紀錄類指標
# ────────────────────────────────────────────────────────────
def _extract_pnl(trades: Union["pd.DataFrame", Sequence[float]]) -> "pd.Series":
    """
    從交易紀錄取出每筆已實現損益（pnl）。

    支援兩種輸入：
        - pandas.DataFrame：需有 'pnl' 欄位（每筆交易的淨損益）。
        - 一般序列：直接視為 pnl 數列。
    """
    if isinstance(trades, pd.DataFrame):
        if trades.empty or "pnl" not in trades.columns:
            return pd.Series([], dtype=float)
        return trades["pnl"].astype(float).dropna()
    return pd.Series(list(trades), dtype=float).dropna()


def win_rate(trades: Union["pd.DataFrame", Sequence[float]]) -> float:
    """
    勝率 = 獲利交易數 / 總交易數，範圍 0.0 ~ 1.0。

    pnl > 0 視為獲利；pnl == 0（持平）不計入獲利。無交易回傳 0.0。
    """
    pnl = _extract_pnl(trades)
    if len(pnl) == 0:
        return 0.0
    wins = int((pnl > 0).sum())
    return wins / len(pnl)


def profit_factor(trades: Union["pd.DataFrame", Sequence[float]]) -> float:
    """
    獲利因子（Profit Factor）= 總獲利 / 總虧損（取絕對值）。

    > 1 代表整體獲利。若無任何虧損交易但有獲利，回傳 inf；
    完全無交易或無獲利時回傳 0.0。
    """
    pnl = _extract_pnl(trades)
    if len(pnl) == 0:
        return 0.0
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())  # 轉正值
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


# ────────────────────────────────────────────────────────────
# 一次算齊（便利函式）
# ────────────────────────────────────────────────────────────
def compute_all(
    equity: EquityLike,
    trades: Union["pd.DataFrame", Sequence[float]],
    periods_per_year: int = 365,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    一次計算所有指標，回傳 dict。供 BacktestEngine 組裝 BacktestResult。

    回傳鍵：
        sharpe, calmar, max_drawdown, total_return,
        win_rate, profit_factor, num_trades
    """
    pnl = _extract_pnl(trades)
    return {
        "sharpe": sharpe(equity, periods_per_year, risk_free_rate),
        "calmar": calmar(equity, periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "total_return": total_return(equity),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "num_trades": int(len(pnl)),
    }
