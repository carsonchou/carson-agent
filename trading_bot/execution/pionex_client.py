"""
Pionex 私有 REST API 客戶端封裝。

本模組只負責「與 Pionex 交易所溝通」這件事，不含任何業務邏輯或安全旗標判斷：
  - HMAC-SHA256 簽名（依 Pionex 官方規格）
  - 下單（市價 / 限價）
  - 查持倉、查餘額
  - 撤單、查訂單

安全提醒：本檔案會「真的」送單到交易所。dry_run 的判斷請在上層 executor 處理，
不要把安全旗標放在這裡，以免責任分散。

Pionex 官方簽名規格（簡述）：
  1. 必帶 query 參數 `timestamp`（毫秒）。
  2. 將所有 query 參數依 key 字母排序後組成 querystring。
  3. 簽名原文 = METHOD + PATH + '?' + sorted_querystring（若有 body 再串接 JSON body）。
  4. signature = HMAC_SHA256(api_secret, 原文) 取十六進位小寫。
  5. 標頭帶入：
       PIONEX-KEY       : api_key
       PIONEX-SIGNATURE : signature
  6. POST/DELETE 等帶 body 的請求，Content-Type 為 application/json，
     且簽名原文需把 body 字串接在最後。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Optional
from urllib.parse import urlencode

try:
    import requests
except ImportError as exc:  # pragma: no cover - 套件缺失時給清楚錯誤
    raise ImportError(
        "PionexClient 需要 'requests' 套件，請先執行：pip install requests>=2.31.0"
    ) from exc


class PionexAPIError(RuntimeError):
    """Pionex API 回傳錯誤（result=false 或 HTTP 非 2xx）時拋出。"""

    def __init__(self, message: str, *, code: Optional[str] = None, payload: Any = None):
        super().__init__(message)
        self.code = code
        self.payload = payload


# ── 細分錯誤型別（皆繼承 PionexAPIError，舊有 except PionexAPIError 仍相容）──
# 區分的關鍵：呼叫端要能判斷「確定沒成交（可安全重送）」vs「不確定（可能已成交，
# 必須查單對帳，不可當拒單）」vs「暫時性（可退避重試）」。
class PionexNetworkError(PionexAPIError):
    """網路層失敗 / timeout：請求是否送達『不確定』。對下單而言不可當成拒單，須對帳。"""


class PionexRateLimitError(PionexAPIError):
    """HTTP 429 限流：暫時性，idempotent 請求可退避重試。"""


class PionexServerError(PionexAPIError):
    """HTTP 5xx 伺服器錯誤：暫時性，idempotent 請求可退避重試。"""


class PionexClientError(PionexAPIError):
    """HTTP 4xx(非429) 或 result=false：『確定』被拒，重試無益。"""


class PionexClient:
    """
    封裝 Pionex 私有 REST API。

    參數
    ----
    api_key:    Pionex API Key
    api_secret: Pionex API Secret（用於 HMAC 簽名）
    base_url:   API 根網址，預設 https://api.pionex.com
    timeout:    單次請求逾時秒數
    session:    可注入自訂 requests.Session（測試用）
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.pionex.com",
        timeout: float = 10.0,
        session: Optional["requests.Session"] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        sleep_fn=None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("PionexClient 需要有效的 api_key 與 api_secret")
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        # 暫時性錯誤（429/5xx/網路）的退避重試：僅對 idempotent 方法(GET/DELETE)生效，
        # POST 下單一律不自動重試（避免重複下單），交由上層查單對帳。
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = float(backoff_base)
        self._sleep = sleep_fn or time.sleep

    # idempotent 方法才可安全自動重試
    _IDEMPOTENT = frozenset({"GET", "DELETE"})

    # ────────────────────────────────────────────────────────────
    # 簽名與低階請求
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _timestamp_ms() -> int:
        """目前 Unix 時間（毫秒）。"""
        return int(time.time() * 1000)

    def _sign(self, method: str, path: str, params: dict, body_str: str = "") -> str:
        """
        依 Pionex 規格計算簽名。

        原文格式：METHOD + PATH + '?' + sorted_querystring + body_str
        （params 一定含 timestamp；querystring 依 key 排序）
        """
        # 依 key 排序，確保簽名可重現
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        query_string = urlencode(sorted_items)
        message = f"{method.upper()}{path}?{query_string}{body_str}"
        return hmac.new(
            self.api_secret, message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        """
        發送已簽名的私有請求，回傳解析後的 JSON dict。

        會自動加入 timestamp、計算簽名、帶上認證標頭。
        """
        method_up = method.upper()
        idempotent = method_up in self._IDEMPOTENT
        attempt = 0
        while True:
            try:
                return self._request_once(method_up, path, params, body)
            except (PionexNetworkError, PionexRateLimitError, PionexServerError) as exc:
                # 暫時性錯誤：僅 idempotent 方法可重試；POST(下單)一律往上拋，交給對帳
                if not idempotent or attempt >= self.max_retries:
                    raise
                wait = self.backoff_base * (2 ** attempt)
                attempt += 1
                self._sleep(wait)
                # 迴圈重試（會以新 timestamp 重新簽名）

    def _request_once(
        self, method_up: str, path: str, params: Optional[dict], body: Optional[dict]
    ) -> dict:
        """單次已簽名請求；依失敗型態拋出對應的細分錯誤。"""
        params = dict(params or {})
        params["timestamp"] = self._timestamp_ms()

        # 帶 body 的請求需序列化為 JSON 並納入簽名
        body_str = ""
        if body is not None:
            # 用 separators 去除空白，確保送出的字串與簽名原文一致
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

        signature = self._sign(method_up, path, params, body_str)

        headers = {
            "PIONEX-KEY": self.api_key,
            "PIONEX-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(
                method=method_up,
                url=url,
                params=params,
                data=body_str.encode("utf-8") if body_str else None,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # 網路層失敗/timeout：請求是否送達不確定（對下單尤其關鍵）
            raise PionexNetworkError(f"Pionex 請求失敗（網路層）：{exc}") from exc

        # 解析 JSON
        try:
            data = resp.json()
        except ValueError as exc:
            # 非 JSON 多半伴隨 HTTP 錯誤；依 status 分類
            if resp.status_code == 429:
                raise PionexRateLimitError(
                    f"Pionex 限流(429)，回應非 JSON：{resp.text[:200]}",
                    code="429",
                ) from exc
            if resp.status_code >= 500:
                raise PionexServerError(
                    f"Pionex 伺服器錯誤({resp.status_code})，回應非 JSON：{resp.text[:200]}",
                    code=str(resp.status_code),
                ) from exc
            raise PionexClientError(
                f"Pionex 回應非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}",
                code=str(resp.status_code),
            ) from exc

        if resp.status_code >= 400:
            if resp.status_code == 429:
                raise PionexRateLimitError(
                    "Pionex 限流(429)", code="429", payload=data
                )
            if resp.status_code >= 500:
                raise PionexServerError(
                    f"Pionex 伺服器錯誤 {resp.status_code}",
                    code=str(resp.status_code), payload=data,
                )
            raise PionexClientError(
                f"Pionex HTTP 錯誤 {resp.status_code}",
                code=str(resp.status_code), payload=data,
            )

        # Pionex 統一以 result 旗標標示成功與否（確定失敗，非暫時性）
        if isinstance(data, dict) and data.get("result") is False:
            raise PionexClientError(
                f"Pionex API 回傳失敗：{data.get('message', data)}",
                code=str(data.get("code")),
                payload=data,
            )

        return data

    # ────────────────────────────────────────────────────────────
    # 公開查詢（可選用，部分端點不需簽名，但統一走簽名請求亦可）
    # ────────────────────────────────────────────────────────────
    def get_balances(self) -> dict:
        """
        查詢帳戶餘額。

        回傳 Pionex 原始 JSON，data.balances 為各幣種餘額清單，
        每筆含 coin / free / frozen 等欄位。
        """
        return self._request("GET", "/api/v1/account/balances")

    def get_balance(self, asset: str) -> float:
        """
        取得單一幣種「可用」餘額（free）。查無則回 0.0。
        """
        data = self.get_balances()
        balances = (data.get("data") or {}).get("balances") or []
        for item in balances:
            if str(item.get("coin", "")).upper() == asset.upper():
                return float(item.get("free", 0.0))
        return 0.0

    # ────────────────────────────────────────────────────────────
    # 下單 / 撤單 / 查單
    # ────────────────────────────────────────────────────────────
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        *,
        size: Optional[float] = None,
        price: Optional[float] = None,
        amount: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """
        送出訂單。

        參數
        ----
        symbol:       交易對，如 "BTC_USDT"
        side:         "BUY" 或 "SELL"
        order_type:   "MARKET" 或 "LIMIT"
        size:         下單數量（base 資產，如 BTC 顆數）；限價單與市價賣單通常用 size
        price:        限價單價格（LIMIT 必填）
        amount:       市價買單可改用 quote 金額下單（如花多少 USDT 買）
        client_order_id: 自訂訂單編號（冪等用）

        回傳 Pionex 原始 JSON。
        """
        side = side.upper()
        order_type = order_type.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side 必須為 BUY 或 SELL，收到：{side}")
        if order_type not in ("MARKET", "LIMIT"):
            raise ValueError(f"order_type 必須為 MARKET 或 LIMIT，收到：{order_type}")

        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if order_type == "LIMIT":
            if price is None or size is None:
                raise ValueError("限價單（LIMIT）必須提供 price 與 size")
            body["price"] = str(price)
            body["size"] = str(size)
        else:  # MARKET
            # 市價買單可用 amount(quote) 或 size(base)；市價賣單用 size
            if amount is not None:
                body["amount"] = str(amount)
            elif size is not None:
                body["size"] = str(size)
            else:
                raise ValueError("市價單（MARKET）必須提供 size 或 amount 其一")

        if client_order_id:
            body["clientOrderId"] = client_order_id

        return self._request("POST", "/api/v1/trade/order", body=body)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """依交易所訂單編號撤單。"""
        body = {"symbol": symbol, "orderId": str(order_id)}
        return self._request("DELETE", "/api/v1/trade/order", body=body)

    def get_order(self, symbol: str, order_id: str) -> dict:
        """查詢單一訂單狀態。"""
        params = {"symbol": symbol, "orderId": str(order_id)}
        return self._request("GET", "/api/v1/trade/order", params=params)

    def get_open_orders(self, symbol: Optional[str] = None) -> dict:
        """查詢未成交訂單；不帶 symbol 則查全部。"""
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/api/v1/trade/openOrders", params=params)

    def get_position(self, symbol: str) -> dict:
        """
        查詢持倉。

        Pionex 現貨並無傳統「持倉」概念，持倉等同 base 資產餘額；
        此方法回傳原始 fills/餘額資訊，由上層 executor 換算為 Position。
        對合約商品則回傳對應持倉資料。
        """
        # 現貨：以餘額代表持倉；合約：可改打對應持倉端點。
        # 為通用性，這裡回傳 fills（成交明細）供上層彙整。
        params = {"symbol": symbol}
        return self._request("GET", "/api/v1/trade/fills", params=params)
