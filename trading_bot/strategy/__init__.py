"""
策略層 (strategy)。

對外匯出：
- 指標純函式：atr / supertrend / ema
- 策略基底：BaseStrategy
- 具體策略：SuperTrendStrategy
"""
from __future__ import annotations

from .base import BaseStrategy
from .supertrend import SuperTrendStrategy
from .smc import SMCStrategy
# 注意：先 import 子模組 supertrend，再 import 指標函式 supertrend，
# 確保套件命名空間中的 `supertrend` 綁定到「函式」而非「子模組」。
from .indicators import atr, ema, supertrend


def create_strategy(name: str, **params):
    """
    策略工廠：依名稱建立策略實例（main.build_strategy 會優先呼叫本函式）。

    支援：
      - "supertrend" / "super_trend" → SuperTrendStrategy（單一 SuperTrend 翻轉）
      - "smc"                        → SMCStrategy（Smart Money Concepts：BOS/CHoCH + FVG）

    params 直接來自 config.strategy.params；未知參數由各策略建構子忽略或報錯。
    """
    key = (name or "").strip().lower()
    if key in ("supertrend", "super_trend"):
        return SuperTrendStrategy(**params)
    if key in ("smc", "smart_money", "smartmoney"):
        return SMCStrategy(**params)
    raise ValueError(
        f"未知策略名稱：{name!r}。可用：'supertrend'、'smc'。"
    )


__all__ = [
    "atr",
    "ema",
    "supertrend",
    "BaseStrategy",
    "SuperTrendStrategy",
    "SMCStrategy",
    "create_strategy",
]
