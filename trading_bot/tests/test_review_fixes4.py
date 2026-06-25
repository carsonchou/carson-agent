"""
Code review 架構級修復驗證（Batch 3，#7）。

涵蓋：
  - DataFeed.last_is_forming() 預設 True。
  - coordinator 依資料源 last_is_forming() 對齊策略 drop_forming
    （False feed → 策略不砍最後一根；True feed → 砍）。

執行：cd trading_bot && python tests/test_review_fixes4.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

import pandas as pd  # noqa: E402

from core.interfaces import Candle, DataFeed, Signal, SignalType, Strategy  # noqa: E402
from execution.executor import PaperExecutor  # noqa: E402
from risk.risk_manager import BasicRiskManager  # noqa: E402
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


class _Feed(DataFeed):
    def __init__(self, forming=True):
        self._forming = forming
        self.ts = datetime(2026, 1, 1)

    def get_historical(self, symbol, interval, limit):
        idx = pd.date_range(end=self.ts, periods=120, freq="h")
        return pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                             "close": 100.0, "volume": 1.0}, index=idx)

    def get_latest(self, symbol, interval):
        return Candle(timestamp=self.ts, open=100.0, high=100.0,
                      low=100.0, close=100.0, volume=1.0)

    def last_is_forming(self):
        return self._forming


class _ClosedOnlyFeed(_Feed):
    """純歷史/回測 feed：只回已收盤 K 棒。"""
    def __init__(self):
        super().__init__(forming=False)


class _DefaultFeed(DataFeed):
    """不覆寫 last_is_forming → 應吃到預設 True。"""
    def get_historical(self, symbol, interval, limit):
        return pd.DataFrame()

    def get_latest(self, symbol, interval):
        return Candle(timestamp=datetime(2026, 1, 1), open=1, high=1, low=1, close=1, volume=1)


class _StratWithFlag(Strategy):
    name = "flagstrat"

    def __init__(self, drop_forming=True):
        self.drop_forming = drop_forming

    def warmup_bars(self):
        return 1

    def generate(self, df):
        return Signal(type=SignalType.HOLD, symbol="BTC_USDT",
                      timestamp=datetime.now(), price=100.0)


def _coord(feed, strat, d):
    return TradingCoordinator(
        data_feed=feed, strategy=strat, risk_manager=BasicRiskManager({}),
        executor=PaperExecutor(), symbol="BTC_USDT", interval="1h",
        dry_run=True, poll_interval_sec=0, state_path=os.path.join(d, "s.json"),
    )


def test_default_last_is_forming_true():
    check("#7 DataFeed.last_is_forming() 預設 True", _DefaultFeed().last_is_forming() is True)


def test_align_drop_forming_to_feed():
    with tempfile.TemporaryDirectory() as d:
        # 純收盤 feed → 策略 drop_forming 應被對齊為 False
        s1 = _StratWithFlag(drop_forming=True)
        _coord(_ClosedOnlyFeed(), s1, d)
        check("#7 純收盤 feed → 策略 drop_forming 對齊為 False", s1.drop_forming is False)

        # forming feed → 維持 True
        s2 = _StratWithFlag(drop_forming=True)
        _coord(_Feed(forming=True), s2, d)
        check("#7 forming feed → 策略 drop_forming 維持 True", s2.drop_forming is True)


if __name__ == "__main__":
    test_default_last_is_forming_true()
    test_align_drop_forming_to_feed()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
