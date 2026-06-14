"""
風控與監控模組（risk/）。

- BasicRiskManager：實作 RiskManager 介面，負責倉位計算、停損、單日虧損上限、曝險上限。
- Monitor：以 rich 顯示即時終端機面板，並提供 alert() 告警介面。

匯出：
    >>> from trading_bot.risk import BasicRiskManager, Monitor
"""
from __future__ import annotations

from .risk_manager import BasicRiskManager
from .monitor import Monitor

__all__ = ["BasicRiskManager", "Monitor"]
