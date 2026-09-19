"""業務處理層 —— 統一入口 process_event()：去重 → 記帳 → 名冊 → 交付 → ntfy。

正規化層吐出的 NormalizedEvent 一律進這裡。各 kind 走不同分支：
  REFUND               → 退款簿負值(去重) + finance 負值沖銷 + 名冊移出（不交付）
  SUB_CANCEL           → 名冊移出（不記帳、不交付）
  SALE/SUB_NEW/RENEW   → 銷售簿(去重) + finance 進帳 + 名冊(訂閱才動) + 交付 + ntfy
  IGNORED              → 不處理
去重是冪等關鍵：webhook at-least-once 重送同一事件不會重複記帳/沖銷/寄信。
"""
from __future__ import annotations

from . import customers, delivery, ledger, revenue, subscribers
from .events import EventKind


def process_event(ev, settings) -> dict:
    """處理一個已驗簽、已正規化的事件。回一份結果摘要（給路由回應/日誌）。"""
    if ev.kind == EventKind.IGNORED:
        return {"status": "ignored", "event": ev.raw_event}

    # ── 退款：負值沖銷 + 移出名冊，不交付 ──
    if ev.kind == EventKind.REFUND:
        first = ledger.append_refund(settings.sales_ledger, ev)
        if first:
            revenue.record(ev, settings, refund=True)          # 只有非重複退款才沖銷
        subscribers.apply_event(settings.subscribers_book, ev)  # 冪等：移出 active
        return {"status": "refund_logged" if first else "refund_duplicate",
                "order_id": ev.order_id}

    # ── 取消訂閱：只移出名冊 ──
    if ev.kind == EventKind.SUB_CANCEL:
        subscribers.apply_event(settings.subscribers_book, ev)
        return {"status": "subscription_cancelled", "email": ev.email}

    # ── 進帳事件（一次性/訂閱成立/續訂）──
    if not ev.email:
        return {"status": "rejected", "reason": "缺買家 email，無法交付/記名冊"}

    first = ledger.append_sale(settings.sales_ledger, ev)
    if not first:
        return {"status": "duplicate", "event_key": ev.event_key}

    revenue.record(ev, settings)                                # 分幣別進帳
    customers.record(settings.customers_book, ev)               # 顧客簿（所有買家）
    if ev.is_subscription:
        subscribers.apply_event(settings.subscribers_book, ev)  # 訂閱閉環

    delivered = delivery.deliver(ev, settings)                  # config 驅動交付信
    if delivered.get("sent"):
        ledger.mark_delivered(settings.sales_ledger, ev.event_key)
    delivery.notify(ev, settings, delivered)

    return {"status": "accepted", "platform": ev.platform, "kind": ev.kind.value,
            "order_id": ev.order_id, "sku_id": ev.sku_id, "tier": ev.tier,
            "delivered": delivered}
