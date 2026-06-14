"""
TradingView 行情資料來源（交叉比對用）。

實作 core.interfaces.DataFeed，透過非官方套件 tvdatafeed 抓取
與 Pionex 同標的的資料，用於與主資料源交叉比對、偵測背離。

注意：
- tvdatafeed 為非官方套件，可能因 TradingView 改版而失效，故所有對其
  的依賴都採「延遲匯入 + graceful 降級」：套件未安裝時不在 import 階段崩潰，
  而是在實際呼叫時拋出清楚的提示，方便上層選擇略過交叉比對。
- TradingView 的 symbol / interval 與 Pionex 格式不同，本類別負責轉換：
    Pionex "BTC_USDT"  →  TradingView symbol "BTCUSDT" + exchange（預設 "PIONEX"）
    "15M"              →  tvdatafeed.Interval.in_15_minute
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - 環境問題
    raise ImportError(
        "TradingViewFeed 需要 'pandas' 套件，請先安裝：pip install pandas"
    ) from exc

from core.interfaces import Candle, DataFeed


class TradingViewUnavailableError(RuntimeError):
    """tvdatafeed 套件不可用（未安裝或登入失敗）時拋出。"""


class TradingViewFeed(DataFeed):
    """TradingView 資料來源（交叉比對 / 備援用）。"""

    # 預設交易所代號；Pionex 在 TradingView 上的交易所代號。
    DEFAULT_EXCHANGE = "PIONEX"

    def __init__(
        self,
        exchange: str = DEFAULT_EXCHANGE,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        """
        參數：
            exchange：TradingView 交易所代號（預設 "PIONEX"）。
            username / password：TradingView 帳密（可選；不填則匿名抓取，
                                  可用性與歷史深度較受限）。
            timeout：保留參數（tvdatafeed 內部未直接支援，僅作介面一致）。
        """
        self.exchange = exchange
        self._username = username
        self._password = password
        self.timeout = timeout
        # 延遲初始化：第一次真正需要時才建立 tvdatafeed 連線。
        self._tv = None
        self._tv_module = None
        self._interval_enum = None

    # ────────────────────────────────────────────────────────────
    # 套件可用性 / 延遲初始化
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def is_available() -> bool:
        """檢查 tvdatafeed 是否已安裝（不建立連線）。"""
        try:
            import tvDatafeed  # noqa: F401
            return True
        except ImportError:
            try:
                import tvdatafeed  # noqa: F401  # 部分版本套件名小寫
                return True
            except ImportError:
                return False

    def _load_module(self):
        """匯入 tvdatafeed 模組（容忍大小寫差異），失敗時拋出清楚錯誤。"""
        if self._tv_module is not None:
            return self._tv_module
        module = None
        try:
            import tvDatafeed as module  # type: ignore
        except ImportError:
            try:
                import tvdatafeed as module  # type: ignore
            except ImportError as exc:
                raise TradingViewUnavailableError(
                    "未安裝 tvdatafeed 套件，無法使用 TradingView 交叉比對。\n"
                    "請安裝：pip install tvdatafeed\n"
                    "（此為非官方套件；若不需交叉比對可忽略並停用 data.cross_check）"
                ) from exc
        self._tv_module = module
        return module

    def _ensure_connection(self):
        """確保 tvdatafeed 連線已建立（延遲建立、僅一次）。"""
        if self._tv is not None:
            return self._tv
        module = self._load_module()
        try:
            TvDatafeed = module.TvDatafeed
            self._interval_enum = module.Interval
            # 帳密皆有才登入，否則匿名連線。
            if self._username and self._password:
                self._tv = TvDatafeed(
                    username=self._username, password=self._password
                )
            else:
                self._tv = TvDatafeed()
        except Exception as exc:  # tvdatafeed 內部例外型別不穩定
            raise TradingViewUnavailableError(
                f"建立 TradingView 連線失敗：{exc}"
            ) from exc
        return self._tv

    # ────────────────────────────────────────────────────────────
    # 格式轉換
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def pionex_symbol_to_tv(symbol: str) -> str:
        """把 Pionex "BTC_USDT" 轉成 TradingView "BTCUSDT"。"""
        return symbol.replace("_", "").replace("-", "").upper()

    def _to_tv_interval(self, interval: str):
        """把介面 interval 字串對應成 tvdatafeed.Interval 列舉值。"""
        if self._interval_enum is None:
            self._ensure_connection()
        Interval = self._interval_enum

        key = interval.strip().lower()
        mapping = {
            "1m": Interval.in_1_minute,
            "1min": Interval.in_1_minute,
            "3m": Interval.in_3_minute,
            "5m": Interval.in_5_minute,
            "5min": Interval.in_5_minute,
            "15m": Interval.in_15_minute,
            "15min": Interval.in_15_minute,
            "30m": Interval.in_30_minute,
            "30min": Interval.in_30_minute,
            "45m": Interval.in_45_minute,
            "60m": Interval.in_1_hour,
            "1h": Interval.in_1_hour,
            "2h": Interval.in_2_hour,
            "3h": Interval.in_3_hour,
            "4h": Interval.in_4_hour,
            "1d": Interval.in_daily,
            "1day": Interval.in_daily,
            "1w": Interval.in_weekly,
            "1week": Interval.in_weekly,
            "1mo": Interval.in_monthly,
        }
        if key not in mapping:
            raise ValueError(
                f"TradingViewFeed 不支援的 interval：{interval!r}"
            )
        return mapping[key]

    @staticmethod
    def _tv_df_to_contract_df(raw: "pd.DataFrame") -> pd.DataFrame:
        """把 tvdatafeed 回傳的 DataFrame 轉成符合介面契約的格式。"""
        columns = ["open", "high", "low", "close", "volume"]
        if raw is None or raw.empty:
            empty = pd.DataFrame(columns=columns)
            empty.index = pd.DatetimeIndex([], name="timestamp")
            return empty

        df = raw.copy()
        # tvdatafeed 欄位通常為小寫 open/high/low/close/volume，且帶 symbol 欄。
        rename = {}
        for col in df.columns:
            low = col.lower()
            if low in {"open", "high", "low", "close", "volume"}:
                rename[col] = low
        df = df.rename(columns=rename)

        keep = [c for c in columns if c in df.columns]
        df = df[keep]
        for c in keep:
            df[c] = df[c].astype(float)

        # index 為 datetime；統一命名為 timestamp 並補上 UTC 時區資訊。
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize(timezone.utc)
        else:
            df.index = df.index.tz_convert(timezone.utc)
        df.index.name = "timestamp"
        return df

    # ────────────────────────────────────────────────────────────
    # DataFeed 介面實作
    # ────────────────────────────────────────────────────────────
    def get_historical(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """
        回傳歷史 K 棒 DataFrame（欄位 [open, high, low, close, volume]，index=timestamp）。

        套件不可用時拋 TradingViewUnavailableError，由上層決定是否略過交叉比對。
        """
        tv = self._ensure_connection()
        tv_symbol = self.pionex_symbol_to_tv(symbol)
        tv_interval = self._to_tv_interval(interval)

        try:
            raw = tv.get_hist(
                symbol=tv_symbol,
                exchange=self.exchange,
                interval=tv_interval,
                n_bars=max(1, int(limit)),
            )
        except Exception as exc:
            raise TradingViewUnavailableError(
                f"TradingView 抓取失敗（{self.exchange}:{tv_symbol} {interval}）：{exc}"
            ) from exc

        return self._tv_df_to_contract_df(raw)

    def get_latest(self, symbol: str, interval: str) -> Candle:
        """
        回傳最新一根「已收盤」K 棒。

        抓兩根並取倒數第二根（已收盤），避免重繪。
        """
        df = self.get_historical(symbol, interval, limit=2)
        if df.empty:
            raise TradingViewUnavailableError(
                f"TradingView 無資料可回傳最新 K 棒：symbol={symbol}"
            )

        if len(df) >= 2:
            row = df.iloc[-2]
            ts = df.index[-2]
        else:
            row = df.iloc[-1]
            ts = df.index[-1]

        return Candle(
            timestamp=ts.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )

    def get_latest_price(self, symbol: str, interval: str = "1M") -> float:
        """取得最新收盤價（供 DataReconciler 交叉比對）。"""
        candle = self.get_latest(symbol, interval)
        return float(candle.close)
