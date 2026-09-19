# -*- coding: utf-8 -*-
"""
test_gauge_history.py — 市場溫度逐日歷史(scan.append_gauge_history)。

這是**純附加的觀測記錄**,掛在產線掃描器收尾。最重要的一條不是「有沒有寫對」,
而是「**寫壞了會不會拖垮掃描**」—— S1/S2/S3/S6 全靠那支掃描器,漏記一天可以,掛掉不行。
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import scan  # noqa: E402


def _state(day="2026-07-17", temp=45.4, mode="daily", confirmed=True, ok=True, trend="UP"):
    return {
        "ok": ok, "ts": f"{day}T17:04:55", "date": day, "source": "cache",
        "mode": mode, "confirmed": confirmed, "universe": 1925,
        "index": {"name": "0050", "price": 106.4, "chg": 0.09, "trend": trend,
                  "above_yearline": True},
        "gauge": {"temperature": temp, "label": "中性", "avg_rsi": 48.8, "breadth": 40.9,
                  "adv": 1060, "dec": 588, "flat": 277, "adr": 1.8, "nh": 95, "nl": 88,
                  "nhnl": 7, "vol_med": 0.58,
                  "components": {"rsi": 48.8, "breadth": 40.9, "adr": 64.3,
                                 "nhnl": 50.7, "vol": 8.0}},
    }


def _rows(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestAppendGaugeHistory(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "gauge_history.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── 基本:寫得出來、欄位齊全、格式可被未來的分析程式讀 ──────────────────
    def test_writes_record_with_all_reconstruction_fields(self):
        self.assertTrue(scan.append_gauge_history(_state(), self.p))
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # 溫度公式的 5 個成分都要在 —— 少一個,未來就重建不出同一個溫度
        for k in ("rsi", "breadth", "adr", "nhnl", "vol"):
            self.assertIn(k, r["components"])
        # 未來對照需要的原始量 + 大盤
        for k in ("date", "ts", "source", "mode", "confirmed", "universe", "temperature",
                  "avg_rsi", "breadth", "adv", "dec", "flat", "adr", "nh", "nl", "nhnl",
                  "vol_med", "index_price", "index_chg", "index_trend", "index_above_yearline"):
            self.assertIn(k, r, f"缺欄位 {k}")
        self.assertEqual(r["date"], "2026-07-17")
        self.assertEqual(r["temperature"], 45.4)

    def test_components_can_rebuild_the_temperature(self):
        """存下來的成分必須真的能還原溫度(否則存了也沒用)。
        公式:.30rsi + .25breadth + .15adr + .20nhnl + .10vol(見 scan.py 溫度區)。"""
        scan.append_gauge_history(_state(), self.p)
        c = _rows(self.p)[0]["components"]
        temp = (0.30 * c["rsi"] + 0.25 * c["breadth"] + 0.15 * c["adr"]
                + 0.20 * c["nhnl"] + 0.10 * c["vol"])
        self.assertAlmostEqual(round(temp, 1), 45.4, places=1)

    def test_is_valid_jsonl_one_object_per_line(self):
        scan.append_gauge_history(_state("2026-07-15"), self.p)
        scan.append_gauge_history(_state("2026-07-16"), self.p)
        text = self.p.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"), "最後一行要有換行(否則下次追加會黏行)")
        for line in text.splitlines():
            self.assertIsInstance(json.loads(line), dict)

    # ── 冪等:app 一天會反覆跑 ────────────────────────────────────────────
    def test_same_day_twice_keeps_one_record(self):
        scan.append_gauge_history(_state("2026-07-17", temp=44.0), self.p)
        scan.append_gauge_history(_state("2026-07-17", temp=45.4), self.p)
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1, "同日重跑不可以寫兩筆")
        self.assertEqual(rows[0]["temperature"], 45.4, "同日應保留最後一次(收盤後的確認值)")

    def test_intraday_then_confirmed_keeps_confirmed(self):
        """正方向:盤中先跑、收盤後再跑 → 留下 confirmed 的那筆(乾淨序列的來源)。"""
        scan.append_gauge_history(_state("2026-07-17", temp=44.0, mode="intraday",
                                         confirmed=False), self.p)
        scan.append_gauge_history(_state("2026-07-17", temp=45.4, mode="daily",
                                         confirmed=True), self.p)
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["confirmed"])
        self.assertEqual(rows[0]["mode"], "daily")

    def test_confirmed_then_intraday_keeps_confirmed(self):
        """🔴 反方向(真實世界會走的那條,第一版沒測到、實測會壞):
        cron 14:00 寫確認值 → 看板 app.py:59 無條件 run_once(realtime=True) 每 30 分寫盤中值
        → 若「後寫的贏」,確認值就被蓋掉,而且**看起來完全正常**,半年後才會發現全是 false。
        規則必須是 confirmed 優先。"""
        scan.append_gauge_history(_state("2026-07-17", temp=45.4, mode="daily",
                                         confirmed=True), self.p)
        for _ in range(3):        # 看板盤後連跑 3 輪
            scan.append_gauge_history(_state("2026-07-17", temp=44.0, mode="intraday",
                                             confirmed=False), self.p)
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["confirmed"], "確認值被盤中暫定值蓋掉了 → 這個檔會白存半年")
        self.assertEqual(rows[0]["mode"], "daily")
        self.assertEqual(rows[0]["temperature"], 45.4)

    def test_confirmed_write_returns_false_when_blocked(self):
        """被擋下時要回 False(呼叫端可判斷),且不可拋。"""
        scan.append_gauge_history(_state("2026-07-17", confirmed=True), self.p)
        self.assertFalse(scan.append_gauge_history(
            _state("2026-07-17", temp=44.0, mode="intraday", confirmed=False), self.p))

    def test_both_confirmed_last_write_wins(self):
        """同為 confirmed → 後寫的贏(例如收盤後 cron 重跑修正)。"""
        scan.append_gauge_history(_state("2026-07-17", temp=45.4, confirmed=True), self.p)
        scan.append_gauge_history(_state("2026-07-17", temp=46.9, confirmed=True), self.p)
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature"], 46.9)

    def test_both_unconfirmed_last_write_wins(self):
        """同為盤中暫定 → 後寫的贏(當天還沒有確認值,最新的暫定值比較有用)。"""
        scan.append_gauge_history(_state("2026-07-17", temp=44.0, confirmed=False), self.p)
        scan.append_gauge_history(_state("2026-07-17", temp=44.8, confirmed=False), self.p)
        rows = _rows(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature"], 44.8)

    def test_confirmed_priority_does_not_leak_across_days(self):
        """昨天的確認值不可以擋住今天的盤中值(規則只在同一天內生效)。"""
        scan.append_gauge_history(_state("2026-07-16", confirmed=True), self.p)
        self.assertTrue(scan.append_gauge_history(
            _state("2026-07-17", temp=44.0, mode="intraday", confirmed=False), self.p))
        self.assertEqual(len(_rows(self.p)), 2)

    # ── mkt_long_ok:溫度的 ×0.90 開關,不可讓未來的人自己推 ──────────────
    def test_mkt_long_ok_stored_and_matches_compute_index_contract(self):
        """compute_index:trend=="UP" → True;"DOWN" → False;
        **資料不足時回 (trend=None, long_ok=True)** —— 照 trend=="UP" 推會得到 False(錯)。"""
        for trend, want in (("UP", True), ("DOWN", False), (None, True)):
            p = self.tmp / f"g_{trend}.jsonl"
            scan.append_gauge_history(_state(trend=trend), p)
            self.assertEqual(_rows(p)[0]["mkt_long_ok"], want,
                             f"trend={trend} 的 mkt_long_ok 應為 {want}")

    def test_mkt_long_ok_agrees_with_temperature_ratio(self):
        """交叉驗算:mkt_long_ok=True 時 temperature 應等於未打折的加權和。"""
        scan.append_gauge_history(_state(trend="UP"), self.p)
        r = _rows(self.p)[0]
        c = r["components"]
        weighted = (0.30 * c["rsi"] + 0.25 * c["breadth"] + 0.15 * c["adr"]
                    + 0.20 * c["nhnl"] + 0.10 * c["vol"])
        self.assertTrue(r["mkt_long_ok"])
        self.assertAlmostEqual(round(weighted, 1), r["temperature"], places=1)

    # ── .bak:整檔重寫的保險 ─────────────────────────────────────────────
    def test_bak_holds_previous_version(self):
        scan.append_gauge_history(_state("2026-07-15"), self.p)
        scan.append_gauge_history(_state("2026-07-16"), self.p)
        bak = self.p.with_suffix(self.p.suffix + ".bak")
        self.assertTrue(bak.exists(), "重寫前沒留備份")
        self.assertEqual([r["date"] for r in _rows(bak)], ["2026-07-15"],
                         ".bak 應是「這次寫入之前」的版本")
        self.assertEqual([r["date"] for r in _rows(self.p)], ["2026-07-15", "2026-07-16"])

    def test_bak_failure_does_not_block_main_write(self):
        """備份只是保險,備份失敗不可以擋住主寫入。"""
        scan.append_gauge_history(_state("2026-07-15"), self.p)
        import shutil as _sh
        orig = _sh.copy2
        try:
            _sh.copy2 = lambda *a, **k: (_ for _ in ()).throw(OSError("bak fail"))
            self.assertTrue(scan.append_gauge_history(_state("2026-07-16"), self.p))
        finally:
            _sh.copy2 = orig
        self.assertEqual(len(_rows(self.p)), 2)

    def test_multiple_days_accumulate_sorted(self):
        for d in ("2026-07-17", "2026-07-15", "2026-07-16"):
            scan.append_gauge_history(_state(d), self.p)
        rows = _rows(self.p)
        self.assertEqual([r["date"] for r in rows],
                         ["2026-07-15", "2026-07-16", "2026-07-17"])

    # ── 不記垃圾 ─────────────────────────────────────────────────────────
    def test_skips_failed_scan(self):
        self.assertFalse(scan.append_gauge_history(_state(ok=False), self.p))
        self.assertFalse(self.p.exists())

    def test_skips_when_gauge_missing(self):
        st = _state()
        st["gauge"] = {}
        self.assertFalse(scan.append_gauge_history(st, self.p))

    def test_skips_when_date_malformed(self):
        self.assertFalse(scan.append_gauge_history(_state(day="nope"), self.p))

    def test_corrupt_line_is_dropped_not_fatal(self):
        self.p.write_text('{"date":"2026-07-15","temperature":40}\n'
                          "{壞掉的行不是 json\n", encoding="utf-8")
        self.assertTrue(scan.append_gauge_history(_state("2026-07-17"), self.p))
        rows = _rows(self.p)
        self.assertEqual([r["date"] for r in rows], ["2026-07-15", "2026-07-17"])

    # ── 🔴 最重要:寫檔爆炸絕不可以拖垮掃描 ────────────────────────────────
    def test_write_failure_never_raises(self):
        """故障注入:原子寫檔拋例外 → 必須吞掉回 False,**不可以往上拋**。
        (掃描主流程在這行之後還要印摘要/推播;這裡拋出去 = 掃描器掛掉 = 旗艦主體斷炊)"""
        orig = scan._atomic_write_text
        try:
            def boom(path, text):
                raise OSError("disk full / 目錄唯讀")
            scan._atomic_write_text = boom
            self.assertFalse(scan.append_gauge_history(_state(), self.p))
        finally:
            scan._atomic_write_text = orig

    def test_unreadable_existing_file_never_raises(self):
        orig = Path.read_text
        try:
            def boom(self, *a, **k):
                raise OSError("read error")
            Path.read_text = boom
            self.p.write_text("x", encoding="utf-8")
            self.assertFalse(scan.append_gauge_history(_state(), self.p))
        finally:
            Path.read_text = orig

    def test_garbage_state_never_raises(self):
        """任何形狀的爛輸入都不可以拋(掃描器只管掃描,不該被觀測記錄搞死)。"""
        for bad in (None, {}, {"ok": True}, {"ok": True, "gauge": None},
                    {"ok": True, "gauge": {"temperature": 1}, "date": None}):
            try:
                scan.append_gauge_history(bad, self.p)
            except Exception as e:  # noqa: BLE001
                self.fail(f"爛輸入 {bad!r} 讓函式拋了 {type(e).__name__}: {e}")


class TestCallSiteIsSafe(unittest.TestCase):
    def test_called_after_state_written_and_ok_check(self):
        """呼叫點必須在 state.json 落地 + ok 檢查之後 —— 這是「爆掉也不影響主產物」的結構保證。"""
        src = Path(scan.__file__).read_text(encoding="utf-8")
        i_write = src.index("_atomic_write_json(STATE_FILE, state)")
        i_ok = src.index('if not state.get("ok"):', i_write)
        i_call = src.index("append_gauge_history(state)", i_ok)
        self.assertLess(i_write, i_call, "gauge 記錄不可以在 state.json 寫入之前")
        self.assertLess(i_ok, i_call, "gauge 記錄不可以在 ok 檢查之前(失敗的掃描不該被記)")

    def test_function_body_has_exception_guard(self):
        """防線本身要在:整段包 try/except。拿掉 → 故障注入測試會轉紅。"""
        import inspect
        src = inspect.getsource(scan.append_gauge_history)
        self.assertIn("try:", src)
        self.assertIn("except Exception", src)


if __name__ == "__main__":
    unittest.main()
