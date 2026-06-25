"""
Code review 架構級修復驗證（Batch 5，#6）。

涵蓋：
  - Decimal 記帳：大量小額累加不漂移（size/entry_price/realized 精確）。
  - 持久化以字串保精度，save→load 往返不失真。
  - 相容舊格式（state 檔內為數字）。
  - 對外仍回 float（介面不變）。

執行：cd trading_bot && python tests/test_review_fixes6.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

from core.interfaces import Side  # noqa: E402
from risk.position_tracker import PositionTracker  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"PASS  {name}")
    else:
        _failed += 1
        print(f"FAIL  {name}")


def test_no_accumulation_drift():
    t = PositionTracker()
    # 1000 筆 0.001@100 同向加倉 → size 精確 1.0、entry 精確 100，無 float 漂移
    for _ in range(1000):
        t.record_fill("BTC_USDT", Side.BUY, 0.001, 100.0)
    pos = t.get("BTC_USDT")
    check("#6 size 累加精確 == 1.0", pos.size == 1.0)
    check("#6 entry_price 精確 == 100.0", pos.entry_price == 100.0)
    # 內部以 Decimal 儲存（精確）
    check("#6 內部 size 為 Decimal 且精確",
          t.positions["BTC_USDT"].size == Decimal("1.000"))


def test_realized_no_drift():
    t = PositionTracker()
    # 1000 次 0.1@100 買、0.1@110 賣 → 每次 realized=+1，總和精確 1000
    for _ in range(1000):
        t.record_fill("X", Side.BUY, 0.1, 100.0)
        t.record_fill("X", Side.SELL, 0.1, 110.0)
    check("#6 realized 累加精確 == 1000（Decimal 無漂移）",
          t.realized_pnl_total == Decimal("1000.0"))
    check("#6 平倉後精確空手", t.get("X").size == 0.0)


def test_persistence_precision_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "s.json")
        t = PositionTracker.load(sp)
        t.record_fill("X", Side.BUY, 0.30000001, 12345.6789)
        t2 = PositionTracker.load(sp)
        check("#6 save→load 精度不失真(size)",
              t2.positions["X"].size == t.positions["X"].size)
        check("#6 save→load 精度不失真(entry)",
              t2.positions["X"].entry_price == t.positions["X"].entry_price)
        # 確認檔案內存的是字串（保精度）
        raw = json.loads(open(sp, encoding="utf-8").read())
        check("#6 持久化以字串保存",
              isinstance(raw["positions"]["X"]["size"], str))


def test_backward_compat_numeric_state():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "s.json")
        # 舊格式：數字而非字串
        old = {"realized_pnl_total": 5.0, "last_bar_ts": "2026-01-01T00:00:00",
               "positions": {"X": {"size": 2.0, "entry_price": 100.0}}}
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(old, f)
        t = PositionTracker.load(sp)
        check("#6 相容舊數字格式(size)", t.get("X").size == 2.0)
        check("#6 相容舊數字格式(realized)", t.realized_pnl_total == Decimal("5.0"))


if __name__ == "__main__":
    test_no_accumulation_drift()
    test_realized_no_drift()
    test_persistence_precision_roundtrip()
    test_backward_compat_numeric_state()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
