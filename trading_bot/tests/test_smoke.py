"""
煙霧測試（smoke test）— 整合層最小驗證。

驗證重點：
    1. 各模組皆可被 import（核心契約、設定、資料、策略、風控、執行、回測、協調）。
    2. SuperTrend 指標在合成資料上能算出有效值（非全 NaN）。
    3. SuperTrendStrategy 能在合成資料上產生 Signal（不崩潰）。
    4. PaperExecutor 能模擬下單，且買進/賣出方向、餘額、持倉數學正確
       （這同時驗證跨模組的 Side/Order 型別身分一致，避免「雙重模組」問題）。
    5. BacktestEngine 能跑完一輪回測並回傳 BacktestResult。
    6. main.py 的工廠函式能依設定組裝出策略/風控/執行器。

執行方式
--------
    # 方式 A：用 pytest（建議）
    cd trading_bot
    python -m pytest tests/test_smoke.py -v

    # 方式 B：直接執行（不需安裝 pytest）
    cd trading_bot
    python tests/test_smoke.py

設計：本檔自行把「trading_bot 目錄」加入 sys.path，因此可從任意工作目錄執行。
"""
from __future__ import annotations

import os
import sys
import warnings

# ── 讓測試可獨立執行：把 trading_bot 目錄（本檔之父目錄之父）加入 sys.path ──
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)          # .../trading_bot
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


# ════════════════════════════════════════════════════════════
# 共用：合成 OHLCV 資料（先跌後漲，保證 SuperTrend 會翻轉）
# ════════════════════════════════════════════════════════════
def _make_synthetic_ohlcv(n: int = 120) -> pd.DataFrame:
    """產生一段「先跌後漲」的合成 K 棒，足以讓指標暖機並翻轉。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    half = n // 2
    base = np.concatenate([np.linspace(100, 80, half), np.linspace(80, 120, n - half)])
    noise = np.sin(np.arange(n)) * 0.5
    close = base + noise
    df = pd.DataFrame(
        {
            "open": close + 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 10.0),
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


# ════════════════════════════════════════════════════════════
# 1) 各模組可被 import
# ════════════════════════════════════════════════════════════
def test_imports():
    """所有公開模組都應可被 import，不缺套件、不互相打架。"""
    import core.interfaces  # noqa: F401
    import config  # noqa: F401
    import data  # noqa: F401
    import strategy  # noqa: F401
    import risk  # noqa: F401
    import execution  # noqa: F401
    import backtest  # noqa: F401
    import orchestrator  # noqa: F401
    import main  # noqa: F401


def test_type_identity_is_unified():
    """核心型別（Side）在不同模組中必須是同一個類別物件。

    若 import 慣例不一致導致 core.interfaces 被載入兩次，會出現兩個
    不同的 Side 類別，使 isinstance 檢查失效、買賣方向錯亂。此測試守住該回歸。
    """
    import core.interfaces as ci
    from execution import executor as ex_mod

    assert ci.Side is ex_mod.Side, "Side 型別身分不一致（模組被重複載入）"


# ════════════════════════════════════════════════════════════
# 2) SuperTrend 指標在合成資料上能算出值
# ════════════════════════════════════════════════════════════
def test_supertrend_indicator_computes():
    from strategy.indicators import atr, supertrend

    df = _make_synthetic_ohlcv()
    atr_series = atr(df, length=10)
    assert atr_series.notna().any(), "ATR 全為 NaN"
    assert float(atr_series.iloc[-1]) > 0, "ATR 末值應為正"

    direction, line = supertrend(df, length=10, mult=3.0)
    assert direction.notna().any(), "SuperTrend 方向全為 NaN"
    assert line.notna().any(), "SuperTrend 軌道全為 NaN"
    # 末值方向應為 ±1
    last_dir = int(direction.dropna().iloc[-1])
    assert last_dir in (1, -1), f"方向應為 ±1，得到 {last_dir}"
    # 先跌後漲：應至少發生一次翻轉
    flips = int((direction.diff().abs() > 0).sum())
    assert flips >= 1, "先跌後漲序列應至少翻轉一次"


# ════════════════════════════════════════════════════════════
# 3) 策略能產生訊號
# ════════════════════════════════════════════════════════════
def test_strategy_generates_signal():
    from core.interfaces import Signal, SignalType
    from strategy.supertrend import SuperTrendStrategy

    df = _make_synthetic_ohlcv()
    strat = SuperTrendStrategy(atr_length=10, multiplier=3.0, symbol="BTC_USDT")
    assert strat.warmup_bars() > 0
    sig = strat.generate(df)
    assert isinstance(sig, Signal)
    assert sig.type in set(SignalType)

    # 暖機不足時應安全回 HOLD，而非報錯
    sig_short = strat.generate(df.iloc[:3])
    assert sig_short.type == SignalType.HOLD


# ════════════════════════════════════════════════════════════
# 4) PaperExecutor 能模擬下單（買賣方向 / 餘額 / 持倉數學）
# ════════════════════════════════════════════════════════════
def test_paper_executor_simulates_orders():
    from core.interfaces import Order, OrderStatus, Side
    from execution.executor import PaperExecutor

    ex = PaperExecutor()  # 預設 10,000 USDT
    start_usdt = ex.get_balance("USDT")
    assert start_usdt == 10_000.0

    # 買進 0.01 BTC @ 50000 → 應扣 500 USDT、增 0.01 BTC、持倉 +0.01
    buy = Order(symbol="BTC_USDT", side=Side.BUY, quantity=0.01, price=50_000.0)
    filled = ex.submit(buy)
    assert filled.status == OrderStatus.FILLED
    assert filled.filled_qty == 0.01
    assert filled.avg_fill_price == 50_000.0

    pos = ex.get_position("BTC_USDT")
    assert pos.size == 0.01, f"買進後持倉應為 +0.01，得到 {pos.size}"
    assert pos.entry_price == 50_000.0
    assert ex.get_balance("USDT") == 9_500.0, "買進應扣 500 USDT"
    assert ex.get_balance("BTC") == 0.01

    # 賣出 0.01 BTC @ 51000 → 平倉，USDT 回補
    sell = Order(symbol="BTC_USDT", side=Side.SELL, quantity=0.01, price=51_000.0)
    ex.submit(sell)
    pos2 = ex.get_position("BTC_USDT")
    assert pos2.size == 0.0, f"賣出平倉後持倉應歸零，得到 {pos2.size}"
    assert ex.get_balance("USDT") == 9_500.0 + 510.0


def test_paper_executor_factory_via_config():
    """dry_run=true 時，execution.build_executor 應回傳 PaperExecutor（不觸網）。"""
    from execution import PaperExecutor, build_executor

    cfg = {
        "dry_run": True,
        "trading": {"symbol": "BTC_USDT", "quote_asset": "USDT"},
    }
    ex = build_executor(cfg)
    assert isinstance(ex, PaperExecutor)


# ════════════════════════════════════════════════════════════
# 5) 回測引擎能跑完一輪
# ════════════════════════════════════════════════════════════
def test_backtest_engine_runs():
    from core.interfaces import BacktestResult
    from backtest.engine import BacktestEngine
    from strategy.supertrend import SuperTrendStrategy

    df = _make_synthetic_ohlcv()
    strat = SuperTrendStrategy(atr_length=10, multiplier=3.0, symbol="BTC_USDT")
    result = BacktestEngine(strategy=strat, stop_loss_pct=2.0).run(
        df, interval="15M", print_summary=False
    )
    assert isinstance(result, BacktestResult)
    assert isinstance(result.equity_curve, pd.Series)
    assert isinstance(result.trades, pd.DataFrame)
    assert len(result.equity_curve) == len(df)
    assert result.num_trades >= 0


# ════════════════════════════════════════════════════════════
# 6) main.py 工廠能組裝各層
# ════════════════════════════════════════════════════════════
def test_main_factories_build_components():
    import main
    from config import AppConfig
    from core.interfaces import Executor, RiskManager, Strategy

    # 直接用預設 AppConfig（dry_run=True，supertrend 策略），不讀檔、不觸網
    cfg = AppConfig()

    strat = main.build_strategy(cfg)
    assert isinstance(strat, Strategy)

    rm = main.build_risk_manager(cfg)
    assert isinstance(rm, RiskManager)

    ex = main.build_executor(cfg)
    assert isinstance(ex, Executor)


# ════════════════════════════════════════════════════════════
# 直接執行：不需 pytest 也能跑（簡易 runner）
# ════════════════════════════════════════════════════════════
def _run_all() -> int:
    tests = [
        test_imports,
        test_type_identity_is_unified,
        test_supertrend_indicator_computes,
        test_strategy_generates_signal,
        test_paper_executor_simulates_orders,
        test_paper_executor_factory_via_config,
        test_backtest_engine_runs,
        test_main_factories_build_components,
    ]
    failed = 0
    for t in tests:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t()
            print(f"PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__} -> {exc!r}")
    print(f"\n=== {len(tests) - failed}/{len(tests)} 通過 ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
