"""
回測層（backtest）— 事件驅動回測引擎與績效指標。

對外公開：
    BacktestEngine : 事件驅動回測引擎，吃 Strategy + 歷史 DataFrame，回傳 BacktestResult。
    metrics        : 純函式績效指標模組（sharpe / calmar / max_drawdown ...）。

最小使用範例（一行跑完並印出摘要）：
    >>> from backtest import BacktestEngine
    >>> result = BacktestEngine(my_strategy).run(df, interval="15M", print_summary=True)

也可單獨使用指標：
    >>> from backtest import metrics
    >>> metrics.sharpe(equity_curve, periods_per_year=365)
"""
from __future__ import annotations

from . import metrics
from .engine import BacktestEngine

__all__ = ["BacktestEngine", "metrics"]
