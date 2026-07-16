# -*- coding: utf-8 -*-
"""test_product_factory_v2.py — 一次性 SKU 工廠 v2 單元測試(不渲染 PDF、不連網)。

覆蓋:誠信守門拒絕未溯源數字、SKU 組裝完整性、listing 欄位完整、
tokenizer 切片對齊只補真來源大數字的子數(不放行憑空數字)、殖利率不再×100。
pytest:python -m pytest quant-service/ecommerce/tests -q
unittest:python quant-service/ecommerce/tests/test_product_factory_v2.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ECOM = HERE.parent
for p in (str(ECOM), str(ECOM.parent.parent / "youtube_channel" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import product_factory_v2 as pf  # noqa: E402
from product_factory import Provenance  # noqa: E402


def _ctx():
    return pf.load_ctx()


class TestProvenanceGate(unittest.TestCase):
    def test_gate_rejects_fabricated_number(self):
        """憑空塞一個沒入池的績效數字 → 守門必須擋下(fail-closed)。"""
        prov = Provenance()
        pf._pool(prov, 25.1)  # 只有 25.1 是有來源的
        item = {"sku": "TEST", "prov": prov,
                "gate_units": ['<div class="unit">勝率 <b>87.3%</b>,年化 <b>25.1%</b></div>']}
        bad = pf.gate_sku(item)
        vals = {round(c["value"], 1) for c in bad}
        self.assertIn(87.3, vals)            # 未入池的 87.3 被擋
        self.assertNotIn(25.1, vals)         # 有來源的 25.1 放行

    def test_gate_passes_when_all_pooled(self):
        prov = Provenance()
        pf._pool(prov, 25.1, 46.5)
        item = {"sku": "T", "prov": prov,
                "gate_units": ['<div>年化 25.1%,回撤 46.5%</div>']}
        self.assertEqual(pf.gate_sku(item), [])

    def test_tokenizer_reconcile_forgives_only_real_slices(self):
        """FG 對 5 位數% 會切子數;對齊只補真來源大數字的子數,不補憑空數字。"""
        prov = Provenance()
        pf._pool(prov, 10027.7)              # 真來源大數字
        pf._reconcile_tokenizer(prov)
        self.assertTrue(any(abs(p - 27.7) < 0.2 for p in prov.pool))   # 27.7 是 10027.7 的切片 → 補上
        self.assertFalse(any(abs(p - 88.8) < 0.2 for p in prov.pool))  # 88.8 非任何來源切片 → 不補


class TestSKUAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _ctx()

    def test_all_builders_pass_gate(self):
        """六個 builder 產出的每個 SKU 變體都要通過誠信守門(真實資料)。"""
        for sid, fn in pf.BUILDERS.items():
            items = fn(self.ctx)
            self.assertTrue(items, f"{sid} 應有產出")
            for it in items:
                bad = pf.gate_sku(it)
                self.assertEqual(bad, [], f"{it['sku']}_{it['lang']} 不該被守門擋:{bad[:2]}")

    def test_item_shape_complete(self):
        for sid, fn in pf.BUILDERS.items():
            for it in fn(self.ctx):
                for k in ("sku", "lang", "platform", "prov", "gate_units", "listing", "artifacts"):
                    self.assertIn(k, it, f"{sid} 缺 {k}")
                self.assertTrue(it["artifacts"], f"{sid} 無成品檔")
                # 每個成品 kind 合法
                for fnpath, kind, payload in it["artifacts"]:
                    self.assertIn(kind, ("pdf", "xlsx", "csv"))

    def test_listing_fields_complete(self):
        for sid, fn in pf.BUILDERS.items():
            for it in fn(self.ctx):
                lst = it["listing"]
                for k in ("sku", "lang", "platform", "title", "description", "tags", "price"):
                    self.assertIn(k, lst)
                self.assertTrue(lst["title"] and lst["description"] and lst["tags"])
                self.assertLessEqual(len(lst["title"]), 140)
                self.assertLessEqual(len(lst["tags"]), 13)
                # 定價鍵對應語系
                self.assertIn("NTD" if it["lang"] == "zh" else "USD", lst["price"])

    def test_listing_no_hype_words(self):
        ban = ("穩賺", "保證", "必賺", "翻倍", "guaranteed")
        for sid, fn in pf.BUILDERS.items():
            for it in fn(self.ctx):
                for tag in it["listing"]["tags"]:
                    self.assertFalse(any(b in tag for b in ban), f"{sid} tag 含誇大詞:{tag}")

    def test_c1_langs_and_c2_langs(self):
        """C1/C2 出中英雙版;T1/T2/M1/M2 只出中版(對齊商業規格 §3 收斂)。"""
        langs = {sid: sorted({it["lang"] for it in fn(self.ctx)}) for sid, fn in pf.BUILDERS.items()}
        self.assertEqual(langs["C1"], ["en", "zh"])
        self.assertEqual(langs["C2"], ["en", "zh"])
        self.assertEqual(langs["T1"], ["zh"])
        self.assertEqual(langs["M1"], ["zh"])


class TestCorrectness(unittest.TestCase):
    def test_dividend_yield_not_x100(self):
        """殖利率欄位已是百分比,體檢卡不得再×100(0.91 應顯示 ~0.9 而非 91)。"""
        ctx = _ctx()
        prov = Provenance()
        ff = pf.facts_for(ctx["checkup"], "2330")
        html = pf.checkup_card(prov, "2330", "台積電", ff)
        self.assertIn("殖利率", html)
        # 91.0 不該出現在殖利率 KPI(0.91 已是 %)
        self.assertNotIn('>91.0<small>%', html)

    def test_checkup_card_pools_all_shown_numbers(self):
        """體檢卡渲染的每個 %數字都要能被守門找到來源(池已含)。"""
        ctx = _ctx()
        prov = Provenance()
        ff = pf.facts_for(ctx["checkup"], "2330")
        html = pf.checkup_card(prov, "2330", "台積電", ff)
        pf._reconcile_tokenizer(prov)
        bad = prov.gate(pf.RK.gate_text([html]), "2330")
        self.assertEqual(bad, [], f"漏綁來源:{[(c['value'], c['clause'][:30]) for c in bad][:3]}")


if __name__ == "__main__":
    unittest.main()
