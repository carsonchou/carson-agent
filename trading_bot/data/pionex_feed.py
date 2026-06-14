"""
Pionex（派網）行情資料來源。

實作 core.interfaces.DataFeed，透過 Pionex 官方公開 REST API
取得歷史 / 最新 K 棒。公開行情端點不需要 API 金鑰、不需簽名。

API 文件：https://pionex-doc.gitbook.io/apidocs/restful/markets/get-kline-data
端點：GET /api/v1/market/klines
參數：
    symbol   交易對，例如 "BTC_USDT"
    interval K 棒週期，例如 "1M" / "5M" / "15M" / "1H" / "1D"
    limit    回傳筆數（Pionex 上限為 500）
    endTime  （可選）毫秒時間戳，回傳此時間之前的資料

回應格式（data.klines）每筆為一個 dict：
    {
        "time":   開盤時間（毫秒）,
        "open":   開盤價（字串）,
        "high":   最高價（字串）,
        "low":    最低價（字串）,
        "close":  收盤價（字串）,
        "volume": 成交量（字串）
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# requests 為硬性相依；缺套件時給清楚錯誤提示，避免 import 整個專案時神祕崩潰。
try:
    import requests
except ImportError as exc:  # pragma: no cover - 環境問題
    raise ImportError(
        "PionexFeed 需要 'requests' 套件，請先安裝：pip install requests"
    ) from exc

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - 環境問題
    raise ImportError(
        "PionexFeed 需要 'pandas' 套件，請先安裝：pip install pandas"
    ) from exc

from core.interfaces import Candle, DataFeed


class PionexFeed(DataFeed):
    """Pionex 公開行情資料來源。"""

    # Pionex klines 端點單次回傳上限。
    MAX_LIMIT: int = 500

    # 介面常見的 interval 寫法 → Pionex 認可的 interval。
    # Pionex 支援：1M,5M,15M,30M,60M,4H,8H,12H,1D,1W (以官方為準)
    # 這裡做寬鬆對應，讓上層可用 "15M" 或 "15m" 或 "15min" 等寫法。
    _INTERVAL_MAP: dict[str, str] = {
        "1m": "1M",
        "1min": "1M",
        "5m": "5M",
        "5min": "5M",
        "15m": "15M",
        "15min": "15M",
        "30m": "30M",
        "30min": "30M",
        "60m": "60M",
        "1h": "60M",
        "60min": "60M",
        "4h": "4H",
        "8h": "8H",
        "12h": "12H",
        "1d": "1D",
        "1day": "1D",
        "1w": "1W",
        "1week": "1W",
    }

    # Pionex 官方直接支援的 interval（已是正確大小寫）。
    _PIONEX_VALID = {"1M", "5M", "15M", "30M", "60M", "4H", "8H", "12H", "1D", "1W"}

    def __init__(
        self,
        base_url: str = "https://api.pionex.com",
        timeout: float = 10.0,
        session: Optional["requests.Session"] = None,
    ) -> None:
        """
        參數：
            base_url：Pionex API 根網址（取自 config 的 pionex.base_url）。
            timeout：單次請求逾時秒數。
            session：可注入自訂 requests.Session（便於測試 / 連線重用）。
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    # ────────────────────────────────────────────────────────────
    # interval 正規化
    # ────────────────────────────────────────────────────────────
    def _normalize_interval(self, interval: str) -> str:
        """把上層傳入的 interval 對應成 Pionex 認可的字串。"""
        if interval in self._PIONEX_VALID:
            return interval
        key = interval.strip().lower()
        if key in self._INTERVAL_MAP:
            return self._INTERVAL_MAP[key]
        # 容忍大寫單位的非標準寫法，例如使用者直接輸入合法值的變體。
        upper = interval.strip().upper()
        if upper in self._PIONEX_VALID:
            return upper
        raise ValueError(
            f"不支援的 interval：{interval!r}。"
            f"可用值範例：{sorted(self._PIONEX_VALID)}"
        )

    # ────────────────────────────────────────────────────────────
    # 低階 HTTP 呼叫
    # ────────────────────────────────────────────────────────────
    def _request_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        end_time_ms: Optional[int] = None,
    ) -> list[dict]:
        """呼叫 Pionex klines 端點並回傳原始 klines 清單。"""
        url = f"{self.base_url}/api/v1/market/klines"
        params: dict[str, object] = {
            "symbol": symbol,
            "interval": interval,
            "limit": max(1, min(int(limit), self.MAX_LIMIT)),
        }
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Pionex klines 請求失敗（symbol={symbol}, interval={interval}）：{exc}"
            ) from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Pionex 回應非合法 JSON：{resp.text[:200]}") from exc

        # Pionex 統一回應格式：{"result": true, "data": {...}}
        if not payload.get("result", False):
            raise RuntimeError(f"Pionex API 回報錯誤：{payload}")

        data = payload.get("data") or {}
        klines = data.get("klines")
        if klines is None:
            raise RuntimeError(f"Pionex 回應缺少 klines 欄位：{payload}")
        return klines

    @staticmethod
    def _klines_to_df(klines: list[dict]) -> pd.DataFrame:
        """把原始 klines 清單轉成符合介面契約的 DataFrame。"""
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        if not klines:
            empty = pd.DataFrame(columns=columns[1:])
            empty.index = pd.DatetimeIndex([], name="timestamp")
            return empty

        rows = []
        for k in klines:
            # 毫秒時間戳轉為 UTC datetime。
            ts = datetime.fromtimestamp(int(k["time"]) / 1000.0, tz=timezone.utc)
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(k["open"]),
                    "high": float(k["high"]),
                    "low": float(k["low"]),
                    "close": float(k["close"]),
                    "volume": float(k["volume"]),
                }
            )

        df = pd.DataFrame(rows, columns=columns)
        # 依時間排序（Pionex 可能回傳新→舊），並設為 index。
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.set_index("timestamp")
        return df

    # ────────────────────────────────────────────────────────────
    # DataFeed 介面實作
    # ────────────────────────────────────────────────────────────
    def get_historical(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """
        回傳歷史 K 棒 DataFrame。

        欄位：[open, high, low, close, volume]，index 為 timestamp（UTC, tz-aware）。
        若 limit 超過 Pionex 單次上限（500），自動分頁向前抓取並拼接。
        """
        norm = self._normalize_interval(interval)
        target = max(1, int(limit))

        # 單次即可滿足。
        if target <= self.MAX_LIMIT:
            klines = self._request_klines(symbol, norm, target)
            return self._klines_to_df(klines)

        # 需要分頁：用 endTime 往更早的時間遊走。
        collected: list[dict] = []
        end_time_ms: Optional[int] = None
        seen_first_times: set[int] = set()

        while len(collected) < target:
            batch = self._request_klines(
                symbol, norm, self.MAX_LIMIT, end_time_ms=end_time_ms
            )
            if not batch:
                break

            # 以 time 排序確保順序穩定（新→舊處理較直覺）。
            batch_sorted = sorted(batch, key=lambda k: int(k["time"]))
            earliest = int(batch_sorted[0]["time"])

            # 防止無限迴圈：若最早時間沒有再往前推進，跳出。
            if earliest in seen_first_times:
                collected.extend(batch_sorted)
                break
            seen_first_times.add(earliest)

            collected.extend(batch_sorted)

            # 下一頁抓取此批最早 K 棒之前的資料。
            end_time_ms = earliest - 1

            if len(batch) < self.MAX_LIMIT:
                # 沒有更多資料了。
                break

        df = self._klines_to_df(collected)
        # 去除可能的重複 index，保留最後 target 根。
        df = df[~df.index.duplicated(keep="last")]
        if len(df) > target:
            df = df.iloc[-target:]
        return df

    def get_latest(self, symbol: str, interval: str) -> Candle:
        """
        回傳最新一根「已收盤」K 棒。

        Pionex klines 端點會包含尚未收盤的當前 K 棒，因此抓兩根、
        取倒數第二根（已收盤）以避免重繪。
        """
        norm = self._normalize_interval(interval)
        klines = self._request_klines(symbol, norm, limit=2)
        df = self._klines_to_df(klines)
        if df.empty:
            raise RuntimeError(f"Pionex 無資料可回傳最新 K 棒：symbol={symbol}")

        # 取已收盤的那一根：若有兩根以上，倒數第二根為已收盤。
        row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        ts = df.index[-2] if len(df) >= 2 else df.index[-1]

        return Candle(
            timestamp=ts.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )

    def get_ticker_price(self, symbol: str) -> float:
        """
        取得最新成交價（即時，未必收盤），供 DataReconciler 交叉比對使用。

        端點：GET /api/v1/market/tickers?symbol=...
        若該端點不可用，退而求其次回傳最新 K 棒收盤價。
        """
        url = f"{self.base_url}/api/v1/market/tickers"
        try:
            resp = self._session.get(
                url, params={"symbol": symbol}, timeout=self.timeout
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("result", False):
                data = payload.get("data") or {}
                tickers = data.get("tickers") or []
                if tickers:
                    t = tickers[0]
                    # close 為最新成交價。
                    price = t.get("close") or t.get("last")
                    if price is not None:
                        return float(price)
        except (requests.RequestException, ValueError, KeyError):
            # 退回 K 棒收盤價。
            pass

        klines = self._request_klines(symbol, self._normalize_interval("1M"), limit=1)
        df = self._klines_to_df(klines)
        if df.empty:
            raise RuntimeError(f"Pionex 無法取得 {symbol} 的最新價格")
        return float(df.iloc[-1]["close"])
