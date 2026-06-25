"""
Code review 架構級修復驗證（Batch 1）。

涵蓋：
  #2 風控當日狀態持久化：盤中重啟後當日已實現損益 / 起始權益沿用（不歸零）。
  #1 回撤斷路器納入未實現損益：以「市值化權益」跌幅觸發上限，
     不再只看已實現損益（重倉抱大浮虧也會被擋）。
  回歸：純已實現損益的觸發行為維持不變。

執行：cd trading_bot && python tests/test_review_fixes2.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

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
# #2 當日狀態持久化：重啟沿用
# ──────────────────────────────────────────────────────────────
def test_daily_state_persistence():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "risk.json")
        rm = BasicRiskManager({"max_daily_loss_pct": 10.0}, state_path=sp)
        rm.reset_daily(start_equity=10_000.0)
        rm.register_realized_pnl(-500.0)
        rm.register_realized_pnl(-300.0)
        # 模擬盤中重啟：用同一 state_path 重建
        rm2 = BasicRiskManager({"max_daily_loss_pct": 10.0}, state_path=sp)
        check("#2 重啟後當日已實現損益沿用(-800)",
              abs(rm2.daily_realized_pnl - (-800.0)) < 1e-9)
        check("#2 重啟後當日虧損上限判斷接續(base=10000, -800=8%<10% 未觸發)",
              rm2.daily_loss_limit_hit(9_200.0) is False)
        rm2.register_realized_pnl(-300.0)  # 累計 -1100 = 11% → 觸發
        check("#2 接續累計後觸發上限", rm2.daily_loss_limit_hit(8_900.0) is True)


# ──────────────────────────────────────────────────────────────
# #1 回撤斷路器納入未實現損益（市值化權益跌幅）
# ──────────────────────────────────────────────────────────────
def test_unrealized_drawdown_breaker():
    rm = BasicRiskManager({"max_daily_loss_pct": 10.0})
    rm.reset_daily(start_equity=10_000.0)
    # 沒有任何已實現損益，但市值化權益跌到 8900（-11%）→ 應觸發
    check("#1 無已實現損益、純浮虧 -11% → 觸發回撤上限",
          rm.daily_loss_limit_hit(8_900.0) is True)
    check("#1 浮虧僅 -5% → 不觸發", rm.daily_loss_limit_hit(9_500.0) is False)
    check("#1 權益高於起始 → 不觸發", rm.daily_loss_limit_hit(10_500.0) is False)


def test_realized_loss_still_trips():
    # 回歸：已實現虧損達標時，即使 equity 傳很高也要觸發
    rm = BasicRiskManager({"max_daily_loss_pct": 10.0})
    rm.reset_daily(start_equity=10_000.0)
    rm.register_realized_pnl(-1_500.0)   # -15%
    check("回歸 已實現 -15% → 觸發(即使 equity 傳 99999)",
          rm.daily_loss_limit_hit(99_999.0) is True)


if __name__ == "__main__":
    test_daily_state_persistence()
    test_unrealized_drawdown_breaker()
    test_realized_loss_still_trips()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
