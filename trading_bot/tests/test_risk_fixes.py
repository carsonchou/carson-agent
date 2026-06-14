"""
風控修復驗證測試 — 證明 4 個 critical 修復真的生效。

涵蓋：
  #1 已實現損益回報接線：平倉後 risk_manager.daily_realized_pnl 真的更新。
  #2 實盤停損 entry_price：停損用追蹤器的真實進場價，會真的觸發平倉。
  #4 滑價保護：LiveExecutor 把市價單轉成帶上限的保護限價（用假 client，不觸網）。
  #5 狀態持久化 + 冪等：PositionTracker 存/載；client_order_id 同根同動作一致。
  另：PositionTracker 已實現損益數學（多/空/部分平倉）正確。

執行：cd trading_bot && python tests/test_risk_fixes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

import pandas as pd  # noqa: E402

from core.interfaces import (  # noqa: E402
    Candle, DataFeed, Order, OrderStatus, Position, Side, Signal, SignalType, Strategy,
)
from risk.position_tracker import PositionTracker  # noqa: E402
from risk.risk_manager import BasicRiskManager  # noqa: E402
from execution.executor import PaperExecutor, LiveExecutor  # noqa: E402
from orchestrator.coordinator import TradingCoordinator  # noqa: E402

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
# PositionTracker 數學
# ──────────────────────────────────────────────────────────────
def test_tracker_pnl_math():
    t = PositionTracker()
    # 開多 1@100，平多 1@110 → 實現 +10
    r1 = t.record_fill("BTC_USDT", Side.BUY, 1.0, 100.0)
    r2 = t.record_fill("BTC_USDT", Side.SELL, 1.0, 110.0)
    check("多單獲利平倉 realized=+10", abs(r1) < 1e-9 and abs(r2 - 10.0) < 1e-9)
    check("平倉後空手", t.get("BTC_USDT").size == 0.0)

    # 開多 2@100，部分平 1@90 → 實現 -10，剩 1@100
    t2 = PositionTracker()
    t2.record_fill("X", Side.BUY, 2.0, 100.0)
    r = t2.record_fill("X", Side.SELL, 1.0, 90.0)
    p = t2.get("X")
    check("多單部分虧損平倉 realized=-10", abs(r - (-10.0)) < 1e-9)
    check("部分平倉後剩 1@100", abs(p.size - 1.0) < 1e-9 and abs(p.entry_price - 100.0) < 1e-9)

    # 空單：賣 1@100，買回 1@90 → 實現 +10
    t3 = PositionTracker()
    t3.record_fill("X", Side.SELL, 1.0, 100.0)
    r = t3.record_fill("X", Side.BUY, 1.0, 90.0)
    check("空單獲利平倉 realized=+10", abs(r - 10.0) < 1e-9)


# ──────────────────────────────────────────────────────────────
# Stub 資料源 / 策略：可控制價格與訊號
# ──────────────────────────────────────────────────────────────
class StubFeed(DataFeed):
    def __init__(self):
        self.price = 100.0
        self.ts = datetime(2026, 1, 1, 0, 0, 0)

    def get_historical(self, symbol, interval, limit):
        idx = pd.date_range(end=self.ts, periods=120, freq="h")
        return pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                             "close": self.price, "volume": 1.0}, index=idx)

    def get_latest(self, symbol, interval):
        return Candle(timestamp=self.ts, open=self.price, high=self.price,
                      low=self.price, close=self.price, volume=1.0)


class ScriptedStrategy(Strategy):
    name = "scripted"

    def __init__(self, script):
        self._script = list(script)  # SignalType 序列
        self._i = 0

    def warmup_bars(self):
        return 1

    def generate(self, df):
        st = self._script[self._i] if self._i < len(self._script) else SignalType.HOLD
        self._i += 1
        price = float(df["close"].iloc[-1])
        return Signal(type=st, symbol="BTC_USDT", timestamp=datetime.now(),
                      price=price, confidence=1.0, reason="scripted")


# ──────────────────────────────────────────────────────────────
# #1 + #2：停損觸發 + 已實現損益回報
# ──────────────────────────────────────────────────────────────
def test_stop_and_pnl_wired():
    feed = StubFeed()
    strat = ScriptedStrategy([SignalType.OPEN_LONG, SignalType.HOLD])
    rm = BasicRiskManager({"position_pct": 50.0, "stop_loss_pct": 2.0,
                           "max_daily_loss_pct": 10.0, "max_position_pct": 100.0})
    paper = PaperExecutor(quote_asset="USDT")
    with tempfile.TemporaryDirectory() as d:
        coord = TradingCoordinator(
            data_feed=feed, strategy=strat, risk_manager=rm, executor=paper,
            symbol="BTC_USDT", interval="1h", base_asset="BTC", quote_asset="USDT",
            dry_run=True, poll_interval_sec=0, state_path=os.path.join(d, "s.json"),
        )
        # Bar 1：價 100 → 開多
        feed.price = 100.0; feed.ts += timedelta(hours=1)
        coord.run_once()
        pos1 = coord.tracker.get("BTC_USDT")
        check("#2 開多後追蹤器有部位且 entry_price≈100",
              pos1.size > 0 and abs(pos1.entry_price - 100.0) < 1e-6)

        # Bar 2：價跌到 90（跌破 2% 停損 98）→ 停損觸發、平倉、回報虧損
        feed.price = 90.0; feed.ts += timedelta(hours=1)
        coord.run_once()
        pos2 = coord.tracker.get("BTC_USDT")
        check("#2 停損真的觸發 → 已平倉(空手)", pos2.size == 0.0)
        check("#1 已實現損益有回報給風控(<0)", rm.daily_realized_pnl < 0)
        check("#1 風控當日虧損可被偵測(daily_loss_limit_hit 邏輯能算)",
              isinstance(rm.daily_loss_limit_hit(10000.0), bool))


# ──────────────────────────────────────────────────────────────
# #5：狀態持久化 + 冪等 client_order_id
# ──────────────────────────────────────────────────────────────
def test_persistence_and_idempotency():
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "state.json")
        t = PositionTracker.load(sp)
        t.record_fill("BTC_USDT", Side.BUY, 1.0, 100.0)
        t.mark_bar("2026-01-01T05:00:00")
        # 重新載入 → 部位與 last_bar 還在
        t2 = PositionTracker.load(sp)
        check("#5 持久化：重載後部位還在", abs(t2.get("BTC_USDT").size - 1.0) < 1e-9)
        check("#5 持久化：重載後 last_bar_ts 還在", t2.last_bar_ts == "2026-01-01T05:00:00")

    # 冪等 client_order_id：同根同動作 → 同 id
    feed = StubFeed()
    coord = TradingCoordinator(
        data_feed=feed, strategy=ScriptedStrategy([]), risk_manager=BasicRiskManager({}),
        executor=PaperExecutor(), symbol="BTC_USDT", interval="1h", dry_run=True,
        poll_interval_sec=0, state_path=None,
    )
    o1 = Order(symbol="BTC_USDT", side=Side.BUY, quantity=1.0)
    o2 = Order(symbol="BTC_USDT", side=Side.BUY, quantity=1.0)
    bar = datetime(2026, 1, 1, 5, 0, 0)
    coord._prep_order(o1, 100.0, bar, "OPEN_LONG")
    coord._prep_order(o2, 100.0, bar, "OPEN_LONG")
    check("#3 冪等：同根同動作 client_order_id 一致", o1.client_order_id == o2.client_order_id)
    check("#3 帶參考價(供滑價保護)", o1.raw.get("ref_price") == 100.0)


# ──────────────────────────────────────────────────────────────
# #4：滑價保護（假 client，不觸網）
# ──────────────────────────────────────────────────────────────
class FakeClient:
    def __init__(self):
        self.last = None

    def place_order(self, **kw):
        self.last = kw
        return {"data": {"status": "FILLED", "filledSize": kw["size"],
                         "avgPrice": kw["price"] or 0.0}}


def test_slippage_protection():
    fc = FakeClient()
    ex = LiveExecutor(client=fc, symbol="BTC_USDT", dry_run=False, max_slippage_pct=0.5)
    # 市價買單 + 參考價 100 → 應轉成 LIMIT，價 ≤ 100*1.005
    o = Order(symbol="BTC_USDT", side=Side.BUY, quantity=1.0, price=None,
              raw={"ref_price": 100.0})
    ex.submit(o)
    check("#4 市價買單轉成保護限價(LIMIT)", fc.last["order_type"] == "LIMIT")
    check("#4 買單限價=參考價+0.5%上限", abs(fc.last["price"] - 100.5) < 1e-6)

    # 市價賣單 → 限價 = 100*0.995
    fc2 = FakeClient()
    ex2 = LiveExecutor(client=fc2, symbol="BTC_USDT", dry_run=False, max_slippage_pct=0.5)
    o2 = Order(symbol="BTC_USDT", side=Side.SELL, quantity=1.0, price=None,
               raw={"ref_price": 100.0})
    ex2.submit(o2)
    check("#4 賣單限價=參考價-0.5%下限", abs(fc2.last["price"] - 99.5) < 1e-6)


if __name__ == "__main__":
    test_tracker_pnl_math()
    test_stop_and_pnl_wired()
    test_persistence_and_idempotency()
    test_slippage_protection()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
