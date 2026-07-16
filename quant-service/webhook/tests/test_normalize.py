"""正規化層測試：各平台 payload → kind + 欄位；config 的 sku/tier 分類。"""
from __future__ import annotations

import unittest

import _util  # noqa: F401
from webhook import normalize
from webhook.config import classify_tier, resolve_sku
from webhook.events import EventKind


class TestGumroad(unittest.TestCase):
    def test_one_time_sale(self):
        ev = normalize.parse_gumroad({
            "seller_id": "X", "sale_id": "s1", "email": "a@b.com",
            "product_name": "台股定投追蹤模板", "price": "14900", "currency": "twd",
        })
        self.assertEqual(ev.kind, EventKind.SALE)
        self.assertEqual(ev.event_key, "gumroad:s1")
        self.assertEqual(ev.amount, 149.0)          # 分 → 元
        self.assertEqual(ev.currency, "TWD")
        self.assertEqual(ev.sku_id, "T1_dca_tracker")

    def test_refund(self):
        ev = normalize.parse_gumroad({"sale_id": "s2", "refunded": "true",
                                      "product_name": "x", "price": "100"})
        self.assertEqual(ev.kind, EventKind.REFUND)

    def test_subscription_cancel(self):
        ev = normalize.parse_gumroad({"sale_id": "s3", "cancelled": "true",
                                      "recurrence": "monthly", "product_name": "週報"})
        self.assertEqual(ev.kind, EventKind.SUB_CANCEL)


class TestLemonSqueezy(unittest.TestCase):
    def _p(self, event, **attrs):
        return {"meta": {"event_name": event},
                "data": {"id": "d1", "attributes": {"order_number": "o1",
                         "user_email": "u@e.com", "total": 3900, "currency": "USD", **attrs}}}

    def test_sale(self):
        ev = normalize.parse_lemonsqueezy(self._p(
            "order_created", first_order_item={"product_name": "TW Full-Market Backtest Pack"}))
        self.assertEqual(ev.kind, EventKind.SALE)
        self.assertEqual(ev.amount, 39.0)
        self.assertEqual(ev.sku_id, "C1_fullmarket_pack")

    def test_sub_new_and_renew(self):
        self.assertEqual(normalize.parse_lemonsqueezy(self._p("subscription_created")).kind,
                         EventKind.SUB_NEW)
        self.assertEqual(normalize.parse_lemonsqueezy(self._p("subscription_payment_success")).kind,
                         EventKind.SUB_RENEW)

    def test_refund_and_ignored(self):
        self.assertEqual(normalize.parse_lemonsqueezy(self._p("order_refunded")).kind,
                         EventKind.REFUND)
        self.assertEqual(normalize.parse_lemonsqueezy(self._p("subscription_updated")).kind,
                         EventKind.IGNORED)


class TestWhop(unittest.TestCase):
    def test_sub_lifecycle(self):
        base = {"data": {"id": "m1", "email": "w@e.com", "product": "週報",
                         "final_amount": 15, "currency": "USD"}}
        self.assertEqual(normalize.parse_whop({**base, "type": "membership.went_valid"}).kind,
                         EventKind.SUB_NEW)
        self.assertEqual(normalize.parse_whop({**base, "type": "payment.succeeded"}).kind,
                         EventKind.SUB_RENEW)
        self.assertEqual(normalize.parse_whop({**base, "type": "membership.cancelled"}).kind,
                         EventKind.SUB_CANCEL)
        self.assertEqual(normalize.parse_whop({**base, "type": "payment.refunded"}).kind,
                         EventKind.REFUND)

    def test_tier_from_amount(self):
        ev = normalize.parse_whop({"type": "membership.went_valid",
                                   "data": {"id": "m2", "email": "w@e.com",
                                            "product": "週報", "final_amount": 15, "currency": "USD"}})
        self.assertEqual(ev.tier, "full")


class TestPortaly(unittest.TestCase):
    def test_sale_and_sub(self):
        sale = normalize.parse_portaly({"data": {"order_id": "p1", "status": "paid",
                                        "email": "t@e.com", "amount": 990, "currency": "TWD",
                                        "product_name": "全市場回測數據包"}})
        self.assertEqual(sale.kind, EventKind.SALE)
        self.assertEqual(sale.sku_id, "C1_fullmarket_pack")

        sub = normalize.parse_portaly({"event": "subscription_created",
                                       "data": {"order_id": "p2", "email": "t@e.com",
                                       "amount": 99, "currency": "TWD", "product_name": "台股全市場週報"}})
        self.assertEqual(sub.kind, EventKind.SUB_NEW)
        self.assertEqual(sub.tier, "basic")

    def test_chinese_name_key(self):
        ev = normalize.parse_portaly({"data": {"order_id": "p3", "status": "paid",
                                      "email": "t@e.com", "姓名": "王小明", "amount": 149,
                                      "product_name": "週報", "currency": "TWD"}})
        self.assertEqual(ev.name, "王小明")


class TestConfigClassify(unittest.TestCase):
    def test_classify_tier(self):
        self.assertEqual(classify_tier(99, "TWD"), "basic")
        self.assertEqual(classify_tier(149, "TWD"), "full")
        self.assertEqual(classify_tier(1290, "TWD"), "full_annual")
        self.assertEqual(classify_tier(9, "USD"), "basic")
        self.assertEqual(classify_tier(500, "TWD"), "unknown")

    def test_resolve_sku_prefers_kind(self):
        self.assertEqual(resolve_sku("台股全市場週報", EventKind.SUB_NEW)["sku_id"], "SUB_weekly")
        self.assertEqual(resolve_sku("台股定投追蹤模板", EventKind.SALE)["sku_id"], "T1_dca_tracker")


if __name__ == "__main__":
    unittest.main()
