"""
Code review 修復驗證測試 — 證明本輪 review 後的修復真的生效。

涵蓋（皆為「驗證過確實存在、且能安全修」的項目）：
  A. risk_manager：signal.confidence=None 不再讓 evaluate 崩潰（fail-open 風險）。
  B. position_tracker：原子寫檔（不留半損毀 state、無 .tmp 殘檔）。
  C. position_tracker：state 檔損毀時 load 不拋例外、回退空追蹤器。
  D. position_tracker：非法成交（qty<=0）回 0 且不改動部位。
  E. position_tracker：多執行緒並發 record_fill 不漏更新（鎖生效）。

執行：cd trading_bot && python tests/test_review_fixes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

from core.interfaces import Position, Side, Signal, SignalType  # noqa: E402
from risk.position_tracker import PositionTracker  # noqa: E402
from risk.risk_manager import BasicRiskManager  # noqa: E402

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


# ──────────────────────────────────────────────────────────────
# A. confidence=None 不再崩潰
# ──────────────────────────────────────────────────────────────
def test_confidence_none_no_crash():
    rm = BasicRiskManager({"position_pct": 50.0, "max_position_pct": 100.0})
    pos = Position(symbol="BTC_USDT", size=0.0, entry_price=0.0)
    sig = Signal(type=SignalType.OPEN_LONG, symbol="BTC_USDT",
                 timestamp=datetime.now(), price=100.0, confidence=None)
    try:
        order = rm.evaluate(sig, pos, equity=10_000.0)
        crashed = False
    except Exception as exc:  # noqa: BLE001
        order = None
        crashed = True
        print(f"      (crashed: {exc!r})")
    check("A confidence=None 不再讓 evaluate 崩潰", not crashed)
    check("A confidence=None 視為 1.0 → 仍核可開倉", order is not None and order.quantity > 0)


# ──────────────────────────────────────────────────────────────
# B. 原子寫檔：無 .tmp 殘檔、state 可正常載回
# ──────────────────────────────────────────────────────────────
def test_atomic_save():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "state.json")
        t = PositionTracker.load(sp)
        t.record_fill("BTC_USDT", Side.BUY, 1.0, 100.0)
        t.mark_bar("2026-01-01T00:00:00")
        leftovers = [f for f in os.listdir(d) if ".tmp" in f]
        check("B 原子寫檔後無 .tmp 殘檔", leftovers == [])
        check("B state 檔存在", os.path.exists(sp))
        t2 = PositionTracker.load(sp)
        check("B 重載後部位正確", abs(t2.get("BTC_USDT").size - 1.0) < 1e-9)


# ──────────────────────────────────────────────────────────────
# C. 損毀 state → load 不拋例外、回退空追蹤器
# ──────────────────────────────────────────────────────────────
def test_corrupt_state_load():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "state.json")
        with open(sp, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ]]]")
        try:
            t = PositionTracker.load(sp)
            raised = False
        except Exception:  # noqa: BLE001
            t = None
            raised = True
        check("C 損毀 state：load 不拋例外", not raised)
        check("C 損毀 state：回退空追蹤器（空手）",
              t is not None and t.get("BTC_USDT").size == 0.0)


# ──────────────────────────────────────────────────────────────
# D. 非法成交回 0 且不改動部位
# ──────────────────────────────────────────────────────────────
def test_invalid_fill_ignored():
    t = PositionTracker()
    t.record_fill("X", Side.BUY, 1.0, 100.0)
    before = t.get("X").size
    r1 = t.record_fill("X", Side.BUY, 0.0, 100.0)    # qty<=0
    r2 = t.record_fill("X", Side.BUY, 1.0, 0.0)      # price<=0
    after = t.get("X").size
    check("D 非法成交 realized=0", abs(r1) < 1e-12 and abs(r2) < 1e-12)
    check("D 非法成交不改動部位", abs(after - before) < 1e-12)


# ──────────────────────────────────────────────────────────────
# E. 並發 record_fill 不漏更新（鎖生效）
# ──────────────────────────────────────────────────────────────
def test_concurrent_record_fill():
    t = PositionTracker()
    n = 200

    def worker():
        t.record_fill("BTC_USDT", Side.BUY, 1.0, 100.0)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    size = t.get("BTC_USDT").size
    check(f"E 並發 {n} 筆開多無漏更新（size={size}）", abs(size - n) < 1e-9)


if __name__ == "__main__":
    test_confidence_none_no_crash()
    test_atomic_save()
    test_corrupt_state_load()
    test_invalid_fill_ignored()
    test_concurrent_record_fill()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
