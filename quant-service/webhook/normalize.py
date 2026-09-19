"""正規化層 —— 各平台 payload → NormalizedEvent（純函式，不碰密鑰）。

驗簽已在 verify.py 做完，這裡只負責「把各平台的欄位差異抹平」+ 判斷 EventKind
（一次性成交 / 訂閱三態 / 退款 / 略過）+ 用 config 補上 sku_id/tier。因為不碰密鑰、
不做 IO，這層可以被大量單元測試直接餵 dict 驗證，不需要起 server。

⚠️ 校準註記：Whop / Portaly 的 data 欄位官方未第一手明列，欄位名為「防禦式多鍵擷取」。
上線前拿真實測試 webhook 校準時，改動集中在各 parser 的：
  1) 事件名 → kind 的對應表（_WHOP_* / _LS_* / _PORTALY_STATUS_*）
  2) 欄位擷取的候選鍵順序（email/name/product/amount/order_id/period_end）
其餘各層（驗簽/去重/記帳/名冊/交付）不需動。
"""
from __future__ import annotations

from typing import Optional

from .config import classify_tier, resolve_sku
from .events import EventKind, NormalizedEvent


def _to_float(v) -> float:
    try:
        return round(float(v), 2)
    except Exception:  # noqa: BLE001
        return 0.0


def _first(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _enrich(ev: NormalizedEvent) -> NormalizedEvent:
    """補 sku_id；訂閱事件再補 tier。集中在正規化層出口，業務層拿到就已完整。"""
    sku = resolve_sku(ev.product, ev.kind)
    ev.sku_id = sku["sku_id"]
    if ev.is_subscription:
        ev.tier = classify_tier(ev.amount, ev.currency)
    return ev


# ── Gumroad ──────────────────────────────────────────────────────────────────
def parse_gumroad(form: dict) -> NormalizedEvent:
    """Gumroad Ping（x-www-form-urlencoded）。欄位依 https://gumroad.com/ping：
    seller_id/product_name/email/price(分)/currency/sale_id/order_number/refunded/disputed/
    recurrence(有=訂閱)/cancelled(訂閱取消)/subscription_id。"""
    sale_id = _first(form, "sale_id", "order_number")
    refunded = str(form.get("refunded", "")).lower() == "true"
    disputed = str(form.get("disputed", "")).lower() == "true"
    cancelled = str(form.get("cancelled", "")).lower() == "true"
    is_sub = bool(form.get("recurrence") or form.get("subscription_id"))
    # Gumroad 對「訂閱首期 vs 續期」無獨立旗標；有 subscription_id 且非首期難分，
    # 保守：訂閱扣款一律當 SUB_RENEW，除非帶 is_first/ trial 之類（暫無官方鍵 → 待校準）。
    if refunded or disputed:
        kind = EventKind.REFUND
    elif cancelled:
        kind = EventKind.SUB_CANCEL
    elif is_sub:
        first = str(form.get("is_recurring_charge", "")).lower() in ("", "false")
        kind = EventKind.SUB_NEW if first else EventKind.SUB_RENEW
    else:
        kind = EventKind.SALE
    ev = NormalizedEvent(
        platform="gumroad",
        kind=kind,
        event_key=f"gumroad:{sale_id}",
        email=(_first(form, "email")).strip(),
        name=_first(form, "full_name", "purchaser_id"),
        product=_first(form, "product_name", "permalink"),
        amount=_to_float(form.get("price", 0)) / 100.0,   # price 以最小幣值單位（分）
        currency=(_first(form, "currency", default="usd")).upper(),
        order_id=sale_id,
        raw_event="refunded" if refunded else ("cancelled" if cancelled else "sale"),
    )
    return _enrich(ev)


# ── Lemon Squeezy ────────────────────────────────────────────────────────────
_LS_KIND = {
    "order_created": EventKind.SALE,
    "subscription_created": EventKind.SUB_NEW,
    "subscription_payment_success": EventKind.SUB_RENEW,
    "subscription_cancelled": EventKind.SUB_CANCEL,
    "subscription_expired": EventKind.SUB_CANCEL,
    "order_refunded": EventKind.REFUND,
    "subscription_payment_refunded": EventKind.REFUND,
}


def parse_lemonsqueezy(payload: dict) -> NormalizedEvent:
    """Lemon Squeezy JSON。meta.event_name / data.attributes.{user_email,user_name,
    order_number,total(分),currency,first_order_item.product_name,renews_at}。"""
    event = (payload.get("meta") or {}).get("event_name", "")
    attrs = (payload.get("data") or {}).get("attributes") or {}
    first_item = attrs.get("first_order_item") or {}
    order_id = str(_first(attrs, "order_number") or (payload.get("data") or {}).get("id") or "")
    kind = _LS_KIND.get(event, EventKind.IGNORED)
    ev = NormalizedEvent(
        platform="lemonsqueezy",
        kind=kind,
        event_key=f"lemonsqueezy:{order_id}",
        email=(_first(attrs, "user_email")).strip(),
        name=_first(attrs, "user_name"),
        product=_first(first_item, "product_name") or _first(attrs, "product_name"),
        amount=_to_float(attrs.get("total", 0)) / 100.0,   # total 以分計
        currency=(_first(attrs, "currency", default="USD")).upper(),
        order_id=order_id,
        period_end=attrs.get("renews_at") or attrs.get("ends_at"),
        raw_event=event,
    )
    return _enrich(ev)


# ── Whop ─────────────────────────────────────────────────────────────────────
_WHOP_KIND = {
    "payment.succeeded": EventKind.SUB_RENEW,   # 反覆扣款；首期由 membership.went_valid 抓
    "membership.went_valid": EventKind.SUB_NEW,
    "membership.activated": EventKind.SUB_NEW,
    "membership.went_invalid": EventKind.SUB_CANCEL,
    "membership.cancelled": EventKind.SUB_CANCEL,
    "payment.refunded": EventKind.REFUND,
}


def parse_whop(payload: dict, wh_id: str = "") -> NormalizedEvent:
    """Whop JSON（Standard Webhooks）。type(如 payment.succeeded) / data{...}。
    ⚠️ data 內欄位名官方未第一手明列 → 防禦式多鍵擷取（待真實 webhook 校準）。"""
    etype = _first(payload, "type", "action")
    d = payload.get("data") or {}
    user = d.get("user") if isinstance(d.get("user"), dict) else {}
    did = str(_first(d, "id") or wh_id or "")
    kind = _WHOP_KIND.get(etype, EventKind.IGNORED)
    ev = NormalizedEvent(
        platform="whop",
        kind=kind,
        event_key=f"whop:{wh_id or did}",
        email=(_first(d, "email", "user_email") or _first(user, "email")).strip(),
        name=_first(d, "name") or _first(user, "username", "name"),
        product=_first(d, "product", "plan", "product_name"),
        amount=_to_float(_first(d, "final_amount", "amount", "subtotal", default=0)),
        currency=(_first(d, "currency", default="USD")).upper(),
        order_id=did,
        period_end=d.get("renewal_period_end") or d.get("expires_at"),
        raw_event=etype,
    )
    return _enrich(ev)


# ── Portaly（台灣訂閱主柱）────────────────────────────────────────────────────
# ⚠️ 官方無第一手 webhook spec（僅 n8n 教學證實 webhook 存在且含 姓名/email）。
# status/事件名 → kind 對應與欄位名皆為暫定，上線前用真實 Portaly 測試 webhook 校準。
_PORTALY_STATUS_KIND = {
    "paid": EventKind.SALE, "completed": EventKind.SALE, "success": EventKind.SALE,
    "subscription_created": EventKind.SUB_NEW, "subscribed": EventKind.SUB_NEW,
    "subscription_renewed": EventKind.SUB_RENEW, "renewed": EventKind.SUB_RENEW,
    "subscription_cancelled": EventKind.SUB_CANCEL, "cancelled": EventKind.SUB_CANCEL,
    "unsubscribed": EventKind.SUB_CANCEL,
    "refunded": EventKind.REFUND, "refund": EventKind.REFUND,
}


def parse_portaly(payload: dict) -> NormalizedEvent:
    """Portaly JSON。data 可能包一層或攤平；status/event 決定 kind、is_subscription
    看是否帶訂閱旗標。欄位候選鍵含中文（姓名）。全為暫定，待校準。"""
    d = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    order_id = str(_first(d, "order_id", "id", "order_number"))
    status = str(_first(payload, "event", "type") or _first(d, "status", "event")).lower()
    is_sub = bool(d.get("is_subscription") or d.get("subscription_id")
                  or "subscri" in status or status in ("renewed", "unsubscribed"))
    kind = _PORTALY_STATUS_KIND.get(status)
    if kind is None:
        # 沒對到已知 status：有訂閱旗標當續訂、否則當一次性成交（保守收進金流閉環）。
        kind = EventKind.SUB_RENEW if is_sub else EventKind.SALE
    ev = NormalizedEvent(
        platform="portaly",
        kind=kind,
        event_key=f"portaly:{order_id}",
        email=(_first(d, "email", "buyer_email", "customer_email")).strip(),
        name=_first(d, "name", "buyer_name", "姓名"),
        product=_first(d, "product_name", "product", "item_name"),
        amount=_to_float(_first(d, "amount", "price", "total", default=0)),
        currency=(_first(d, "currency", default="TWD")).upper(),
        order_id=order_id,
        period_end=d.get("period_end") or d.get("next_billing_at"),
        raw_event=status,
    )
    return _enrich(ev)
