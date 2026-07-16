"""路由整合測試（TestClient，不連外網）：
簽章通過/失敗/密鑰未設、去重、退款沖銷、訂閱名冊閉環、交付信 config 驅動。
TestClient 會同步跑完 BackgroundTasks，故可在 post 後直接驗記帳/名冊狀態。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _util
from fastapi.testclient import TestClient
from webhook import ledger, subscribers
from webhook.app import build_app
from webhook.config import Settings


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.entries: list = []
        self.mails: list = []
        self.settings = _util.make_settings(self.dir, _entries=self.entries, _mails=self.mails)
        self.client = TestClient(build_app(self.settings))

    # ── Lemon Squeezy：簽章通過/失敗/密鑰未設 ──
    def _ls_body(self, event="order_created", **attrs):
        payload = {"meta": {"event_name": event},
                   "data": {"id": "d1", "attributes": {"order_number": "o1",
                            "user_email": "u@e.com", "total": 500, "currency": "USD",
                            "first_order_item": {"product_name": "台股定投追蹤模板"}, **attrs}}}
        return json.dumps(payload).encode("utf-8")

    def test_ls_valid_signature_accepted(self):
        body = self._ls_body()
        sig = _util.sign_hex("lssec", body)
        r = self.client.post("/sale-ping/lemonsqueezy", content=body,
                             headers={"X-Signature": sig})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "accepted")
        # 背景任務已跑：記帳簿有一筆、finance adder 被呼叫、交付信寄出
        self.assertEqual(len(ledger.load_json(self.settings.sales_ledger, [])), 1)
        self.assertEqual(len(self.entries), 1)
        self.assertEqual(self.entries[0]["etype"], "product")   # 一次性→product
        self.assertEqual(len(self.mails), 1)
        # ntfy 走注入的假 poster（證明測試不打外網），Title 為 ASCII
        self.assertEqual(len(self.settings._ntfy), 1)
        self.assertTrue(self.settings._ntfy[0]["title"].isascii())
        # 顧客簿記到這位買家
        cust = ledger.load_json(self.settings.customers_book, {})
        self.assertIn("u@e.com", cust)
        self.assertEqual(cust["u@e.com"]["orders"], 1)

    def test_ls_bad_signature_401(self):
        body = self._ls_body()
        r = self.client.post("/sale-ping/lemonsqueezy", content=body,
                             headers={"X-Signature": "deadbeef"})
        self.assertEqual(r.status_code, 401)

    def test_missing_secret_503(self):
        s = _util.make_settings(self.dir, lemonsqueezy_secret="")
        client = TestClient(build_app(s), raise_server_exceptions=False)
        body = self._ls_body()
        r = client.post("/sale-ping/lemonsqueezy", content=body,
                        headers={"X-Signature": _util.sign_hex("lssec", body)})
        self.assertEqual(r.status_code, 503)

    def test_ls_dedup(self):
        body = self._ls_body()
        sig = _util.sign_hex("lssec", body)
        h = {"X-Signature": sig}
        self.client.post("/sale-ping/lemonsqueezy", content=body, headers=h)
        self.client.post("/sale-ping/lemonsqueezy", content=body, headers=h)  # 重送
        self.assertEqual(len(ledger.load_json(self.settings.sales_ledger, [])), 1)
        self.assertEqual(len(self.entries), 1)                  # 不重複記帳

    def test_ls_refund_reverses(self):
        # 先成交
        body = self._ls_body()
        self.client.post("/sale-ping/lemonsqueezy", content=body,
                         headers={"X-Signature": _util.sign_hex("lssec", body)})
        # 再退款
        rbody = self._ls_body(event="order_refunded")
        r = self.client.post("/sale-ping/lemonsqueezy", content=rbody,
                             headers={"X-Signature": _util.sign_hex("lssec", rbody)})
        self.assertEqual(r.json()["status"], "refund_logged")
        # finance 有一筆負值沖銷
        neg = [e for e in self.entries if e["amount"] < 0]
        self.assertEqual(len(neg), 1)

    # ── Portaly：訂閱名冊閉環（成立→取消）──
    def _portaly_post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        sig = _util.sign_hex("psec", body)
        return self.client.post("/sale-ping/portaly", content=body,
                                headers={"X-Portaly-Signature": sig})

    def test_portaly_subscription_lifecycle(self):
        r = self._portaly_post({"event": "subscription_created",
                                "data": {"order_id": "p1", "email": "sub@e.com",
                                "amount": 149, "currency": "TWD",
                                "product_name": "台股全市場週報", "姓名": "王"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(subscribers.count_active(self.settings.subscribers_book), 1)
        self.assertEqual(self.entries[0]["etype"], "newsletter")  # 訂閱→newsletter
        # 取消 → 移出名單（同步處理）
        r2 = self._portaly_post({"event": "subscription_cancelled",
                                 "data": {"order_id": "p2", "email": "sub@e.com",
                                 "product_name": "台股全市場週報"}})
        self.assertEqual(r2.json()["status"], "subscription_cancelled")
        self.assertEqual(subscribers.count_active(self.settings.subscribers_book), 0)

    def test_portaly_export_feeds_weekly_list(self):
        self._portaly_post({"event": "subscription_created",
                            "data": {"order_id": "p1", "email": "a@e.com", "amount": 149,
                            "currency": "TWD", "product_name": "台股全市場週報"}})
        rows = subscribers.export_active(self.settings.subscribers_book)
        self.assertEqual(rows[0]["email"], "a@e.com")

    # ── Gumroad：token 驗證 ──
    def test_gumroad_token_and_sale(self):
        form = "seller_id=SELLER123&sale_id=g1&email=g%40e.com&product_name=%E5%AE%9A%E6%8A%95&price=14900&currency=twd"
        r = self.client.post("/sale-ping/gumroad?token=ptok", content=form.encode(),
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(ledger.load_json(self.settings.sales_ledger, [])), 1)

    def test_gumroad_bad_token_401(self):
        form = "seller_id=SELLER123&sale_id=g2&email=g%40e.com&price=100"
        r = self.client.post("/sale-ping/gumroad?token=WRONG", content=form.encode(),
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 401)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn("active_subscribers", r.json())

    # ── B1 回歸（VERIFY_REPORT_phase3a）：簽章合法但 body 壞 → 必須 400 不是 500 ──
    # 5xx 會讓 webhook 平台無限重試（retry storm），4xx 才會讓它停止重投壞蛋。
    def test_malformed_json_valid_signature_400_not_500(self):
        cases = [
            ("lemonsqueezy", "lssec", "X-Signature", b"{not json"),
            ("lemonsqueezy", "lssec", "X-Signature", b""),
            ("portaly", "psec", "X-Portaly-Signature", b"{not json"),
            ("portaly", "psec", "X-Portaly-Signature", b""),
        ]
        for platform, secret, hdr_name, body in cases:
            with self.subTest(platform=platform, body=body):
                headers = {hdr_name: _util.sign_hex(secret, body)}
                r = self.client.post(f"/sale-ping/{platform}", content=body, headers=headers)
                self.assertEqual(r.status_code, 400, f"{platform} 壞 body 應回 400，實得 {r.status_code}")
        # 服務未死、也沒有任何東西被記帳
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(len(ledger.load_json(self.settings.sales_ledger, [])), 0)
        self.assertEqual(len(self.entries), 0)

    def test_malformed_json_whop_400_not_500(self):
        body = b"{broken"
        sig = _util.sign_standard_webhooks(self.settings.whop_secret, "wh_x", "1", body)
        r = self.client.post("/sale-ping/whop", content=body,
                             headers={"webhook-id": "wh_x", "webhook-timestamp": "1",
                                      "webhook-signature": sig})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_malformed_json_bad_signature_still_401_not_400(self):
        """順序正確性：驗簽在解析之前——壞 body + 壞簽章要回 401（不洩漏解析結果）。"""
        r = self.client.post("/sale-ping/portaly", content=b"{not json",
                             headers={"X-Portaly-Signature": "deadbeef"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
