"""LINE Pay Online API v3 客戶端 —— 個股體檢 T3 SKU 用「先建付款、導轉、confirm 回呼」
取代原本 Shopee/Portaly 那種「導去平台上架好的靜態連結」模式。

跟既有四平台的根本差異：Gumroad/Portaly/LemonSqueezy/Whop 是**平台主動打我們的
webhook**（verify.py 驗 inbound 簽章）；LINE Pay 沒有這種伺服器對伺服器推播，正規流程是：

  1) 伺服端呼叫 Request API 建一筆付款（帶 orderId/amount），拿到 info.paymentUrl.web，
     導使用者過去付款。
  2) 使用者在 LINE Pay 頁面完成付款，LINE Pay 用 302 導回我們給的 confirmUrl，
     並自動附上 ?transactionId=...&orderId=...（不是我們自己拼的，是 LINE Pay 加的）。
  3) 伺服端拿 transactionId 呼叫 Confirm API（帶回同一組 amount/currency）才算真的扣款
     完成——**這通 API 呼叫本身就是驗證來源的機制**：要嘛我們的 channel secret 簽得出
     正確簽章、LINE Pay 也會核對 amount/currency 跟 Request 時是否一致，兩者對不上
     直接回非 0000，我們就不記帳不交付。不需要像其他四平台那樣另外驗 inbound 簽章
     （這步的「輸入」是我們自己打出去的 API 呼叫，不是別人打進來的 request）。

密鑰未設一律 fail-closed（不建立付款、不確認付款），與 verify.py 四平台紅線一致：
寧可讓使用者看到「付款連結尚未上架」，不吐一個會失敗的連結或假裝付款成功。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Optional

import httpx


class LinePayError(RuntimeError):
    """LINE Pay API 回傳非成功 returnCode、回應格式不對、或呼叫本身失敗。"""


def _api_base(env: str) -> str:
    return ("https://api-pay.line.me" if (env or "sandbox").strip().lower() == "production"
            else "https://sandbox-api-pay.line.me")


def _signature(channel_secret: str, uri: str, body: str, nonce: str) -> str:
    """X-LINE-Authorization = base64(HMAC-SHA256(channelSecret, channelSecret+uri+body+nonce))。"""
    msg = (channel_secret + uri + body + nonce).encode("utf-8")
    digest = hmac.new(channel_secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _httpx_post(url: str, headers: dict, body: str) -> tuple[int, str]:
    r = httpx.post(url, headers=headers, content=body.encode("utf-8"), timeout=15)
    return r.status_code, r.text


def _post(settings, path: str, payload: dict) -> dict:
    """組簽章 + 打 POST，回解析後的 JSON。settings.linepay_http_post 可注入假函式
    （測試用，不打外網，回 (status, body_text)）。密鑰未設/網路失敗/非 0000 一律拋
    LinePayError，呼叫端接住轉成「尚未上架」，不讓例外炸到使用者、也不假裝成功。"""
    if not (settings.linepay_channel_id and settings.linepay_channel_secret):
        raise LinePayError("LINE_PAY_CHANNEL_ID / LINE_PAY_CHANNEL_SECRET 未設定")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    nonce = uuid.uuid4().hex
    sig = _signature(settings.linepay_channel_secret, path, body, nonce)
    headers = {
        "Content-Type": "application/json",
        "X-LINE-ChannelId": settings.linepay_channel_id,
        "X-LINE-Authorization-Nonce": nonce,
        "X-LINE-Authorization": sig,
    }
    poster = settings.linepay_http_post or _httpx_post
    try:
        _status, resp_body = poster(_api_base(settings.linepay_env) + path, headers, body)
    except Exception as exc:  # noqa: BLE001
        raise LinePayError(f"呼叫 LINE Pay 失敗：{exc}") from exc
    try:
        data = json.loads(resp_body)
    except Exception as exc:  # noqa: BLE001
        raise LinePayError(f"LINE Pay 回應非 JSON：{resp_body[:200]!r}") from exc
    if str(data.get("returnCode")) != "0000":
        raise LinePayError(f"LINE Pay 拒絕：{data.get('returnCode')} {data.get('returnMessage')}")
    return data


def request_payment(settings, *, order_id: str, amount: int, currency: str,
                    product_name: str, confirm_url: str, cancel_url: str) -> dict:
    """建一筆待付款。成功回 {'transaction_id':..., 'payment_url': 'https://...'}。
    失敗一律拋 LinePayError（呼叫端轉成「付款連結尚未上架」）。"""
    payload = {
        "amount": amount, "currency": currency, "orderId": order_id,
        "packages": [{
            "id": order_id, "amount": amount, "name": "量化阿森",
            "products": [{"name": product_name, "quantity": 1, "price": amount}],
        }],
        "redirectUrls": {"confirmUrl": confirm_url, "cancelUrl": cancel_url},
    }
    data = _post(settings, "/v3/payments/request", payload)
    info = data.get("info") or {}
    url = (info.get("paymentUrl") or {}).get("web") or ""
    tx_id = info.get("transactionId")
    if not url or not tx_id:
        raise LinePayError(f"LINE Pay 回應缺 paymentUrl/transactionId：{data}")
    return {"transaction_id": str(tx_id), "payment_url": url}


def confirm_payment(settings, *, transaction_id: str, amount: int, currency: str) -> dict:
    """使用者付款完成、LINE Pay 導回 confirmUrl 後，伺服端拿 transactionId 呼叫這支才算
    真的扣款成功。amount/currency 要與建立時一致——這是防竄改查詢參數的主要防線，
    LINE Pay 對不上會直接拒絕（非 0000），呼叫端就不會記帳/交付。"""
    payload = {"amount": amount, "currency": currency}
    return _post(settings, f"/v3/payments/{transaction_id}/confirm", payload)
