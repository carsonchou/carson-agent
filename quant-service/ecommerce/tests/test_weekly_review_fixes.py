# -*- coding: utf-8 -*-
"""test_weekly_review_fixes.py — 釘死 REVIEW_weekly_value 的續訂殺手修復(2026-07-17)。

不碰檔案系統、不渲染 PDF、不寄信、**不打外部網路**(點播現算一律注入 stub)。
執行:pytest quant-service/ecommerce/tests/test_weekly_review_fixes.py -q
"""
import copy
import datetime as _dt
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ECOM = HERE.parent
ROOT = ECOM.parent.parent
for p in (str(ECOM), str(ROOT / "youtube_channel" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import weekly_report_v2 as W  # noqa: E402


def _state():
    return {
        "date": "2026-07-16",
        "gauge": {"temperature": 45.4, "label": "中性", "breadth": 40.9, "adr": 1.8,
                  "avg_rsi": 48.8, "adv": 1060, "dec": 588, "flat": 277, "nh": 95, "nl": 88},
        "index": {"name": "0050", "price": 106.4, "chg": 0.09, "trend": "UP", "above_yearline": True},
        "wave_top": [{"code": "6414", "name": "樺漢", "industry": "電腦及週邊", "price": 400.0,
                      "chg": 4.17, "rsi": 64.2, "score": 83.6, "st": "UP"}],
        "track": {"n_closed": 19, "n_open": 278, "win_rate": 0.158, "avg_r": -0.61,
                  "avg_ret_pct": -7.77, "long_win_rate": 0.167, "short_win_rate": 0.154,
                  "recent": [{"code": "7751", "name": "捷普", "side": "short", "entry": 1370,
                              "exit": 1420, "ret_pct": -3.6, "r": -0.5, "result": "loss",
                              "exit_reason": "stop"}]},
    }


def _boom(code):
    raise AssertionError(f"不該呼叫現算引擎(code={code})")


# ══════════════════════════════════════════════════════════════════════════════
#  #5 名稱缺失「代號 代號」(評審實測 12 處)
# ══════════════════════════════════════════════════════════════════════════════
def test_name_map_never_falls_back_to_code():
    """map 不得拿代號當名字 —— 那正是「2891 2891」的上游成因。"""
    st = {"wave_top": [{"code": "9999", "name": "9999"}, {"code": "6414", "name": "樺漢"}]}
    m = W.build_name_map(st, {"by_code": {}}, [])
    assert "9999" not in m, "名稱等於代號時不該進 map(會被印成「9999 9999」)"
    assert m.get("6414") == "樺漢"


def test_stock_cell_prints_code_once_when_name_unknown():
    html = W._stock_cell({}, "2891")
    assert html.count("2891") == 1, f"代號被印了不只一次:{html}"
    html2 = W._stock_cell({"2891": "中信金"}, "2891")
    assert "中信金" in html2 and html2.count("2891") == 1


def test_name_map_resolves_reviewer_reported_codes():
    """評審點名的 12 檔只在 valuation/chips(無 name 欄)、不在 state.wave_top,
    必須靠 adaptive/twstock 補齊。"""
    m = W.build_name_map({}, {"by_code": {}}, W.load_adaptive())
    missing = [c for c in ("1102", "1423", "1432", "1446", "2356", "2387",
                           "2536", "2891", "3045", "4137", "5225", "5706") if c not in m]
    assert not missing, f"仍查不到名稱:{missing}"
    assert m["2891"] == "中信金" and m["3045"] == "台灣大"


# ══════════════════════════════════════════════════════════════════════════════
#  #6 S5 高殖利率陷阱揭露
# ══════════════════════════════════════════════════════════════════════════════
def test_s5_discloses_yield_trap_and_industry_concentration():
    valdoc = {"date": "2026-07-16", "data": {
        "2545": {"dividend_yield": 13.99, "pe": 5.0, "pb": 0.8},
        "2536": {"dividend_yield": 13.54, "pe": 6.0, "pb": 0.9},
        "5522": {"dividend_yield": 13.26, "pe": 7.0, "pb": 1.0},
        "2330": {"dividend_yield": 0.9, "pe": 32.5, "pb": 6.0}}}
    nmap = {"2545": "皇建", "2536": "宏普", "5522": "遠雄", "2330": "台積電"}
    imap = {"2545": "建材營造業", "2536": "建材營造業", "5522": "建材營造業", "2330": "半導體業"}
    sec = W.sec_S5(valdoc, nmap, imap)
    html = "".join(sec["units"])
    assert "風險揭露" in html
    assert "不等於好標的" in html or "不可持續" in html
    assert "建材營造業" in html, "產業欄/集中度未揭露"
    for banned in ("建議買進", "推薦買進", "值得買", "應該買"):
        assert banned not in html, f"風險揭露不得變成買賣建議:{banned}"


def test_s5_yield_trap_note_survives_gate():
    valdoc = {"date": "2026-07-16", "data": {
        "2545": {"dividend_yield": 13.99, "pe": 5.0, "pb": 0.8},
        "2330": {"dividend_yield": 0.9, "pe": 32.5, "pb": 6.0}}}
    sec = W.sec_S5(valdoc, {"2545": "皇建", "2330": "台積電"},
                   {"2545": "建材營造業", "2330": "半導體業"})
    bad = sec["prov"].gate(W._gate_text_from_units(sec["units"]), "S5")
    assert bad == [], f"S5 被守門擋:{[(c['value'], c['clause'][:40]) for c in bad]}"


# ══════════════════════════════════════════════════════════════════════════════
#  #2 S6 重新定位 + 樣本不足(且不得靠弱化守門過關)
# ══════════════════════════════════════════════════════════════════════════════
def test_wilson_ci_matches_textbook_values():
    """自寫統計必須對得上教科書值,否則就是自造數字。"""
    lo, hi = W.wilson_ci(50, 100)
    assert abs(lo - 0.4038) < 0.001 and abs(hi - 0.5962) < 0.001
    lo2, hi2 = W.wilson_ci(3, 19)
    assert abs(lo2 - 0.0552) < 0.001 and abs(hi2 - 0.3757) < 0.001
    assert W.wilson_ci(0, 0) is None


def test_s6_reframed_as_trust_anchor_not_scorecard():
    sec = W.sec_S6(_state())
    assert "成績單" not in sec["title"], "舊 framing 讓最低價層的門面自曝其短"
    assert "不賣訊號" in sec["title"]
    html = "".join(sec["units"])
    assert "只賣數據" in html or "不喊單" in html


def test_s6_proves_sample_insufficiency_with_interval():
    """光寫「樣本不足」是空話 —— 要給區間讓讀者自己看有多不足。"""
    html = "".join(W.sec_S6(_state())["units"])
    assert "樣本不足,不可外推" in html
    assert "信賴區間" in html
    assert "5.5%" in html and "37.6%" in html, "n=19/k=3 的 Wilson 區間端點未出現"


def test_s6_passes_gate_without_pooling_confidence_level():
    """🔴 最重要:S6 過守門,但**不是靠把 95 灌進池**過的。
    把信心水準 95 入池 → 日後捏造的「勝率 95%」就撞得到鄰居 = 為自己文案弱化守門。"""
    sec = W.sec_S6(_state())
    bad = sec["prov"].gate(W._gate_text_from_units(sec["units"]), "S6")
    assert bad == [], f"S6 被守門擋下:{[(c['value'], c['clause'][:40]) for c in bad]}"
    assert not any(abs(p - 95.0) < 0.01 for p in sec["prov"].pool), \
        "95(信心水準)被灌進池 → 守門被弱化"


def test_s6_gate_still_catches_fabricated_win_rate():
    """反向證明:上一條不是把守門關掉換來的。"""
    sec = W.sec_S6(_state())
    sec["units"] = list(sec["units"]) + ["<div>本策略勝率 95.0%,年化報酬 88.8%</div>"]
    bad = sec["prov"].gate(W._gate_text_from_units(sec["units"]), "S6")
    vals = {round(c["value"], 1) for c in bad}
    assert 95.0 in vals and 88.8 in vals


# ══════════════════════════════════════════════════════════════════════════════
#  #1 S8 真輪替 + 不得宣稱假的「月度輪替」
# ══════════════════════════════════════════════════════════════════════════════
def test_s8_theme_rotates_monthly_and_is_deterministic():
    idx = {W.s8_theme_index(_dt.date(2026, m, 1)) for m in range(1, 13)}
    assert idx == {0, 1, 2}, "一年內三個主題都要輪到"
    assert W.s8_theme_index(_dt.date(2026, 7, 1)) == W.s8_theme_index(_dt.date(2026, 7, 28)), "月內不得變"
    assert W.s8_theme_index(_dt.date(2026, 7, 1)) != W.s8_theme_index(_dt.date(2026, 8, 1)), "跨月必須換"


@pytest.mark.parametrize("month", [1, 2, 3])
def test_s8_every_theme_builds_and_discloses_update_rule(month):
    """三個主題都要能產出,且都要講清更新節奏與快照日(不得再假裝每週新鮮)。"""
    sec = W.sec_S8(W.load_adaptive(), {}, today=_dt.date(2026, month, 15))
    html = "".join(sec["units"])
    assert not sec.get("degraded"), f"主題 {W.s8_theme_index(_dt.date(2026, month, 15))} 產不出來"
    assert "每月換一次主題" in html and "同一個月內的每週內容相同" in html, "未揭露更新節奏"
    assert "靜態快照" in html and "距今" in html, "未標快照日/新鮮度"


def test_s8_title_no_longer_claims_unconditional_rotation():
    """舊標題「結構基準(月度輪替)」在什麼都沒輪的時候就是不實宣稱。"""
    sec = W.sec_S8(W.load_adaptive(), {})
    assert sec["title"] != "結構基準(月度輪替)"
    assert "本月主題" in sec["title"]


@pytest.mark.parametrize("month", [1, 2, 3])
def test_s8_themes_pass_gate(month):
    sec = W.sec_S8(W.load_adaptive(), {}, today=_dt.date(2026, month, 15))
    bad = sec["prov"].gate(W._gate_text_from_units(sec["units"]), "S8")
    assert bad == [], f"S8 主題被守門擋:{[(c['value'], c['clause'][:40]) for c in bad]}"


# ══════════════════════════════════════════════════════════════════════════════
#  #3 S7 開放點播(唯一護城河)
# ══════════════════════════════════════════════════════════════════════════════
def test_s7_empty_queue_is_identical_and_calls_no_engine():
    """佇列空 → 行為必須與改版前完全相同,且**絕不呼叫現算引擎**
    (現在 0 訂閱,這是常態路徑)。

    ⚠️ 這個測試第一版只比對 base(None) vs empty([]) 是否相等 —— 那是**空測**:
    突變測試證明,如果兩條路徑被同樣打壞(例如空佇列時硬塞一檔進點播),兩邊仍然相等、
    測試照樣綠。所以必須改成斷言「**沒有任何點播的痕跡**」這個絕對事實,而不是兩者自洽。
    """
    ck = W.load_checkup()
    base = W.sec_S7(ck)
    empty = W.sec_S7(ck, requests_doc={"requests": []}, ensure_fn=_boom)
    assert base["units"] == empty["units"], "空佇列改變了輸出 → 行為不再等價"
    assert not base.get("degraded")
    for label, sec in (("None", base), ("[]", empty)):
        html = "".join(sec["units"])
        assert "訂戶點播" not in html, f"佇列空({label})卻出現點播徽章 → 憑空多了一檔點播"
        assert "訂戶點播" not in sec["units"][0]
        assert "檔訂戶點播" not in html, f"佇列空({label})卻宣稱本期含點播"
        assert "下期優先處理" not in html


def test_s7_request_actually_reorders_vs_empty_queue():
    """點播要真的把該檔提前 —— 用「與空佇列的順序差異」證明,而不是只看它有沒有出現
    (2317 本來就在庫內、空佇列時也會出現在後面,只看『有沒有出現』會是空測)。"""
    import re as _re
    ck = W.load_checkup()

    def order(sec):
        # 只抓體檢卡上的代號 span(font-size:11px 那個);不能只用 color:var(--tx3),
        # 那個顏色在 lead 的說明文字也有 → 會把整句話當成代號抓進來。
        return _re.findall(r'font-size:11px;color:var\(--tx3\)">(\w+)<', "".join(sec["units"]))

    empty_order = order(W.sec_S7(ck, requests_doc={"requests": []}, ensure_fn=_boom))
    doc = {"requests": [{"email": "a@b.c", "code": "2317", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": 0}]}
    req_order = order(W.sec_S7(ck, requests_doc=doc, ensure_fn=_boom))
    assert empty_order and req_order
    assert empty_order[0] != "2317", "測試前提:2317 本來不是第一個(否則證明不了提前)"
    assert req_order[0] == "2317", "點播沒有把該檔提前"
    assert set(empty_order) == set(req_order), "點播不該讓其他檔消失"


def test_s7_request_for_in_library_stock_appears_first_without_engine():
    ck = W.load_checkup()
    doc = {"requests": [{"email": "a@b.c", "code": "2317", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": 0}]}
    sec = W.sec_S7(ck, requests_doc=doc, ensure_fn=_boom)   # 庫內已有 → 不該現算
    assert "訂戶點播" in "".join(sec["units"])
    assert doc["requests"][0]["status"] == "fulfilled"
    assert doc["requests"][0]["fulfilled_in"]
    assert "2317" in sec["units"][0], "點播檔沒有排在最前面"


def test_s7_request_not_in_library_triggers_engine_and_appears(monkeypatch):
    """不在庫的點播 → 呼叫現算引擎 → 出現在報告(stub,零外部網路)。"""
    ck = W.load_checkup()
    fake = copy.deepcopy(ck)
    called = []

    def stub(code):
        called.append(code)
        for k, f in list(ck["results"].items()):
            if "__2330" in k:
                nk = k.replace("2330", code)
                g = dict(f)
                g["key"] = nk
                fake["results"][nk] = g
        fake["by_code"][code] = {"name": "點播股"}
        return True

    monkeypatch.setattr(W, "load_checkup", lambda: fake)
    doc = {"requests": [{"email": "a@b.c", "code": "9999", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": 0}]}
    sec = W.sec_S7(ck, requests_doc=doc, ensure_fn=stub)
    assert called == ["9999"], "沒有呼叫現算引擎"
    assert "9999" in sec["units"][0]
    assert doc["requests"][0]["status"] == "fulfilled"


def test_s7_engine_failure_is_failsafe_not_fatal():
    """引擎炸掉 → 不可炸整份週報、不可編數字;降級說明 + 保留佇列下期重試。"""
    ck = W.load_checkup()

    def boom(code):
        raise RuntimeError("FinMind 連線逾時")

    doc = {"requests": [{"email": "a@b.c", "code": "8888", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": 0}]}
    sec = W.sec_S7(ck, requests_doc=doc, ensure_fn=boom)
    assert not sec.get("degraded"), "其餘輪替檔仍應正常交付"
    html = "".join(sec["units"])
    assert "8888" in html and "下期優先處理" in html, "未對訂戶說明點播為何沒出現"
    assert doc["requests"][0]["status"] == "pending", "暫時性失敗不該直接槍斃"
    assert doc["requests"][0]["attempts"] == 1
    assert doc["requests"][0]["last_error"]


def test_s7_gives_up_after_max_attempts():
    ck = W.load_checkup()
    doc = {"requests": [{"email": "a@b.c", "code": "8888", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": W.REQ_MAX_ATTEMPTS - 1}]}
    W.sec_S7(ck, requests_doc=doc, ensure_fn=lambda c: False)
    assert doc["requests"][0]["status"] == "failed", "不該無限重試"


def test_s7_mentions_ondemand_when_no_requests():
    """佇列空時要讓讀者知道有點播(這是 basic→full 的升級動機)。"""
    assert "點播" in "".join(W.sec_S7(W.load_checkup())["units"])


def test_s7_passes_gate_with_request():
    ck = W.load_checkup()
    doc = {"requests": [{"email": "a@b.c", "code": "2317", "requested_at": "2026-07-17",
                         "status": "pending", "attempts": 0}]}
    sec = W.sec_S7(ck, requests_doc=doc, ensure_fn=_boom)
    bad = sec["prov"].gate(W._gate_text_from_units(sec["units"]), "S7")
    assert bad == [], f"S7 被守門擋:{[(c['value'], c['clause'][:40]) for c in bad]}"


# ── 點播資格/額度(fail-closed)──────────────────────────────────────────────
def test_submit_request_requires_full_tier():
    doc = {"requests": []}
    ok, msg = W.submit_request("nobody@x.com", "2330", doc=doc, subscribers=[],
                               nmap={"2330": "台積電"})
    assert ok is False and "完整版" in msg
    assert doc["requests"] == []


def test_submit_request_rejects_unknown_code():
    ok, msg = W.submit_request("a@x.com", "0000", doc={"requests": []},
                               subscribers=[{"email": "a@x.com"}], nmap={"2330": "台積電"})
    assert ok is False and "查無代號" in msg


def test_submit_request_enforces_monthly_quota_and_resets():
    subs = [{"email": "a@x.com"}]
    doc = {"requests": []}
    nmap = {"2330": "台積電", "2317": "鴻海"}
    d = _dt.date(2026, 7, 17)
    ok1, _ = W.submit_request("a@x.com", "2330", doc=doc, subscribers=subs, nmap=nmap, today=d)
    ok2, msg2 = W.submit_request("a@x.com", "2317", doc=doc, subscribers=subs, nmap=nmap, today=d)
    assert ok1 is True and ok2 is False and "額度已用完" in msg2
    ok3, _ = W.submit_request("a@x.com", "2317", doc=doc, subscribers=subs, nmap=nmap,
                              today=_dt.date(2026, 8, 1))
    assert ok3 is True, "跨月應重置額度"


def test_load_requests_missing_file_is_empty_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "CHECKUP_REQUESTS", tmp_path / "nope.json")
    assert W.load_requests()["requests"] == []
