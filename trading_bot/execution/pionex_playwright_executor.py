"""
Pionex 網頁 UI 備援下單管道（Playwright 版）。

定位（依專案決策）：當官方 REST API 掛掉 / 維護 / 風控暫鎖時，作為**備援**
下單管道——用真實瀏覽器、重用既有已登入的 Pionex session，在現貨交易頁
按市價買賣。實作 core.interfaces.Executor，可被 build_executor 工廠掛入。

安全核心（最重要）：
- 嚴格尊重 dry_run。dry_run=True 時，submit() 一律「只模擬、不點擊送出」，
  回傳一個標記 simulated=True 的 Order，永不對 Pionex 真的下單。
- 即使誤設 dry_run=False，也預設 require_confirm=True：除非明確關閉，
  否則只填好下單表單、停在「送出前」一步，不自動按下最終送出鈕。
  這是備援管道的最後一道人為防線（API 主路徑才走全自動）。

備註：
- 網頁 DOM/selector 會隨 Pionex 改版變動，故所有 selector 集中於
  _SELECTORS，方便日後維護。
- Playwright 採延遲匯入，未安裝不影響整個專案被 import。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from core.interfaces import Executor, Order, OrderStatus, Position, Side


class PionexPlaywrightError(RuntimeError):
    """Playwright 不可用、或網頁下單流程失敗時拋出。"""


# 網頁元素 selector（集中管理；Pionex 改版時只需改這裡）。
# 註：以常見的多語系 aria/文字為主，盡量耐改版。
_SELECTORS = {
    "buy_tab": 'button:has-text("Buy"), button:has-text("買入")',
    "sell_tab": 'button:has-text("Sell"), button:has-text("賣出")',
    "market_tab": 'div:has-text("Market"), div:has-text("市價")',
    "amount_input": 'input[placeholder*="Amount"], input[placeholder*="數量"]',
    "submit_button": 'button[type="submit"], button:has-text("下單"), button:has-text("Place")',
}


class PionexPlaywrightExecutor(Executor):
    """以真實瀏覽器在 Pionex 網頁下單的備援執行器。"""

    def __init__(
        self,
        symbol: str = "BTC_USDT",
        dry_run: bool = True,
        user_data_dir: Optional[str] = None,
        headless: bool = True,
        require_confirm: bool = True,
        timeout_ms: int = 20_000,
        base_web_url: str = "https://www.pionex.com",
    ) -> None:
        """
        參數：
            symbol：交易對（如 BTC_USDT）。
            dry_run：安全旗標。True = 只模擬、不真送單（強烈建議驗證前保持 True）。
            user_data_dir：瀏覽器持久化 profile（重用既有 Pionex 登入 session）；
                           預設專案根的 .pw_pionexprofile。
            headless：是否無頭。
            require_confirm：dry_run=False 時是否仍停在「最終送出前」一步（預設 True）。
            timeout_ms：頁面操作逾時。
            base_web_url：Pionex 網頁根網址。
        """
        if user_data_dir is None:
            root = Path(__file__).resolve().parents[2]  # .../carson-agent
            user_data_dir = str(root / ".pw_pionexprofile")
        self.symbol = symbol
        self.dry_run = bool(dry_run)
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.require_confirm = bool(require_confirm)
        self.timeout_ms = timeout_ms
        self.base_web_url = base_web_url.rstrip("/")

        # 模擬模式的記憶體帳本（與 PaperExecutor 行為一致，便於演練）
        self._sim_positions: dict[str, Position] = {}
        self.order_log: list[Order] = []

    # ────────────────────────────────────────────────────────────
    # Executor 介面
    # ────────────────────────────────────────────────────────────
    def submit(self, order: Order) -> Order:
        """
        下單。dry_run=True 時只模擬、不觸網；dry_run=False 才走真實瀏覽器。
        """
        # ── 安全第一：dry_run 一律模擬，永不點擊送出 ──
        if self.dry_run:
            return self._simulate_fill(order, note="dry_run：網頁備援只模擬，未真的下單")

        # ── 實盤備援路徑：真實瀏覽器操作 ──
        return self._web_submit(order)

    def get_position(self, symbol: str) -> Position:
        """
        查詢持倉。
        dry_run：回模擬帳本。實盤：從網頁資產頁讀取（簡化：回空手，建議以 API 主源為準）。
        """
        if self.dry_run:
            return self._sim_positions.get(
                symbol, Position(symbol=symbol, size=0.0, entry_price=0.0)
            )
        # 網頁讀持倉較不穩定；備援管道建議仍以 API（PionexClient）查詢持倉為準。
        return Position(symbol=symbol, size=0.0, entry_price=0.0)

    def get_balance(self, asset: str) -> float:
        """查餘額。dry_run 回模擬值；實盤備援建議仍以 API 為準（此處回 0.0 佔位）。"""
        if self.dry_run:
            return 0.0
        return 0.0

    # ────────────────────────────────────────────────────────────
    # 模擬成交（dry_run）
    # ────────────────────────────────────────────────────────────
    def _simulate_fill(self, order: Order, note: str) -> Order:
        """純記憶體模擬成交，不觸網。"""
        fill_price = order.price or float((order.raw or {}).get("ref_price", 0.0))
        side = order.side.value if isinstance(order.side, Side) else str(order.side)

        pos = self._sim_positions.get(
            order.symbol, Position(symbol=order.symbol, size=0.0, entry_price=0.0)
        )
        delta = order.quantity if side == Side.BUY.value else -order.quantity
        new_size = pos.size + delta
        if pos.size == 0 or (pos.size > 0) != (new_size > 0):
            pos.entry_price = fill_price if new_size != 0 else 0.0
        pos.size = 0.0 if abs(new_size) < 1e-12 else new_size
        self._sim_positions[order.symbol] = pos

        order.status = OrderStatus.FILLED
        order.filled_qty = order.quantity
        order.avg_fill_price = fill_price
        order.client_order_id = order.client_order_id or f"pw-sim-{uuid.uuid4().hex[:12]}"
        order.raw = {**(order.raw or {}), "simulated": True, "channel": "playwright", "note": note}
        self.order_log.append(order)
        return order

    # ────────────────────────────────────────────────────────────
    # 真實網頁下單（dry_run=False）
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _import_playwright():
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:
            raise PionexPlaywrightError(
                "未安裝 playwright，無法使用網頁備援下單。\n"
                "請安裝：pip install playwright 並執行 playwright install chromium"
            ) from exc
        return sync_playwright

    def _web_submit(self, order: Order) -> Order:
        """用真實瀏覽器在 Pionex 現貨頁下市價單（備援）。"""
        sync_playwright = self._import_playwright()
        side = order.side.value if isinstance(order.side, Side) else str(order.side)
        is_buy = side == Side.BUY.value

        # Pionex 現貨交易頁 URL（symbol 以網頁格式 BTC_USDT）
        trade_url = f"{self.base_web_url}/trade/{order.symbol}"

        pw = sync_playwright().start()
        try:
            context = pw.chromium.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.new_page()
            try:
                page.goto(trade_url, timeout=self.timeout_ms, wait_until="domcontentloaded")

                # 1) 選 買/賣 分頁
                page.click(_SELECTORS["buy_tab"] if is_buy else _SELECTORS["sell_tab"],
                           timeout=self.timeout_ms)
                # 2) 選 市價
                page.click(_SELECTORS["market_tab"], timeout=self.timeout_ms)
                # 3) 填數量
                page.fill(_SELECTORS["amount_input"], str(order.quantity),
                          timeout=self.timeout_ms)

                # 4) 送出 — 預設停在最終送出前，需明確 require_confirm=False 才自動按下
                if self.require_confirm:
                    order.status = OrderStatus.NEW
                    order.client_order_id = (
                        order.client_order_id or f"pw-staged-{uuid.uuid4().hex[:12]}"
                    )
                    order.raw = {
                        "channel": "playwright",
                        "staged": True,
                        "note": "已填妥下單表單，停在最終送出前（require_confirm=True）；"
                                "如需自動送出請設 require_confirm=False。",
                    }
                    return order

                page.click(_SELECTORS["submit_button"], timeout=self.timeout_ms)
                order.status = OrderStatus.NEW  # 網頁無法保證即時成交回報
                order.client_order_id = (
                    order.client_order_id or f"pw-{uuid.uuid4().hex[:12]}"
                )
                order.raw = {"channel": "playwright", "submitted": True}
                return order
            finally:
                context.close()
        except Exception as exc:
            order.status = OrderStatus.REJECTED
            order.raw = {"channel": "playwright", "error": str(exc)}
            return order
        finally:
            pw.stop()
