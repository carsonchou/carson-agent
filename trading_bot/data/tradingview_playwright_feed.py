"""
TradingView 資料源（Playwright 版）。

用「真實瀏覽器」開 TradingView 圖表頁，重用既有已登入的瀏覽器 profile，
抓取即時報價作為交叉比對來源。相比非官方套件 tvdatafeed，瀏覽器路徑
更耐反爬、且能沿用使用者已登入的 session。

定位（依專案決策）：
- 主要用途：交叉比對「最新價」(get_latest_price)，餵給 DataReconciler，
  與 Pionex 主源價格比對，價差過大時暫停交易。
- 歷史 K 棒：TradingView 圖表以 canvas 繪製，DOM 內並無乾淨的 OHLCV，
  故 get_historical 不從畫面硬刮（會得到不可靠資料）。歷史資料請用
  PionexFeed（主資料源）。此處 get_historical 會給清楚指引而非回傳髒資料。

設計重點：
- Playwright 採延遲匯入：未安裝時不影響整個專案被 import。
- 重用既有 profile：預設指向專案根的 .pw_tvprofile（持久化登入狀態）。
- 每次取價開→關 context，避免長時間佔用瀏覽器；也可傳 reuse_context=True
  讓多次取價共用同一個瀏覽器（即時交易輪詢時較省資源）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "TradingViewPlaywrightFeed 需要 pandas，請先安裝：pip install pandas"
    ) from exc

from core.interfaces import Candle, DataFeed


class TradingViewPlaywrightError(RuntimeError):
    """Playwright 不可用、或 TradingView 取價失敗時拋出。"""


# 介面 interval → TradingView URL 的 interval 參數（分鐘數 / D / W）。
_TV_INTERVAL = {
    "1M": "1", "5M": "5", "15M": "15", "30M": "30",
    "60M": "60", "1H": "60", "2H": "120", "4H": "240",
    "8H": "480", "12H": "720", "1D": "D", "1W": "W",
}


class TradingViewPlaywrightFeed(DataFeed):
    """以真實瀏覽器抓 TradingView 報價的交叉比對資料源。"""

    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        exchange: str = "BINANCE",
        headless: bool = True,
        timeout_ms: int = 20_000,
        reuse_context: bool = False,
    ) -> None:
        """
        參數：
            user_data_dir：瀏覽器持久化 profile 目錄（重用既有登入 session）。
                           預設為專案根的 .pw_tvprofile。
            exchange：TradingView 上的交易所前綴（如 BINANCE / COINBASE）；
                      Pionex 本身在 TV 無對應，故交叉比對採同幣對的主流交易所價。
            headless：是否無頭執行（背景跑用 True；除錯時可 False 看畫面）。
            timeout_ms：頁面載入 / 等待元素逾時。
            reuse_context：True 時保持瀏覽器常駐、多次取價共用（即時交易較省）。
        """
        # 預設重用專案根的 .pw_tvprofile（與既有 TV 登入流程一致）。
        if user_data_dir is None:
            root = Path(__file__).resolve().parents[2]  # .../carson-agent
            user_data_dir = str(root / ".pw_tvprofile")
        self.user_data_dir = user_data_dir
        self.exchange = exchange.upper()
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.reuse_context = reuse_context

        self._pw = None
        self._context = None  # 常駐模式下的 persistent context

    # ────────────────────────────────────────────────────────────
    # Playwright 生命週期
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _import_playwright():
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:
            raise TradingViewPlaywrightError(
                "未安裝 playwright，無法使用 TradingView 瀏覽器交叉比對。\n"
                "請安裝：pip install playwright 並執行 playwright install chromium"
            ) from exc
        return sync_playwright

    def _open_context(self):
        """開一個持久化瀏覽器 context（重用既有 profile）。"""
        sync_playwright = self._import_playwright()
        pw = sync_playwright().start()
        try:
            context = pw.chromium.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            pw.stop()
            raise TradingViewPlaywrightError(
                f"啟動瀏覽器失敗（profile={self.user_data_dir}）：{exc}"
            ) from exc
        return pw, context

    def _ensure_context(self):
        """常駐模式：確保 context 已開啟並重用。"""
        if self._context is None:
            self._pw, self._context = self._open_context()
        return self._context

    def close(self) -> None:
        """關閉常駐瀏覽器（reuse_context=True 時使用後請呼叫）。"""
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    # ────────────────────────────────────────────────────────────
    # 取價核心
    # ────────────────────────────────────────────────────────────
    def _tv_symbol(self, symbol: str) -> str:
        """把 'BTC_USDT' 轉成 TradingView 代號 'BINANCE:BTCUSDT'。"""
        compact = symbol.replace("_", "").replace("-", "").upper()
        return f"{self.exchange}:{compact}"

    def _scrape_price_on_page(self, page, tv_symbol: str, interval: str) -> float:
        """在已開好的 page 上載入圖表並讀出最新價。"""
        tv_int = _TV_INTERVAL.get(interval.upper(), "60")
        url = (
            f"https://www.tradingview.com/chart/"
            f"?symbol={tv_symbol}&interval={tv_int}"
        )
        page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")

        # TradingView 圖表的最新價會出現在右側價軸的「最後價標籤」，
        # 以及左上角商品圖例。優先讀價軸標籤，較貼近即時成交價。
        selectors = [
            'div[class*="priceAxisCurrentPrice"]',          # 價軸最後價
            'div[class*="valueValue-"]',                      # 圖例 OHLC 數值
            'span[class*="last-"]',                           # 部分版型的 last 元素
        ]
        last_err = None
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=self.timeout_ms // len(selectors))
                text = page.locator(sel).first.inner_text(timeout=3_000)
                price = _parse_price(text)
                if price is not None:
                    return price
            except Exception as exc:  # 換下一個 selector
                last_err = exc
                continue

        raise TradingViewPlaywrightError(
            f"無法從 TradingView 讀出 {tv_symbol} 最新價"
            + (f"（最後錯誤：{last_err}）" if last_err else "")
        )

    def get_latest_price(self, symbol: str, interval: str = "60M") -> float:
        """
        取得 TradingView 上該幣對最新價（交叉比對主用）。

        DataReconciler 會優先呼叫本方法。回傳 float 價格。
        """
        tv_symbol = self._tv_symbol(symbol)

        if self.reuse_context:
            context = self._ensure_context()
            page = context.new_page()
            try:
                return self._scrape_price_on_page(page, tv_symbol, interval)
            finally:
                page.close()

        # 一次性模式：開→取→關
        pw, context = self._open_context()
        try:
            page = context.new_page()
            return self._scrape_price_on_page(page, tv_symbol, interval)
        finally:
            context.close()
            pw.stop()

    # ────────────────────────────────────────────────────────────
    # DataFeed 介面實作
    # ────────────────────────────────────────────────────────────
    def get_latest(self, symbol: str, interval: str) -> Candle:
        """
        回傳「最新價」包成的退化 Candle（OHLC 同為最新價）。

        說明：TradingView 圖表 DOM 無乾淨單根 OHLCV，交叉比對只需要「價」，
        故以最新價組成 Candle 供 DataReconciler 的 get_latest 路徑使用。
        若需要精確 OHLCV，請改用 PionexFeed。
        """
        price = self.get_latest_price(symbol, interval)
        now = datetime.now(timezone.utc)
        return Candle(
            timestamp=now, open=price, high=price, low=price, close=price, volume=0.0
        )

    def get_historical(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """
        TradingView 圖表為 canvas 繪製，DOM 無可靠 OHLCV；不從畫面硬刮。

        歷史 K 棒請使用 PionexFeed（主資料源）。此處明確拋出指引，
        避免回傳不可靠資料污染回測 / 訊號。
        """
        raise TradingViewPlaywrightError(
            "TradingViewPlaywrightFeed 不提供歷史 K 棒（圖表為 canvas，無乾淨 OHLCV）。\n"
            "歷史資料請使用 PionexFeed.get_historical；TV 僅作『最新價』交叉比對。"
        )


# ────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────
def _parse_price(text: str) -> Optional[float]:
    """從畫面文字解析價格數字（去除千分位逗號與貨幣符號）。"""
    if not text:
        return None
    # 抓第一個像價格的數字（允許逗號千分位與小數點）。
    m = re.search(r"[-+]?[\d,]*\.?\d+", text.replace(" ", "").replace(" ", ""))
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    return val if val > 0 else None
