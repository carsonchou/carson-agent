# -*- coding: utf-8 -*-
"""整合測試:金流名冊(webhook.subscribers)↔ 週報寄送介面(weekly_report_v2.load_send_list)。

契約(名冊 schema 為金流層真相):
  - 名冊 = 扁平 dict {email_lower: {email,name,tier,platform,status,...}};active = status=="active"
  - export_active(path, tier) 是單一事實來源;load_send_list(tier) 直呼它(import 不到才走本地後備)
  - tier 分層:basic < full < full_annual;tier="full" 只回完整版及以上
本測試:用 webhook.apply_event 建真名冊 → export → load,斷言逐欄一致 + 分層正確 + 後備等價。

執行:pytest quant-service/ecommerce/tests/ -q
"""
import builtins
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ECOM = HERE.parent
QUANT = ECOM.parent
ROOT = QUANT.parent
for p in (str(ECOM), str(QUANT), str(ROOT / "youtube_channel" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import weekly_report_v2 as W  # noqa: E402
from webhook.subscribers import export_active, apply_event  # noqa: E402
from webhook.events import NormalizedEvent, EventKind  # noqa: E402


def _ev(kind, email, tier, oid):
    return NormalizedEvent(platform="portaly", kind=kind, event_key=oid, email=email,
                           name=email.split("@")[0], tier=tier, amount=149.0, currency="TWD",
                           order_id=oid, period_end="2026-08-16")


def _build_roster(path):
    """建一個真名冊:full / basic / full_annual 各一個 active,外加一個取消的(不該入名單)。"""
    apply_event(path, _ev(EventKind.SUB_NEW, "Full@x.com", "full", "o1"))
    apply_event(path, _ev(EventKind.SUB_NEW, "basic@x.com", "basic", "o2"))
    apply_event(path, _ev(EventKind.SUB_NEW, "annual@x.com", "full_annual", "o3"))
    apply_event(path, _ev(EventKind.SUB_NEW, "gone@x.com", "full", "o4"))
    apply_event(path, _ev(EventKind.SUB_CANCEL, "gone@x.com", "full", "o5"))  # 取消 → 移出


def test_export_load_contract_all(tmp_path, monkeypatch):
    roster = tmp_path / "subs.json"
    _build_roster(roster)
    monkeypatch.setattr(W, "SUBSCRIBERS", roster)
    exported = export_active(roster)
    loaded = W.load_send_list()
    assert loaded == exported, "load_send_list 應與 export_active 逐欄一致"
    emails = {r["email"] for r in loaded}
    assert emails == {"Full@x.com", "basic@x.com", "annual@x.com"}
    assert "gone@x.com" not in emails, "取消者不得出現在寄送名單"
    # 形狀契約
    for r in loaded:
        assert set(r.keys()) == {"email", "name", "tier", "platform"}


def test_tier_layering_full_only(tmp_path, monkeypatch):
    roster = tmp_path / "subs.json"
    _build_roster(roster)
    monkeypatch.setattr(W, "SUBSCRIBERS", roster)
    exported = export_active(roster, tier="full")
    loaded = W.load_send_list(tier="full")
    assert loaded == exported
    emails = {r["email"] for r in loaded}
    assert "basic@x.com" not in emails, "基礎版訂閱者不該收到完整版名單"
    assert {"Full@x.com", "annual@x.com"} <= emails, "full / full_annual 應收得到完整版"


def test_basic_tier_includes_everyone_active(tmp_path, monkeypatch):
    roster = tmp_path / "subs.json"
    _build_roster(roster)
    monkeypatch.setattr(W, "SUBSCRIBERS", roster)
    loaded = W.load_send_list(tier="basic")   # 基礎版:所有 active(權重 >= 1)都收得到
    emails = {r["email"] for r in loaded}
    assert {"Full@x.com", "basic@x.com", "annual@x.com"} == emails


def test_local_fallback_matches_export(tmp_path, monkeypatch):
    """強制 export_active import 失敗 → 本地後備讀取,結果必須與 export_active 一致。"""
    roster = tmp_path / "subs.json"
    _build_roster(roster)
    monkeypatch.setattr(W, "SUBSCRIBERS", roster)
    expected = export_active(roster, tier="full")

    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name.startswith("webhook"):
            raise ImportError("forced for fallback test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    got = W.load_send_list(tier="full")
    assert got == expected, "本地後備讀取應與 export_active 契約一致"


def test_missing_roster_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "SUBSCRIBERS", tmp_path / "nope.json")
    assert W.load_send_list() == []
    assert W.load_send_list(tier="full") == []
