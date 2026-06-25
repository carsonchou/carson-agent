"""
Code review 架構級修復驗證（Batch 4，#3 #4）。

涵蓋：
  #3 錯誤分類：429→RateLimit、5xx→Server、4xx→Client、result=false→Client、
     網路層→Network。
  #4 idempotent(GET) 暫時性錯誤退避重試；POST(下單)不自動重試（交給對帳）。
  #4 數量/價格取整 helper（floor_to_step / round_to_tick）。
  #3 executor：不確定(網路/5xx)標 NEW+needs_reconcile（不當拒單）；確定拒單→REJECTED。

執行：cd trading_bot && python tests/test_review_fixes5.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

import requests  # noqa: E402

from core.interfaces import Order, OrderStatus, Side  # noqa: E402
from execution.pionex_client import (  # noqa: E402
    PionexClient, PionexClientError, PionexNetworkError,
    PionexRateLimitError, PionexServerError,
)
from execution.executor import LiveExecutor, floor_to_step, round_to_tick  # noqa: E402

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


class _Resp:
    def __init__(self, status, payload, text="x"):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is _NOJSON:
            raise ValueError("not json")
        return self._payload


_NOJSON = object()


class _Session:
    """可腳本化的假 session：steps 為 (status, payload) 或 Exception。"""
    def __init__(self, steps):
        self._steps = list(steps)
        self.calls = 0

    def request(self, **kw):
        self.calls += 1
        step = self._steps[min(self.calls - 1, len(self._steps) - 1)]
        if isinstance(step, Exception):
            raise step
        status, payload = step
        return _Resp(status, payload)


def _client(steps, **kw):
    return PionexClient(api_key="k", api_secret="s", session=_Session(steps),
                        backoff_base=0.0, **kw)


# ── #3 錯誤分類 ──
def test_error_classification():
    cases = [
        ((429, {"result": False}), PionexRateLimitError, "429→RateLimit"),
        ((503, {"result": False}), PionexServerError, "5xx→Server"),
        ((400, {"result": False}), PionexClientError, "4xx→Client"),
        ((200, {"result": False, "message": "bad"}), PionexClientError, "result=false→Client"),
        (requests.ConnectionError("boom"), PionexNetworkError, "網路層→Network"),
    ]
    for step, exc_type, label in cases:
        c = _client([step], max_retries=0)
        try:
            c.get_balances()
            got = None
        except Exception as e:  # noqa: BLE001
            got = type(e)
        check(f"#3 {label}", got is exc_type)


# ── #4 idempotent 退避重試 / POST 不重試 ──
def test_idempotent_retry():
    # GET 連兩次 500 再成功 → 應重試到成功
    c = _client([(500, {}), (500, {}), (200, {"result": True, "data": {"ok": 1}})],
                max_retries=3)
    data = c.get_balances()
    check("#4 GET 暫時性錯誤退避重試後成功", data.get("data", {}).get("ok") == 1)
    check("#4 GET 共嘗試 3 次", c._session.calls == 3)


def test_post_no_retry():
    # POST 下單遇 500 → 立即拋（不自動重試，避免重複下單）
    c = _client([(500, {}), (200, {"result": True})], max_retries=3)
    try:
        c.place_order("BTC_USDT", "BUY", "MARKET", size=1.0)
        raised = None
    except Exception as e:  # noqa: BLE001
        raised = type(e)
    check("#4 POST 5xx 立即拋 PionexServerError", raised is PionexServerError)
    check("#4 POST 不自動重試（只嘗試 1 次）", c._session.calls == 1)


# ── #4 取整 helper ──
def test_rounding_helpers():
    check("#4 floor_to_step 數量向下取整", abs(floor_to_step(1.2345, 0.01) - 1.23) < 1e-9)
    check("#4 floor_to_step None→原樣", floor_to_step(1.2345, None) == 1.2345)
    check("#4 round_to_tick 價格到 tick", abs(round_to_tick(100.037, 0.05) - 100.05) < 1e-9)
    check("#4 round_to_tick None→原樣", round_to_tick(100.037, None) == 100.037)


# ── #3 executor 不確定 vs 確定拒單 ──
class _FakeClient:
    def __init__(self, exc):
        self._exc = exc

    def place_order(self, **kw):
        raise self._exc


def test_executor_uncertain_vs_rejected():
    # 網路錯誤（不確定）→ NEW + needs_reconcile，不可當拒單
    ex = LiveExecutor(client=_FakeClient(PionexNetworkError("timeout")),
                      symbol="BTC_USDT", dry_run=False)
    o = ex.submit(Order(symbol="BTC_USDT", side=Side.BUY, quantity=1.0, raw={"ref_price": 100.0}))
    check("#3 不確定→狀態 NEW（非 REJECTED）", o.status == OrderStatus.NEW)
    check("#3 不確定→標 needs_reconcile", o.raw.get("needs_reconcile") is True)

    # 確定被拒（4xx）→ REJECTED
    ex2 = LiveExecutor(client=_FakeClient(PionexClientError("bad param")),
                       symbol="BTC_USDT", dry_run=False)
    o2 = ex2.submit(Order(symbol="BTC_USDT", side=Side.BUY, quantity=1.0, raw={"ref_price": 100.0}))
    check("#3 確定拒單→狀態 REJECTED", o2.status == OrderStatus.REJECTED)


if __name__ == "__main__":
    test_error_classification()
    test_idempotent_retry()
    test_post_no_retry()
    test_rounding_helpers()
    test_executor_uncertain_vs_rejected()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
