# -*- coding: utf-8 -*-
"""
test_valuation.py — 財務估值模型(valuation.py)不連網測試。

對每一法做公式對拍(手算預期 cheap/fair/expensive)、position 分級邊界測試、缺資料降級
(某法跳過、全缺回 None 不炸)、gap_to_fair_pct 計算、Excel 匯出(openpyxl 有裝才測)。
絕不打真的 FinMind/query/LLM/網路。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402
import valuation as vl  # noqa: E402


# ── 通用工具 ─────────────────────────────────────────────────────────────────
class TestPercentile(unittest.TestCase):
    def test_known_values(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(vl._percentile(vals, 0.25), 2.0)
        self.assertEqual(vl._percentile(vals, 0.50), 3.0)
        self.assertEqual(vl._percentile(vals, 0.75), 4.0)

    def test_single_value(self):
        self.assertEqual(vl._percentile([9.0], 0.25), 9.0)

    def test_empty_returns_none(self):
        self.assertIsNone(vl._percentile([], 0.5))


class TestClamp(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(vl._clamp(10, 5, 30), 10)

    def test_below_clamps_to_lo(self):
        self.assertEqual(vl._clamp(2, 5, 30), 5)

    def test_above_clamps_to_hi(self):
        self.assertEqual(vl._clamp(50, 5, 30), 30)


class TestIndustryPeBand(unittest.TestCase):
    def test_semiconductor(self):
        self.assertEqual(vl._industry_pe_band("半導體業"), (15.0, 20.0, 25.0))

    def test_finance(self):
        self.assertEqual(vl._industry_pe_band("金融保險業"), (10.0, 12.5, 15.0))

    def test_traditional(self):
        self.assertEqual(vl._industry_pe_band("水泥工業"), (12.0, 15.0, 18.0))

    def test_other_default(self):
        self.assertEqual(vl._industry_pe_band("其他"), (12.0, 16.0, 20.0))

    def test_none_falls_to_other(self):
        self.assertEqual(vl._industry_pe_band(None), (12.0, 16.0, 20.0))


class TestQuarterlyEpsAndTtm(unittest.TestCase):
    def test_quarterly_eps_sorted_and_deduped(self):
        fs_rows = [
            {"date": "2025-06-30", "type": "EPS", "value": "2.0"},
            {"date": "2025-03-31", "type": "EPS", "value": "1.0"},
            {"date": "2025-03-31", "type": "EPS", "value": "1.5"},   # 同日重複，後者覆蓋
            {"date": "2025-03-31", "type": "Revenue", "value": "999"},  # 非 EPS，忽略
        ]
        # 用等價 _num 實作(fundamentals._num 邏輯很單純：轉 float，壞值 None)
        def _num(x):
            try:
                return float(x)
            except Exception:
                return None
        got = vl._quarterly_eps(fs_rows, _num)
        self.assertEqual(got, [("2025-03-31", 1.5), ("2025-06-30", 2.0)])

    def test_rolling_ttm_needs_4_quarters(self):
        seq = [("2025Q1", 1.0), ("2025Q2", 1.0), ("2025Q3", 1.0), ("2025Q4", 1.0), ("2026Q1", 2.0)]
        got = vl._rolling_ttm(seq)
        # 前3筆資料不足(<4季)不輸出；第4筆起可算
        self.assertEqual(got, [("2025Q4", 4.0), ("2026Q1", 5.0)])

    def test_rolling_ttm_insufficient_returns_empty(self):
        self.assertEqual(vl._rolling_ttm([("2025Q1", 1.0), ("2025Q2", 1.0)]), [])


class TestQuarterLabel(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(vl._quarter_label("2025-03-31"), "2025Q1")
        self.assertEqual(vl._quarter_label("2025-06-30"), "2025Q2")
        self.assertEqual(vl._quarter_label("2025-09-30"), "2025Q3")
        self.assertEqual(vl._quarter_label("2025-12-31"), "2025Q4")

    def test_bad_input_returns_original(self):
        self.assertEqual(vl._quarter_label("garbage"), "garbage")


# ── 四法公式對拍：n=81 收盤序列 100..180，percentile 索引落在整數(20/40/60)不需內插 ──
_CLOSES_81 = [100.0 + i for i in range(81)]  # 100..180


class TestMethodPE(unittest.TestCase):
    def test_historical_percentile_band(self):
        df = _util.make_df(_CLOSES_81)
        # 單一 EPS_ttm=10.0(日期早於所有交易日)，merge_asof backward 全對齊到 10.0
        eps_ttm_series = [("2020-01-01", 10.0)]
        m = vl._method_pe(df, eps_ttm_series, eps_ttm_now=10.0, industry="半導體業")
        self.assertIsNotNone(m)
        # pe_series[i] = (100+i)/10，k=20/40/60 對應 close=120/140/160
        self.assertAlmostEqual(m["cheap"], 120.0, places=2)
        self.assertAlmostEqual(m["fair"], 140.0, places=2)
        self.assertAlmostEqual(m["expensive"], 160.0, places=2)
        self.assertEqual(m["source"], "歷史PE分位")

    def test_insufficient_history_falls_back_to_industry_default(self):
        df = _util.make_df(_CLOSES_81[:10])
        m = vl._method_pe(df, [], eps_ttm_now=10.0, industry="半導體業")
        self.assertIsNotNone(m)
        self.assertEqual(m["source"], "產業預設")
        # 半導體預設 15-25 倍，fair 取中值 20
        self.assertEqual(m["cheap"], 150.0)
        self.assertEqual(m["fair"], 200.0)
        self.assertEqual(m["expensive"], 250.0)

    def test_missing_eps_ttm_returns_none(self):
        df = _util.make_df(_CLOSES_81)
        self.assertIsNone(vl._method_pe(df, [], eps_ttm_now=None, industry="其他"))
        self.assertIsNone(vl._method_pe(df, [], eps_ttm_now=0, industry="其他"))

    def test_missing_df_returns_none(self):
        self.assertIsNone(vl._method_pe(None, [], eps_ttm_now=10.0, industry="其他"))


class TestMethodDividend(unittest.TestCase):
    def test_historical_percentile_band(self):
        df = _util.make_df(_CLOSES_81)
        fnd = {"cash_div_ttm": 5.0, "dividend_yield": 3.0}
        m = vl._method_dividend(df, fnd)
        self.assertIsNotNone(m)
        # 手算：sorted yields 對應 close 180-j；P25(j=20)->close160->yield=5/160；
        # cheap=5/y_hi(close100端,j=60,5/120)=120；fair=5/y_mid(j=40,5/140)=140；
        # expensive=5/y_lo(j=20,5/160)=160
        self.assertAlmostEqual(m["cheap"], 120.0, places=2)
        self.assertAlmostEqual(m["fair"], 140.0, places=2)
        self.assertAlmostEqual(m["expensive"], 160.0, places=2)
        self.assertEqual(m["source"], "歷史殖利率分位")

    def test_no_cash_div_returns_none(self):
        df = _util.make_df(_CLOSES_81)
        self.assertIsNone(vl._method_dividend(df, {"cash_div_ttm": None}))
        self.assertIsNone(vl._method_dividend(df, {"cash_div_ttm": 0}))

    def test_insufficient_history_uses_tier_default(self):
        df = _util.make_df(_CLOSES_81[:10])
        # 高息股(dividend_yield>=5) → 目標殖利率 5-7%
        m_hi = vl._method_dividend(df, {"cash_div_ttm": 6.0, "dividend_yield": 6.0})
        self.assertEqual(m_hi["source"], "等級預設")
        self.assertAlmostEqual(m_hi["cheap"], 6.0 / 0.07, places=2)
        self.assertAlmostEqual(m_hi["expensive"], 6.0 / 0.05, places=2)
        # 一般股 → 目標殖利率 3-4%
        m_lo = vl._method_dividend(df, {"cash_div_ttm": 3.0, "dividend_yield": 2.0})
        self.assertAlmostEqual(m_lo["cheap"], 3.0 / 0.04, places=2)
        self.assertAlmostEqual(m_lo["expensive"], 3.0 / 0.03, places=2)


class TestMethodPB(unittest.TestCase):
    def test_historical_percentile_band(self):
        df = _util.make_df(_CLOSES_81)
        price = 180.0
        fnd = {"pb": 2.0}   # BVPS = 180/2 = 90
        m = vl._method_pb(df, price, fnd)
        self.assertIsNotNone(m)
        # pb_series[i]=(100+i)/90，k=20/40/60 對應 close=120/140/160 → *BVPS(90)/close 值本身即倍數
        self.assertAlmostEqual(m["cheap"], 120.0, places=2)
        self.assertAlmostEqual(m["fair"], 140.0, places=2)
        self.assertAlmostEqual(m["expensive"], 160.0, places=2)

    def test_missing_pb_returns_none(self):
        df = _util.make_df(_CLOSES_81)
        self.assertIsNone(vl._method_pb(df, 180.0, {"pb": None}))
        self.assertIsNone(vl._method_pb(df, 180.0, {"pb": 0}))

    def test_missing_price_returns_none(self):
        df = _util.make_df(_CLOSES_81)
        self.assertIsNone(vl._method_pb(df, None, {"pb": 2.0}))


class TestMethodGrowth(unittest.TestCase):
    def test_peg_within_clamp(self):
        fnd = {"eps_yoy": 20.0}
        ms = vl._method_growth("2330", eps_ttm_now=10.0, fnd=fnd, fundamentals_mod=None)
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertEqual(m["fair"], 200.0)      # 10*20
        self.assertEqual(m["cheap"], 160.0)      # 200*0.8
        self.assertEqual(m["expensive"], 240.0)  # 200*1.2

    def test_peg_clamped_low(self):
        fnd = {"eps_yoy": 2.0}   # < 5 → clamp 到 5
        ms = vl._method_growth("2330", eps_ttm_now=10.0, fnd=fnd, fundamentals_mod=None)
        self.assertEqual(ms[0]["fair"], 50.0)

    def test_peg_clamped_high(self):
        fnd = {"eps_yoy": 50.0}  # > 30 → clamp 到 30
        ms = vl._method_growth("2330", eps_ttm_now=10.0, fnd=fnd, fundamentals_mod=None)
        self.assertEqual(ms[0]["fair"], 300.0)

    def test_no_eps_yoy_skips_peg(self):
        ms = vl._method_growth("2330", eps_ttm_now=10.0, fnd={"eps_yoy": None}, fundamentals_mod=None)
        self.assertEqual(ms, [])

    def test_gordon_growth_model(self):
        fnd = {"eps_yoy": None, "div_freq": 4, "cash_div_ttm": 10.0}
        orig = vl._estimate_dividend_growth
        vl._estimate_dividend_growth = lambda code, mod: 0.04
        try:
            ms = vl._method_growth("2330", eps_ttm_now=None, fnd=fnd, fundamentals_mod=object())
        finally:
            vl._estimate_dividend_growth = orig
        self.assertEqual(len(ms), 1)
        m = ms[0]
        # D1=10*(1.04)=10.4；fair=10.4/(0.09-0.04)=208；cheap(r=0.10)=10.4/0.06≈173.33；expensive(r=0.08)=10.4/0.04=260
        self.assertAlmostEqual(m["fair"], 208.0, places=2)
        self.assertAlmostEqual(m["cheap"], 173.33, places=1)
        self.assertAlmostEqual(m["expensive"], 260.0, places=2)

    def test_gordon_skipped_when_g_exceeds_r(self):
        fnd = {"eps_yoy": None, "div_freq": 4, "cash_div_ttm": 10.0}
        orig = vl._estimate_dividend_growth
        vl._estimate_dividend_growth = lambda code, mod: 0.20   # clamp 到 0.08，但仍 <0.09 不觸發跳過
        try:
            ms = vl._method_growth("2330", eps_ttm_now=None, fnd=fnd, fundamentals_mod=object())
        finally:
            vl._estimate_dividend_growth = orig
        self.assertEqual(len(ms), 1)   # clamp(0.20,0,0.08)=0.08 < r=0.09，仍可算

    def test_gordon_skipped_without_div_freq(self):
        fnd = {"eps_yoy": None, "div_freq": None, "cash_div_ttm": 10.0}
        ms = vl._method_growth("2330", eps_ttm_now=None, fnd=fnd, fundamentals_mod=object())
        self.assertEqual(ms, [])


# ── position 分級邊界測試 + gap_to_fair_pct ──────────────────────────────────
class TestClassifyPosition(unittest.TestCase):
    def test_missing_price_or_fair(self):
        self.assertEqual(vl._classify_position(None, 90, 100, 110), ("資料不足", None))
        self.assertEqual(vl._classify_position(100, 90, None, 110), ("資料不足", None))

    def test_cheap_boundary(self):
        pos, gap = vl._classify_position(89.9, 90, 100, 110)
        self.assertEqual(pos, "便宜")

    def test_low_boundary_at_cheap(self):
        pos, _ = vl._classify_position(90.0, 90, 100, 110)   # ==cheap → 不算便宜(便宜是 <cheap)
        self.assertEqual(pos, "偏低")

    def test_low_just_below_fair95(self):
        pos, _ = vl._classify_position(94.9, 90, 100, 110)   # <95 → 偏低
        self.assertEqual(pos, "偏低")

    def test_fair_at_95_boundary(self):
        pos, _ = vl._classify_position(95.0, 90, 100, 110)   # ==95 → 合理(左閉)
        self.assertEqual(pos, "合理")

    def test_fair_at_105_boundary(self):
        pos, _ = vl._classify_position(105.0, 90, 100, 110)  # ==105 → 合理(右閉)
        self.assertEqual(pos, "合理")

    def test_high_just_above_105(self):
        pos, _ = vl._classify_position(105.1, 90, 100, 110)  # >105 → 偏高
        self.assertEqual(pos, "偏高")

    def test_high_at_expensive_boundary(self):
        pos, _ = vl._classify_position(110.0, 90, 100, 110)  # ==expensive → 偏高(右閉)
        self.assertEqual(pos, "偏高")

    def test_expensive_above_boundary(self):
        pos, _ = vl._classify_position(110.1, 90, 100, 110)
        self.assertEqual(pos, "昂貴")

    def test_gap_to_fair_pct(self):
        _, gap = vl._classify_position(110.0, 90, 100, 110)
        self.assertEqual(gap, 10.0)    # (110/100-1)*100
        _, gap2 = vl._classify_position(80.0, 90, 100, 110)
        self.assertEqual(gap2, -20.0)

    def test_missing_cheap_or_expensive_falls_back_to_fair_no_crash(self):
        pos, gap = vl._classify_position(100.0, None, 100, None)
        self.assertEqual(pos, "合理")
        self.assertEqual(gap, 0.0)


# ── build_valuation 整合測試：monkeypatch query/analyst/fundamentals/ai_agents ──
class _FakeFundamentals:
    """假 fundamentals 模組(整合測試用)：不打真網路，回固定資料。"""

    def __init__(self, fnd=None, rat=None, fs_rows=None):
        self._fnd = fnd or {}
        self._rat = rat or {}
        self._fs_rows = fs_rows or []

    def load_fundamentals(self, code, offline=True):
        return dict(self._fnd)

    def load_financial_ratios(self, code):
        return dict(self._rat)

    def _finmind(self, dataset, code, start_date):
        if dataset == "TaiwanStockFinancialStatements":
            return self._fs_rows
        return []

    @staticmethod
    def _num(x):
        try:
            return float(x)
        except Exception:
            return None


class TestBuildValuationIntegration(unittest.TestCase):
    def setUp(self):
        import query, analyst, ai_agents
        self._q_resolve = query._resolve_code
        self._q_meta = query._meta
        self._a_load = analyst._load_ohlcv
        self._save_state = ai_agents.save_state
        query._resolve_code = lambda q: q
        query._meta = lambda code: ("測試股", "半導體業")
        ai_agents.save_state = lambda name, obj: None   # 隔離：測試不得寫真檔

    def tearDown(self):
        import query, analyst, ai_agents
        query._resolve_code = self._q_resolve
        query._meta = self._q_meta
        analyst._load_ohlcv = self._a_load
        ai_agents.save_state = self._save_state

    def test_full_success_all_methods(self):
        import analyst
        df = _util.make_df(_CLOSES_81)
        analyst._load_ohlcv = lambda code: df
        fake_fd = _FakeFundamentals(
            fnd={"eps_ttm": 10.0, "eps_yoy": 15.0, "pe": 14.0, "pb": 2.0,
                 "dividend_yield": 3.0, "cash_div_ttm": 5.0, "div_freq": 2,
                 "gross_margin": 50.0, "op_margin": 30.0},
            rat={"current_ratio": 2.0, "debt_ratio": 30.0, "fcf": 100.0, "roe": 20.0,
                 "grade": {"current_ratio": "好"}},
        )
        sys.modules["fundamentals"] = fake_fd
        try:
            r = vl.build_valuation("2330")
        finally:
            del sys.modules["fundamentals"]
        self.assertEqual(r["code"], "2330")
        self.assertEqual(r["price"], 180.0)
        self.assertIsNotNone(r["range"]["fair"])
        # PE/殖利率/PB/PEG 至少 4 法可算出(Gordon 需額外股利歷史，這裡假模組無此序列會跳過或安全降級)
        names = {m["name"] for m in r["methods"]}
        self.assertIn("PE法", names)
        self.assertIn("殖利率法", names)
        self.assertIn("PB法", names)
        self.assertIn("成長模型(PEG)", names)
        self.assertIn(r["position"], ("便宜", "偏低", "合理", "偏高", "昂貴"))
        self.assertIsNotNone(r["gap_to_fair_pct"])
        self.assertEqual(r["ratios"]["current_ratio"], 2.0)
        self.assertEqual(r["eps_history"], [])  # 假模組無 EPS 序列(_finmind 回空)
        self.assertEqual(r["disclaimer"], vl.DISCLAIMER)

    def test_all_data_missing_degrades_gracefully_no_crash(self):
        import analyst
        analyst._load_ohlcv = lambda code: None
        fake_fd = _FakeFundamentals(fnd={}, rat={})
        sys.modules["fundamentals"] = fake_fd
        try:
            r = vl.build_valuation("9999")
        finally:
            del sys.modules["fundamentals"]
        self.assertIsNone(r["price"])
        self.assertEqual(r["range"], {"cheap": None, "fair": None, "expensive": None})
        self.assertEqual(r["methods"], [])
        self.assertEqual(r["position"], "資料不足")
        self.assertIsNone(r["gap_to_fair_pct"])

    def test_empty_code_returns_safe_default(self):
        r = vl.build_valuation("")
        self.assertEqual(r["range"], {"cheap": None, "fair": None, "expensive": None})
        self.assertEqual(r["position"], "資料不足")

    def test_partial_data_some_methods_skip(self):
        """只有 PE 法可算(無 pb/無 cash_div/無 eps_yoy) → methods 只含 PE法，不炸。"""
        import analyst
        df = _util.make_df(_CLOSES_81)
        analyst._load_ohlcv = lambda code: df
        fake_fd = _FakeFundamentals(fnd={"eps_ttm": 10.0}, rat={})
        sys.modules["fundamentals"] = fake_fd
        try:
            r = vl.build_valuation("2330")
        finally:
            del sys.modules["fundamentals"]
        names = {m["name"] for m in r["methods"]}
        self.assertEqual(names, {"PE法"})
        self.assertIsNotNone(r["range"]["fair"])


# ── Excel 匯出（openpyxl 有裝才測；沒裝就 skip） ─────────────────────────────
def _has_openpyxl() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_has_openpyxl(), "openpyxl 未安裝，跳過 Excel 匯出測試")
class TestBuildValuationXlsx(unittest.TestCase):
    def setUp(self):
        import query, analyst, ai_agents
        self._q_resolve = query._resolve_code
        self._q_meta = query._meta
        self._a_load = analyst._load_ohlcv
        self._save_state = ai_agents.save_state
        query._resolve_code = lambda q: q
        query._meta = lambda code: ("測試股", "半導體業")
        ai_agents.save_state = lambda name, obj: None
        df = _util.make_df(_CLOSES_81)
        analyst._load_ohlcv = lambda code: df
        self._fake_fd = _FakeFundamentals(
            fnd={"eps_ttm": 10.0, "eps_yoy": 15.0, "pe": 14.0, "pb": 2.0,
                 "dividend_yield": 3.0, "cash_div_ttm": 5.0},
            rat={"current_ratio": 2.0, "grade": {"current_ratio": "好"}},
        )
        sys.modules["fundamentals"] = self._fake_fd

    def tearDown(self):
        import query, analyst, ai_agents
        query._resolve_code = self._q_resolve
        query._meta = self._q_meta
        analyst._load_ohlcv = self._a_load
        ai_agents.save_state = self._save_state
        if sys.modules.get("fundamentals") is self._fake_fd:
            del sys.modules["fundamentals"]

    def test_xlsx_bytes_non_empty_and_has_4_sheets(self):
        body = vl.build_valuation_xlsx("2330")
        self.assertIsInstance(body, (bytes, bytearray))
        self.assertGreater(len(body), 0)
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(body))
        self.assertEqual(len(wb.sheetnames), 4)
        self.assertIn("估值總表", wb.sheetnames)
        self.assertIn("財務比率", wb.sheetnames)
        self.assertIn("EPS歷史", wb.sheetnames)
        self.assertIn("假設與來源", wb.sheetnames)


if __name__ == "__main__":
    unittest.main()
