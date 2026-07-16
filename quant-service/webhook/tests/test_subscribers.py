"""名冊層測試：訂閱成立/續訂/取消/退款的名冊增刪 + 週報名單導出（含分層）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _util  # noqa: F401
from webhook import subscribers
from webhook.events import EventKind, NormalizedEvent


def _ev(kind, email="s@e.com", tier="full", order="o1", amount=149, cur="TWD", name="A"):
    return NormalizedEvent(platform="portaly", kind=kind, event_key=f"portaly:{order}",
                           email=email, name=name, product="週報", amount=amount,
                           currency=cur, order_id=order, tier=tier)


class TestRoster(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.book = self.dir / "subs.json"

    def test_new_then_active(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW))
        self.assertEqual(subscribers.count_active(self.book), 1)
        rows = subscribers.export_active(self.book)
        self.assertEqual(rows[0]["email"], "s@e.com")
        self.assertEqual(rows[0]["tier"], "full")

    def test_cancel_removes_from_list(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW))
        subscribers.apply_event(self.book, _ev(EventKind.SUB_CANCEL, order="o2"))
        self.assertEqual(subscribers.count_active(self.book), 0)
        self.assertEqual(subscribers.export_active(self.book), [])

    def test_refund_removes_from_list(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW))
        subscribers.apply_event(self.book, _ev(EventKind.REFUND, order="o3"))
        self.assertEqual(subscribers.count_active(self.book), 0)

    def test_renew_reactivates_and_updates_tier(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW, tier="basic", amount=99))
        subscribers.apply_event(self.book, _ev(EventKind.SUB_CANCEL, order="o2"))
        subscribers.apply_event(self.book, _ev(EventKind.SUB_RENEW, tier="full", amount=149, order="o4"))
        self.assertEqual(subscribers.count_active(self.book), 1)
        self.assertEqual(subscribers.export_active(self.book)[0]["tier"], "full")

    def test_one_time_sale_does_not_touch_roster(self):
        subscribers.apply_event(self.book, _ev(EventKind.SALE, order="s1"))
        self.assertEqual(subscribers.count_active(self.book), 0)

    def test_export_tier_filter(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW, email="basic@e.com",
                                               tier="basic", amount=99, order="b1"))
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW, email="full@e.com",
                                               tier="full", amount=149, order="f1"))
        all_active = subscribers.export_active(self.book)
        self.assertEqual(len(all_active), 2)
        full_only = subscribers.export_active(self.book, tier="full")
        self.assertEqual([r["email"] for r in full_only], ["full@e.com"])

    def test_audit_trail_dedup(self):
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW))
        subscribers.apply_event(self.book, _ev(EventKind.SUB_NEW))  # 同 kind+order → 稽核不重覆
        import json
        book = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertEqual(len(book["s@e.com"]["events"]), 1)


if __name__ == "__main__":
    unittest.main()
