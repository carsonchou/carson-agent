"""
協調層子套件 — 多 agent runtime 協調者。

對外暴露 TradingCoordinator 與其組成的各個 agent 包裝類別，
讓 main.py 能組裝並啟動整個交易迴圈。
"""
from __future__ import annotations

from .coordinator import (
    DataAgent,
    ExecutionAgent,
    MonitorAgent,
    RiskAgent,
    StrategyAgent,
    TradingCoordinator,
)

__all__ = [
    "TradingCoordinator",
    "DataAgent",
    "StrategyAgent",
    "RiskAgent",
    "ExecutionAgent",
    "MonitorAgent",
]
