"""
Code review 架構級修復驗證（Batch 2，#5）。

涵蓋：
  - 對帳：本地 tracker 持倉 vs 交易所實際持倉背離 → 觸發 CRITICAL 告警。
  - 對帳：一致 → 不告警、回傳 True。
  - 連續失敗退避告警：資料源持續拋例外時，主迴圈不崩、達門檻推告警。

執行：cd trading_bot && python tests/test_review_fixes3.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

import pandas as pd  # noqa: E402

from core.interfaces import Candle, DataFeed, Side, SignalType, Signal, Strategy  # noqa: E402
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
    def __init__(self, fail=False):
        self.fail = fail
        self.ts = datetime(2026, 1, 1)

    def get_historical(self, symbol, interval, limit):
        idx = pd.date_range(end=self.ts, periods=120, freq="h")
        return pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                             "close": 100.0, "volume": 1.0}, index=idx)

    def get_latest(self, symbol, interval):
        if self.fail:
            raise RuntimeError("模擬資料源掛掉")
        return Candle(timestamp=self.ts, open=100.0, high=100.0,
                      low=100.0, close=100.0, volume=1.0)


class _NoSig(Strategy):
    name = "nosig"

    def warmup_bars(self):
        return 1

    def generate(self, df):
        return Signal(type=SignalType.HOLD, symbol="BTC_USDT",
                      timestamp=datetime.now(), price=100.0)


def _coord(feed, alerts, state_dir):
    # 用獨立 temp state 路徑，避免測試間共用預設 .state 互相污染
    return TradingCoordinator(
        data_feed=feed, strategy=_NoSig(), risk_manager=BasicRiskManager({}),
        executor=PaperExecutor(), symbol="BTC_USDT", interval="1h",
        dry_run=True, poll_interval_sec=0,
        state_path=os.path.join(state_dir, "s.json"),
        alert=lambda lvl, msg: alerts.append((lvl, msg)),
    )


def test_reconcile_divergence_alerts():
    alerts = []
    with tempfile.TemporaryDirectory() as d:
        coord = _coord(_Feed(), alerts, d)
        # 本地追蹤器塞一個部位，但 PaperExecutor 實際持倉為 0 → 背離
        coord.tracker.record_fill("BTC_USDT", Side.BUY, 1.0, 100.0)
        ok = coord._reconcile()
    check("#5 背離時 _reconcile 回 False", ok is False)
    check("#5 背離觸發 CRITICAL 告警",
          any(lvl == "CRITICAL" for lvl, _ in alerts))


def test_reconcile_match_no_alert():
    alerts = []
    with tempfile.TemporaryDirectory() as d:
        coord = _coord(_Feed(), alerts, d)  # tracker 空、executor 空 → 一致
        ok = coord._reconcile()
    check("#5 一致時 _reconcile 回 True", ok is True)
    check("#5 一致時不告警", alerts == [])


def test_failure_backoff_alert():
    alerts = []
    with tempfile.TemporaryDirectory() as d:
        coord = _coord(_Feed(fail=True), alerts, d)
        # 資料源每輪都拋例外；跑 5 輪，主迴圈不應崩潰
        coord.run(max_loops=5)
    check("#5 連續失敗未讓主迴圈崩潰（跑完 5 輪）",
          coord._consecutive_failures >= 3)
    check("#5 連續失敗達門檻推 ERROR 告警",
          any(lvl == "ERROR" for lvl, _ in alerts))


if __name__ == "__main__":
    test_reconcile_divergence_alerts()
    test_reconcile_match_no_alert()
    test_failure_backoff_alert()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
