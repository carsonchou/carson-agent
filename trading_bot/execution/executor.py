"""
執行層：把核心契約的 Order 真正送出（實盤）或模擬（紙上）。

提供三樣東西：
  - LiveExecutor  : 包 PionexClient，送真單到 Pionex（會二次檢查 dry_run）。
  - PaperExecutor : 純記憶體模擬，立即成交，記錄持倉與餘額。
  - build_executor: 工廠函式，依 config.dry_run 決定回傳哪一種。

安全核心：
  dry_run=true  → 一律回傳 PaperExecutor，永不觸網。
  dry_run=false → 回傳 LiveExecutor，但 submit() 內仍會再次確認 dry_run，雙重保險。
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from core.interfaces import (
    Executor,
    Order,
    OrderStatus,
    Position,
    Side,
)
from execution.pionex_client import PionexAPIError, PionexClient


# ════════════════════════════════════════════════════════════
# 實盤執行：包 PionexClient
# ════════════════════════════════════════════════════════════
class LiveExecutor(Executor):
    """
    實盤下單執行器，透過 PionexClient 與交易所溝通。

    參數
    ----
    client:  已建立的 PionexClient
    symbol:  預設交易對（用於餘額/持倉換算的計價幣判斷）
    dry_run: 安全旗標。理論上 build_executor 在 dry_run=true 時不會建立本類別，
             但此處仍保留旗標並於 submit() 二次檢查，作為最後一道防線。
    """

    def __init__(
        self,
        client: PionexClient,
        symbol: str,
        dry_run: bool = False,
        max_slippage_pct: float = 0.5,
    ) -> None:
        self.client = client
        self.symbol = symbol
        self.dry_run = dry_run
        # 市價單滑價保護上限（%）：>0 時把市價單轉成「參考價±此幅度」的保護限價，
        # 避免薄盤/瞬間波動以極差價成交。0 則維持純市價單。
        self.max_slippage_pct = float(max_slippage_pct)

    def submit(self, order: Order) -> Order:
        """送出訂單到 Pionex 並回傳含狀態的 Order。"""
        # ── 最後一道安全防線：即使被誤建為 Live，dry_run 仍能擋住真單 ──
        if self.dry_run:
            raise RuntimeError(
                "LiveExecutor 在 dry_run=true 狀態下被要求送單；已阻擋以保護資金。"
                "請改用 PaperExecutor（透過 build_executor 會自動處理）。"
            )

        side = order.side.value if isinstance(order.side, Side) else str(order.side)
        client_order_id = order.client_order_id or f"bot-{uuid.uuid4().hex[:16]}"

        # ── 滑價保護：市價單若有參考價，轉成帶上限的保護限價 ──
        order_type = "MARKET" if order.price is None else "LIMIT"
        send_price = order.price
        if order_type == "MARKET" and self.max_slippage_pct > 0:
            ref_price = float((order.raw or {}).get("ref_price", 0.0) or 0.0)
            if ref_price > 0:
                slip = self.max_slippage_pct / 100.0
                # 買單容許往上、賣單容許往下，超過即不成交（保護資金）
                send_price = ref_price * (1.0 + slip) if side == "BUY" else ref_price * (1.0 - slip)
                order_type = "LIMIT"

        try:
            resp = self.client.place_order(
                symbol=order.symbol,
                side=side,
                order_type=order_type,
                size=order.quantity,
                price=send_price,
                client_order_id=client_order_id,
            )
        except PionexAPIError as exc:
            # 下單被交易所拒絕：回傳 REJECTED 狀態，保留原始錯誤
            order.status = OrderStatus.REJECTED
            order.client_order_id = client_order_id
            order.raw = {"error": str(exc), "payload": getattr(exc, "payload", None)}
            return order

        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        order.client_order_id = client_order_id
        order.raw = resp if isinstance(resp, dict) else {"raw": resp}

        # 解析交易所回報的成交狀態
        exch_status = str(data.get("status", "")).upper()
        order.status = _map_pionex_status(exch_status)
        order.filled_qty = float(data.get("filledSize", data.get("filledQty", 0.0)) or 0.0)
        order.avg_fill_price = float(
            data.get("avgPrice", data.get("avgFillPrice", 0.0)) or 0.0
        )
        return order

    def get_position(self, symbol: str) -> Position:
        """
        查詢持倉。現貨以 base 資產餘額視為多頭持倉；查無則回空手。
        """
        base_asset = symbol.split("_")[0] if "_" in symbol else symbol
        try:
            size = self.client.get_balance(base_asset)
        except PionexAPIError:
            size = 0.0
        # 現貨無法直接取得進場均價，entry_price 交由上層自行追蹤
        return Position(symbol=symbol, size=size, entry_price=0.0, unrealized_pnl=0.0)

    def get_balance(self, asset: str) -> float:
        """查詢指定幣種可用餘額。"""
        return self.client.get_balance(asset)


# ════════════════════════════════════════════════════════════
# 紙上模擬執行：純記憶體，零觸網
# ════════════════════════════════════════════════════════════
class PaperExecutor(Executor):
    """
    純記憶體模擬執行器，不會連到任何交易所。

    成交模型（簡化）：訂單立即以參考價全額成交。
      - 市價單：以 order 帶入的 price 成交（若無則需上層補；預設視為當前價）
      - 限價單：以 order.price 成交

    餘額：以 quote 資產帳本記帳（預設 USDT），買進扣 quote、增 base；
    賣出反之。供回測/演練追蹤資金曲線。
    """

    def __init__(
        self,
        starting_balances: Optional[dict[str, float]] = None,
        quote_asset: str = "USDT",
    ) -> None:
        # 預設給一筆模擬資金，方便直接演練
        self.balances: dict[str, float] = dict(
            starting_balances or {quote_asset: 10_000.0}
        )
        self.quote_asset = quote_asset
        self._positions: dict[str, Position] = {}
        self.order_log: list[Order] = []

    def submit(self, order: Order) -> Order:
        """模擬成交：立即全額成交並更新記憶體中的持倉與餘額。"""
        fill_price = order.price
        if fill_price is None:
            # 市價單但未帶價：嘗試用 meta 帶入的參考價，否則以 0 記錄（上層應補價）
            fill_price = float(order.raw.get("ref_price", 0.0)) if order.raw else 0.0

        base_asset = (
            order.symbol.split("_")[0] if "_" in order.symbol else order.symbol
        )
        quote_asset = (
            order.symbol.split("_")[1] if "_" in order.symbol else self.quote_asset
        )

        qty = order.quantity
        side = order.side.value if isinstance(order.side, Side) else str(order.side)

        # 更新餘額帳本
        cost = qty * fill_price
        if side == Side.BUY.value:
            self.balances[quote_asset] = self.balances.get(quote_asset, 0.0) - cost
            self.balances[base_asset] = self.balances.get(base_asset, 0.0) + qty
            pos_delta = qty
        else:  # SELL
            self.balances[quote_asset] = self.balances.get(quote_asset, 0.0) + cost
            self.balances[base_asset] = self.balances.get(base_asset, 0.0) - qty
            pos_delta = -qty

        # 更新持倉（加權平均進場價）
        pos = self._positions.get(
            order.symbol, Position(symbol=order.symbol, size=0.0, entry_price=0.0)
        )
        new_size = pos.size + pos_delta
        if (pos.size >= 0) == (pos_delta >= 0) and pos.size != 0:
            # 同向加倉：重算加權均價
            total_cost = pos.entry_price * abs(pos.size) + fill_price * abs(pos_delta)
            pos.entry_price = total_cost / abs(new_size) if new_size != 0 else 0.0
        elif pos.size == 0 or (pos.size > 0) != (new_size > 0):
            # 由空手開倉，或反向翻倉：以本次成交價為新均價
            pos.entry_price = fill_price if new_size != 0 else 0.0
        pos.size = new_size
        if abs(pos.size) < 1e-12:
            pos.size = 0.0
            pos.entry_price = 0.0
        self._positions[order.symbol] = pos

        # 標記訂單為已成交
        order.status = OrderStatus.FILLED
        order.filled_qty = qty
        order.avg_fill_price = fill_price
        order.client_order_id = order.client_order_id or f"paper-{uuid.uuid4().hex[:12]}"
        order.raw = {**(order.raw or {}), "simulated": True, "fill_price": fill_price}
        self.order_log.append(order)
        return order

    def get_position(self, symbol: str) -> Position:
        """回傳模擬持倉；查無則回空手。"""
        return self._positions.get(
            symbol, Position(symbol=symbol, size=0.0, entry_price=0.0, unrealized_pnl=0.0)
        )

    def get_balance(self, asset: str) -> float:
        """回傳模擬帳本中指定幣種餘額。"""
        return float(self.balances.get(asset, 0.0))


# ════════════════════════════════════════════════════════════
# 工廠：依 dry_run 決定執行器
# ════════════════════════════════════════════════════════════
def build_executor(config: Any, channel: str = "api") -> Executor:
    """
    依設定建立對應的執行器。

    安全規則（最重要）：
      config.dry_run == true  → 回傳 PaperExecutor（永不觸網、不會送真單）
      config.dry_run == false → 依 channel 回傳實盤執行器

    參數
    ----
    config: 可以是 dict 或具屬性的物件（如 pydantic model）。
            需含 dry_run，以及（實盤時）pionex.api_key / api_secret / base_url
            與 trading.symbol / quote_asset。
    channel: 實盤下單管道：
            "api"（預設）→ LiveExecutor，走 Pionex 官方 REST API（主路徑）。
            "playwright"/"web" → PionexPlaywrightExecutor，走網頁 UI（備援管道，
                                  API 掛掉時 fallback；預設停在最終送出前）。
            注意：無論 channel 為何，dry_run=true 一律回 PaperExecutor，永不觸網。
    """
    dry_run = _cfg_get(config, "dry_run", default=True)
    # 預設安全：只要不是「明確的 false」一律當作 dry_run
    dry_run = bool(dry_run)

    trading = _cfg_get(config, "trading", default={}) or {}
    symbol = _cfg_get(trading, "symbol", default="BTC_USDT")
    quote_asset = _cfg_get(trading, "quote_asset", default="USDT")

    if dry_run:
        # ── 安全路徑：模擬器，完全不碰交易所（即使指定 playwright 備援也照樣只模擬）──
        if channel in ("playwright", "web"):
            from execution.pionex_playwright_executor import PionexPlaywrightExecutor
            return PionexPlaywrightExecutor(symbol=symbol, dry_run=True)
        return PaperExecutor(quote_asset=quote_asset)

    # ── 實盤備援管道：網頁 UI ──
    if channel in ("playwright", "web"):
        from execution.pionex_playwright_executor import PionexPlaywrightExecutor
        return PionexPlaywrightExecutor(symbol=symbol, dry_run=False)

    # ── 實盤主路徑：官方 API ──
    pionex = _cfg_get(config, "pionex", default={}) or {}
    api_key = _cfg_get(pionex, "api_key", default="")
    api_secret = _cfg_get(pionex, "api_secret", default="")
    base_url = _cfg_get(pionex, "base_url", default="https://api.pionex.com")

    if not api_key or not api_secret or "YOUR_PIONEX" in str(api_key):
        raise ValueError(
            "dry_run=false 但 Pionex 金鑰未正確設定；為保護資金，拒絕建立 LiveExecutor。"
            "請在 config 填入有效的 pionex.api_key / api_secret，或將 dry_run 設回 true。"
        )

    risk = _cfg_get(config, "risk", default={}) or {}
    max_slippage_pct = float(_cfg_get(risk, "max_slippage_pct", default=0.5) or 0.5)

    client = PionexClient(api_key=api_key, api_secret=api_secret, base_url=base_url)
    return LiveExecutor(
        client=client, symbol=symbol, dry_run=False, max_slippage_pct=max_slippage_pct
    )


# ════════════════════════════════════════════════════════════
# 內部工具
# ════════════════════════════════════════════════════════════
def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    """同時支援 dict 與物件屬性的設定讀取。"""
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _map_pionex_status(status: str) -> OrderStatus:
    """把 Pionex 訂單狀態字串對應到核心 OrderStatus。"""
    mapping = {
        "NEW": OrderStatus.NEW,
        "OPEN": OrderStatus.NEW,
        "PENDING": OrderStatus.NEW,
        "FILLED": OrderStatus.FILLED,
        "CLOSED": OrderStatus.FILLED,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "PARTIAL_FILLED": OrderStatus.PARTIALLY_FILLED,
        "CANCELED": OrderStatus.CANCELED,
        "CANCELLED": OrderStatus.CANCELED,
        "REJECTED": OrderStatus.REJECTED,
    }
    return mapping.get(status.upper(), OrderStatus.NEW)
