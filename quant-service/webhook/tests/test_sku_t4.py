"""T4(50 檔方案)SKU 登記回歸。

背景(2026-09-19):fb58bf3c 新增 T4_multi_checkup_50,但 config.SKU_CATALOG 沒登記它
→ download_url_for() **不管 ECOMMERCE_DL_T4 有沒有設**都回 None → 付款後永遠拒寄。
另一個坑:resolve_sku 是子字串比對,T4 商品名含 T3 的「多檔組合」,排序錯會被判成 T3。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import _util  # noqa: F401  (掛 sys.path)
from webhook import delivery, stock_checkup
from webhook.config import download_url_for, resolve_sku
from webhook.events import EventKind

_ECOM = Path(__file__).resolve().parents[2] / "ecommerce"
if str(_ECOM) not in sys.path:
    sys.path.insert(0, str(_ECOM))
import config as ecom_cfg  # noqa: E402

T4 = stock_checkup.SKU_ID_BULK


def _sale():
    return SimpleNamespace(
        kind=EventKind.SALE, sku_id=T4, email="buyer@e.com", name="",
        product=stock_checkup.PRODUCT_NAME_BULK, platform="ecpay", order_id="T4-1",
        amount=500.0, currency="TWD", tier=None, event_key="ecpay:T4-1")


class TestT4Sku(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("ECOMMERCE_DL_T4", None)
        self.sent: list = []
        self.settings = SimpleNamespace(
            dry_run=False, email_sender=lambda to, s, b: self.sent.append((to, s, b)) or True,
            ntfy_poster=None, ntfy_topic="t")

    def tearDown(self):
        os.environ.pop("ECOMMERCE_DL_T4", None)
        if self._saved is not None:
            os.environ["ECOMMERCE_DL_T4"] = self._saved

    def test_link_set_resolves_and_sends(self):
        os.environ["ECOMMERCE_DL_T4"] = "https://example.com/dl/t4"
        self.assertEqual(download_url_for(T4), "https://example.com/dl/t4")
        res = delivery.deliver(_sale(), self.settings)
        self.assertTrue(res["sent"])
        self.assertIn("https://example.com/dl/t4", self.sent[0][2])

    def test_link_unset_still_fail_closed(self):
        self.assertIsNone(download_url_for(T4))
        res = delivery.deliver(_sale(), self.settings)
        self.assertFalse(res["sent"])
        self.assertTrue(res.get("manual_required"))
        self.assertEqual(self.sent, [])

    def test_resolve_sku_does_not_confuse_t3_t4(self):
        self.assertEqual(resolve_sku(stock_checkup.PRODUCT_NAME_BULK, EventKind.SALE)["sku_id"], T4)
        self.assertEqual(resolve_sku(stock_checkup.PRODUCT_NAME, EventKind.SALE)["sku_id"],
                         stock_checkup.SKU_ID)

    def test_price_and_name_match_single_source(self):
        """stock_checkup 的硬寫價/名必須等於 ecommerce/config.ONE_OFF(分岔就紅)。"""
        for key, sku in (("T3", stock_checkup.SKU_ID), ("T4", T4)):
            with self.subTest(sku=sku):
                info = stock_checkup._SKUS[sku]
                self.assertEqual(info["price_ntd"], ecom_cfg.ONE_OFF[key]["ntd"])
                self.assertEqual(info["product_name"], ecom_cfg.ONE_OFF[key]["name_zh"])


if __name__ == "__main__":
    unittest.main()
