"""ECPay(綠界科技)全方位金流 AioCheckOut 客戶端 —— 個股體檢 T3 SKU。

Carson 09-16 拍板改用綠界(LINE Pay 個人申請卡在「Online API」產品門檻未釐清，見
docs/ecommerce/SPEC_stock_checkup_multi_artifact.md 決策點 5)。ECPay 跟其餘四平台
(Gumroad/Portaly/LemonSqueezy/Whop)的整合方式一致 —— **inbound 簽章驗證**：付款完成
後 ECPay 主動 POST 到我方 ReturnURL(背景通知)，我方驗 CheckMacValue 對不對；不像
linepay.py 那樣要伺服端主動打 Confirm API 才算數。

建立訂單本身也不是打 API：ECPay AioCheckOut 是「把簽好章的表單參數交給前端，由瀏覽器
直接 POST 到 ECPay 付款頁」的模式，本檔因此**沒有任何對外 HTTP 呼叫**，純粹是簽章計算
與驗章 —— 比 linepay.py 更好測(不需要假 HTTP transport 就能單元測試)。

CheckMacValue 規則(官方 ECPay-API-Skill 文件 2026-09-16 核對，非憑記憶)：
  1) 參數依名稱做 A-Z 排序(不含 CheckMacValue 自己)
  2) 串成 key=value&key=value...，前面加 "HashKey=xxx&"，後面加 "&HashIV=xxx"
  3) 用「金流版」URL encode：先 percent-encode 全部非英數字元 → 整串轉小寫 →
     再做 .NET 字元還原(%2d→-, %5f→_, %2e→., %21→!, %2a→*, %28→(, %29→), %20→+)
  4) SHA256 雜湊 → 轉大寫
(注意：這套「金流版」encode 跟 ECPay AES 加密服務用的 encode 不同，不可混用。)

密鑰未設一律 fail-closed：不產生付款表單、驗章一律回 False —— 與 verify.py 四平台、
linepay.py 紅線一致，寧可讓使用者看到「付款連結尚未上架」，不吐一個假的付款頁或假裝
付款成功。
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Optional
from urllib.parse import quote


class ECPayError(RuntimeError):
    """ECPay 密鑰未設定，無法產生付款表單。"""


def _action_url(env: str) -> str:
    return ("https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"
            if (env or "test").strip().lower() == "production"
            else "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5")


def _ecpay_urlencode(s: str) -> str:
    """ECPay「金流版」URL encode：percent-encode → 全轉小寫 → .NET 字元還原。"""
    encoded = quote(s, safe="").lower()
    for src, dst in (
        ("%2d", "-"), ("%5f", "_"), ("%2e", "."), ("%21", "!"),
        ("%2a", "*"), ("%28", "("), ("%29", ")"), ("%20", "+"),
    ):
        encoded = encoded.replace(src, dst)
    return encoded


def _check_mac_value(hash_key: str, hash_iv: str, params: dict) -> str:
    """依官方規則計算 CheckMacValue。params 不可包含 CheckMacValue 本身
    （呼叫端負責在算之前把它濾掉——這裡仍防呆濾一次）。"""
    pairs = sorted((k, str(v)) for k, v in params.items() if k != "CheckMacValue")
    raw = "&".join(f"{k}={v}" for k, v in pairs)
    wrapped = f"HashKey={hash_key}&{raw}&HashIV={hash_iv}"
    encoded = _ecpay_urlencode(wrapped)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def build_checkout_params(settings, *, merchant_trade_no: str, amount: int,
                           item_name: str, trade_desc: str, return_url: str,
                           client_back_url: str, order_result_url: str,
                           now: Optional[datetime] = None) -> dict:
    """組出要讓瀏覽器 POST 到 ECPay 付款頁(AioCheckOut/V5)的簽名表單參數。

    回傳 dict 含全部要當 hidden input 送出的欄位 + 一個 "_action_url" 鍵(表單
    action 網址，呼叫端組 HTML 時要記得跳過它、不要當成表單欄位送出)。
    密鑰未設 → 拋 ECPayError，呼叫端接住轉成「付款連結尚未上架」。
    """
    if not (settings.ecpay_merchant_id and settings.ecpay_hash_key and settings.ecpay_hash_iv):
        raise ECPayError("ECPAY_MERCHANT_ID / ECPAY_HASH_KEY / ECPAY_HASH_IV 未設定")
    trade_date = (now or datetime.now()).strftime("%Y/%m/%d %H:%M:%S")
    params = {
        "MerchantID": settings.ecpay_merchant_id,
        "MerchantTradeNo": merchant_trade_no,
        "MerchantTradeDate": trade_date,
        "PaymentType": "aio",
        "TotalAmount": str(int(amount)),
        "TradeDesc": trade_desc,
        "ItemName": item_name,
        "ReturnURL": return_url,
        "ChoosePayment": "ALL",
        "ClientBackURL": client_back_url,
        "OrderResultURL": order_result_url,
        "EncryptType": "1",
    }
    params["CheckMacValue"] = _check_mac_value(
        settings.ecpay_hash_key, settings.ecpay_hash_iv, params)
    params["_action_url"] = _action_url(settings.ecpay_env)
    return params


def verify_notify(settings, form: dict) -> bool:
    """驗證 ReturnURL 背景通知的 CheckMacValue 是否真的是 ECPay(用我方密鑰)簽出來的。

    密鑰未設、或欄位裡沒有 CheckMacValue → 一律回 False(fail-closed，不信任何未驗證
    的通知)。比對用 hmac.compare_digest 避免時序側錄，跟 verify.py 四平台的紀律一致。
    """
    if not (settings.ecpay_hash_key and settings.ecpay_hash_iv):
        return False
    received = str(form.get("CheckMacValue") or "").strip()
    if not received:
        return False
    expected = _check_mac_value(
        settings.ecpay_hash_key, settings.ecpay_hash_iv,
        {k: v for k, v in form.items() if k != "CheckMacValue"})
    return hmac.compare_digest(expected, received.upper())
