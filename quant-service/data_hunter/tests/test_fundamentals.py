# -*- coding: utf-8 -*-
"""
test_fundamentals.py — 基本面/估值解析(fundamentals)不連網測試。
monkeypatch _get(BWIBBU) 與 _finmind(FinMind)，驗證估值/EPS/毛利/營收YoY/股利/除權息解析與缺值降級。
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402
import fundamentals as fd  # noqa: E402


FAKE_BWIBBU = json.dumps([
    {"Code": "2330", "PEratio": "33.68", "DividendYield": "0.88", "PBratio": "11.03"},
    {"Code": "2412", "PEratio": "--", "DividendYield": "3.70", "PBratio": "2.77"},
])


def _fake_finmind(dataset, data_id, start_date):
    if dataset == "TaiwanStockFinancialStatements":
        # 兩季 EPS + 一季 Revenue/GrossProfit/OperatingIncome
        return [
            {"date": "2026-03-31", "type": "EPS", "value": "8.0"},
            {"date": "2025-12-31", "type": "EPS", "value": "7.0"},
            {"date": "2025-09-30", "type": "EPS", "value": "6.0"},
            {"date": "2025-06-30", "type": "EPS", "value": "5.0"},
            {"date": "2025-03-31", "type": "EPS", "value": "4.0"},   # 去年同季(YoY 基準)
            {"date": "2026-03-31", "type": "Revenue", "value": "1000"},
            {"date": "2026-03-31", "type": "GrossProfit", "value": "600"},
            {"date": "2026-03-31", "type": "OperatingIncome", "value": "500"},
        ]
    if dataset == "TaiwanStockMonthRevenue":
        rows = [{"date": f"2026-{m:02d}-10", "revenue": str(100 + m)} for m in range(1, 7)]
        rows += [{"date": f"2025-{m:02d}-10", "revenue": "80"} for m in range(1, 13)]
        return rows
    if dataset == "TaiwanStockDividend":
        return [{"date": "2026-06-15", "CashEarningsDistribution": "6.0",
                 "StockEarningsDistribution": "0.0",
                 "CashExDividendTradingDate": "2026-07-15"}]
    return []


class TestValuation(unittest.TestCase):
    def setUp(self):
        self._g = fd._get
        self._w = fd._atomic_write_json
        fd._get = lambda url, timeout=25: FAKE_BWIBBU
        fd._atomic_write_json = lambda *a, **k: None   # 測試不得寫真快取(隔離)

    def tearDown(self):
        fd._get = self._g
        fd._atomic_write_json = self._w

    def test_bwibbu_parse(self):
        v = fd.fetch_valuation_all()
        self.assertEqual(v["2330"]["pe"], 33.68)
        self.assertEqual(v["2330"]["dividend_yield"], 0.88)
        self.assertEqual(v["2330"]["pb"], 11.03)

    def test_bwibbu_missing_pe_none(self):
        v = fd.fetch_valuation_all()
        self.assertIsNone(v["2412"]["pe"])           # '--' → None
        self.assertEqual(v["2412"]["dividend_yield"], 3.70)


class TestStockFundamentals(unittest.TestCase):
    def setUp(self):
        self._f = fd._finmind
        self._w = fd._atomic_write_json
        fd._finmind = _fake_finmind
        fd._atomic_write_json = lambda *a, **k: None   # 測試不得寫真快取(隔離)

    def tearDown(self):
        fd._finmind = self._f
        fd._atomic_write_json = self._w

    def test_eps_ttm_and_yoy(self):
        d = fd.fetch_stock_fundamentals("2330")
        self.assertEqual(d["eps_q"], 8.0)
        self.assertEqual(d["eps_ttm"], 26.0)          # 8+7+6+5
        self.assertEqual(d["eps_yoy"], 100.0)         # (8-4)/4*100

    def test_margins(self):
        d = fd.fetch_stock_fundamentals("2330")
        self.assertEqual(d["gross_margin"], 60.0)     # 600/1000
        self.assertEqual(d["op_margin"], 50.0)        # 500/1000

    def test_revenue_yoy(self):
        d = fd.fetch_stock_fundamentals("2330")
        # 最新月 rev=106(2026-06)、去年同月 80 → YoY (106-80)/80*100 = 32.5
        self.assertEqual(d["rev_yoy"], 32.5)

    def test_dividend_and_exdate(self):
        d = fd.fetch_stock_fundamentals("2330")
        self.assertEqual(d["cash_div"], 6.0)
        self.assertEqual(d["ex_date"], "2026-07-15")

    def test_missing_all_graceful(self):
        fd._finmind = lambda *a, **k: []
        d = fd.fetch_stock_fundamentals("9999")
        self.assertIsNone(d["eps_ttm"])
        self.assertIsNone(d["rev_yoy"])


class TestDividendTTM(unittest.TestCase):
    """近一年配息合計(ETF 季配)：加總 cash>0 的近 366 天筆、跳過 0.0 占位與逾一年舊筆。"""
    def setUp(self):
        self._f = fd._finmind
        self._w = fd._atomic_write_json
        fd._atomic_write_json = lambda *a, **k: None

    def tearDown(self):
        fd._finmind = self._f
        fd._atomic_write_json = self._w

    def test_etf_quarterly_ttm(self):
        from datetime import date as _d, timedelta as _td
        today = _d.today()
        rows = [
            {"date": (today + _td(days=20)).isoformat(),  "CashEarningsDistribution": "0.0"},   # 未來占位→跳過
            {"date": (today - _td(days=30)).isoformat(),  "CashEarningsDistribution": "1.0"},   # 最近一筆 cash>0
            {"date": (today - _td(days=120)).isoformat(), "CashEarningsDistribution": "0.9"},
            {"date": (today - _td(days=210)).isoformat(), "CashEarningsDistribution": "0.8"},
            {"date": (today - _td(days=300)).isoformat(), "CashEarningsDistribution": "0.7"},
            {"date": (today - _td(days=400)).isoformat(), "CashEarningsDistribution": "0.6"},   # 逾一年→排除
        ]
        fd._finmind = lambda ds, di, sd: rows if ds == "TaiwanStockDividend" else []
        d = fd.fetch_stock_fundamentals("0056")
        self.assertEqual(d["cash_div_ttm"], 3.4)   # 1.0+0.9+0.8+0.7，跳過 0.0 與 0.6(逾一年)
        self.assertEqual(d["div_freq"], 4)          # 季配四筆
        self.assertEqual(d["cash_div"], 1.0)        # 最近一筆 cash>0(非 0.0 占位)

    def test_no_positive_dividend(self):
        from datetime import date as _d, timedelta as _td
        rows = [{"date": (_d.today() + _td(days=10)).isoformat(), "CashEarningsDistribution": "0.0"}]
        fd._finmind = lambda ds, di, sd: rows if ds == "TaiwanStockDividend" else []
        d = fd.fetch_stock_fundamentals("1111")
        self.assertIsNone(d["cash_div_ttm"])        # 無 cash>0 → None
        self.assertIsNone(d["div_freq"])


if __name__ == "__main__":
    unittest.main()
