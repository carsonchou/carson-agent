"""測試共用：把 quant-service 掛上 sys.path + 各平台簽章產生器（本地算，不連網）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import sys
from pathlib import Path

# 掛 sys.path 到 quant-service，讓 `import webhook...` 可用
_QS = Path(__file__).resolve().parents[2]   # quant-service
if str(_QS) not in sys.path:
    sys.path.insert(0, str(_QS))


def sign_hex(secret: str, body: bytes) -> str:
    """Lemon Squeezy / Portaly：hex HMAC-SHA256(raw body)。"""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def sign_standard_webhooks(secret: str, wh_id: str, wh_ts: str, body: bytes) -> str:
    """Whop：Standard Webhooks base64 簽章，回 'v1,<sig>' 格式。"""
    raw = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        key = raw.encode("utf-8")
    signed = f"{wh_id}.{wh_ts}.".encode("utf-8") + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


def make_settings(tmp_path, **over):
    """組一份測試 Settings：tmp 路徑 + 齊全密鑰 + 假 adder/sender + dry_run 關（走 sender）。"""
    from webhook.config import Settings
    recorded_entries = over.pop("_entries", [])
    recorded_mails = over.pop("_mails", [])
    recorded_ntfy = over.pop("_ntfy", [])

    def fake_adder(etype, amount, note="", platform="", stream=None, currency="TWD"):
        recorded_entries.append({"etype": etype, "amount": amount, "note": note,
                                 "platform": platform, "stream": stream, "currency": currency})

    def fake_sender(to, subject, body):
        recorded_mails.append({"to": to, "subject": subject, "body": body})
        return True

    def fake_ntfy(topic, title, body):
        recorded_ntfy.append({"topic": topic, "title": title, "body": body})

    kw = dict(
        sales_ledger=tmp_path / "sales.json",
        customers_book=tmp_path / "customers.json",
        subscribers_book=tmp_path / "subs.json",
        gumroad_seller_id="SELLER123",
        gumroad_ping_token="ptok",
        portaly_secret="psec",
        lemonsqueezy_secret="lssec",
        whop_secret="whsec_" + base64.b64encode(b"whopkey").decode(),
        revenue_adder=fake_adder,
        email_sender=fake_sender,
        ntfy_poster=fake_ntfy,
        dry_run=False,
    )
    kw.update(over)
    s = Settings(**kw)
    s._entries = recorded_entries   # type: ignore[attr-defined]
    s._mails = recorded_mails       # type: ignore[attr-defined]
    s._ntfy = recorded_ntfy         # type: ignore[attr-defined]
    return s
