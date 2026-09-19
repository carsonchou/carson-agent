# -*- coding: utf-8 -*-
"""test_daytrade_brain.py — 盤中淨EV大腦純函式的正確性/邊界/型別測試(不連網、合成資料)。

聚焦 daytrade_brain.py 的數學核心與方向感知邏輯:_sq/_dir_ratio/_vwap_score/_mtf_score/
_wilson/factors/_score/win_prob/_penalties/net_ev/grade/position_size/verdict/fit_logistic。
硬對照(net_ev/wilson/position_size)以手算或獨立公式 oracle 交叉驗證,不猜實作。
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402  # 掛 sys.path,讓生產模組可 import
import daytrade_brain as brain  # noqa: E402


def _wilson_ref(p, n, z=1.96):
    """獨立重算 Wilson 區間作為 oracle(與受測碼同公式,但分開實作以交叉驗證)。"""
    if n <= 0:
        return (max(0.0, p - 0.25), min(1.0, p + 0.25))
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, center - half), 3), round(min(1.0, center + half), 3))


class TestSquash(unittest.TestCase):
    """_sq:線性夾擠且 None→0.5 保底。"""

    def test_midpoint(self):
        self.assertAlmostEqual(brain._sq(2.0, 1.0, 3.0), 0.5)

    def test_clamp_low_and_high(self):
        self.assertEqual(brain._sq(0.0, 1.0, 3.0), 0.0)   # <=lo
        self.assertEqual(brain._sq(5.0, 1.0, 3.0), 1.0)   # >=hi

    def test_none_defaults_half(self):
        self.assertEqual(brain._sq(None, 1.0, 3.0), 0.5)

    def test_degenerate_range(self):
        self.assertEqual(brain._sq(2.0, 3.0, 3.0), 0.5)   # hi==lo → 0.5

    def test_negative_input_clamped(self):
        self.assertEqual(brain._sq(-100.0, 0.0, 1.0), 0.0)


class TestDirRatio(unittest.TestCase):
    """_dir_ratio:做多用原比、做空取倒數、非法值保底 1.0。"""

    def test_long_keeps_ratio(self):
        self.assertEqual(brain._dir_ratio(2.0, True), 2.0)

    def test_short_inverts(self):
        self.assertAlmostEqual(brain._dir_ratio(2.0, False), 0.5)

    def test_zero_and_none_and_negative(self):
        self.assertEqual(brain._dir_ratio(0, True), 1.0)
        self.assertEqual(brain._dir_ratio(None, True), 1.0)
        self.assertEqual(brain._dir_ratio(-1.0, True), 1.0)


class TestVwapScore(unittest.TestCase):
    """_vwap_score:倒U,峰值在 dev=1.5、逆邊與追高衰減、恆在合理下界。"""

    def test_peak_at_1p5(self):
        self.assertAlmostEqual(brain._vwap_score(1.5), 1.0)

    def test_just_above_vwap(self):
        self.assertAlmostEqual(brain._vwap_score(0.0), 0.65)

    def test_wrong_side_penalised(self):
        self.assertAlmostEqual(brain._vwap_score(-1.0), 0.2)   # 0.3+0.1*(-1)
        self.assertEqual(brain._vwap_score(-50.0), 0.1)        # 下界 0.1

    def test_slightly_high_decays_from_peak(self):
        self.assertAlmostEqual(brain._vwap_score(3.0), 0.65)   # 1.0-0.35

    def test_chase_high_floor(self):
        self.assertEqual(brain._vwap_score(100.0), 0.2)        # 追高下界 0.2

    def test_peak_is_maximum(self):
        peak = brain._vwap_score(1.5)
        for d in (-2, 0, 0.5, 1.0, 2.0, 3.0, 5.0):
            self.assertLessEqual(brain._vwap_score(d), peak + 1e-9)

    def test_all_scores_bounded_0_1(self):
        for d in (-10, -1, 0, 1.5, 2, 3, 10, 50):
            v = brain._vwap_score(d)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


class TestMtfScore(unittest.TestCase):
    """_mtf_score:三多×多/三空×空=1.0,分歧=0.3,逆向/不匹配=0.15。"""

    def test_aligned_long(self):
        self.assertEqual(brain._mtf_score("三多", True), 1.0)

    def test_aligned_short(self):
        self.assertEqual(brain._mtf_score("三空", False), 1.0)

    def test_divergence(self):
        self.assertEqual(brain._mtf_score("分歧", True), 0.3)
        self.assertEqual(brain._mtf_score("分歧", False), 0.3)

    def test_counter_direction(self):
        self.assertEqual(brain._mtf_score("三多", False), 0.15)  # 三多但做空
        self.assertEqual(brain._mtf_score("三空", True), 0.15)   # 三空但做多
        self.assertEqual(brain._mtf_score(None, True), 0.15)


class TestWilson(unittest.TestCase):
    """_wilson:n=0 邊界、對稱性、與獨立 oracle 硬對照。"""

    def test_n_zero_boundary(self):
        self.assertEqual(brain._wilson(0.5, 0), (0.25, 0.75))
        self.assertEqual(brain._wilson(0.9, 0), (0.65, 1.0))     # hi 夾到 1.0
        self.assertEqual(brain._wilson(0.1, 0), (0.0, 0.35))     # lo 夾到 0.0

    def test_symmetry_at_half(self):
        lo, hi = brain._wilson(0.5, 100)
        self.assertAlmostEqual(lo + hi, 1.0, places=3)

    def test_matches_oracle(self):
        for p, n in ((0.6, 80), (0.5, 100), (0.3, 25), (0.75, 40)):
            self.assertEqual(brain._wilson(p, n), _wilson_ref(p, n))

    def test_interval_ordered_and_bounded(self):
        lo, hi = brain._wilson(0.6, 30)
        self.assertLessEqual(0.0, lo)
        self.assertLess(lo, hi)
        self.assertLessEqual(hi, 1.0)

    def test_more_samples_tighter(self):
        lo_s, hi_s = brain._wilson(0.6, 10)
        lo_l, hi_l = brain._wilson(0.6, 500)
        self.assertLess(hi_l - lo_l, hi_s - lo_s)


class TestFactors(unittest.TestCase):
    """factors:12 因子齊全、值域 0..1、方向感知(f_vwap/f_rs 隨方向翻轉)、抽單打折。"""

    def _m(self, **kw):
        base = {"vol_ratio": 2.5, "break_atr": 0.8, "vwap_dev": 1.0, "rs": 1.5,
                "ob_ratio": 2.0, "mkt_align": 0.7, "orb_break": True, "room_R": 2.0,
                "mtf": "三多", "vol_type": "攻擊量", "confirmed": True, "inst": 0.6}
        base.update(kw)
        return base

    def test_all_12_keys_present(self):
        f = brain.factors(self._m(), "long")
        self.assertEqual(set(f.keys()), set(brain.WEIGHTS.keys()))

    def test_values_in_unit_interval(self):
        f = brain.factors(self._m(), "long")
        for k, v in f.items():
            self.assertGreaterEqual(v, 0.0, k)
            self.assertLessEqual(v, 1.0, k)

    def test_direction_flips_vwap_and_rs(self):
        m = self._m(vwap_dev=1.0, rs=2.0)  # 站對多方、領漲
        fl = brain.factors(m, "long")
        fs = brain.factors(m, "short")
        # 做多站對邊分數高;同盤面做空則 vwap/rs 應較低
        self.assertGreater(fl["f_vwap"], fs["f_vwap"])
        self.assertGreater(fl["f_rs"], fs["f_rs"])

    def test_pull_order_discounts_ob(self):
        f_no = brain.factors(self._m(pull_order=False), "long")
        f_pull = brain.factors(self._m(pull_order=True), "long")
        self.assertAlmostEqual(f_pull["f_ob"], f_no["f_ob"] * 0.7)

    def test_voltype_mapping(self):
        self.assertEqual(brain.factors(self._m(vol_type="攻擊量"), "long")["f_voltype"], 1.0)
        self.assertEqual(brain.factors(self._m(vol_type="出貨量"), "long")["f_voltype"], 0.0)
        self.assertEqual(brain.factors(self._m(vol_type="中性"), "long")["f_voltype"], 0.5)

    def test_missing_fields_do_not_crash(self):
        f = brain.factors({}, "long")   # 全缺 → 走各自保底
        self.assertEqual(set(f.keys()), set(brain.WEIGHTS.keys()))


class TestScore(unittest.TestCase):
    """_score:加權平均,忽略 None,分母 0 → 0.5。"""

    def test_weighted_average(self):
        self.assertAlmostEqual(brain._score({"a": 1.0, "b": 0.0}, {"a": 0.5, "b": 0.5}), 0.5)

    def test_single_factor(self):
        self.assertAlmostEqual(brain._score({"a": 1.0}, {"a": 0.5}), 1.0)

    def test_empty_defaults_half(self):
        self.assertEqual(brain._score({}, {}), 0.5)

    def test_ignores_none_values(self):
        v = brain._score({"a": 1.0, "b": None}, {"a": 0.5, "b": 0.5})
        self.assertAlmostEqual(v, 1.0)   # b 被忽略

    def test_real_factors_bounded(self):
        f = brain.factors({"vol_ratio": 3, "mtf": "三多", "confirmed": True}, "long")
        s = brain._score(f, brain.WEIGHTS)
        self.assertTrue(0.0 <= s <= 1.0)


class TestWinProb(unittest.TestCase):
    """win_prob:回傳結構、勝率夾在 [0.15,0.90]、來源標記、貝式收縮方向。"""

    def _f(self):
        return brain.factors({"vol_ratio": 3, "mtf": "三多", "confirmed": True,
                              "rs": 2.0, "vwap_dev": 1.0}, "long")

    def test_returns_tuple_shape(self):
        p, lo, hi, src = brain.win_prob(self._f(), "爆量突破", "中性", "盤中")
        self.assertIsInstance(p, float)
        self.assertLessEqual(lo, hi)
        self.assertEqual(src, "heuristic")

    def test_prob_clamped(self):
        p, *_ = brain.win_prob(self._f(), "s", "中性", "盤中")
        self.assertGreaterEqual(p, 0.15)
        self.assertLessEqual(p, 0.90)

    def test_source_logistic_when_weights(self):
        _, _, _, src = brain.win_prob(self._f(), "s", "中性", "盤中",
                                      weights=brain.WEIGHTS)
        self.assertEqual(src, "logistic")

    def test_bayes_shrink_toward_empirical(self):
        f = self._f()
        p_prior, *_ = brain.win_prob(f, "s", "中性", "盤中")
        # 大量高勝率經驗樣本 → 後驗應被拉高
        book = {"s|中性|盤中": {"n": 200, "winrate": 0.85}}
        p_post, lo, hi, _ = brain.win_prob(f, "s", "中性", "盤中", book_stats=book)
        self.assertGreater(p_post, p_prior)


class TestPenalties(unittest.TestCase):
    """_penalties:各風險旗標乘罰、關鍵風險 critical、乾淨盤面無罰。"""

    def test_clean_no_penalty(self):
        mult, flags, critical = brain._penalties({"mkt_align": 0.6}, {}, 2.0)
        self.assertEqual(mult, 1.0)
        self.assertEqual(flags, [])
        self.assertFalse(critical)

    def test_disposition_is_critical(self):
        _, flags, critical = brain._penalties({"disposition": True}, {}, 2.0)
        self.assertTrue(critical)
        self.assertIn("處置分盤不可現沖", flags)

    def test_exec_not_ok_critical(self):
        _, _, critical = brain._penalties({"exec_ok": False}, {}, 2.0)
        self.assertTrue(critical)

    def test_chase_deviation_multiplier(self):
        mult, flags, _ = brain._penalties({"vwap_dev": 5.0, "mkt_align": 0.6}, {}, 2.0)
        self.assertIn("追高乖離", flags)
        self.assertAlmostEqual(mult, 0.85)

    def test_room_insufficient_flag(self):
        _, flags, _ = brain._penalties({"mkt_align": 0.6}, {}, 1.0)
        self.assertIn("空間不足", flags)

    def test_close_to_market_close(self):
        _, flags, _ = brain._penalties({"mkt_align": 0.6}, {"minutes_to_close": 20}, 2.0)
        self.assertIn("接近收盤", flags)

    def test_multiplier_never_exceeds_one(self):
        mult, _, _ = brain._penalties(
            {"vwap_dev": 5, "divergence": True, "attention": True, "pull_order": True,
             "reentry": True, "mkt_align": 0.2}, {"minutes_to_close": 10}, 1.0)
        self.assertLessEqual(mult, 1.0)
        self.assertGreater(mult, 0.0)


class TestNetEv(unittest.TestCase):
    """net_ev:期望值/成本算術硬對照(手算)。"""

    def test_hand_computed_clean_case(self):
        # p=0.5, entry=10, stop=9, lots=1, avg_win_R=2.0, fee_disc=0.3
        # risk_pts=1, shares=1000, amt=10000
        # fee=max(20, 10000*0.001425*0.3=4.275)=20 → 進出各20
        # tax=10000*0.0015=15 → total_cost=55, cost_R=55/1000=0.055
        # ev_gross_R=0.5*2-0.5*1=0.5 ; ev_net_R=0.5-0.055=0.445
        # ev_net_twd=round(0.445*1*1000)=445
        ev = brain.net_ev(0.5, 10.0, 9.0, 1, avg_win_R=2.0, fee_disc=0.3)
        self.assertEqual(ev["total_cost"], 55)
        self.assertEqual(ev["cost_R"], 0.055)
        self.assertEqual(ev["ev_gross_R"], 0.5)
        self.assertEqual(ev["ev_net_R"], 0.445)
        self.assertEqual(ev["ev_net_twd"], 445)

    def test_net_below_gross(self):
        ev = brain.net_ev(0.6, 100.0, 99.0, 1)
        self.assertLess(ev["ev_net_R"], ev["ev_gross_R"])   # 成本恆為正

    def test_etf_lower_tax(self):
        common = dict(entry=50.0, stop=49.0, lots=1)
        ev_stock = brain.net_ev(0.6, is_etf=False, **common)
        ev_etf = brain.net_ev(0.6, is_etf=True, **common)
        self.assertLess(ev_etf["cost_R"], ev_stock["cost_R"])  # ETF 稅率較低

    def test_zero_risk_distance_fallback(self):
        # entry==stop → risk_pts 退回 entry*0.01,不應除零崩潰
        ev = brain.net_ev(0.6, 100.0, 100.0, 1)
        self.assertIsInstance(ev["cost_R"], float)

    def test_fee_floor_applies_on_small_amount(self):
        # amt 很小 → 手續費踩地板 FEE_MIN(20),進出共 40 + 稅
        ev = brain.net_ev(0.5, 5.0, 4.0, 1, fee_disc=0.3)
        # tax = 5000*0.0015 = 7.5 → total = 20+20+7.5 = 47.5 → round 48
        self.assertEqual(ev["total_cost"], 48)


class TestGrade(unittest.TestCase):
    """grade:S/A/B/- 分級門檻邊界值落點。"""

    def test_s_grade_at_boundary(self):
        self.assertEqual(brain.grade(0.62, 0.5, 0.45, 2.0), "S")

    def test_just_below_s_falls_to_a(self):
        self.assertEqual(brain.grade(0.61, 0.5, 0.45, 2.0), "A")  # p<0.62 掉A

    def test_a_grade_boundary(self):
        self.assertEqual(brain.grade(0.55, 0.30, 0.4, 1.5), "A")

    def test_b_grade_boundary(self):
        self.assertEqual(brain.grade(0.50, 0.15, 0.0, 0.0), "B")

    def test_reject_below_b(self):
        self.assertEqual(brain.grade(0.49, 0.15, 0.0, 0.0), "-")   # p<0.50
        self.assertEqual(brain.grade(0.50, 0.14, 0.0, 0.0), "-")   # ev<0.15

    def test_none_room_treated_as_zero(self):
        # room=None → S/A 需要 room 的條件不成立,但 B 不看 room
        self.assertEqual(brain.grade(0.50, 0.15, 0.0, None), "B")


class TestPositionSize(unittest.TestCase):
    """position_size:固定風險%為主軸、Kelly 只在更保守時壓低、連敗降碼、無本金回 None。"""

    def test_risk_based_lots_hand_computed(self):
        # cap=500k, risk_pct=1% → risk_amt=5000; entry=10,stop=9 → risk_pts=1
        # lots_risk = 5000/(1*1000) = 5
        # kelly notional 大(entry小)→ 不壓低 → lots=5
        r = brain.position_size(0.55, 2.0, 10.0, 9.0,
                                {"capital": 500000, "risk_pct": 1.0})
        self.assertEqual(r["lots"], 5)

    def test_no_capital_returns_none(self):
        r = brain.position_size(0.6, 1.5, 100.0, 99.0, None)
        self.assertIsNone(r["lots"])
        self.assertIn("本金", r["note"])

    def test_streak_cut_halves(self):
        r = brain.position_size(0.55, 2.0, 10.0, 9.0,
                                {"capital": 500000, "risk_pct": 1.0}, streak=3)
        self.assertEqual(r["lots"], 2)   # round(5*0.5)=round(2.5)=2

    def test_kelly_clamped_non_negative(self):
        r = brain.position_size(0.30, 1.0, 100.0, 99.0, {"capital": 500000})
        self.assertEqual(r["kelly"], 0.0)   # 負 Kelly 夾到 0

    def test_kelly_capped(self):
        r = brain.position_size(0.90, 3.0, 100.0, 99.0, {"capital": 500000})
        self.assertLessEqual(r["kelly"], 0.25)

    def test_max_lots_cap(self):
        r = brain.position_size(0.55, 2.0, 10.0, 9.0,
                                {"capital": 500000, "risk_pct": 1.0, "max_lots": 3})
        self.assertLessEqual(r["lots"], 3)


class TestVerdict(unittest.TestCase):
    """verdict:整合輸出的關鍵欄位存在性與型別,並驗處置股 critical 擋單。"""

    def _m(self, **kw):
        base = {"entry": 100.0, "stop": 98.0, "room_R": 2.5, "vol_ratio": 3.0,
                "break_atr": 1.0, "vwap_dev": 1.0, "rs": 2.0, "ob_ratio": 2.5,
                "mkt_align": 0.8, "orb_break": True, "mtf": "三多",
                "vol_type": "攻擊量", "confirmed": True, "inst": 0.7}
        base.update(kw)
        return base

    def test_output_keys_and_types(self):
        v = brain.verdict(self._m(), "long", "爆量突破",
                          {"regime": "多頭", "tod": "盤中"})
        for k in ("ok", "grade", "p", "conf", "source", "ev_R", "ev_net_R",
                  "cost_R", "ev_net_twd", "breakeven", "room_R", "size",
                  "flags", "critical", "contrib", "factors", "review"):
            self.assertIn(k, v)
        self.assertIsInstance(v["ok"], bool)
        self.assertIsInstance(v["p"], float)
        self.assertIsInstance(v["conf"], list)
        self.assertEqual(len(v["conf"]), 2)
        self.assertIsInstance(v["flags"], list)
        self.assertIsInstance(v["review"], str)

    def test_disposition_blocks(self):
        v = brain.verdict(self._m(disposition=True), "long", "s",
                          {"regime": "多頭", "tod": "盤中"})
        self.assertTrue(v["critical"])
        self.assertFalse(v["ok"])

    def test_high_quality_setup_worthy(self):
        v = brain.verdict(self._m(), "long", "爆量突破",
                          {"regime": "多頭", "tod": "盤中"},
                          book_stats={"爆量突破": {"n": 120, "winrate": 0.72}})
        self.assertTrue(v["ok"])
        self.assertIn(v["grade"], ("S", "A"))

    def test_prob_within_bounds(self):
        v = brain.verdict(self._m(), "long", "s", {"regime": "中性", "tod": "盤中"})
        self.assertGreaterEqual(v["p"], 0.15)
        self.assertLessEqual(v["p"], 0.90)


class TestFitLogistic(unittest.TestCase):
    """fit_logistic:樣本不足回 None、足量學到方向並正規化。"""

    def test_insufficient_returns_none(self):
        book = [{"result": "win", "factors": {"f_vol": 0.9}} for _ in range(10)]
        self.assertIsNone(brain.fit_logistic(book))

    def test_ignores_unfinalized_rows(self):
        # 49 筆有效 + 一堆 pending → 有效 < 50 → None
        book = [{"result": "win" if i % 2 else "loss",
                 "factors": {"f_vol": 0.9 if i % 2 else 0.1}} for i in range(49)]
        book += [{"result": "pending", "factors": {"f_vol": 0.5}} for _ in range(20)]
        self.assertIsNone(brain.fit_logistic(book))

    def test_learns_direction_and_normalises(self):
        # 只有 f_vol 帶訊號(高→win、低→loss),其餘因子恆 0.5(無資訊)
        book = []
        for i in range(80):
            win = i % 2 == 0
            fac = {k: 0.5 for k in brain.WEIGHTS}
            fac["f_vol"] = 0.9 if win else 0.1
            book.append({"result": "win" if win else "loss", "factors": fac})
        w = brain.fit_logistic(book, iters=400, lr=0.5)
        self.assertIsNotNone(w)
        self.assertEqual(set(w.keys()), set(brain.WEIGHTS.keys()))
        for v in w.values():
            self.assertGreaterEqual(v, 0.0)               # 非負
        self.assertAlmostEqual(sum(w.values()), 1.0, places=2)  # 正規化合計 1
        # 唯一訊號因子應拿到最大權重
        self.assertEqual(max(w, key=w.get), "f_vol")


if __name__ == "__main__":
    unittest.main()
