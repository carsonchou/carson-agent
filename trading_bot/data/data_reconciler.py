"""
資料交叉比對器（DataReconciler）。

把「主資料源」與「交叉比對源」的最新價格做比對，當兩者價差超過
設定的容忍百分比（divergence_tolerance_pct）時，回報 is_diverged=True，
供上層風控決定是否暫停交易（避免單一資料源異常導致錯誤下單）。

設計重點：
- 不直接依賴特定 feed 類別，僅依賴「能提供最新價格」的函式 / 物件，
  方便注入 PionexFeed、TradingViewFeed 或測試用假物件。
- 交叉比對源不可用（例如 tvdatafeed 未安裝）時，採 graceful 降級：
  回傳 is_diverged=False 並在結果中標註 cross_check_available=False，
  讓上層可選擇「容忍降級」或「保守暫停」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Union


# 可接受「物件（有 get_ticker_price / get_latest_price 方法）」或「直接給定的取價函式」。
PriceSource = Union[object, Callable[[str], float]]


@dataclass
class ReconcileResult:
    """交叉比對結果。"""
    symbol: str
    is_diverged: bool                     # True = 價差過大，建議暫停交易
    primary_price: Optional[float]        # 主源最新價
    secondary_price: Optional[float]      # 交叉比對源最新價
    divergence_pct: Optional[float]       # 實際價差百分比（相對主源）
    tolerance_pct: float                  # 容忍門檻
    cross_check_available: bool           # 交叉比對源是否可用
    timestamp: datetime                   # 比對當下時間（UTC）
    reason: str = ""                      # 文字說明（便於日誌追蹤）
    meta: dict = field(default_factory=dict)


class DataReconciler:
    """雙資料源最新價交叉比對器。"""

    def __init__(
        self,
        primary: PriceSource,
        secondary: Optional[PriceSource],
        divergence_tolerance_pct: float = 0.5,
        fail_open: bool = True,
    ) -> None:
        """
        參數：
            primary：主資料源（PionexFeed 或取價函式）。
            secondary：交叉比對源（TradingViewFeed 或取價函式）；None 代表停用交叉比對。
            divergence_tolerance_pct：價差容忍百分比（取自 config 的 data.divergence_tolerance_pct）。
            fail_open：交叉比對源不可用時的策略。
                       True  = 降級放行（is_diverged=False，由上層自行決定）。
                       False = 保守暫停（is_diverged=True）。
        """
        self.primary = primary
        self.secondary = secondary
        self.tolerance_pct = float(divergence_tolerance_pct)
        self.fail_open = fail_open

    # ────────────────────────────────────────────────────────────
    # 取價：相容多種來源型別
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _fetch_price(source: PriceSource, symbol: str) -> float:
        """從來源取得最新價格，相容函式與多種 feed 物件介面。"""
        # 1) 直接是可呼叫物件（取價函式）。
        if callable(source) and not hasattr(source, "get_ticker_price") \
                and not hasattr(source, "get_latest_price") \
                and not hasattr(source, "get_latest"):
            return float(source(symbol))

        # 2) PionexFeed 風格：get_ticker_price。
        if hasattr(source, "get_ticker_price"):
            return float(source.get_ticker_price(symbol))  # type: ignore[attr-defined]

        # 3) TradingViewFeed 風格：get_latest_price。
        if hasattr(source, "get_latest_price"):
            return float(source.get_latest_price(symbol))  # type: ignore[attr-defined]

        # 4) 通用 DataFeed：get_latest 回傳 Candle。
        if hasattr(source, "get_latest"):
            candle = source.get_latest(symbol, "1M")  # type: ignore[attr-defined]
            return float(candle.close)

        raise TypeError(
            f"無法從來源 {type(source).__name__} 取得價格："
            "需提供取價函式或具 get_ticker_price/get_latest_price/get_latest 的物件。"
        )

    @staticmethod
    def _compute_divergence_pct(primary_price: float, secondary_price: float) -> float:
        """計算相對主源的價差百分比（取絕對值）。"""
        if primary_price == 0:
            return float("inf")
        return abs(primary_price - secondary_price) / abs(primary_price) * 100.0

    # ────────────────────────────────────────────────────────────
    # 主要 API
    # ────────────────────────────────────────────────────────────
    def reconcile(self, symbol: str) -> ReconcileResult:
        """
        對指定標的做一次交叉比對。

        回傳 ReconcileResult；is_diverged=True 表示建議暫停交易。
        """
        now = datetime.now(timezone.utc)

        # 主源取價：主源失敗屬嚴重問題，無法判斷市況，採保守暫停。
        try:
            primary_price = self._fetch_price(self.primary, symbol)
        except Exception as exc:
            return ReconcileResult(
                symbol=symbol,
                is_diverged=True,
                primary_price=None,
                secondary_price=None,
                divergence_pct=None,
                tolerance_pct=self.tolerance_pct,
                cross_check_available=False,
                timestamp=now,
                reason=f"主資料源取價失敗，保守暫停：{exc}",
            )

        # 未設定交叉比對源 → 視為停用交叉比對，放行。
        if self.secondary is None:
            return ReconcileResult(
                symbol=symbol,
                is_diverged=False,
                primary_price=primary_price,
                secondary_price=None,
                divergence_pct=None,
                tolerance_pct=self.tolerance_pct,
                cross_check_available=False,
                timestamp=now,
                reason="未設定交叉比對源，僅用主源。",
            )

        # 交叉比對源取價：失敗則依 fail_open 策略降級。
        try:
            secondary_price = self._fetch_price(self.secondary, symbol)
        except Exception as exc:
            diverged = not self.fail_open
            reason = (
                f"交叉比對源不可用（{exc}）；"
                + ("保守暫停。" if diverged else "降級放行（fail_open）。")
            )
            return ReconcileResult(
                symbol=symbol,
                is_diverged=diverged,
                primary_price=primary_price,
                secondary_price=None,
                divergence_pct=None,
                tolerance_pct=self.tolerance_pct,
                cross_check_available=False,
                timestamp=now,
                reason=reason,
            )

        # 兩源都成功 → 計算價差。
        divergence_pct = self._compute_divergence_pct(primary_price, secondary_price)
        is_diverged = divergence_pct > self.tolerance_pct
        reason = (
            f"價差 {divergence_pct:.4f}% "
            + (">" if is_diverged else "<=")
            + f" 容忍 {self.tolerance_pct:.4f}%"
        )

        return ReconcileResult(
            symbol=symbol,
            is_diverged=is_diverged,
            primary_price=primary_price,
            secondary_price=secondary_price,
            divergence_pct=divergence_pct,
            tolerance_pct=self.tolerance_pct,
            cross_check_available=True,
            timestamp=now,
            reason=reason,
        )

    def is_safe_to_trade(self, symbol: str) -> bool:
        """便利方法：True 表示資料一致、可交易；False 表示背離、應暫停。"""
        return not self.reconcile(symbol).is_diverged
