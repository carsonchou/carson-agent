"""
核心契約（Contracts）— 所有模組共同遵守的介面定義。

這個檔案是整個系統的「合約層」：各 agent 並行開發時，
資料層、策略層、回測層、執行層、風控層都必須實作這裡定義的抽象介面，
彼此才能無縫接起來。請勿在此檔加入任何具體實作。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


# ────────────────────────────────────────────────────────────
# 列舉型別
# ────────────────────────────────────────────────────────────
class Side(str, Enum):
    """下單方向。"""
    BUY = "BUY"
    SELL = "SELL"


class SignalType(str, Enum):
    """策略訊號類型。"""
    OPEN_LONG = "OPEN_LONG"     # 開多
    OPEN_SHORT = "OPEN_SHORT"   # 開空
    CLOSE_LONG = "CLOSE_LONG"   # 平多
    CLOSE_SHORT = "CLOSE_SHORT" # 平空
    HOLD = "HOLD"               # 無動作


class OrderStatus(str, Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


# ────────────────────────────────────────────────────────────
# 資料模型
# ────────────────────────────────────────────────────────────
@dataclass
class Candle:
    """單根 K 棒（OHLCV）。"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    """策略產生的交易訊號。"""
    type: SignalType
    symbol: str
    timestamp: datetime
    price: float                       # 訊號當下參考價
    confidence: float = 1.0            # 0~1，供風控調整倉位
    size_pct: Optional[float] = None   # 建議倉位比例（None=交給風控決定）
    reason: str = ""                   # 觸發說明（便於追蹤）
    meta: dict = field(default_factory=dict)


@dataclass
class Order:
    """送往交易所的下單請求 / 回報。"""
    symbol: str
    side: Side
    quantity: float
    price: Optional[float] = None      # None = 市價單
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    raw: dict = field(default_factory=dict)  # 交易所原始回應


@dataclass
class Position:
    """目前持倉狀態。"""
    symbol: str
    size: float = 0.0                  # 正=多, 負=空, 0=空手
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class BacktestResult:
    """回測績效結果。"""
    equity_curve: pd.Series
    trades: pd.DataFrame
    sharpe: float
    calmar: float
    max_drawdown: float
    total_return: float
    win_rate: float
    profit_factor: float
    num_trades: int
    metrics: dict = field(default_factory=dict)


# ────────────────────────────────────────────────────────────
# 抽象介面（各 agent 實作對象）
# ────────────────────────────────────────────────────────────
class DataFeed(ABC):
    """資料來源抽象。Pionex / TradingView 各自實作此介面。"""

    @abstractmethod
    def get_historical(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """回傳歷史 K 棒，欄位：[timestamp, open, high, low, close, volume]，timestamp 為 index。"""
        ...

    @abstractmethod
    def get_latest(self, symbol: str, interval: str) -> Candle:
        """回傳最新一根（已收盤）K 棒。"""
        ...


class Strategy(ABC):
    """交易策略抽象。輸入 K 棒 DataFrame，輸出訊號。"""

    name: str

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> Signal:
        """依當前資料產生最新訊號（須避免重繪：只用已收盤 K 棒）。"""
        ...

    @abstractmethod
    def warmup_bars(self) -> int:
        """指標暖機所需最少 K 棒數。"""
        ...


class Executor(ABC):
    """下單執行抽象。實盤(Pionex) / 紙上(paper) 各自實作。"""

    @abstractmethod
    def submit(self, order: Order) -> Order:
        """送出訂單並回傳含狀態的 Order。"""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        ...

    @abstractmethod
    def get_balance(self, asset: str) -> float:
        ...


class RiskManager(ABC):
    """風控抽象：把訊號轉成「經風控核可」的下單。"""

    @abstractmethod
    def evaluate(self, signal: Signal, position: Position, equity: float) -> Optional[Order]:
        """回傳核可後的 Order；若風控否決則回傳 None。"""
        ...

    @abstractmethod
    def check_stops(self, position: Position, candle: Candle) -> Optional[Order]:
        """檢查停損/停利，需要平倉時回傳平倉 Order。"""
        ...
