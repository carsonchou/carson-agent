"""記帳簿層測試：event_key 去重、退款專屬鍵去重、原子寫入回讀。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _util  # noqa: F401
from webhook import ledger
from webhook.events import EventKind, NormalizedEvent


def _ev(order="o1", amount=100, kind=EventKind.SALE):
    return NormalizedEvent(platform="gumroad", kind=kind, event_key=f"gumroad:{order}",
                           email="a@b.com", product="x", amount=amount, currency="USD",
                           order_id=order, sku_id="T1_dca_tracker")


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "sales.json"

    def test_append_and_dedup(self):
        self.assertTrue(ledger.append_sale(self.path, _ev()))
        self.assertFalse(ledger.append_sale(self.path, _ev()))     # 同 key 去重
        data = ledger.load_json(self.path, [])
        self.assertEqual(len(data), 1)

    def test_mark_delivered(self):
        ledger.append_sale(self.path, _ev())
        ledger.mark_delivered(self.path, "gumroad:o1")
        rec = ledger.load_json(self.path, [])[0]
        self.assertTrue(rec["delivered"])

    def test_refund_dedup(self):
        self.assertTrue(ledger.append_refund(self.path, _ev(amount=100)))
        self.assertFalse(ledger.append_refund(self.path, _ev(amount=100)))  # :refund 去重
        rows = ledger.load_json(self.path, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], -100)               # 負值沖銷
        self.assertEqual(rows[0]["event_key"], "gumroad:o1:refund")


if __name__ == "__main__":
    unittest.main()
