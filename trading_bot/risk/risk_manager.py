"""
基礎風控管理器（BasicRiskManager）。

職責：
    1. 依 config 的 ``position_pct`` 計算每筆下單的倉位大小（佔權益百分比）。
    2. 套用硬性停損 ``stop_loss_pct``（check_stops 判斷是否需要平倉）。
    3. 監控 ``max_daily_loss_pct``：當日累計虧損超過上限時，否決所有新開倉。
    4. 套用 ``max_position_pct`` 曝險上限：避免單一標的曝險超過權益的一定比例。

設計重點：
    - 嚴格遵守 core.interfaces.RiskManager 的抽象介面，函式簽章不可更動。
    - evaluate() 把策略 Signal 轉成「經風控核可」的 Order，否決時回傳 None。
    - check_stops() 依持倉與最新 K 棒判斷是否觸發停損，需要平倉時回傳平倉 Order。
    - 風控本身不送單、不碰交易所；是否真的下單（dry_run）由 Executor 決定。
    - 內部維護「當日已實現損益」狀態，需由外部（交易迴圈）在平倉成交時回報。

使用方式：
    >>> from trading_bot.risk import BasicRiskManager
    >>> rm = BasicRiskManager(config["risk"])
    >>> order = rm.evaluate(signal, position, equity)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

# ── 依賴抽象介面（缺檔時給清楚錯誤）──
try:
    from core.interfaces import (
        Candle,
        Order,
        OrderStatus,
        Position,
        RiskManager,
        Side,
        Signal,
        SignalType,
    )
except ImportError as exc:  # pragma: no cover - 匯入失敗時的友善提示
    raise ImportError(
        "無法匯入 core.interfaces，請確認 trading_bot 套件結構完整，"
        "且從專案根目錄執行（例如 `python -m trading_bot...`）。\n"
        f"原始錯誤：{exc}"
    ) from exc


class BasicRiskManager(RiskManager):
    """依設定檔風控參數運作的基礎風控管理器。"""

    def __init__(
        self,
        risk_config: dict,
        symbol: Optional[str] = None,
        *,
        clock: Optional[type] = None,
    ) -> None:
        """
        參數
        ----
        risk_config:
            config.yaml 中 ``risk`` 區塊的字典，需含：
            position_pct / stop_loss_pct / max_daily_loss_pct / max_position_pct。
            缺漏欄位會套用保守預設值。
        symbol:
            （選填）此風控管理器負責的標的；僅用於記錄，不影響邏輯。
        clock:
            （選填）提供 ``today()`` 與 ``now()`` 的時間來源，方便單元測試注入。
            預設使用標準 ``datetime``。
        """
        cfg = risk_config or {}

        # ── 風控參數（百分比，0~100）──
        self.position_pct: float = float(cfg.get("position_pct", 100.0))
        self.stop_loss_pct: float = float(cfg.get("stop_loss_pct", 2.0))
        self.max_daily_loss_pct: float = float(cfg.get("max_daily_loss_pct", 10.0))
        self.max_position_pct: float = float(cfg.get("max_position_pct", 100.0))

        self.symbol = symbol
        self._clock = clock or datetime

        # ── 當日損益追蹤狀態 ──
        self._today: date = self._current_date()
        self._daily_realized_pnl: float = 0.0   # 當日已實現損益（虧損為負）
        self._daily_start_equity: float = 0.0   # 當日起始權益（首次評估時設定）

        # ── 否決原因（供 Monitor / log 觀察）──
        self.last_rejection: Optional[str] = None

    # ────────────────────────────────────────────────────────────
    # 時間輔助（可被注入的 clock 取代，利於測試）
    # ────────────────────────────────────────────────────────────
    def _current_date(self) -> date:
        now = self._clock.now()
        return now.date() if isinstance(now, datetime) else now

    def _roll_day_if_needed(self, equity: float) -> None:
        """跨日時重置當日損益統計。"""
        today = self._current_date()
        if today != self._today:
            self._today = today
            self._daily_realized_pnl = 0.0
            self._daily_start_equity = equity

    # ────────────────────────────────────────────────────────────
    # 外部回報接口：當日損益狀態維護
    # ────────────────────────────────────────────────────────────
    def register_realized_pnl(self, pnl: float) -> None:
        """
        由交易迴圈在「平倉成交」後呼叫，累計當日已實現損益。

        參數
        ----
        pnl:
            本次平倉的已實現損益（獲利為正、虧損為負）。
        """
        self._daily_realized_pnl += float(pnl)

    def reset_daily(self, start_equity: float = 0.0) -> None:
        """手動重置當日損益統計（例如系統啟動時呼叫）。"""
        self._today = self._current_date()
        self._daily_realized_pnl = 0.0
        self._daily_start_equity = float(start_equity)

    @property
    def daily_realized_pnl(self) -> float:
        """當日累計已實現損益（唯讀）。"""
        return self._daily_realized_pnl

    def daily_loss_limit_hit(self, equity: float) -> bool:
        """
        判斷當日累計虧損是否已達 ``max_daily_loss_pct`` 上限。

        以「當日起始權益」為基準計算虧損百分比；若尚未設定起始權益，
        則退而使用傳入的當前 equity 作基準。
        """
        base = self._daily_start_equity or equity
        if base <= 0:
            return False
        # 僅在淨虧損（pnl < 0）時才需要檢查
        if self._daily_realized_pnl >= 0:
            return False
        loss_pct = (-self._daily_realized_pnl / base) * 100.0
        return loss_pct >= self.max_daily_loss_pct

    # ────────────────────────────────────────────────────────────
    # 核心：訊號 → 核可下單
    # ────────────────────────────────────────────────────────────
    def evaluate(
        self, signal: Signal, position: Position, equity: float
    ) -> Optional[Order]:
        """
        把策略 Signal 轉成「經風控核可」的 Order，否決時回傳 None。

        否決條件（任一成立即否決開倉）：
            - HOLD 訊號（不下單）。
            - 當日虧損已達上限（max_daily_loss_pct）。
            - 計算出的倉位會使總曝險超過 max_position_pct。
            - 權益或價格不合理（<= 0）。

        平倉訊號（CLOSE_LONG / CLOSE_SHORT）不受開倉曝險/虧損上限限制——
        平倉是降低風險的動作，必須允許執行。
        """
        self.last_rejection = None
        self._roll_day_if_needed(equity)

        # 首次評估：建立當日起始權益基準
        if self._daily_start_equity == 0.0 and equity > 0:
            self._daily_start_equity = equity

        # ── 基本健全性檢查 ──
        if signal is None or signal.type == SignalType.HOLD:
            self.last_rejection = "HOLD/無訊號"
            return None

        if equity <= 0:
            self.last_rejection = "權益不足（equity <= 0）"
            return None

        if signal.price is None or signal.price <= 0:
            self.last_rejection = "訊號價格不合理"
            return None

        # ── 平倉訊號優先處理（不受開倉限制）──
        if signal.type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            return self._build_close_order(signal, position)

        # ── 開倉訊號：套用風控上限 ──
        # 1) 當日虧損上限
        if self.daily_loss_limit_hit(equity):
            self.last_rejection = (
                f"當日虧損達上限 {self.max_daily_loss_pct:.1f}%，停止開新倉"
            )
            return None

        # 2) 決定倉位比例：優先用訊號建議，否則用 config 的 position_pct，
        #    再依 confidence 微調，最後不得超過 max_position_pct。
        size_pct = signal.size_pct if signal.size_pct is not None else self.position_pct
        # confidence 容錯：策略可能送 None（介面雖預設 1.0，但明確傳 None 會讓
        # float(None) 拋 TypeError 使整個 evaluate 崩潰，連停損都評估不到 → fail-open）。
        conf_raw = signal.confidence if signal.confidence is not None else 1.0
        confidence = max(0.0, min(1.0, float(conf_raw)))
        size_pct = size_pct * confidence

        # 3) 曝險上限：考量既有持倉的同向曝險
        size_pct = self._apply_exposure_cap(signal, position, equity, size_pct)
        if size_pct <= 0:
            self.last_rejection = (
                f"曝險已達上限 {self.max_position_pct:.1f}%，無可加倉空間"
            )
            return None

        # 4) 換算下單數量（標的數量）
        notional = equity * (size_pct / 100.0)
        quantity = notional / signal.price
        if quantity <= 0:
            self.last_rejection = "計算後下單數量為 0"
            return None

        side = Side.BUY if signal.type == SignalType.OPEN_LONG else Side.SELL

        return Order(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            price=None,  # 市價單；策略若需限價可於 meta 帶入
            status=OrderStatus.NEW,
            raw={
                "source": "BasicRiskManager.evaluate",
                "signal_type": signal.type.value,
                "size_pct": round(size_pct, 4),
                "confidence": confidence,
                "reason": signal.reason,
            },
        )

    def _apply_exposure_cap(
        self, signal: Signal, position: Position, equity: float, size_pct: float
    ) -> float:
        """
        依 max_position_pct 限制「同向加倉」後的總曝險，回傳可用的下單比例。

        - 反向開倉（手上是空、要開多）視為先平再開，不受加倉上限限制。
        - 同向加倉時，計算既有曝險佔比，僅允許補到 max_position_pct 為止。
        """
        if equity <= 0:
            return 0.0

        # 既有持倉的曝險百分比（取絕對值）
        current_notional = abs(position.size) * (signal.price if signal.price else 0.0)
        current_pct = (current_notional / equity) * 100.0 if equity > 0 else 0.0

        opening_long = signal.type == SignalType.OPEN_LONG
        # 判斷是否同向加倉：持倉方向與訊號方向相同
        same_direction = (
            (opening_long and position.size > 0)
            or (not opening_long and position.size < 0)
        )

        if same_direction:
            remaining = self.max_position_pct - current_pct
            if remaining <= 0:
                return 0.0
            return min(size_pct, remaining)

        # 反向或空手：直接受單筆上限約束
        return min(size_pct, self.max_position_pct)

    def _build_close_order(self, signal: Signal, position: Position) -> Optional[Order]:
        """產生平倉 Order：以當前持倉數量反向市價平倉。"""
        if position is None or position.size == 0:
            self.last_rejection = "無持倉可平"
            return None

        # 平多→賣出；平空→買回
        side = Side.SELL if position.size > 0 else Side.BUY
        quantity = abs(position.size)

        return Order(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            price=None,
            status=OrderStatus.NEW,
            raw={
                "source": "BasicRiskManager.evaluate",
                "signal_type": signal.type.value,
                "action": "CLOSE",
                "reason": signal.reason,
            },
        )

    # ────────────────────────────────────────────────────────────
    # 核心：停損判斷
    # ────────────────────────────────────────────────────────────
    def check_stops(self, position: Position, candle: Candle) -> Optional[Order]:
        """
        依硬性停損 ``stop_loss_pct`` 判斷是否需要平倉。

        多單：收盤價跌破 進場價 *(1 - stop_loss_pct%) → 平倉。
        空單：收盤價漲破 進場價 *(1 + stop_loss_pct%) → 平倉。

        觸發時回傳反向市價平倉 Order；否則回傳 None。
        """
        if position is None or position.size == 0:
            return None
        if position.entry_price is None or position.entry_price <= 0:
            return None
        if candle is None or candle.close is None or candle.close <= 0:
            return None
        if self.stop_loss_pct <= 0:
            return None

        stop_frac = self.stop_loss_pct / 100.0
        price = candle.close

        triggered = False
        if position.size > 0:  # 多單
            stop_price = position.entry_price * (1.0 - stop_frac)
            triggered = price <= stop_price
        else:                  # 空單
            stop_price = position.entry_price * (1.0 + stop_frac)
            triggered = price >= stop_price

        if not triggered:
            return None

        side = Side.SELL if position.size > 0 else Side.BUY
        return Order(
            symbol=position.symbol,
            side=side,
            quantity=abs(position.size),
            price=None,
            status=OrderStatus.NEW,
            raw={
                "source": "BasicRiskManager.check_stops",
                "action": "STOP_LOSS",
                "entry_price": position.entry_price,
                "stop_price": round(stop_price, 8),
                "trigger_price": price,
                "stop_loss_pct": self.stop_loss_pct,
            },
        )
