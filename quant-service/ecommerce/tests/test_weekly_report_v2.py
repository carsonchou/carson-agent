# -*- coding: utf-8 -*-
"""weekly_report_v2 單元測試:section 計算 / fail-safe 降級 / provenance fail-closed。

不碰檔案系統、不渲染 PDF、不寄信 —— 純函式層,用 fixture 餵資料。
執行:pytest quant-service/ecommerce/tests/test_weekly_report_v2.py -q
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ECOM = HERE.parent
ROOT = ECOM.parent.parent
sys.path.insert(0, str(ECOM))
sys.path.insert(0, str(ROOT / "youtube_channel" / "scripts"))

import weekly_report_v2 as W  # noqa: E402
from product_factory import Provenance  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────
def _state():
    return {
        "date": "2026-07-16",
        "gauge": {"temperature": 45.4, "label": "中性", "breadth": 40.9, "adr": 1.8,
                  "avg_rsi": 48.8, "adv": 1060, "dec": 588, "flat": 277, "nh": 95, "nl": 88},
        "index": {"name": "0050", "price": 106.4, "chg": 0.09, "trend": "UP", "above_yearline": True},
        "sectors": [
            {"name": "貿易百貨業", "avg_chg": 1.06, "bull_pct": 63.0, "score": 54.0, "count": 19, "inst_count": 15, "leader": "統領 +10.0%"},
            {"name": "橡膠工業", "avg_chg": 0.99, "bull_pct": 100.0, "score": 53.6, "count": 11, "inst_count": 11, "leader": "台橡 +2.4%"},
            {"name": "光電業", "avg_chg": 0.48, "bull_pct": 26.0, "score": 34.7, "count": 117, "inst_count": 57, "leader": "冠西電 +10.0%"},
        ],
        "wave_top": [
            {"code": "6414", "name": "樺漢", "industry": "電腦及週邊", "price": 400.0, "chg": 4.17, "rsi": 64.2, "score": 83.6, "st": "UP"},
            {"code": "8112", "name": "至上", "industry": "電子通路業", "price": 85.6, "chg": 0.23, "rsi": 40.5, "score": 16.6, "st": "DOWN"},
        ],
        "chips": {"consec_top": [{"code": "6741", "name": "91APP", "net": 336, "consec": 10, "side": "foreign"}]},
        "track": {"n_closed": 19, "n_open": 278, "win_rate": 0.158, "avg_r": -0.61,
                  "avg_ret_pct": -7.77, "long_win_rate": 0.167, "short_win_rate": 0.154,
                  "recent": [{"code": "7751", "name": "捷普", "side": "short", "entry": 1370, "exit": 1420,
                              "ret_pct": -3.6, "r": -0.5, "result": "loss", "exit_reason": "stop"}]},
    }


def _chips_week():
    return [
        {"date": "2026-07-14", "data": {"6770": {"foreign_net": 20000}, "2330": {"foreign_net": -5000}}},
        {"date": "2026-07-15", "data": {"6770": {"foreign_net": 34266}, "2330": {"foreign_net": -3000}}},
    ]


def _valdoc():
    return {"date": "20260716", "data": {
        "2442": {"pe": 3.68, "dividend_yield": 13.99, "pb": 0.83},
        "2528": {"pe": 9.27, "dividend_yield": 13.54, "pb": 1.34},
        "1101": {"pe": None, "dividend_yield": 3.4, "pb": 0.75},
        "2330": {"pe": 32.5, "dividend_yield": 2.0, "pb": 8.1},
        "2317": {"pe": 16.7, "dividend_yield": 4.5, "pb": 2.0},
    }}


def _checkup():
    return {
        "by_code": {"2330": {"name": "台積電"}},
        "results": {
            "checkup_long_horizon__2330": {
                "key": "checkup_long_horizon__2330", "claim": "近20年含息還原總報酬 8728.8%（年化 25.1%）",
                "source": "Yahoo Finance", "computed_at": "2026-07-15", "data": {"total": 87.288, "cagr": 0.251}},
            "checkup_crash__2330__crisis2008": {
                "key": "checkup_crash__2330__crisis2008", "claim": "2008金融海嘯期間跌 -43.8%；抱到現在報酬 6414.2%",
                "source": "Yahoo Finance", "computed_at": "2026-07-15", "data": {"dd": -0.438, "hold": 64.142}},
        },
    }


def _adaptive():
    return [
        {"code": "2330", "name": "台積電", "a_net": 1746.9, "a_win": 33.9},
        {"code": "2317", "name": "鴻海", "a_net": -12.3, "a_win": 41.0},
        {"code": "2454", "name": "聯發科", "a_net": 2386.2, "a_win": 37.9},
        {"code": "2603", "name": "長榮", "a_net": 5.0, "a_win": 44.0},
    ]


# ── section 計算(有資料 → OK 且含關鍵數字)──────────────────────────────────
def test_s1_ok():
    s = W.gate_or_degrade(W.sec_S1(_state()))
    assert not s["degraded"]
    html = "".join(s["units"])
    assert "45.4" in html and "40.9" in html


def test_s2_ok():
    s = W.gate_or_degrade(W.sec_S2(_state()))
    assert not s["degraded"]
    assert "貿易百貨業" in "".join(s["units"])


def test_s3_ok():
    s = W.gate_or_degrade(W.sec_S3(_state(), W.build_name_map(_state(), {})))
    assert not s["degraded"]
    assert "樺漢" in "".join(s["units"])


def test_s4_ok_weekly_aggregate():
    st = _state()
    s = W.gate_or_degrade(W.sec_S4(st, _chips_week(), W.build_name_map(st, {})))
    assert not s["degraded"]
    # 6770 週加總 = 20000+34266 = 54266
    assert "54,266" in "".join(s["units"]) or "54266" in "".join(s["units"])


def test_s5_ok_filters_null_pe():
    s = W.gate_or_degrade(W.sec_S5(_valdoc(), W.build_name_map(_state(), {})))
    assert not s["degraded"]
    # 殖利率最高 13.99 應在;PE 中位數以「非 null」計(4 檔:3.68/9.27/32.5/16.7)
    assert "13.99" in "".join(s["units"])


def test_s6_honest_scorecard_shows_losses():
    s = W.gate_or_degrade(W.sec_S6(_state()))
    assert not s["degraded"]
    html = "".join(s["units"])
    assert "15.8" in html            # win_rate 0.158 → 15.8%
    assert "-0.61" in html or "−0.61" in html  # 誠實亮出負 R


def test_s7_groups_crash_under_real_code():
    """回歸測試:crash key = checkup_crash__2330__crisis2008,code 必須是 2330 而非 crisis2008。"""
    s = W.gate_or_degrade(W.sec_S7(_checkup()))
    assert not s["degraded"]
    html = "".join(s["units"])
    assert "台積電" in html
    assert "crisis2008" not in html   # 不得出現以 window 當股名的幽靈卡
    assert "6414.2%" in html          # 崩盤事實逐字引用


def test_s8_median_and_positive_pct():
    s = W.gate_or_degrade(W.sec_S8(_adaptive()))
    assert not s["degraded"]
    html = "".join(s["units"])
    assert "4" in html   # 樣本 4 檔
    # 中位數(1746.9,-12.3,2386.2,5.0)= (5.0+1746.9)/2 = 875.95 → 顯示 +876.0%
    assert "876" in html


# ── fail-safe:資料源缺/空 → 降級,不炸 ────────────────────────────────────────
def test_failsafe_empty_state():
    for fn in (lambda: W.sec_S1({}), lambda: W.sec_S2({}),
               lambda: W.sec_S3({}, {}), lambda: W.sec_S6({})):
        s = fn()
        assert s["degraded"] and "無" in "".join(s["units"])


def test_failsafe_empty_chips():
    s = W.sec_S4(_state(), [], W.build_name_map(_state(), {}))
    assert s["degraded"]


def test_failsafe_valuation_all_null():
    s = W.sec_S5({"data": {"1101": {"pe": None, "dividend_yield": None, "pb": None}}}, {})
    assert s["degraded"]


def test_failsafe_empty_checkup_and_adaptive():
    assert W.sec_S7({"results": {}, "by_code": {}})["degraded"]
    assert W.sec_S8([])["degraded"]


# ── provenance fail-closed:餵未溯源績效數字 → gate 擋下降級 ────────────────────
def test_provenance_rejects_unsourced_number():
    prov = Provenance()  # 空池,未 _pool 任何數字
    sec = {"id": "SX", "title": "測試段", "tier": "full", "degraded": False, "prov": prov,
           "units": ['<div class="metricrow">策略回測報酬率 <b>87.3%</b></div>']}
    out = W.gate_or_degrade(sec)
    assert out["degraded"] and out.get("gated_out"), "未溯源的 87.3% 必須被 fail-closed 擋下"
    # 原本「以 87.3% 作為事實陳述」的那一列已被移除(降級卡雖會說明擋了哪個數字,
    # 但不再把它當事實呈現);確認原始 claim 渲染消失。
    joined = "".join(out["units"])
    assert "<b>87.3%</b>" not in joined and "回測報酬率" not in joined


def test_provenance_passes_sourced_number():
    prov = Provenance()
    W._pool(prov, 87.3)  # 模擬:此數字來自來源欄位,已入池
    sec = {"id": "SX", "title": "測試段", "tier": "full", "degraded": False, "prov": prov,
           "units": ['<div class="metricrow">策略回測報酬率 <b>87.3%</b></div>']}
    out = W.gate_or_degrade(sec)
    assert not out["degraded"], "已溯源(入池)的數字應通過 gate"


def test_pool_fg_handles_5digit_percent():
    """>4 位數百分比(台股怪物報酬)不得因 FG tokenizer 侷限而誤殺。"""
    prov = Provenance()
    W._pool(prov, "近20年總報酬 21051.3%")  # 來源字串
    # FG 會把 21051.3% 抽成 1051.3(整數位 \d{1,4});_pool_fg 應已把 1051.3 入池
    bad = prov.gate("近20年總報酬 21051.3%", "t")
    assert not bad, "合法大數的 FG-tokenized 形式應已入池,不該被擋"


# ── 稽核檔覆蓋率回歸(VERIFY_REPORT_phase3a A1/A3)────────────────────────────
# v1 只有 S7 寫 prov.records:gate 全段有效(擋得下造假),但持久化稽核檔只覆蓋 1/8 段,
# 外部稽核者無法只憑該檔回查 S1–S6/S8。以下釘死「每段都要留存證」。
def test_all_sections_write_provenance_records():
    st = _state()
    nmap = W.build_name_map(st, _checkup())
    cases = {
        "S1": W.sec_S1(st), "S2": W.sec_S2(st), "S3": W.sec_S3(st, nmap),
        "S4": W.sec_S4(st, _chips_week(), nmap), "S5": W.sec_S5(_valdoc(), nmap),
        "S6": W.sec_S6(st), "S7": W.sec_S7(_checkup()), "S8": W.sec_S8(_adaptive()),
    }
    for sid, sec in cases.items():
        recs = sec["prov"].records
        assert recs, f"{sid} 未留任何溯源存證(A1 回歸:稽核檔會只覆蓋部分段)"
        for r in recs:
            assert r.get("source"), f"{sid} 有存證未標來源"
            assert r.get("field"), f"{sid} 有存證未標欄位"


def test_provenance_records_carry_structured_values():
    """A3:數值型要存 value(不能全 null),稽核才能程式化比對而非只靠文字。"""
    recs = W.sec_S1(_state())["prov"].records
    vals = [r for r in recs if r.get("value") is not None]
    assert vals, "S1 存證應含結構化數值"
    got = {r["field"]: r["value"] for r in vals}
    assert got.get("temperature") == _state()["gauge"]["temperature"], "存證數值須等同來源欄位值"


def test_s7_provenance_text_not_truncated():
    """A2:稽核檔不得自己把來源文字截斷(v1 存 txt[:60],斷在數字中間像壞數字)。"""
    ck = _checkup()
    recs = W.sec_S7(ck)["prov"].records
    claims = {f["key"]: (f.get("claim") or "") for r in ck["results"].values() for f in r.get("facts", [])}
    assert recs
    for r in recs:
        src_claim = claims.get(r["field"])
        if src_claim:
            assert r["text"] == src_claim.strip(), f"{r['field']} 存證文字被截斷/竄改"


# ── 交付介面:訂閱名冊不存在 → 空清單,不炸 ──────────────────────────────────
def test_load_send_list_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "SUBSCRIBERS", tmp_path / "nope.json")
    assert W.load_send_list() == []


def test_load_send_list_reads_active(monkeypatch, tmp_path):
    # 真實 schema:扁平 dict {email_lower: {...,status}};active = status=="active"
    f = tmp_path / "subs.json"
    f.write_text(
        '{"a@x.com":{"email":"a@x.com","name":"A","tier":"full","platform":"portaly","status":"active"},'
        '"b@x.com":{"email":"b@x.com","name":"B","tier":"basic","platform":"portaly","status":"cancelled"}}',
        encoding="utf-8")
    monkeypatch.setattr(W, "SUBSCRIBERS", f)
    out = W.load_send_list()
    assert len(out) == 1 and out[0]["email"] == "a@x.com"
