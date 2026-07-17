# -*- coding: utf-8 -*-
"""
test_daytrade_elig_failclosed.py — 當沖適格清單的 fail-CLOSED 契約(2026-07-17)。

背景:舊版是 **fail-OPEN** —— TWSE 掛掉時 `_fetch_json` 吞成 `[]`,`refresh()` 照樣寫出
`{"disposition": []}`,與「今天真的 0 檔處置股」在檔案層面完全無法區分 → M1 免費磁鐵
(賣點=報單前防呆)會印「處置股 0 檔」= 告訴當沖客這檔可以沖。安全清單上的 fail-open。

關鍵事實(2026-07-17 唯讀 curl 實測,由 team-lead 提供):
  TWSE 沒資料 → [{"Number":"0","Code":"","Name":"",...}]   ← **哨兵列**(非空 list)
  TWSE 掛掉   → []                                          ← 空 list
所以在 fetch 層分得出來:非空 list = 抓到了;None/空 list = 抓不到。

本檔一律用注入模擬三種情境,**不打外部網路**。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402,F401
import daytrade_eligibility as elig  # noqa: E402

SENTINEL = [{"Number": "0", "Code": "", "Name": "", "NumberOfAnnouncement": "0"}]
REAL_PUNISH = [{"Number": "1", "Code": "052974", "Name": "今國光統一5C購02"},
               {"Number": "2", "Code": "1234", "Name": "測試股"}]
REAL_NOTICE = [{"Number": "1", "Code": "9999", "Name": "注意股測試"}]


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "elig.json"
        self._orig_path = elig._cache_path
        self._orig_fetch = elig._fetch_json
        self._orig_dir = elig.CACHE_DIR
        elig._cache_path = lambda d=None: self.p
        elig.CACHE_DIR = self.tmp
        elig._CACHE = None

    def tearDown(self):
        elig._cache_path = self._orig_path
        elig._fetch_json = self._orig_fetch
        elig.CACHE_DIR = self._orig_dir
        elig._CACHE = None
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fetch(self, punish, notice):
        def f(url, timeout=12):
            return punish if "punish" in url else notice
        elig._fetch_json = f


class TestThreeScenarios(_Base):
    # ── 情境①:真資料 → 正常寫檔、可信 ──────────────────────────────────
    def test_real_data_writes_and_is_trusted(self):
        self._fetch(REAL_PUNISH, REAL_NOTICE)
        r = elig.refresh()
        self.assertTrue(r["ok"])
        self.assertEqual(r["disposition"], ["052974", "1234"])
        self.assertEqual(r["attention"], ["9999"])
        self.assertTrue(self.p.exists(), "抓到資料卻沒寫檔")
        self.assertTrue(elig.is_trusted(json.loads(self.p.read_text(encoding="utf-8"))))

    # ── 情境②:哨兵列(TWSE 活著、今天真的沒資料)→ 寫「0 檔」且**可信** ──
    def test_sentinel_row_means_genuinely_zero_and_is_trusted(self):
        self._fetch(SENTINEL, SENTINEL)
        r = elig.refresh()
        self.assertTrue(r["ok"], "哨兵列代表 TWSE 有回應、今天真的沒資料 → 必須是可信的 0 檔")
        self.assertEqual(r["disposition"], [], "哨兵列的空 Code 不可以變成幽靈代號")
        self.assertEqual(r["attention"], [])
        self.assertTrue(self.p.exists())
        self.assertTrue(elig.is_trusted(elig.load()))
        self.assertEqual(elig.load()["disposition"], [])

    # ── 情境③:空陣列(TWSE 掛掉)→ **不寫檔**、不可信 ────────────────────
    def test_empty_array_means_fetch_failed_and_does_not_write(self):
        self._fetch([], [])
        r = elig.refresh()
        self.assertFalse(r["ok"])
        self.assertIn("抓取失敗", r["reason"])
        self.assertFalse(self.p.exists(), "抓不到卻寫了檔 → 會被誤讀成「今天 0 檔」")
        self.assertFalse(elig.is_trusted(elig.load()))

    def test_fetch_exception_means_untrusted(self):
        """_fetch_json 回 None(網路炸掉)→ 同樣不可信、不寫檔。"""
        elig._fetch_json = lambda url, timeout=12: None
        r = elig.refresh()
        self.assertFalse(r["ok"])
        self.assertFalse(self.p.exists())

    def test_partial_failure_is_untrusted(self):
        """一個端點掛掉 → 無法完整回答「這檔能不能沖」→ 整份不可信,不給半套當全套。"""
        self._fetch(REAL_PUNISH, [])
        r = elig.refresh()
        self.assertFalse(r["ok"])
        self.assertFalse(self.p.exists())

    # ── 🔴 最重要:失敗不可以蓋掉今天稍早抓成功的好資料 ──────────────────
    def test_failure_never_destroys_earlier_good_data(self):
        self._fetch(REAL_PUNISH, REAL_NOTICE)
        elig.refresh()                                   # 09:00 抓成功
        good = json.loads(self.p.read_text(encoding="utf-8"))
        self._fetch([], [])
        elig.refresh()                                   # 14:00 TWSE 掛掉
        still = json.loads(self.p.read_text(encoding="utf-8"))
        self.assertEqual(still, good, "失敗的抓取把稍早的好資料蓋掉了")
        self.assertTrue(elig.is_trusted(elig.load()))


class TestLoadFailClosed(_Base):
    def test_missing_file_is_untrusted_not_empty_allow_all(self):
        d = elig.load()
        self.assertFalse(d["ok"], "沒有檔案卻回可信 → 一切放行(fail-open)")
        self.assertIn("reason", d)
        self.assertEqual(d["disposition"], [])          # 鍵仍在,既有呼叫端不會 KeyError

    def test_legacy_file_without_ok_but_with_data_is_trusted(self):
        """舊格式(無 ok 欄位)但有 21 檔處置股 → 顯然抓成功過 → 可信。"""
        self.p.write_text(json.dumps({"updated": "2026-07-13T09:05:36",
                                      "disposition": ["1101", "2330"], "attention": []}),
                          encoding="utf-8")
        self.assertTrue(elig.load()["ok"])

    def test_legacy_empty_file_is_untrusted(self):
        """舊格式且全空 → 無法分辨「真的 0 檔」與「抓取失敗寫空」→ fail-closed 當不可信。"""
        self.p.write_text(json.dumps({"updated": "2026-07-13T09:05:36",
                                      "disposition": [], "attention": []}), encoding="utf-8")
        self.assertFalse(elig.load()["ok"])

    def test_corrupt_file_is_untrusted_not_fatal(self):
        self.p.write_text("{壞掉的 json", encoding="utf-8")
        d = elig.load()
        self.assertFalse(d["ok"])


class TestStatusHonestAndFailClosed(_Base):
    def test_status_trusted_when_data_good(self):
        e = {"ok": True, "disposition": ["2330"], "attention": ["1101"]}
        s = elig.status("2330", e)
        self.assertTrue(s["trusted"])
        self.assertTrue(s["disposition"])
        self.assertFalse(s["can_daytrade"])
        s2 = elig.status("6414", e)
        self.assertTrue(s2["can_daytrade"])
        self.assertTrue(s2["trusted"])

    def test_status_untrusted_does_not_claim_disposition(self):
        """🔴 誠實:資料不可信時**不可以**反過來宣稱它是處置股(那會讓 1900 檔全被標「處置分盤」
        = 假話)。要 fail-closed 的責任在 trusted,不是拿 disposition 假裝知道。"""
        e = {"ok": False, "reason": "抓取失敗", "disposition": [], "attention": []}
        s = elig.status("2330", e)
        self.assertFalse(s["trusted"], "不可信卻回 trusted=True → 下游會照常放行")
        self.assertFalse(s["disposition"], "不知道就不可以宣稱它是處置股")
        self.assertFalse(s["attention"])


class TestBrainBlocksOnUnverified(unittest.TestCase):
    """守門鏈的最後一段:daytrade_brain._penalties 的 critical=True → 該訊號不放行。"""

    def test_unverified_eligibility_is_critical_with_honest_label(self):
        """清單抓不到 → 擋單(critical),且措辭必須是「無法確認」而不是謊稱「處置分盤」。"""
        import daytrade_brain as brain
        mult, flags, critical = brain._penalties({"elig_unverified": True}, {}, None)
        self.assertTrue(critical, "適格清單抓不到卻沒擋單 → fail-open(等於告訴人家可以沖)")
        joined = "".join(flags)
        self.assertIn("無法確認", joined)
        self.assertNotIn("處置分盤不可現沖", joined, "不知道就不可以說它是處置股(那是假話)")

    def test_trusted_eligibility_does_not_block(self):
        """清單可信時不可以誤擋 —— fail-closed 不能變成「永遠都擋」。"""
        _m, flags, critical = brain_penalties({"elig_unverified": False})
        self.assertFalse(critical)
        self.assertFalse(any("無法確認" in f for f in flags))

    def test_real_disposition_still_blocks_with_its_own_label(self):
        """既有行為不可退化:真的是處置股 → 仍然擋、仍然用原本的措辭。"""
        _m, flags, critical = brain_penalties({"disposition": True})
        self.assertTrue(critical)
        self.assertIn("處置分盤不可現沖", "".join(flags))


def brain_penalties(m: dict):
    import daytrade_brain as brain
    return brain._penalties(m, {}, None)


if __name__ == "__main__":
    unittest.main()


class TestEligDayGuard(unittest.TestCase):
    """`if mh` 移出後,必須有**獨立**的日次守衛 —— 否則盤後每 30 分打一次 TWSE。"""

    def _src(self, name):
        return (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8")

    def test_app_has_independent_elig_day_guard(self):
        s = self._src("app.py")
        self.assertIn("elig_day", s, "沒有獨立守衛 → 會每輪打 TWSE")
        i_guard = s.index("if elig_day != today:")
        i_refresh = s.index("daytrade_eligibility.refresh()")
        self.assertLess(i_guard, i_refresh, "refresh 必須在日次守衛之內")
        # refresh 不可以再被關在 `if mh:` 裡(那正是停在 07-13 的原因)
        i_mh = s.index("            if mh:", i_guard)
        self.assertLess(i_refresh, i_mh, "refresh 又被關回盤中閘裡了")

    def test_app_only_marks_done_when_trusted(self):
        """抓失敗不可以記「今天做過了」,否則當天就再也不會重試。"""
        s = self._src("app.py")
        i = s.index("if elig_day != today:")
        blk = s[i:i + 1400]
        self.assertIn("is_trusted", blk)
        j_trust = blk.index("is_trusted")
        j_set = blk.index("elig_day = today")
        self.assertLess(j_trust, j_set, "elig_day 應該只在 is_trusted 為真時才設")

    def test_app_logs_instead_of_silent_pass(self):
        """舊版 `except: pass` 吞掉的是 ImportError / API 形狀改變 =「真的壞了」→ 必須留痕。"""
        s = self._src("app.py")
        i = s.index("if elig_day != today:")
        blk = s[i:i + 1400]
        self.assertNotIn("except Exception:\n                    pass", blk)
        self.assertIn("print(", blk)

    def test_loop_has_same_guard(self):
        s = self._src("loop.py")
        self.assertIn("elig_day", s)
        i_guard = s.index("if elig_day != _date.today():")
        i_refresh = s.index("daytrade_eligibility.refresh()")
        self.assertLess(i_guard, i_refresh)
