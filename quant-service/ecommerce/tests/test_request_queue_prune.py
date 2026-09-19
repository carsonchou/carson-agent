"""點播佇列裁剪:控制檔案增長,但**絕不裁掉付了錢還沒被服務的人**。

背景(VERIFY_REPORT_weekly_fixes MINOR-4):佇列只 append,fulfilled/failed 永久留存,
長年累積會讓檔案愈來愈大(功能無誤,屬衛生問題)。

裁剪的危險在於「為了省空間而丟掉待辦」。本測試群釘死那條線:
**pending 永不裁剪** —— 那是完整版訂戶點播了、我們還沒交付的請求。丟掉它 =
「收了錢沒給東西」,是本專案定義的最不可接受的失敗(見 51b5da1 unknown-tier 那次)。
即使 pending 卡了兩年也留著:那代表引擎一直算不出來,是該被看見的問題,不是垃圾。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

_ECOM = Path(__file__).resolve().parents[1]
if str(_ECOM) not in sys.path:
    sys.path.insert(0, str(_ECOM))

import weekly_report_v2 as W  # noqa: E402


def _old(days: int) -> str:
    return (W.TODAY - timedelta(days=days)).isoformat()


def test_pending_never_pruned_even_when_ancient():
    """核心:付了錢還沒服務到的人,不管多久都要留著。"""
    doc = {"requests": [
        {"email": "a@e.com", "code": "2330", "status": "pending", "requested_at": _old(900)},
    ]}
    n = W._prune_requests(doc)
    assert n == 0
    assert len(doc["requests"]) == 1, "卡了兩年的 pending 被裁掉 = 收了錢沒給東西"


def test_old_closed_records_pruned():
    doc = {"requests": [
        {"email": "b@e.com", "code": "2317", "status": "fulfilled", "fulfilled_in": _old(400)},
        {"email": "c@e.com", "code": "2454", "status": "failed", "failed_at": _old(400)},
    ]}
    n = W._prune_requests(doc)
    assert n == 2 and doc["requests"] == []


def test_recent_closed_records_kept():
    doc = {"requests": [
        {"email": "d@e.com", "code": "2603", "status": "fulfilled", "fulfilled_in": _old(10)},
    ]}
    assert W._prune_requests(doc) == 0 and len(doc["requests"]) == 1


def test_unparseable_date_kept():
    """日期讀不出來 → 保留。不確定就別刪(刪錯不可逆,留著只是佔幾百 bytes)。"""
    for stamp in (None, "", "not-a-date", 20260101):
        doc = {"requests": [{"email": "e@e.com", "code": "1101",
                             "status": "fulfilled", "fulfilled_in": stamp}]}
        assert W._prune_requests(doc) == 0, f"日期={stamp!r} 讀不出來卻被裁掉了"


def test_mixed_queue_keeps_pending_and_recent():
    doc = {"requests": [
        {"email": "p@e.com", "code": "2330", "status": "pending", "requested_at": _old(999)},
        {"email": "o@e.com", "code": "2317", "status": "fulfilled", "fulfilled_in": _old(500)},
        {"email": "r@e.com", "code": "2454", "status": "fulfilled", "fulfilled_in": _old(5)},
    ]}
    W._prune_requests(doc)
    left = {r["email"] for r in doc["requests"]}
    assert left == {"p@e.com", "r@e.com"}, f"裁錯人,剩下 {left}"


def test_no_requests_key_is_noop():
    for doc in ({}, {"requests": None}, {"requests": []}):
        assert W._prune_requests(doc) == 0
