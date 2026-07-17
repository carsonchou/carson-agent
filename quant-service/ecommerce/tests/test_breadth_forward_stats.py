# -*- coding: utf-8 -*-
"""S1「這溫度能拿來擇時嗎」區塊 + 事實檔產生器的回歸測試。

釘死的三件事(每一條拿掉防線都會轉紅,見各 docstring):
  1. 統計是**算出來的**,不是硬編(用合成資料驗桶邏輯與基準);
  2. 呈現的每個數字都**綁得到 provenance**,且整段**過得了 fail-closed gate**;
  3. **誠信邊界**:必須明說這不是對官方溫度做回測、必須標樣本期間/來源、不可有預測語氣、
     事實檔不在時整塊消失(降級,不編數字)。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ECOM = HERE.parent
for p in (str(ECOM), str(ECOM.parent.parent / "youtube_channel" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import breadth_forward_stats as B  # noqa: E402
import weekly_report_v2 as W  # noqa: E402
from product_factory import Provenance  # noqa: E402


def _synth():
    """合成資料:60 檔 × 800 天。刻意讓答案可以手算驗證,不依賴真實檔案。"""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2015-01-01", periods=800)
    closes = {}
    for i in range(260):                      # ≥MIN_UNIVERSE(200)才會有有效日
        walk = 100 + np.cumsum(rng.normal(0, 1, len(idx)))
        closes[f"T{i}_TW"] = pd.Series(walk, index=idx)
    walk = 100 + np.cumsum(rng.normal(0.05, 1, len(idx)))
    closes[B.BENCH] = pd.Series(walk, index=idx)
    return closes


class TestGenerator:
    def test_buckets_are_computed_not_hardcoded(self):
        """換一份資料 → 數字必須跟著變(硬編的話兩份會一樣)。"""
        doc = B.compute(_synth())
        assert doc["ok"], doc.get("error")
        real = json.loads((B.OUT_FILE).read_text(encoding="utf-8")) if B.OUT_FILE.exists() else None
        assert doc["baseline"]["n_days"] > 0
        if real and real.get("ok"):
            assert doc["baseline"]["up_rate_pct"] != real["baseline"]["up_rate_pct"] or \
                   doc["baseline"]["n_days"] != real["baseline"]["n_days"], \
                   "合成資料與真實資料算出完全相同的結果 → 高度可疑(硬編?)"

    def test_baseline_matches_manual_recompute(self):
        """基準值必須等於「自己拿同一份資料手算」的結果。"""
        import pandas as pd
        closes = _synth()
        doc = B.compute(closes)
        px = pd.DataFrame(closes).sort_index()
        ma = px.rolling(B.MA_WIN).mean()
        valid = px.notna() & ma.notna()
        nv = valid.sum(axis=1)
        br = ((px > ma) & valid).sum(axis=1) / nv.replace(0, pd.NA) * 100
        br = br[nv >= B.MIN_UNIVERSE].dropna()
        b = closes[B.BENCH].reindex(br.index).ffill()
        fwd = (b.shift(-B.FWD_DAYS) / b - 1) * 100
        df = pd.DataFrame({"breadth": br, "fwd": fwd}).dropna()
        assert doc["baseline"]["n_days"] == len(df)
        assert doc["baseline"]["up_rate_pct"] == round(float((df.fwd > 0).mean() * 100), 1)

    def test_middle_dev_is_derived_from_data(self):
        """中間桶與基準的差距必須由資料算出——文案不可手打(手打的數字 gate 看不見)。"""
        doc = B.compute(_synth())
        mids = [r for r in doc["buckets"]
                if not r["insufficient"] and r["lo"] >= 20 and r["hi"] <= 80]
        if mids:
            expect = round(max(abs(r["up_rate_pct"] - doc["baseline"]["up_rate_pct"]) for r in mids), 1)
            assert doc["middle_max_dev_pct_points"] == expect

    def test_insufficient_bucket_emits_no_numbers(self):
        """樣本不足的桶不可以生出中位/上漲率(寧可標樣本不足,不編)。"""
        doc = B.compute(_synth())
        for r in doc["buckets"]:
            if r["insufficient"]:
                assert r["median_fwd_pct"] is None and r["up_rate_pct"] is None

    def test_no_data_degrades_not_fabricates(self):
        assert B.compute({})["ok"] is False
        assert B.compute({"XXX_TW": None})["ok"] is False


class TestS1Block:
    def _stats(self):
        s = W.load_breadth_stats()
        if not s:
            pytest.skip("twdata/breadth_forward_stats.json 尚未產生(跑 breadth_forward_stats.py)")
        return s

    def test_every_number_shown_is_in_provenance(self):
        """呈現的每個數字都要查得到來源(A1 紀律:綁定數字→來源存證)。"""
        st = self._stats()
        prov = Provenance()
        html = W._timing_block(prov, st)
        assert html
        recs = {r["field"]: r["value"] for r in prov.records}
        for f in ("baseline_up_rate_pct", "baseline_median_fwd_pct", "baseline_n_days",
                  "baseline_n_independent", "n_stocks", "forward_days",
                  "spread_pct_points", "middle_max_dev_pct_points"):
            assert f in recs, f"{f} 沒進 provenance"
        assert recs["baseline_up_rate_pct"] == st["baseline"]["up_rate_pct"]
        assert recs["n_stocks"] == st["n_stocks"]
        for b in st["buckets"]:
            lab = f'{b["lo"]}–{b["hi"]}'
            got = [r for r in prov.records if lab in (r.get("source") or "")]
            assert got, f"桶 {lab} 沒進 provenance"

    def test_block_passes_fail_closed_gate(self):
        """整段 S1(含新區塊)必須過得了守門,否則買家根本看不到。"""
        sec = W.sec_S1(W.load_state())
        if sec.get("degraded"):
            pytest.skip("state.json 無 gauge 資料")
        out = W.gate_or_degrade(dict(sec))
        assert not out["degraded"], f"S1 被守門擋下:{out.get('gated_out')}"

    def test_bucket_labels_do_not_masquerade_as_perf_claims(self):
        """桶界不可寫成「20~40%」——那會被守門判成查無來源的績效宣稱、整段被隱藏。
        (正解是改寫呈現、把 % 移到欄位標題,**不是**把 40/60/80/101 灌進池弱化守門。)"""
        st = self._stats()
        prov = Provenance()
        html = W._timing_block(prov, st)
        for b in st["buckets"]:
            assert f'{b["lo"]}~{b["hi"]}%' not in html
        # 且守門對這一段不得有任何 flag
        text = re.sub(r"<[^>]+>", " ", html)
        assert not prov.gate(text, "S1-timing")

    def test_confidence_boundaries_not_pooled(self):
        """桶界不可進池:進了池,日後捏造的「勝率 60%」就撞得到鄰居。"""
        st = self._stats()
        prov = Provenance()
        W._timing_block(prov, st)
        for v in (40.0, 60.0, 80.0, 101.0):
            assert not W.FG._sourced_strict(v, prov.pool), f"{v} 被灌進池 → 守門被弱化"

    def test_states_it_is_not_a_backtest_of_the_official_gauge(self):
        """最重要的誠信邊界:不可讓讀者以為這是在對頂上那個溫度做回測。
        (那是「頭條數字對得上、內部成分全錯」的同型陷阱。)"""
        st = self._stats()
        html = W._timing_block(Provenance(), st)
        txt = re.sub(r"<[^>]+>", "", html)
        assert "不是對本段頂上那個數字做回測" in txt
        assert "定義與資料源皆不同" in txt
        assert "不是對『市場溫度』這個指標本身做回測" in txt

    def test_discloses_sample_period_and_source(self):
        st = self._stats()
        txt = re.sub(r"<[^>]+>", "", W._timing_block(Provenance(), st))
        assert str(st["period_start"]) in txt and str(st["period_end"]) in txt
        assert "cache_adj" in txt
        assert str(st["baseline"]["n_days"]) in txt
        assert "介紹 ≠ 推薦" in txt

    def test_no_prediction_language(self):
        """是「歷史上這樣」,不是「所以現在該如何」。"""
        st = self._stats()
        txt = re.sub(r"<[^>]+>", "", W._timing_block(Provenance(), st))
        for bad in ("應該買", "建議買", "會漲", "將會", "看好", "逢低", "進場點", "現在該"):
            assert bad not in txt, f"出現預測/建議語氣:{bad}"

    def test_missing_stats_file_removes_block_entirely(self):
        """事實檔不在 → 整塊消失(降級),絕不編數字、也不留半截版面。"""
        prov = Provenance()
        assert W._timing_block(prov, {}) == ""
        assert W._timing_block(prov, {"ok": False}) == ""
        assert prov.records == []

    def test_load_breadth_stats_tolerates_garbage(self, tmp_path, monkeypatch):
        bad = tmp_path / "b.json"
        bad.write_text("{壞檔", encoding="utf-8")
        monkeypatch.setattr(W, "BREADTH_STATS", bad)
        assert W.load_breadth_stats() == {}
        monkeypatch.setattr(W, "BREADTH_STATS", tmp_path / "nope.json")
        assert W.load_breadth_stats() == {}
