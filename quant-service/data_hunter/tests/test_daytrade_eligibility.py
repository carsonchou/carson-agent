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
    """_fetch_json:合法 list 回傳、非 list 回 []、例外吞成 []。全程打樁不連網。"""

    def test_valid_list(self):
        payload = json.dumps([{"Code": "1101"}]).encode("utf-8")
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(payload)):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(out, [{"Code": "1101"}])

    def test_non_list_json_becomes_empty(self):
        payload = json.dumps({"not": "a list"}).encode("utf-8")
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(payload)):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(out, [])

    def test_exception_swallowed(self):
        with mock.patch.object(elig.urllib.request, "urlopen",
                               side_effect=OSError("network down")):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(out, [])

    def test_bad_json_becomes_empty(self):
        with mock.patch.object(elig.urllib.request, "urlopen",
                               return_value=_FakeResp(b"<<not json>>")):
            out = elig._fetch_json("https://example.invalid/x")
        self.assertEqual(out, [])


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
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}], []]):
            elig.refresh()
        p = elig._cache_path()
        self.assertTrue(p.exists())
        saved = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(saved["disposition"], ["1101"])

    def test_load_reads_written_cache(self):
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}],
                                                                 [{"Code": "2330"}]]):
            elig.refresh()
        loaded = elig.load()   # offline 預設,直接讀快取
        self.assertEqual(loaded["disposition"], ["1101"])
        self.assertEqual(loaded["attention"], ["2330"])

    def test_load_missing_offline_returns_empty(self):
        # temp 目錄無快取檔 + offline=True → 回空(全部視為可當沖)
        loaded = elig.load(offline=True)
        self.assertEqual(loaded["disposition"], [])
        self.assertEqual(loaded["attention"], [])

    def test_load_missing_non_offline_triggers_refresh(self):
        with mock.patch.object(elig, "_fetch_json", side_effect=[[{"Code": "1101"}], []]):
            loaded = elig.load(offline=False)   # 缺檔 → 觸發 refresh(已打樁)
        self.assertEqual(loaded["disposition"], ["1101"])


if __name__ == "__main__":
    unittest.main()
