"""
trading_bot — Pionex 自動交易系統頂層套件。

子套件：
    core        核心契約（interfaces）：所有抽象介面與資料模型。
    config      設定載入與驗證（pydantic）。
    data        行情資料來源（Pionex 主源 + TradingView 交叉比對）。
    strategy    交易策略（SuperTrend 等）。
    risk        風控與監控。
    execution   下單執行（實盤 Pionex / 紙上模擬）。
    backtest    事件驅動回測引擎與績效指標。
    orchestrator 協調層：把各層接起來驅動主迴圈。

匯入慣例
--------
專案內部混用兩種匯入寫法：
    from trading_bot.core.interfaces import ...   # 以 trading_bot 之父目錄為 sys.path 根
    from core.interfaces import ...               # 以 trading_bot 目錄本身為 sys.path 根

為了讓兩種寫法都能解析，main.py 與 tests 會同時把「trading_bot 目錄」與
「其父目錄」加入 sys.path。
"""

__all__ = [
    "core",
    "config",
    "data",
    "strategy",
    "risk",
    "execution",
    "backtest",
    "orchestrator",
]
