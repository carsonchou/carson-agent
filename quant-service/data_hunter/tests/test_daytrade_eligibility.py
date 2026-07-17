# -*- coding: utf-8 -*-
"""test_daytrade_eligibility.py — 當沖資格/處置/注意股清單純函式測試(不連網、urllib 全打樁)。

status/_cache_path 為純函式直接測;_fetch_json/refresh/load 會連網或寫檔 → 用
unittest.mock 打樁 urllib、把快取目錄導向 tempfile,絕不真的打 TWSE OpenAPI。
註:任務描述提到的 _parse_date 在實際原始碼中不存在,本模組僅有 _cache_path/_fetch_json/
refresh/load/status,故針對實際存在的函式撰寫。
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _util  # noqa: E402  # 掛 sys.path,讓生產模組可 import
import daytrade_eligibility as elig  # noqa: E402


class TestStatus(unittest.TestCase):
    """status:處置股不可現沖、注意股標記、預設可當沖、缺鍵不崩。"""

    def test_disposition_blocks_daytrade(self):
        e = {"disposition": ["1101"], "attention": []}
        r = elig.status("1101", e)
        self.assertFalse(r["can_daytrade"])
        self.assertTrue(r["disposition"])
        self.assertFalse(r["attention"])

    def test_attention_flagged_but_tradable(self):
        e = {"disposition": [], "attention": ["2330"]}
        r = elig.status("2330", e)
        self.assertTrue(r["can_daytrade"])
        self.assertFalse(r["disposition"])
        self.assertTrue(r["attention"])

    def test_normal_stock_all_clear(self):
        e = {"disposition": ["1101"], "attention": ["2330"]}
        r = elig.status("6505", e)
        self.assertTrue(r["can_daytrade"])
        self.assertFalse(r["disposition"])
        self.assertFalse(r["attention"])

    def test_missing_keys_do_not_crash(self):
        r = elig.status("9999", {})   # get 回 None → `or []`
        self.assertTrue(r["can_daytrade"])
        self.assertFalse(r["disposition"])
        self.assertFalse(r["attention"])

    def test_none_valued_keys(self):
        r = elig.status("9999", {"disposition": None, "attention": None})
        self.assertTrue(r["can_daytrade"])

    def test_uses_module_cache_when_elig_none(self):
        # elig=None → 走全域 _CACHE;注入已知快取,驗證不觸發磁碟/網路
        prev = elig._CACHE
        try:
            elig._CACHE = {"disposition": ["1234"], "attention": []}
            r = elig.status("1234")
            self.assertFalse(r["can_daytrade"])
        finally:
            elig._CACHE = prev


class TestCachePath(unittest.TestCase):
    """_cache_path:依日期組出 YYYYMMDD 檔名,None→今日。"""

    def test_explicit_date_filename(self):
        p = elig._cache_path(date(2025, 1, 2))
        self.assertEqual(p.name, "daytrade_eligibility_20250102.json")

    def test_default_uses_today(self):
        p = elig._cache_path()
        self.assertEqual(p.name, f"daytrade_eligibility_{date.today():%Y%m%d}.json")

    def test_under_cache_dir(self):
        p = elig._cache_path(date(2025, 12, 31))
        self.assertEqual(p.parent, elig.CACHE_DIR)


class _FakeResp:
    """模擬 urlopen 回傳物件(支援 with 語法與 .read())。"""

    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFetchJson(unittest.TestCase):
    """_fetch_json:合法 list 回傳;**抓不到一律回 None**(不是 [])。全程打樁不連網。

    ⚠️ 契約變更(2026-07-17,Carson 拍板):本組原本斷言「失敗 → 回 []」——那正是
    **fail-open 的根**:TWSE「今天真的沒資料」時回的是 [哨兵列](非空),失敗時回 [],
    舊版把失敗也變成 [] → 上層完全分不出「抓不到」與「今天 0 檔」→ refresh() 寫出
    `disposition: []` → M1 免費磁鐵印「處置股 0 檔」= 告訴當沖客這檔可以沖。
    這幾個測試當時是把 bug 當成規格釘住了。原意(壞輸入不可以炸)完全保留,
    只是把期望值從「[]」改成「None = 抓不到」。詳見 test_daytrade_elig_failclosed.py。
    """

    def test_valid_list(self):
        payload = json.dumps([{"Code": "1101"}]).encode("utf-8")
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(payload)):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(out, [{"Code": "1101"}])

    def test_non_list_json_is_none_not_empty(self):
        """形狀不對 = 抓不到(API 改版),不可以偽裝成「今天沒資料」。"""
        payload = json.dumps({"not": "a list"}).encode("utf-8")
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(payload)):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertIsNone(out)

    def test_exception_is_none_not_empty(self):
        """網路炸掉 → None(抓不到)。不炸、但也不可以回 [] 假裝成空清單。"""
        with mock.patch.object(elig.urllib.request, "urlopen",
                               side_effect=OSError("network down")):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertIsNone(out)

    def test_bad_json_is_none_not_empty(self):
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(b"<<not json>>")):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertIsNone(out)

    def test_sentinel_row_is_returned_as_data(self):
        """TWSE「今天沒資料」的哨兵列是**有效回應**,必須原樣回傳(不可當成失敗)。"""
        payload = json.dumps([{"Number": "0", "Code": "", "Name": ""}]).encode("utf-8")
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(payload)):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(len(out), 1)


class TestRefreshAndLoad(unittest.TestCase):
    """refresh:解析/去重/排序/去空白並寫檔;load:讀回同一份、缺檔 offline 回空。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        # 把快取目錄導向 temp(_cache_path 於呼叫時讀 CACHE_DIR 全域)
        self._patch = mock.patch.object(elig, "CACHE_DIR", self._dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_refresh_parses_dedups_sorts_strips(self):
        punish = [{"Code": "1101"}, {"Code": "1101"}, {"Code": " 2330 "}]
        notice = [{"Code": "6505"}, {"Code": ""}]  # 空碼應被濾掉
        with mock.patch.object(elig, "_fetch_json", side_effect=[punish, notice]):
            out = elig.refresh()
        self.assertEqual(out["disposition"], ["1101", "2330"])  # 去重+去空白+排序
        self.assertEqual(out["attention"], ["6505"])            # 空碼濾除
        self.assertIn("updated", out)

    def test_refresh_writes_cache_file(self):
        # 契約變更(2026-07-17):notice 原本餵 `[]`,而 `[]` 現在的意思是「**抓不到**」
        # → 整份不可信 → 依規不寫檔,本測試就會紅。這不是回歸,是舊測試餵了一個
        # 現實中不存在的回應:TWSE 沒資料時回的是**哨兵列**([{"Code":""}]),不是 []。
        # 改餵哨兵列 = 貼近真實,原意(抓到就要寫檔)完全保留。
        sentinel = [{"Number": "0", "Code": "", "Name": ""}]
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}], sentinel]):
            elig.refresh()
        p = elig._cache_path()
        self.assertTrue(p.exists())
        saved = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(saved["disposition"], ["1101"])
        self.assertEqual(saved["attention"], [])    # 哨兵列 → 真的 0 檔
        self.assertTrue(saved["ok"])                # 且是**可信的** 0 檔

    def test_refresh_does_not_write_when_fetch_failed(self):
        """新增(這正是 fail-open 的修補點):抓不到 → 不寫檔,免得被誤讀成「今天 0 檔」。"""
        with mock.patch.object(elig, "_fetch_json", side_effect=[None, None]):
            out = elig.refresh()
        self.assertFalse(out["ok"])
        self.assertFalse(elig._cache_path().exists())

    def test_load_reads_written_cache(self):
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}],
                                                                 [{"Code": "2330"}]]):
            elig.refresh()
        loaded = elig.load()   # offline 預設,直接讀快取
        self.assertEqual(loaded["disposition"], ["1101"])
        self.assertEqual(loaded["attention"], ["2330"])

    def test_load_missing_offline_is_untrusted_not_allow_all(self):
        # 契約變更(2026-07-17):原本註解寫「回空(**全部視為可當沖**)」——那就是 fail-open。
        # 現在:清單仍是空 list(既有呼叫端不會 KeyError),但 **ok=False** 明說「不可信」,
        # 呼叫端必須據此擋單/顯示「無法確認」,不可以再把「空」當成「今天沒有處置股」。
        loaded = elig.load(offline=True)
        self.assertEqual(loaded["disposition"], [])
        self.assertEqual(loaded["attention"], [])
        self.assertFalse(loaded["ok"], "缺檔卻回可信 → 一切放行(fail-open)")
        self.assertIn("reason", loaded)

    def test_load_missing_non_offline_triggers_refresh(self):
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}], []]):
            loaded = elig.load(offline=False)   # 缺檔 → 觸發 refresh(已打樁)
        self.assertEqual(loaded["disposition"], ["1101"])


if __name__ == "__main__":
    unittest.main()
