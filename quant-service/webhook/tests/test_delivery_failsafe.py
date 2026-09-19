"""交付 fail-safe 回歸:下載連結未備妥時,絕不把 placeholder 內部字寄給付錢的客人。

背景(2026-07-16):`_download_block()` 在 ECOMMERCE_DL_* 未設時會塞一段
「下載連結為 placeholder…設定環境變數 ECOMMERCE_DL_* 即可帶入真連結」——那是開發者筆記。
以前 dry_run 恆 True(沒人載 quant-service/.env)所以永遠不會外流;.env 載入器修好後,
SMTP 憑證一被讀到 `dry_run=not(SMTP_USER and SMTP_PASS)` 就自動關 → 真客人會收到那封信。
本測試釘死:寧可不寄+ntfy 叫 Carson 手動交付,也不寄壞連結。
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

import _util  # noqa: F401  (掛 sys.path)
from webhook import delivery
from webhook.events import EventKind


def _sale(sku_id="T1_dca_tracker", email="buyer@e.com"):
    return SimpleNamespace(
        kind=EventKind.SALE, sku_id=sku_id, email=email, name="王",
        product="台股定投追蹤模板", platform="gumroad", order_id="o-1",
        amount=99.0, currency="TWD", tier=None, event_key="gumroad:o-1")


class TestDeliveryFailsafe(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in
                       ("ECOMMERCE_DL_T1", "ECOMMERCE_DL_T2", "ECOMMERCE_DL_C1", "ECOMMERCE_DL_C2")}
        self.sent: list = []
        self.settings = SimpleNamespace(
            dry_run=False,                       # 模擬「SMTP 齊備 → dry_run 自動關」的真實上線態
            email_sender=lambda to, s, b: self.sent.append((to, s, b)) or True,
            ntfy_poster=None, ntfy_topic="t")

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_missing_download_link_refuses_to_send(self):
        """核心:連結沒設 + dry_run 已關 → 拒寄,且明確標 manual_required。"""
        res = delivery.deliver(_sale(), self.settings)
        self.assertFalse(res["sent"], "下載連結未設時絕不可寄出")
        self.assertTrue(res.get("manual_required"), "必須標記需人工交付")
        self.assertEqual(len(self.sent), 0, "不可有任何信真的送出去")

    def test_placeholder_text_never_reaches_customer(self):
        """付錢的客人不可能收到『設定環境變數 ECOMMERCE_DL_*』這種開發者筆記。"""
        delivery.deliver(_sale(), self.settings)
        leaked = [b for _, _, b in self.sent if "ECOMMERCE_DL" in b or "placeholder" in b.lower()]
        self.assertEqual(leaked, [], "placeholder 內部字外洩給客人")

    def test_link_present_sends_normally(self):
        """反向:連結設好了就正常寄,別因為 fail-safe 把正常交付也擋掉。"""
        os.environ["ECOMMERCE_DL_T1"] = "https://example.com/dl/t1"
        res = delivery.deliver(_sale(), self.settings)
        self.assertTrue(res["sent"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("https://example.com/dl/t1", self.sent[0][2])

    def test_subscription_unaffected(self):
        """訂閱開通信不含下載連結,不該被這個 fail-safe 誤擋(那是旗艦金流)。"""
        ev = _sale()
        ev.kind = EventKind.SUB_NEW
        ev.product = "台股全市場週報"
        ev.tier = "full"
        res = delivery.deliver(ev, self.settings)
        self.assertTrue(res["sent"], "訂閱開通信不該被誤擋")

    def test_dry_run_still_short_circuits(self):
        """dry_run 仍優先:未上線狀態一律不寄(既有紀律不可回歸)。"""
        self.settings.dry_run = True
        res = delivery.deliver(_sale(), self.settings)
        self.assertFalse(res["sent"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(len(self.sent), 0)

    def test_ntfy_escalates_manual_delivery(self):
        """有人付錢卻寄不出去 → ntfy 必須用不同標題吵醒 Carson,不能跟一般成交同級。"""
        posted: list = []
        self.settings.ntfy_poster = lambda topic, title, body: posted.append((title, body))
        ev = _sale()
        delivered = delivery.deliver(ev, self.settings)
        delivery.notify(ev, self.settings, delivered)
        self.assertEqual(len(posted), 1)
        title, body = posted[0]
        self.assertIn("MANUAL", title.upper(), "標題要能一眼看出需人工處理")
        self.assertTrue(title.isascii(), "ntfy Title 必須 ASCII(header 限制)")
        self.assertIn("手動交付", body)


if __name__ == "__main__":
    unittest.main()
