"""stock_checkup.py 路由測試：ECPay 是純簽章驗證(沒有對外 HTTP 呼叫)，用 ecpay._check_mac_value
本人算出的簽章組出「假裝是 ECPay 送來的」背景通知，不連外網、不動真錢。data_hunter 走真實
離線引擎（live=False，讀既有快取，跟其他 smoke test 一致，證明是真串接不是回假資料）。
重點覆蓋 fail-closed 分支：密鑰/PUBLIC_BASE_URL 未設、驗章失敗、金額不符、RtnCode 失敗、
重複通知不重複記帳、未知訂單。"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _util
from webhook.ecpay import _check_mac_value
from fastapi.testclient import TestClient
from webhook.app import build_app
from webhook.ledger import load_json
from webhook import stock_checkup as sc
from webhook.stock_checkup import _pick_teaser_stats, _teaser_line


class TestStockCheckup(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.entries: list = []
        self.mails: list = []
        self.ntfy: list = []
        self.settings = _util.make_settings(
            self.dir, _entries=self.entries, _mails=self.mails, _ntfy=self.ntfy,
            stock_checkup_orders=self.dir / "sco.json",
            ecpay_merchant_id="2000132", ecpay_hash_key="hashkey123", ecpay_hash_iv="hashiv456",
            public_base_url="https://example.trycloudflare.com",
        )
        self.client = TestClient(build_app(self.settings))

    def _order(self, **over):
        body = {"codes": ["2330"], "email": "buyer@example.com"}
        body.update(over)
        return self.client.post("/api/stock-checkup/order", json=body)

    def _notify_form(self, token: str, ntd: int, *, rtn_code="1", trade_amt=None,
                     trade_no="ecpaytx001", bad_sig=False):
        """組一份「假裝是 ECPay 送來的」背景通知表單，簽章用真正的 CheckMacValue 演算法算，
        跟 ecpay.py 用同一套規則但獨立算一次（不是呼叫 ecpay.py 本身），避免測試跟實作抄同一顆骰子。"""
        form = {
            "MerchantID": "2000132", "MerchantTradeNo": token,
            "RtnCode": rtn_code, "RtnMsg": "交易成功",
            "TradeNo": trade_no, "TradeAmt": str(trade_amt if trade_amt is not None else ntd),
            "PaymentDate": "2026/09/16 12:00:00", "PaymentType": "Credit_CreditCard",
            "TradeDate": "2026/09/16 11:58:00", "SimulatePaid": "0",
        }
        if bad_sig:
            form["CheckMacValue"] = "0" * 64
        else:
            form["CheckMacValue"] = _check_mac_value(
                self.settings.ecpay_hash_key, self.settings.ecpay_hash_iv, form)
        return form

    # ── 頁面 + 分析 ──────────────────────────────────────────────────────────
    def test_page_served(self):
        r = self.client.get("/stock-checkup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_analyze_real_data_hunter(self):
        r = self.client.post("/api/stock-checkup/analyze", json={"codes": ["2330"]})
        self.assertEqual(r.status_code, 200)
        results = r.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["code"], "2330")

    def test_analyze_too_many_codes_422(self):
        r = self.client.post("/api/stock-checkup/analyze",
                             json={"codes": ["1101", "1102", "1103", "1104", "1105", "1106"]})
        self.assertEqual(r.status_code, 422)

    def test_analyze_result_carries_teaser_fields(self):
        r = self.client.post("/api/stock-checkup/analyze", json={"codes": ["2330"]})
        result = r.json()["results"][0]
        self.assertIn("teaser_stats", result)
        self.assertIn("teaser_line", result)
        self.assertIsInstance(result["teaser_stats"], list)
        self.assertIsInstance(result["teaser_line"], str)

    def test_analyze_unknown_sku_422(self):
        r = self.client.post("/api/stock-checkup/analyze",
                             json={"codes": ["2330"], "sku_id": "bogus"})
        self.assertEqual(r.status_code, 422)

    # ── 50 檔方案(T4_multi_checkup_50):獨立 SKU,不動 T3 既有行為 ─────────────
    def test_analyze_bulk_sku_over_5_codes_runs_as_background_job(self):
        codes = ["2330", "2317", "2454", "2603", "2882", "1301"]
        r = self.client.post("/api/stock-checkup/analyze",
                             json={"codes": codes, "sku_id": "T4_multi_checkup_50"})
        self.assertEqual(r.status_code, 202)
        job = r.json()
        self.assertEqual(job["total"], 6)

        data = None
        deadline = time.time() + 90
        while time.time() < deadline:
            status = self.client.get(f"/api/stock-checkup/analyze/{job['job_id']}")
            self.assertEqual(status.status_code, 200)
            data = status.json()
            if data["status"] == "done":
                break
            time.sleep(0.5)
        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "done")
        self.assertEqual({r["code"] for r in data["results"]}, set(codes))

    def test_analyze_bulk_sku_within_5_codes_stays_synchronous(self):
        r = self.client.post("/api/stock-checkup/analyze",
                             json={"codes": ["2330"], "sku_id": "T4_multi_checkup_50"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["code"], "2330")

    def test_analyze_status_unknown_job_404(self):
        r = self.client.get("/api/stock-checkup/analyze/no-such-job")
        self.assertEqual(r.status_code, 404)

    def test_order_token_prefix_matches_sku(self):
        t3_token = self._order().json()["token"]
        t4_token = self._order(sku_id="T4_multi_checkup_50").json()["token"]
        self.assertTrue(t3_token.startswith("T3"))
        self.assertTrue(t4_token.startswith("T4"))

    def test_order_bulk_sku_pricing_and_product_name(self):
        r = self._order(sku_id="T4_multi_checkup_50")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["ntd"], 500)
        orders = load_json(self.settings.stock_checkup_orders, {})
        order = orders[data["token"]]
        self.assertEqual(order["product_name"], "個股體檢多檔組合(最多50檔)")
        self.assertEqual(order["sku_id"], "T4_multi_checkup_50")

    def test_order_bulk_sku_allows_more_than_5_codes(self):
        r = self._order(sku_id="T4_multi_checkup_50",
                        codes=["1101", "1102", "1103", "1104", "1105", "1106"])
        self.assertEqual(r.status_code, 200)

    def test_order_bulk_sku_still_caps_at_50(self):
        r = self._order(sku_id="T4_multi_checkup_50",
                        codes=[f"11{i:02d}" for i in range(51)])
        self.assertEqual(r.status_code, 422)

    def test_notify_bulk_sku_records_bulk_price_and_product(self):
        token = self._order(sku_id="T4_multi_checkup_50").json()["token"]
        form = self._notify_form(token, 500)
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.text, "1|OK")
        orders = load_json(self.settings.stock_checkup_orders, {})
        self.assertTrue(orders[token]["paid"])
        self.assertEqual(self.entries[-1]["amount"], 500.0)
        self.assertIn("個股體檢多檔組合(最多50檔)", self.entries[-1]["note"])

    def test_extract_codes_max_codes_clamped_at_route_level(self):
        # 前端亂傳超過 MAX_STOCKS_BULK(或 <=0)的數字，伺服端要在真正呼叫 vision 之前
        # 夾在 [1, MAX_STOCKS_BULK] 之間——不信任前端傳的數字本身。mock vision.extract_codes
        # 是因為它會打真的 OPENROUTER_API_KEY，不適合在單元測試連外網。
        with mock.patch("webhook.stock_checkup.vision.extract_codes") as fake:
            fake.return_value = ["2330"]
            files = {"file": ("shot.png", b"fake-bytes", "image/png")}
            r = self.client.post("/api/stock-checkup/extract-codes",
                                 files=files, data={"max_codes": "99999"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(fake.call_args[0][2], sc.MAX_STOCKS_BULK)

            r2 = self.client.post("/api/stock-checkup/extract-codes",
                                  files=files, data={"max_codes": "0"})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(fake.call_args[0][2], 1)


    # ── 建立訂單 / ECPay 表單簽章 ────────────────────────────────────────────
    def test_order_bad_email_422(self):
        r = self._order(email="not-an-email")
        self.assertEqual(r.status_code, 422)

    def test_order_gets_real_ecpay_checkout_url(self):
        r = self._order()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["checkout_configured"])
        self.assertIn("/api/stock-checkup/ecpay/checkout/", data["checkout_url"])
        # checkout 頁要真的帶出簽好章的表單，導向 ECPay 測試付款頁
        page = self.client.get(f"/api/stock-checkup/ecpay/checkout/{data['token']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("payment-stage.ecpay.com.tw", page.text)
        self.assertIn('name="CheckMacValue"', page.text)
        self.assertIn(f'name="MerchantTradeNo" value="{data["token"]}"', page.text)

    def test_order_fails_closed_without_public_base_url(self):
        self.settings.public_base_url = ""
        r = self._order()
        data = r.json()
        self.assertIsNone(data["checkout_url"])
        self.assertFalse(data["checkout_configured"])

    def test_order_fails_closed_without_ecpay_keys(self):
        self.settings.ecpay_hash_key = ""
        r = self._order()
        data = r.json()
        self.assertIsNone(data["checkout_url"])
        self.assertFalse(data["checkout_configured"])

    def test_checkout_unknown_token_404(self):
        r = self.client.get("/api/stock-checkup/ecpay/checkout/no-such-token")
        self.assertEqual(r.status_code, 404)

    # ── ECPay 背景通知(notify) ────────────────────────────────────────────
    def test_notify_completes_order_and_triggers_delivery(self):
        token = self._order().json()["token"]
        form = self._notify_form(token, 100)
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "1|OK")
        orders = load_json(self.settings.stock_checkup_orders, {})
        self.assertTrue(orders[token]["paid"])
        self.assertEqual(orders[token]["ecpay_trade_no"], "ecpaytx001")
        # ECOMMERCE_DL_T3 未設 → needs_manual_delivery，不真寄交付信但要 ntfy 叫 Carson 手動出件
        self.assertTrue(any(n["title"].startswith("CarsonQuant MANUAL DELIVERY")
                            for n in self.ntfy))

    def test_notify_rejects_bad_signature(self):
        token = self._order().json()["token"]
        form = self._notify_form(token, 100, bad_sig=True)
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.text, "0|CheckMacValueError")
        orders = load_json(self.settings.stock_checkup_orders, {})
        self.assertFalse(orders[token]["paid"])

    def test_notify_rejects_amount_mismatch(self):
        token = self._order().json()["token"]
        form = self._notify_form(token, 100, trade_amt=1)
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.text, "0|AmountMismatch")
        orders = load_json(self.settings.stock_checkup_orders, {})
        self.assertFalse(orders[token]["paid"])

    def test_notify_rtncode_failure_does_not_mark_paid(self):
        token = self._order().json()["token"]
        form = self._notify_form(token, 100, rtn_code="10100058")
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.text, "1|OK")   # 仍要回 1|OK，只是不記帳
        orders = load_json(self.settings.stock_checkup_orders, {})
        self.assertFalse(orders[token]["paid"])

    def test_notify_unknown_token(self):
        form = self._notify_form("no-such-token", 100)
        r = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r.text, "0|OrderNotFound")

    def test_notify_twice_does_not_double_deliver(self):
        token = self._order().json()["token"]
        form = self._notify_form(token, 100)
        self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        ntfy_count_after_first = len(self.ntfy)
        r2 = self.client.post("/api/stock-checkup/ecpay/notify", data=form)
        self.assertEqual(r2.text, "1|OK")
        self.assertEqual(len(self.ntfy), ntfy_count_after_first)   # 沒有重複叫出件

    def test_result_page_ok(self):
        token = self._order().json()["token"]
        r = self.client.get("/api/stock-checkup/ecpay/result",
                            params={"MerchantTradeNo": token, "RtnCode": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("付款處理中", r.text)

    def test_result_page_failed(self):
        r = self.client.get("/api/stock-checkup/ecpay/result",
                            params={"MerchantTradeNo": "x", "RtnCode": "0"})
        self.assertIn("付款未完成", r.text)


class TestTeaser(unittest.TestCase):
    """免費預覽「數字+缺口式教唆」的確定性(非LLM)挑選邏輯——沒資料的欄位不准出現。"""

    def test_picks_up_to_two_available_stats_in_priority_order(self):
        stats = _pick_teaser_stats({"dividend_yield": 4.5, "pe": 15, "eps_yoy": None})
        self.assertEqual(stats, [
            {"label": "殖利率", "value": "+4.5%"},
            {"label": "本益比", "value": "15倍"},
        ])

    def test_skips_missing_fields_entirely(self):
        stats = _pick_teaser_stats({"dividend_yield": None, "pe": None, "eps_yoy": -12.3})
        self.assertEqual(stats, [{"label": "EPS 年增率", "value": "-12.3%"}])

    def test_no_data_at_all_yields_empty_list(self):
        self.assertEqual(_pick_teaser_stats({}), [])

    def test_teaser_line_contrasts_strong_and_weak_pillar(self):
        health = {"pillars": {
            "技術": {"score": 90, "has_data": True},
            "籌碼": {"score": 50, "has_data": True},
            "基本面": {"score": 40, "has_data": True},
            "估值": {"score": 30, "has_data": True},
        }}
        line = _teaser_line(health)
        self.assertIn("技術面", line)
        self.assertIn("估值面", line)

    def test_teaser_line_neutral_when_pillars_close(self):
        health = {"pillars": {
            "技術": {"score": 60, "has_data": True},
            "籌碼": {"score": 55, "has_data": True},
        }}
        self.assertIn("接近", _teaser_line(health))

    def test_teaser_line_handles_missing_pillar_data(self):
        health = {"pillars": {"技術": {"score": 60, "has_data": True}}}
        self.assertIn("補齊", _teaser_line(health))


if __name__ == "__main__":
    unittest.main()
