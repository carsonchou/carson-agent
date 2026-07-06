# -*- coding: utf-8 -*-
"""
test_daytrade.py — 盤中即時當沖決策系統(批1) 不連網單元測試。
涵蓋：量化淨EV大腦(因子/勝率/淨EV/分級/部位/gate/penalty/logistic)、CDP、累積器、
觸發+二次確認、regime、批次抓價解析、可當沖過濾、推播去重。
"""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402
import daytrade_brain as brain          # noqa: E402
import daytrade_live as dl              # noqa: E402
import daytrade_eligibility as elig     # noqa: E402
import realtime_quote as rq             # noqa: E402


# ── 大腦 ─────────────────────────────────────────────────────────────────────
class TestBrain(unittest.TestCase):
    def test_cdp(self):
        m = dl.cdp_map(100, 90, 95)
        self.assertEqual(m["CDP"], 95.0)
        self.assertEqual(m["AH"], 105.0)
        self.assertEqual(m["NH"], 100.0)
        self.assertEqual(m["NL"], 90.0)
        self.assertEqual(m["AL"], 85.0)

    def test_net_ev_below_gross_and_breakeven(self):
        ev = brain.net_ev(0.6, 100, 98, lots=1, avg_win_R=1.5, fee_disc=0.3)
        self.assertAlmostEqual(ev["ev_gross_R"], 0.5, places=3)
        self.assertLess(ev["ev_net_R"], ev["ev_gross_R"])          # 扣成本後變小
        self.assertGreater(ev["cost_R"], 0)
        self.assertAlmostEqual(ev["breakeven"], 100.24, places=1)  # 進場+成本/股

    def test_grade_tiers(self):
        self.assertEqual(brain.grade(0.65, 0.55, 0.5, 2.5), "S")
        self.assertEqual(brain.grade(0.57, 0.35, 0.4, 1.6), "A")
        self.assertEqual(brain.grade(0.52, 0.20, 0.4, 1.0), "B")
        self.assertEqual(brain.grade(0.40, 0.05, 0.3, 1.0), "-")

    def test_position_size_risk_primary(self):
        s = brain.position_size(0.6, 1.5, 100, 98, {"capital": 1_000_000, "risk_pct": 1.0})
        self.assertEqual(s["lots"], 2)          # kelly 1.67 < risk 5*0.5 → 用kelly≈2
        self.assertIsNotNone(s["kelly"])

    def test_position_size_no_capital(self):
        s = brain.position_size(0.6, 1.5, 100, 98, {})
        self.assertIsNone(s["lots"])

    def test_position_streak_cut(self):
        base = brain.position_size(0.6, 1.5, 100, 90, {"capital": 5_000_000, "risk_pct": 1.0})
        cut = brain.position_size(0.6, 1.5, 100, 90, {"capital": 5_000_000, "risk_pct": 1.0}, streak=3)
        self.assertLessEqual(cut["lots"], base["lots"])

    def _base_m(self, **kw):
        m = {"entry": 100, "stop": 98, "vol_ratio": 3.0, "break_atr": 1.0, "vwap_dev": 0.8,
             "rs": 2.0, "ob_ratio": 2.5, "mkt_align": 1.0, "orb_break": True, "room_R": 2.5,
             "mtf": "三多", "vol_type": "攻擊量", "confirmed": True, "inst": 0.8}
        m.update(kw)
        return m

    def test_verdict_worthy_high_quality(self):
        v = brain.verdict(self._base_m(), "long", "爆量突破多日高",
                          {"regime": "趨勢多日", "tod": "盤中", "minutes_to_close": 120},
                          cfg={"capital": 1_000_000, "risk_pct": 1, "ev_lots": 2})
        self.assertTrue(v["ok"])
        self.assertIn(v["grade"], ("S", "A"))
        self.assertGreaterEqual(v["ev_net_R"], 0.30)
        self.assertIn("值得", v["review"])

    def test_verdict_chase_penalised(self):
        v = brain.verdict(self._base_m(vwap_dev=5.0), "long", "爆量突破多日高",
                          {"regime": "趨勢多日", "tod": "盤中", "minutes_to_close": 120},
                          cfg={"ev_lots": 1})
        self.assertIn("追高乖離", v["flags"])

    def test_verdict_room_insufficient_blocked(self):
        v = brain.verdict(self._base_m(room_R=0.8), "long", "爆量突破多日高",
                          {"regime": "趨勢多日", "tod": "盤中", "minutes_to_close": 120},
                          cfg={"ev_lots": 1})
        self.assertFalse(v["ok"])
        self.assertIn("空間不足", v["flags"])

    def test_verdict_disposition_critical(self):
        v = brain.verdict(self._base_m(disposition=True), "long", "爆量突破多日高",
                          {"regime": "趨勢多日", "tod": "盤中", "minutes_to_close": 120},
                          cfg={"ev_lots": 1})
        self.assertFalse(v["ok"])
        self.assertTrue(v["critical"])

    def test_win_prob_bayes_shrink(self):
        f = brain.factors(self._base_m(), "long")
        # 無 book → 先驗
        p0, lo0, hi0, src0 = brain.win_prob(f, "s", "趨勢多日", "盤中", None)
        # 有 book 高勝率經驗 → 往經驗靠、信心變窄
        bs = {"s|趨勢多日|盤中": {"n": 40, "winrate": 0.75}}
        p1, lo1, hi1, src1 = brain.win_prob(f, "s", "趨勢多日", "盤中", bs)
        self.assertGreater(p1, p0)
        self.assertLess(hi1 - lo1, hi0 - lo0)

    def test_fit_logistic_learns(self):
        keys = list(brain.WEIGHTS.keys())
        book = []
        for i in range(60):
            hi = i % 2 == 0
            fac = {k: (0.9 if (k == "f_vol" and hi) else 0.3) for k in keys}
            book.append({"result": "win" if hi else "loss", "factors": fac})
        w = brain.fit_logistic(book)
        self.assertIsNotNone(w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=2)
        self.assertEqual(max(w, key=w.get), "f_vol")     # 學到 f_vol 最有鑑別度

    def test_fit_logistic_insufficient(self):
        self.assertIsNone(brain.fit_logistic([{"result": "win", "factors": {}}] * 10))


# ── 引擎：累積器 / 觸發 / regime ──────────────────────────────────────────────
class TestEngine(unittest.TestCase):
    def setUp(self):
        # 隔離：不寫真檔
        self._w, self._si, self._rb, self._sp = dl._write, dl._save_intraday, dl._record_book, dl._save_pushed
        dl._write = lambda *a, **k: None
        dl._save_intraday = lambda *a, **k: None
        dl._record_book = lambda *a, **k: None
        dl._save_pushed = lambda *a, **k: None
        self._mo = dl.scan._market_open_now

    def tearDown(self):
        dl._write, dl._save_intraday, dl._record_book, dl._save_pushed = self._w, self._si, self._rb, self._sp
        dl.scan._market_open_now = self._mo

    def _pool(self):
        return [{"code": "2330", "name": "台積電", "industry": "半導體", "prev_close": 980,
                 "prev_high": 985, "prev_low": 970, "recent_high20": 995, "recent_low20": 940,
                 "recent_high60": 1000, "recent_low60": 900, "atr22": 16.0, "adr_pct": 3.5,
                 "avg_vol20": 30_000_000, "day_trade_pct": 30, "turnover_60d": 5e9,
                 "consec_buy_days": 4, "attention": False, "can_daytrade": True, "pscore": 0.9}]

    def _q(self, price, vollots, h, l, bid=800, ask=300):
        return {"price": price, "volume": vollots, "open": 985, "high": h, "low": l,
                "prev_close": 980, "chg_pct": round((price / 980 - 1) * 100, 2),
                "bid": [{"price": price - 1, "vol": bid}], "ask": [{"price": price, "vol": ask}]}

    def test_accumulator_vwap_and_orb(self):
        acc = {}
        f1 = dl._update_acc(acc, self._q(990, 20000, 992, 985), datetime(2026, 7, 6, 9, 10), 3e7)
        # 09:10 仍在 ORB 窗
        self.assertFalse(f1["orb_frozen"])
        f2 = dl._update_acc(acc, self._q(1000, 40000, 1000, 986), datetime(2026, 7, 6, 9, 20), 3e7)
        self.assertTrue(f2["orb_frozen"])                     # 09:20 ORB 已凍結
        self.assertIsNotNone(f2["vwap"])
        self.assertGreater(f2["vol_ratio"], 0)                # 量能投影

    def test_regime_labels(self):
        self.assertEqual(dl._regime({"price": 100, "chg_pct": 0.9}, {"vwap_num": 99, "vwap_den": 1})["label"], "趨勢多日")
        self.assertEqual(dl._regime({"price": 100, "chg_pct": -1.2}, {"vwap_num": 101, "vwap_den": 1})["label"], "弱勢日")
        self.assertEqual(dl._regime({"price": 100, "chg_pct": 0.1}, {"vwap_num": 100, "vwap_den": 1})["label"], "震盪日")

    def test_detect_long_breakout(self):
        acc = {"per_code": {}}
        regime = {"label": "趨勢多日"}
        cands = dl.detect_signals(self._pool(), acc, regime,
                                  {"2330": self._q(1001, 45000, 1001, 986)}, datetime(2026, 7, 6, 10, 30))
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["dir"], "long")
        self.assertEqual(c["setup"], "爆量突破多日高")
        self.assertLess(c["stop"], c["entry"])                # 多方停損在進場下
        self.assertGreater(c["targets"][0], c["entry"])

    def test_detect_no_trigger_low_volume(self):
        acc = {"per_code": {}}
        cands = dl.detect_signals(self._pool(), acc, {"label": "趨勢多日"},
                                  {"2330": self._q(1001, 3000, 1001, 986)}, datetime(2026, 7, 6, 10, 30))
        self.assertEqual(len(cands), 0)                       # 量能不足不觸發

    def test_second_confirmation_on_choppy_day(self):
        # 震盪日：需二次確認(下一輪仍守)。第一輪 armed 不發、第二輪確認才發。
        acc = {"per_code": {}}
        pool = self._pool()
        c1 = dl.detect_signals(pool, acc, {"label": "震盪日"},
                               {"2330": self._q(1001, 60000, 1001, 986)}, datetime(2026, 7, 6, 10, 30))
        self.assertEqual(len(c1), 0)                          # 第一輪只 arm
        self.assertIn("armed", acc["per_code"]["2330"])
        c2 = dl.detect_signals(pool, acc, {"label": "震盪日"},
                               {"2330": self._q(1003, 90000, 1003, 986)}, datetime(2026, 7, 6, 10, 32))
        self.assertEqual(len(c2), 1)
        self.assertTrue(c2[0]["confirmed"])

    def test_scan_live_integration_and_dedup(self):
        dl.scan._market_open_now = lambda: True
        import notify
        sent = []
        _b = notify.broadcast
        notify.broadcast = lambda msg, title="", priority="default": sent.append(1) or {}
        try:
            pool = self._pool()
            idx = {"price": 18000, "chg_pct": 0.9}
            cfg = {"capital": 1_000_000, "risk_pct": 1, "ev_lots": 2}
            acc_state = {"date": "2026-07-06", "per_code": {}, "index": {"vwap_num": 0, "vwap_den": 0}}
            dl._load_intraday = lambda t: acc_state
            pushed_state = set()
            dl._load_pushed = lambda t: pushed_state
            dl._save_pushed = lambda t, k: pushed_state.update(k)
            # 建 vwap 低 → 突破 → 確認
            dl.scan_live(pool, push=True, now=datetime(2026, 7, 6, 10, 20),
                         quotes={"2330": self._q(988, 20000, 990, 985, 500, 500)}, index_quote=idx, cfg=cfg)
            dl.scan_live(pool, push=True, now=datetime(2026, 7, 6, 10, 22),
                         quotes={"2330": self._q(1006, 50000, 1006, 986, 1500, 300)}, index_quote=idx, cfg=cfg)
            o = dl.scan_live(pool, push=True, now=datetime(2026, 7, 6, 10, 24),
                             quotes={"2330": self._q(1008, 68000, 1008, 986, 1600, 250)}, index_quote=idx, cfg=cfg)
            self.assertEqual(o["regime"]["label"], "趨勢多日")
            self.assertGreaterEqual(len(o["signals"]) + len(o["filtered"]), 1)
            self.assertLessEqual(len(sent), 1)                # 去重：同 code:dir 至多推一次
        finally:
            notify.broadcast = _b


# ── 可當沖過濾 ───────────────────────────────────────────────────────────────
class TestEligibility(unittest.TestCase):
    def test_status(self):
        e = {"disposition": ["1234"], "attention": ["5678"]}
        self.assertFalse(elig.status("1234", e)["can_daytrade"])
        self.assertTrue(elig.status("5678", e)["attention"])
        self.assertTrue(elig.status("2330", e)["can_daytrade"])


# ── 批次即時報價解析 ─────────────────────────────────────────────────────────
class TestBatchQuote(unittest.TestCase):
    def test_fetch_quotes_batch(self):
        payload = {"rtcode": "0000", "msgArray": [
            {"c": "2330", "n": "台積電", "z": "1000", "y": "980", "o": "985", "h": "1002", "l": "984",
             "v": "50000", "a": "1001_1002_", "f": "300_200_", "b": "999_998_", "g": "800_600_"},
            {"c": "2317", "n": "鴻海", "z": "205", "y": "200", "o": "201", "h": "206", "l": "200",
             "v": "30000", "a": "206_", "f": "500_", "b": "205_", "g": "700_"},
        ]}

        class _Resp:
            def read(self_):
                return json.dumps(payload).encode("utf-8")

        _orig = rq.urllib.request.urlopen
        rq.urllib.request.urlopen = lambda *a, **k: _Resp()
        try:
            out = rq.fetch_quotes_batch(["2330", "2317"])
        finally:
            rq.urllib.request.urlopen = _orig
        self.assertIn("2330", out)
        self.assertIn("2317", out)
        self.assertEqual(out["2330"]["price"], 1000.0)
        self.assertTrue(out["2330"]["bid"])                   # 五檔解析
        self.assertEqual(out["2317"]["prev_close"], 200.0)


if __name__ == "__main__":
    unittest.main()
