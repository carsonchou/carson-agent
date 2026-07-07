# -*- coding: utf-8 -*-
"""
test_fundamentals_ratios.py — 財務比率(fundamentals.fetch_financial_ratios/load_financial_ratios)不連網測試。

monkeypatch _finmind 回假三表(資產負債表/現金流量表/財報)資料，驗證流動比/速動比/負債比/
利息保障倍數/FCF/ROE 算出正確值＋判級(好/普/差)，以及任何子項缺資料 → None 不炸。
絕不打真的 FinMind/網路。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402
import fundamentals as fd  # noqa: E402


def _fake_finmind_full(dataset, data_id, start_date):
    if dataset == "TaiwanStockBalanceSheet":
        return [
            {"date": "2026-03-31", "type": "CurrentAssets", "value": "2000"},
            {"date": "2026-03-31", "type": "CurrentLiabilities", "value": "1000"},
            {"date": "2026-03-31", "type": "Inventories", "value": "300"},
            {"date": "2026-03-31", "type": "TotalAssets", "value": "5000"},
            {"date": "2026-03-31", "type": "Liabilities", "value": "1500"},
            {"date": "2026-03-31", "type": "Equity", "value": "3500"},
        ]
    if dataset == "TaiwanStockCashFlowsStatement":
        return [
            {"date": "2026-03-31", "type": "CashFlowsFromOperatingActivities", "value": "800"},
            {"date": "2026-03-31", "type": "PropertyAndPlantAndEquipment", "value": "-200"},
            {"date": "2026-03-31", "type": "InterestExpense", "value": "40"},
        ]
    if dataset == "TaiwanStockFinancialStatements":
        return [{"date": "2026-03-31", "type": "OperatingIncome", "value": "600"}]
    return []


class TestFinancialRatiosCalc(unittest.TestCase):
    def setUp(self):
        self._f = fd._finmind
        self._w = fd._atomic_write_json
        self._lsf = fd.load_stock_fundamentals
        self._lv = fd.load_valuation
        self._lp = fd._latest_price
        fd._finmind = _fake_finmind_full
        fd._atomic_write_json = lambda *a, **k: None            # 測試不得寫真快取(隔離)
        fd.load_stock_fundamentals = lambda code, offline=True: {"eps_ttm": 10.0}
        fd.load_valuation = lambda offline=True: {"2330": {"pb": 5.0}}
        fd._latest_price = lambda code: 100.0

    def tearDown(self):
        fd._finmind = self._f
        fd._atomic_write_json = self._w
        fd.load_stock_fundamentals = self._lsf
        fd.load_valuation = self._lv
        fd._latest_price = self._lp

    def test_current_and_quick_ratio(self):
        r = fd.fetch_financial_ratios("2330")
        self.assertEqual(r["current_ratio"], 2.0)          # 2000/1000
        self.assertEqual(r["quick_ratio"], 1.7)             # (2000-300)/1000

    def test_debt_ratio(self):
        r = fd.fetch_financial_ratios("2330")
        self.assertEqual(r["debt_ratio"], 30.0)             # 1500/5000*100

    def test_fcf_and_op_cf(self):
        r = fd.fetch_financial_ratios("2330")
        self.assertEqual(r["op_cf"], 800.0)
        self.assertEqual(r["fcf"], 600.0)                   # 800 - abs(-200)

    def test_interest_cover(self):
        r = fd.fetch_financial_ratios("2330")
        self.assertEqual(r["interest_cover"], 15.0)         # 600/40

    def test_roe_uses_health_roe_est(self):
        # eps_ttm=10, pb=5, price=100 → 10*5/100*100 = 50.0
        r = fd.fetch_financial_ratios("2330")
        self.assertEqual(r["roe"], 50.0)

    def test_grades(self):
        r = fd.fetch_financial_ratios("2330")
        g = r["grade"]
        self.assertEqual(g["current_ratio"], "好")           # 2.0 > 1.5
        self.assertEqual(g["debt_ratio"], "好")               # 30 < 40
        self.assertEqual(g["fcf"], "好")                      # 600 > 0
        self.assertEqual(g["interest_cover"], "好")           # 15 > 5
        self.assertEqual(g["roe"], "好")                      # 50 > 15


class TestFinancialRatiosMissingData(unittest.TestCase):
    def setUp(self):
        self._f = fd._finmind
        self._w = fd._atomic_write_json
        self._lsf = fd.load_stock_fundamentals
        self._lv = fd.load_valuation
        self._lp = fd._latest_price
        fd._atomic_write_json = lambda *a, **k: None

    def tearDown(self):
        fd._finmind = self._f
        fd._atomic_write_json = self._w
        fd.load_stock_fundamentals = self._lsf
        fd.load_valuation = self._lv
        fd._latest_price = self._lp

    def test_all_empty_does_not_raise_and_all_none(self):
        fd._finmind = lambda *a, **k: []
        fd.load_stock_fundamentals = lambda code, offline=True: None
        fd.load_valuation = lambda offline=True: {}
        fd._latest_price = lambda code: None
        r = fd.fetch_financial_ratios("9999")
        for k in ("current_ratio", "quick_ratio", "debt_ratio", "interest_cover", "fcf", "op_cf", "roe"):
            self.assertIsNone(r[k])
        for v in r["grade"].values():
            self.assertIsNone(v)

    def test_partial_data_only_computes_available(self):
        # 只有資產負債表，沒有現金流量表/財報 → 流動比/負債比可算，FCF/利息保障/ROE 為 None
        def _partial(dataset, data_id, start_date):
            if dataset == "TaiwanStockBalanceSheet":
                return [
                    {"date": "2026-03-31", "type": "CurrentAssets", "value": "1000"},
                    {"date": "2026-03-31", "type": "CurrentLiabilities", "value": "500"},
                    {"date": "2026-03-31", "type": "TotalAssets", "value": "3000"},
                    {"date": "2026-03-31", "type": "Liabilities", "value": "900"},
                ]
            return []
        fd._finmind = _partial
        fd.load_stock_fundamentals = lambda code, offline=True: None
        fd.load_valuation = lambda offline=True: {}
        fd._latest_price = lambda code: None
        r = fd.fetch_financial_ratios("1111")
        self.assertEqual(r["current_ratio"], 2.0)
        self.assertIsNone(r["quick_ratio"])           # 無 Inventories → None
        self.assertEqual(r["debt_ratio"], 30.0)
        self.assertIsNone(r["fcf"])
        self.assertIsNone(r["interest_cover"])
        self.assertIsNone(r["roe"])

    def test_zero_denominator_does_not_raise(self):
        def _zero_liab(dataset, data_id, start_date):
            if dataset == "TaiwanStockBalanceSheet":
                return [
                    {"date": "2026-03-31", "type": "CurrentAssets", "value": "1000"},
                    {"date": "2026-03-31", "type": "CurrentLiabilities", "value": "0"},
                    {"date": "2026-03-31", "type": "TotalAssets", "value": "0"},
                    {"date": "2026-03-31", "type": "Liabilities", "value": "500"},
                ]
            return []
        fd._finmind = _zero_liab
        fd.load_stock_fundamentals = lambda code, offline=True: None
        fd.load_valuation = lambda offline=True: {}
        fd._latest_price = lambda code: None
        r = fd.fetch_financial_ratios("2222")               # 除以 0 不炸(0 視同缺資料 → None)
        self.assertIsNone(r["current_ratio"])
        self.assertIsNone(r["debt_ratio"])


class TestLoadFinancialRatios(unittest.TestCase):
    def setUp(self):
        self._dir = fd.FUND_DIR
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        fd.FUND_DIR = Path(self._tmp.name)

    def tearDown(self):
        fd.FUND_DIR = self._dir
        self._tmp.cleanup()

    def test_missing_cache_offline_returns_none(self):
        self.assertIsNone(fd.load_financial_ratios("9999", offline=True))

    def test_missing_cache_non_offline_fetches(self):
        orig = fd.fetch_financial_ratios
        called = {}
        def _fake(code):
            called["code"] = code
            return {"code": code, "current_ratio": 1.0}
        fd.fetch_financial_ratios = _fake
        try:
            r = fd.load_financial_ratios("2330", offline=False)
            self.assertEqual(called.get("code"), "2330")
            self.assertEqual(r["current_ratio"], 1.0)
        finally:
            fd.fetch_financial_ratios = orig

    def test_stale_cache_offline_returns_old_data(self):
        import json
        from datetime import datetime, timedelta
        old = {"code": "2330", "current_ratio": 9.9,
               "fetched_at": (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")}
        (fd.FUND_DIR / "stock_ratios_2330.json").write_text(json.dumps(old), encoding="utf-8")
        r = fd.load_financial_ratios("2330", offline=True)
        self.assertEqual(r["current_ratio"], 9.9)


if __name__ == "__main__":
    unittest.main()
