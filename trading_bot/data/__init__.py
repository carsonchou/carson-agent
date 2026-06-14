"""
資料層（data）：行情資料來源與交叉比對。

匯出：
    PionexFeed                — Pionex 官方公開行情 REST 資料源（主源）。
    TradingViewFeed           — TradingView 交叉比對資料源（需 tvdatafeed，可選）。
    TradingViewUnavailableError — tvdatafeed 不可用時的例外。
    DataReconciler            — 雙源最新價交叉比對器。
    ReconcileResult           — 交叉比對結果資料模型。

注意：本 __init__ 採延遲匯入，缺少選用套件（如 tvdatafeed）時，
仍可正常匯入 PionexFeed / DataReconciler，不會在 import data 階段崩潰。
"""
from __future__ import annotations

from .pionex_feed import PionexFeed
from .data_reconciler import DataReconciler, ReconcileResult

# TradingViewFeed 本身已對 tvdatafeed 做延遲匯入，故此處可安全匯入類別；
# 真正需要 tvdatafeed 的時機是在呼叫 get_historical / get_latest 時。
from .tradingview_feed import TradingViewFeed, TradingViewUnavailableError

__all__ = [
    "PionexFeed",
    "TradingViewFeed",
    "TradingViewUnavailableError",
    "DataReconciler",
    "ReconcileResult",
]
