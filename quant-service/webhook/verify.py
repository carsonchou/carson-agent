"""驗簽層 —— 四平台簽章驗證，全部 fail-closed、timing-safe。

- primitives（純函式，好測）：verify_hmac_hex / verify_standard_webhooks / token_ok
- guards（吃 Settings、raise HTTPException）：require_* —— 密鑰未設 → 503、簽章不符 → 401

密鑰未設一律回 503（拒絕接受「無法驗證來源」的請求），這是 v1 就有的紅線，v2 原樣保留。
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import HTTPException


# ── primitives ───────────────────────────────────────────────────────────────
def verify_hmac_hex(secret: str, body: bytes, provided: str) -> bool:
    """HMAC-SHA256 hex digest 比對（Lemon Squeezy / Portaly）。timing-safe。"""
    if not secret or not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.strip().lower())


def verify_standard_webhooks(secret: str, wh_id: str, wh_ts: str,
                             body: bytes, sig_header: str) -> bool:
    """Standard Webhooks 規格（Whop）：簽章內容 = f"{id}.{ts}.{body}"，
    HMAC-SHA256 以 base64 解碼後的密鑰，輸出 base64，比對 header 內任一 v1 簽章。
    密鑰常帶 whsec_ 前綴，前綴後為 base64。"""
    if not (secret and wh_id and wh_ts and sig_header):
        return False
    raw_secret = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except Exception:  # noqa: BLE001
        key = raw_secret.encode("utf-8")
    signed = f"{wh_id}.{wh_ts}.".encode("utf-8") + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in sig_header.split():
        candidate = part.split(",", 1)[1] if part.startswith("v1,") else part
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def token_ok(provided: str, expected: str) -> bool:
    """shared-secret token timing-safe 比對（Gumroad Ping）。"""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.strip(), expected.strip())


# ── guards（fail-closed，raise HTTPException）────────────────────────────────
def require_gumroad(settings, form: dict, token: str) -> None:
    """Gumroad 無 HMAC；seller_id 是公開資訊不算密鑰 → 驗真靠賣家自訂 Ping URL 上的
    私密 shared-secret token（?token= 或 X-Ping-Token）。token 與 seller_id 任一未設或不符即擋。"""
    if not settings.gumroad_ping_token:
        raise HTTPException(503, "GUMROAD_PING_TOKEN 未設定，無法驗證 Gumroad 來源")
    if not token_ok(token, settings.gumroad_ping_token):
        raise HTTPException(401, "Gumroad ping token 不符（偽造來源已擋）")
    if not settings.gumroad_seller_id:
        raise HTTPException(503, "GUMROAD_SELLER_ID 未設定，無法驗證來源")
    if (form.get("seller_id") or "") != settings.gumroad_seller_id:
        raise HTTPException(401, "Gumroad seller_id 不符")


def require_lemonsqueezy(settings, body: bytes, sig: str) -> None:
    if not settings.lemonsqueezy_secret:
        raise HTTPException(503, "LEMONSQUEEZY_WEBHOOK_SECRET 未設定")
    if not verify_hmac_hex(settings.lemonsqueezy_secret, body, sig or ""):
        raise HTTPException(401, "Lemon Squeezy 簽章驗證失敗")


def require_whop(settings, body: bytes, wh_id: str, wh_ts: str, wh_sig: str) -> None:
    if not settings.whop_secret:
        raise HTTPException(503, "WHOP_WEBHOOK_SECRET 未設定")
    if not verify_standard_webhooks(settings.whop_secret, wh_id, wh_ts, body, wh_sig or ""):
        raise HTTPException(401, "Whop 簽章驗證失敗")


def require_portaly(settings, body: bytes, sig: str) -> None:
    """⚠️ Portaly 官方無第一手 webhook spec；此處採 HMAC-SHA256 hex（header X-Portaly-Signature）。
    上線前需以真實 Portaly 測試 webhook 校準簽章機制（見 normalize.parse_portaly 的校準註記）。"""
    if not settings.portaly_secret:
        raise HTTPException(503, "PORTALY_WEBHOOK_SECRET 未設定")
    if not verify_hmac_hex(settings.portaly_secret, body, sig or ""):
        raise HTTPException(401, "Portaly 簽章驗證失敗")
