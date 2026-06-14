"""
core — 核心契約層。

只包含抽象介面（DataFeed / Strategy / Executor / RiskManager）與
資料模型（Candle / Signal / Order / Position / BacktestResult）。
請勿在此放任何具體實作，以保持各模組可並行開發、無縫對接。
"""
from .interfaces import (
    BacktestResult,
    Candle,
    DataFeed,
    Executor,
    Order,
    OrderStatus,
    Position,
    RiskManager,
    Side,
    Signal,
    SignalType,
    Strategy,
)

__all__ = [
    "Side",
    "SignalType",
    "OrderStatus",
    "Candle",
    "Signal",
    "Order",
    "Position",
    "BacktestResult",
    "DataFeed",
    "Strategy",
    "Executor",
    "RiskManager",
]
