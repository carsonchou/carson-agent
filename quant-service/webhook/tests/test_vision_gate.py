"""vision.gate_codes() 確定性查表閘門——模型猜的代號一律要過:代號存在於 twstock 上市櫃清單
且官方名稱與截圖上的名稱正規化後一致,否則標「無法辨識」、不送進分析。

失敗形狀(先寫、再寫閘門):
① 代號存在但名稱對不上(模型把「凱基台灣TOP50」猜成 00922 國泰台灣領袖50)
② 代號不存在(009186,Carson 實測撞到的)
③ 名稱對但數字對調(009861 不存在;060819 存在但是別檔)
正控制:009816 + 凱基台灣TOP50 必須通過。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _util
from webhook import vision

TOP50 = "凱基台灣TOP50"


def _gate(*items):
    return vision.gate_codes(list(items))


def _unrec_names(unrec):
    return [u["name"] for u in unrec]


class TestVisionGate(unittest.TestCase):
    def test_positive_control_009816_passes(self):
        codes, unrec = _gate({"code": "009816", "name": TOP50})
        assert codes == ["009816"] and unrec == []

    def test_positive_control_normalizes_fullwidth_and_spaces(self):
        codes, unrec = _gate({"code": "009816", "name": " 凱基台灣ＴＯＰ５０ "})
        assert codes == ["009816"] and unrec == []

    def test_shape1_code_exists_name_mismatch(self):
        codes, unrec = _gate({"code": "00922", "name": TOP50})
        assert codes == [] and _unrec_names(unrec) == [TOP50]

    def test_shape2_code_does_not_exist(self):
        codes, unrec = _gate({"code": "009186", "name": TOP50})
        assert codes == [] and _unrec_names(unrec) == [TOP50]

    def test_shape3_swapped_digits_nonexistent(self):
        codes, unrec = _gate({"code": "009861", "name": TOP50})
        assert codes == [] and len(unrec) == 1

    def test_shape3_swapped_digits_lands_on_other_existing_code(self):
        assert "060819" in vision._official_names()  # 前提:這個對調結果真的是另一檔存在的代號
        codes, unrec = _gate({"code": "060819", "name": TOP50})
        assert codes == [] and len(unrec) == 1

    def test_missing_name_cannot_be_verified(self):
        codes, unrec = _gate("009816", {"code": "009816", "name": ""})
        assert codes == [] and len(unrec) == 2

    def test_mixed_batch_keeps_only_verified_in_order(self):
        codes, unrec = _gate({"code": "2330", "name": "台積電"},
                             {"code": "009186", "name": TOP50},
                             {"code": "009816", "name": TOP50},
                             {"code": "2330", "name": "台積電"})
        assert codes == ["2330", "009816"] and _unrec_names(unrec) == [TOP50]

    def test_table_unavailable_fails_closed(self):
        with mock.patch("webhook.vision._official_names", return_value=None):
            codes, unrec = _gate({"code": "009816", "name": TOP50})
        assert codes == [] and len(unrec) == 1

    def test_route_never_returns_unverified_code(self):
        from fastapi.testclient import TestClient
        from webhook.app import build_app
        d = Path(tempfile.mkdtemp())
        client = TestClient(build_app(_util.make_settings(
            d, _entries=[], _mails=[], _ntfy=[], stock_checkup_orders=d / "sco.json")))
        with mock.patch("webhook.stock_checkup.vision.extract_codes",
                        return_value=[{"code": "009186", "name": TOP50},
                                      {"code": "2330", "name": "台積電"}]):
            r = client.post("/api/stock-checkup/extract-codes",
                            files={"file": ("s.png", b"x", "image/png")})
        assert r.status_code == 200
        body = r.json()
        assert body["codes"] == ["2330"]
        assert "009186" not in r.text
        assert body["unrecognized"][0]["name"] == TOP50
