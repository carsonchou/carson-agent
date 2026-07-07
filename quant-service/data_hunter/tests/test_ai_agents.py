# -*- coding: utf-8 -*-
"""
test_ai_agents.py — AI agent 共用地基(ai_agents.py)不連網測試。

monkeypatch llm.complete / query.analyze_stock / news.load_news / realtime_quote.fetch_*，
驗證 research_agent 能組出正確 schema、價格/漲跌一律用 analyze_stock 真值覆蓋(不讓 LLM 亂編)、
缺持股不炸、LLM 失敗不炸、簡轉繁不炸、save_state/load_state round-trip。
絕不打真的 LLM/FinMind/網路。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402
import ai_agents  # noqa: E402
import llm  # noqa: E402
import query  # noqa: E402
import news  # noqa: E402
import realtime_quote  # noqa: E402


FAKE_LLM_JSON = json.dumps({
    "market": {"tone": "偏多", "one_line": "大盤溫和上攻", "international": "美股續強"},
    "holdings": [
        {"code": "2330", "today": "外資買超", "impact": "偏多", "watch": "留意獲利了結賣壓", "price": 999},
        {"code": "2317", "today": "營收持平", "impact": "中性", "watch": "觀察出貨動能", "price": 888},
    ],
    "actions_note": "留意美股波動",
}, ensure_ascii=False)


def _fake_analyze_stock(code, live=False):
    data = {
        "2330": {"name": "台積電", "price": 1100.0, "chg": 1.5},
        "2317": {"name": "鴻海", "price": 210.0, "chg": -0.5},
    }
    d = data.get(code, {"name": code, "price": 100.0, "chg": 0.0})
    return {
        "ok": True, "code": code, "name": d["name"], "price": d["price"], "chg": d["chg"],
        "health": {"grade": "B", "overall": 72, "pillars": {}},
        "consec_buy_days": 3, "rev_yoy": 12.3, "eps_ttm": 8.1,
    }


def _fake_load_news(name, code, offline=True, limit=8):
    return [{"title": f"{name} 測試新聞", "source": "測試來源", "time": "07/07 09:00", "link": "http://x"}]


class _TmpHereMixin:
    """把 ai_agents.HERE/PREFS_FILE/MARKET_STATE_FILE 導向暫存目錄，測試不寫進真正的
    data_hunter/state_research.json，也不受本機真實 prefs.json/state.json 內容影響。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp_here = Path(self._tmpdir.name)
        self._orig_here = ai_agents.HERE
        self._orig_prefs = ai_agents.PREFS_FILE
        self._orig_market = ai_agents.MARKET_STATE_FILE
        ai_agents.HERE = self._tmp_here
        ai_agents.PREFS_FILE = self._tmp_here / "prefs.json"
        ai_agents.MARKET_STATE_FILE = self._tmp_here / "state.json"

    def tearDown(self):
        ai_agents.HERE = self._orig_here
        ai_agents.PREFS_FILE = self._orig_prefs
        ai_agents.MARKET_STATE_FILE = self._orig_market
        self._tmpdir.cleanup()


class TestStateRoundTrip(_TmpHereMixin, unittest.TestCase):
    def test_save_then_load(self):
        obj = {"hello": "world", "n": 3}
        ai_agents.save_state("unittest_tmp", obj)
        got = ai_agents.load_state("unittest_tmp")
        self.assertEqual(got, obj)

    def test_load_missing_returns_empty_dict(self):
        self.assertEqual(ai_agents.load_state("does_not_exist"), {})

    def test_save_is_atomic_no_tmp_left(self):
        ai_agents.save_state("unittest_tmp2", {"a": 1})
        self.assertTrue((self._tmp_here / "state_unittest_tmp2.json").exists())
        self.assertFalse((self._tmp_here / "state_unittest_tmp2.json.tmp").exists())


class TestToTraditional(unittest.TestCase):
    def test_handles_str_list_dict_without_raising(self):
        self.assertEqual(ai_agents._to_traditional("hello")[:5], "hello")
        self.assertIsInstance(ai_agents._to_traditional(["a", "b"]), list)
        self.assertIsInstance(ai_agents._to_traditional({"k": "v"}), dict)

    def test_handles_non_str_scalar(self):
        self.assertEqual(ai_agents._to_traditional(123), 123)
        self.assertIsNone(ai_agents._to_traditional(None))


class TestAsk(unittest.TestCase):
    def setUp(self):
        self._orig_complete = llm.complete

    def tearDown(self):
        llm.complete = self._orig_complete

    def test_valid_json_returns_dict(self):
        llm.complete = lambda prompt, max_tokens=3500, json_mode=False, temperature=None: '{"a": 1, "b": "x"}'
        out = ai_agents.ask("prompt", system="sys")
        self.assertEqual(out, {"a": 1, "b": "x"})

    def test_invalid_json_returns_error_dict_not_exception(self):
        llm.complete = lambda prompt, max_tokens=3500, json_mode=False, temperature=None: "not json at all"
        out = ai_agents.ask("prompt")
        self.assertEqual(out.get("_error"), "json parse failed")
        self.assertIn("_raw", out)

    def test_non_json_mode_returns_text(self):
        llm.complete = lambda prompt, max_tokens=3500, json_mode=False, temperature=None: "plain text"
        out = ai_agents.ask("prompt", json_mode=False)
        self.assertIsInstance(out, str)
        self.assertIn("plain text", out)


class TestPortfolioCodes(_TmpHereMixin, unittest.TestCase):
    def _write_prefs(self, dh_portfolio, dh_watch):
        data = {"dh_portfolio": json.dumps(dh_portfolio, ensure_ascii=False),
                "dh_watch": json.dumps(dh_watch, ensure_ascii=False)}
        ai_agents.PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ai_agents.PREFS_FILE.write_text(json.dumps({"data": data, "ts": 1}, ensure_ascii=False), encoding="utf-8")

    def test_extracts_codes_from_two_level_json_strings(self):
        pf = {"cash": 1000, "txns": [
            {"code": "2330", "side": "buy", "shares": 1000, "price": 500},
            {"code": "2317", "side": "buy", "shares": 2000, "price": 100},
        ], "dividends": [], "snapshots": []}
        watch = [{"code": "2454", "name": "聯發科"}]
        self._write_prefs(pf, watch)
        codes = ai_agents._portfolio_codes()
        self.assertEqual(set(codes), {"2330", "2317", "2454"})

    def test_fully_sold_position_excluded(self):
        pf = {"cash": 1000, "txns": [
            {"code": "2330", "side": "buy", "shares": 1000, "price": 500},
            {"code": "2330", "side": "sell", "shares": 1000, "price": 550},
        ], "dividends": [], "snapshots": []}
        self._write_prefs(pf, [])
        self.assertEqual(ai_agents._portfolio_codes(), [])

    def test_missing_prefs_file_returns_empty(self):
        self.assertEqual(ai_agents._portfolio_codes(), [])

    def test_corrupt_prefs_json_does_not_raise(self):
        ai_agents.PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ai_agents.PREFS_FILE.write_text("{not valid json", encoding="utf-8")
        self.assertEqual(ai_agents._portfolio_codes(), [])


class TestResearchAgent(_TmpHereMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._orig_complete = llm.complete
        self._orig_analyze = query.analyze_stock
        self._orig_news = news.load_news
        self._orig_fetch_idx = realtime_quote.fetch_indices
        self._orig_fetch_intl = realtime_quote.fetch_international
        llm.complete = lambda prompt, max_tokens=3500, json_mode=False, temperature=None: FAKE_LLM_JSON
        query.analyze_stock = _fake_analyze_stock
        news.load_news = _fake_load_news
        realtime_quote.fetch_indices = lambda: []
        realtime_quote.fetch_international = lambda: []

    def tearDown(self):
        llm.complete = self._orig_complete
        query.analyze_stock = self._orig_analyze
        news.load_news = self._orig_news
        realtime_quote.fetch_indices = self._orig_fetch_idx
        realtime_quote.fetch_international = self._orig_fetch_intl
        super().tearDown()

    def test_schema_and_price_overridden_by_real_value(self):
        out = ai_agents.research_agent(codes=["2330", "2317"])
        for key in ("date", "ts", "market", "holdings", "actions_note"):
            self.assertIn(key, out)
        self.assertEqual(out["market"]["tone"], "偏多")
        self.assertEqual(len(out["holdings"]), 2)
        h0 = next(h for h in out["holdings"] if h["code"] == "2330")
        # LLM 幻覺出的 price:999 必須被 analyze_stock 真值 1100.0 覆蓋
        self.assertEqual(h0["price"], 1100.0)
        self.assertEqual(h0["chg_pct"], 1.5)
        self.assertEqual(h0["grade"], "B")
        self.assertEqual(h0["today"], "外資買超")
        self.assertTrue(h0["news_ref"])

    def test_dedupes_and_caps_at_20(self):
        codes = [str(2000 + i) for i in range(25)] + ["2000"]  # 重複 + 超過 20
        out = ai_agents.research_agent(codes=codes)
        self.assertLessEqual(len(out["holdings"]), 20)

    def test_persisted_to_state_research(self):
        out = ai_agents.research_agent(codes=["2330"])
        got = ai_agents.load_state("research")
        self.assertEqual(got, out)

    def test_no_holdings_returns_error_not_exception(self):
        out = ai_agents.research_agent(codes=[])
        self.assertEqual(out.get("error"), "無持股")
        self.assertEqual(out.get("holdings"), [])

    def test_no_portfolio_no_codes_arg_falls_back_gracefully(self):
        # prefs.json 不存在(暫存目錄裡沒建) → _portfolio_codes 回空 → 走無持股分支，不炸
        out = ai_agents.research_agent(codes=None)
        self.assertEqual(out.get("error"), "無持股")

    def test_llm_failure_does_not_crash_and_yields_valid_schema(self):
        def _boom(prompt, max_tokens=3500, json_mode=False, temperature=None):
            raise RuntimeError("所有 LLM 供應商都失敗")
        llm.complete = _boom
        out = ai_agents.research_agent(codes=["2330"])
        self.assertIn("holdings", out)
        self.assertEqual(len(out["holdings"]), 1)
        # LLM 全掛：today/impact/watch 退回空字串，但價格仍是真值、不是空的
        self.assertEqual(out["holdings"][0]["today"], "")
        self.assertEqual(out["holdings"][0]["price"], 1100.0)
        self.assertEqual(out["market"]["tone"], "中性")   # 預設值

    def test_llm_malformed_json_does_not_crash(self):
        llm.complete = lambda prompt, max_tokens=3500, json_mode=False, temperature=None: "totally not json"
        out = ai_agents.research_agent(codes=["2330"])
        self.assertEqual(len(out["holdings"]), 1)
        self.assertEqual(out["holdings"][0]["today"], "")

    def test_query_analyze_stock_failure_does_not_crash(self):
        def _boom(code, live=False):
            raise RuntimeError("network down")
        query.analyze_stock = _boom
        out = ai_agents.research_agent(codes=["2330"])
        self.assertEqual(len(out["holdings"]), 1)
        self.assertIsNone(out["holdings"][0]["price"])   # 抓不到價 → None，不是亂編


if __name__ == "__main__":
    unittest.main()
