"""
設定子套件 — 對外只暴露載入器與資料模型。

使用範例：
    from config import load_config
    cfg = load_config()            # 自動找 config.yaml，否則回退 example
    print(cfg.trading.symbol)
"""
from __future__ import annotations

from .loader import load_config
from .models import (
    AppConfig,
    DataConfig,
    NotifyConfig,
    PionexConfig,
    RiskConfig,
    StrategyConfig,
    TradingConfig,
)

__all__ = [
    "load_config",
    "AppConfig",
    "PionexConfig",
    "TradingConfig",
    "StrategyConfig",
    "RiskConfig",
    "DataConfig",
    "NotifyConfig",
]
