"""
事件驅動回測引擎（BacktestEngine）。

吃一個 Strategy（符合 core.interfaces.Strategy）+ 歷史 K 棒 DataFrame，
逐根 K 棒重播（replay）市場，模擬策略的進出場，計入手續費與停損，
最後回傳 core.interfaces.BacktestResult。

設計重點：
    - 避免未來函數（look-ahead bias）：
      第 i 根收盤後才把「截至 i」的資料餵給策略產生訊號，
      訊號於「下一根（i+1）開盤價」成交，更貼近實盤。
    - 手續費：每次成交（進場 + 出場）都以成交金額 * fee_rate 扣除。
    - 停損：以硬性停損百分比（stop_loss_pct）控管；在每根 K 棒的
      high/low 內判斷是否觸及停損價，觸及則於停損價出場（保守處理）。
    - 倉位模型：單一標的、全倉現貨多單（long-only）為主，
      同時支援做空（OPEN_SHORT/CLOSE_SHORT），方向相反邏輯對稱。

只用一行即可跑完並印出摘要：
    >>> from backtest.engine import BacktestEngine
    >>> result = BacktestEngine(strategy).run(df, print_summary=True)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "backtest.engine 需要 numpy 與 pandas，請先安裝：pip install numpy pandas"
    ) from exc

# 與核心契約對接：BacktestResult / Strategy / Signal / SignalType
try:
    from core.interfaces import (
        BacktestResult,
        Signal,
        SignalType,
        Strategy,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "無法匯入 core.interfaces，請確認從專案根目錄執行，"
        "或將 trading_bot 加入 PYTHONPATH。原始錯誤："
        f"{exc}"
    ) from exc

from . import metrics as _metrics


# ────────────────────────────────────────────────────────────
# 週期 → 每年 K 棒數（年化用）
# ────────────────────────────────────────────────────────────
# Pionex 週期格式（如 "15M"、"1H"、"1D"）對應每年大約有幾根 K 棒。
# 用於 sharpe / calmar 的年化；找不到時退回 365（日線）。
_MINUTES_PER_INTERVAL = {
    "1M": 1, "3M": 3, "5M": 5, "15M": 15, "30M": 30,
    "1H": 60, "2H": 120, "4H": 240, "6H": 360, "8H": 480, "12H": 720,
    "1D": 1440, "1W": 10080,
}
_MINUTES_PER_YEAR = 365 * 24 * 60


def _periods_per_year(interval: str) -> int:
    """由週期字串推算每年 K 棒數，供年化指標使用。"""
    minutes = _MINUTES_PER_INTERVAL.get((interval or "").upper())
    if not minutes:
        return 365
    return max(1, _MINUTES_PER_YEAR // minutes)


# ────────────────────────────────────────────────────────────
# 內部狀態
# ────────────────────────────────────────────────────────────
@dataclass
class _Trade:
    """一筆完整的進出場交易紀錄（內部用）。"""
    symbol: str
    side: str               # "LONG" 或 "SHORT"
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    quantity: float
    fee: float              # 進場+出場總手續費
    pnl: float              # 淨損益（已扣手續費）
    return_pct: float       # 報酬率（相對進場金額）
    reason: str             # 出場原因（signal / stop_loss / end_of_data）


class BacktestEngine:
    """
    事件驅動回測引擎。

    參數：
        strategy        : 任一符合 core.interfaces.Strategy 的策略實例。
        initial_capital : 初始資金（報價資產，如 USDT）。
        fee_rate        : 單邊手續費率（0.0005 = 0.05%）。
        stop_loss_pct   : 硬性停損百分比（2.0 = 2%）；<=0 表示停用。
        slippage_pct    : 成交滑價百分比（單邊），模擬實際成交偏移。
        allow_short     : 是否允許做空訊號（OPEN_SHORT/CLOSE_SHORT）。

    主要方法：
        run(df) -> BacktestResult
    """

    def __init__(
        self,
        strategy: Strategy,
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.0005,
        stop_loss_pct: float = 2.0,
        slippage_pct: float = 0.0,
        allow_short: bool = True,
    ) -> None:
        if strategy is None:
            raise ValueError("strategy 不可為 None")
        if initial_capital <= 0:
            raise ValueError("initial_capital 必須為正數")
        self.strategy = strategy
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.stop_loss_pct = float(stop_loss_pct)
        self.slippage_pct = float(slippage_pct)
        self.allow_short = bool(allow_short)

    # ────────────────────────────────────────────────────────
    # 公開 API
    # ────────────────────────────────────────────────────────
    def run(
        self,
        df: "pd.DataFrame",
        interval: str = "1D",
        print_summary: bool = False,
    ) -> BacktestResult:
        """
        執行回測。

        參數：
            df            : 歷史 K 棒，需含 [open, high, low, close, volume]，
                            index 建議為時間（DatetimeIndex）。
            interval      : K 棒週期字串（如 "15M"），用於年化指標。
            print_summary : True 時於回測後印出績效摘要。

        回傳：
            core.interfaces.BacktestResult
        """
        df = self._validate_df(df)
        warmup = max(1, int(self.strategy.warmup_bars()))
        symbol = self._infer_symbol(df)

        n = len(df)
        # 權益曲線（mark-to-market，逐根以收盤價估值）
        equity_index = []
        equity_values = []
        trades: list[_Trade] = []

        cash = self.initial_capital          # 現金（報價資產）
        position_side = 0                    # 1=多, -1=空, 0=空手
        entry_price = 0.0                    # 進場均價
        quantity = 0.0                       # 持倉數量（基礎資產）
        entry_time: Optional[datetime] = None
        stop_price = 0.0                     # 當前停損價

        # 待執行訊號：第 i 根收盤產生，第 i+1 根開盤成交
        pending_signal: Optional[SignalType] = None

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        timestamps = list(df.index)

        for i in range(n):
            ts = timestamps[i]
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]

            # ── 1) 先處理上一根掛單的開盤成交 ──
            if pending_signal is not None:
                fill_px = self._apply_slippage(o, pending_signal)
                position_side, entry_price, quantity, cash, entry_time, stop_price, closed = (
                    self._execute_signal(
                        pending_signal, symbol, ts, fill_px,
                        position_side, entry_price, quantity, cash,
                        entry_time, trades,
                    )
                )
                pending_signal = None

            # ── 2) 盤中停損檢查（持倉時）──
            if position_side != 0 and self.stop_loss_pct > 0:
                hit, exit_px = self._check_stop(position_side, stop_price, h, l)
                if hit:
                    cash = self._close_position(
                        symbol, ts, exit_px, position_side, entry_price,
                        quantity, cash, entry_time, trades, reason="stop_loss",
                    )
                    position_side, entry_price, quantity, entry_time, stop_price = 0, 0.0, 0.0, None, 0.0

            # ── 3) 收盤後產生新訊號（避免未來函數）──
            #     只把「截至本根（含）」的資料餵給策略。
            if i + 1 >= warmup and i < n - 1:  # 最後一根不再進新單
                window = df.iloc[: i + 1]
                signal = self._safe_generate(window)
                if signal is not None:
                    decided = self._decide(signal.type, position_side)
                    if decided is not None:
                        pending_signal = decided

            # ── 4) 逐根 mark-to-market 估值 ──
            equity = self._mark_to_market(
                cash, position_side, quantity, entry_price, c
            )
            equity_index.append(ts)
            equity_values.append(equity)

        # ── 收盤強制平倉（資料結束時若仍有持倉）──
        if position_side != 0 and n > 0:
            last_ts = timestamps[-1]
            last_close = closes[-1]
            cash = self._close_position(
                symbol, last_ts, last_close, position_side, entry_price,
                quantity, cash, entry_time, trades, reason="end_of_data",
            )
            # 修正最後一點權益為純現金（已平倉）
            equity_values[-1] = cash

        # ── 組裝結果 ──
        equity_curve = pd.Series(equity_values, index=equity_index, dtype=float, name="equity")
        trades_df = self._trades_to_df(trades)
        ppy = _periods_per_year(interval)
        m = _metrics.compute_all(equity_curve, trades_df, periods_per_year=ppy)

        result = BacktestResult(
            equity_curve=equity_curve,
            trades=trades_df,
            sharpe=m["sharpe"],
            calmar=m["calmar"],
            max_drawdown=m["max_drawdown"],
            total_return=m["total_return"],
            win_rate=m["win_rate"],
            profit_factor=m["profit_factor"],
            num_trades=m["num_trades"],
            metrics={
                "initial_capital": self.initial_capital,
                "final_equity": float(equity_values[-1]) if equity_values else self.initial_capital,
                "fee_rate": self.fee_rate,
                "stop_loss_pct": self.stop_loss_pct,
                "slippage_pct": self.slippage_pct,
                "interval": interval,
                "periods_per_year": ppy,
                "strategy": getattr(self.strategy, "name", type(self.strategy).__name__),
            },
        )

        if print_summary:
            self.print_summary(result)
        return result

    # ────────────────────────────────────────────────────────
    # 績效摘要列印
    # ────────────────────────────────────────────────────────
    @staticmethod
    def print_summary(result: BacktestResult) -> None:
        """以純文字印出回測績效摘要（不依賴 rich，缺套件也能跑）。"""
        meta = result.metrics or {}
        pf = result.profit_factor
        pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
        lines = [
            "═" * 48,
            f" 回測績效摘要  策略：{meta.get('strategy', 'N/A')}",
            "═" * 48,
            f" 初始資金      : {meta.get('initial_capital', 0):,.2f}",
            f" 期末權益      : {meta.get('final_equity', 0):,.2f}",
            f" 總報酬率      : {result.total_return * 100:,.2f}%",
            f" 年化夏普      : {result.sharpe:.3f}",
            f" 卡瑪比率      : {result.calmar:.3f}",
            f" 最大回撤      : {result.max_drawdown * 100:,.2f}%",
            f" 勝率          : {result.win_rate * 100:,.2f}%",
            f" 獲利因子      : {pf_str}",
            f" 交易筆數      : {result.num_trades}",
            "═" * 48,
        ]
        print("\n".join(lines))

    # ────────────────────────────────────────────────────────
    # 內部：驗證 / 推斷
    # ────────────────────────────────────────────────────────
    @staticmethod
    def _validate_df(df: "pd.DataFrame") -> "pd.DataFrame":
        """檢查必要欄位並回傳乾淨副本。"""
        if not isinstance(df, pd.DataFrame):
            raise TypeError("df 必須是 pandas.DataFrame")
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"df 缺少必要欄位：{sorted(missing)}")
        if len(df) == 0:
            raise ValueError("df 不可為空")
        out = df.copy()
        # 確保數值型別、去除全 NaN 列
        for col in ("open", "high", "low", "close"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out.dropna(subset=["open", "high", "low", "close"])
        if len(out) == 0:
            raise ValueError("df 清洗後沒有有效 K 棒")
        return out

    @staticmethod
    def _infer_symbol(df: "pd.DataFrame") -> str:
        """嘗試從 DataFrame 推斷標的；找不到回傳 'UNKNOWN'。"""
        if "symbol" in df.columns and len(df) > 0:
            return str(df["symbol"].iloc[0])
        name = getattr(df, "name", None)
        return str(name) if name else "UNKNOWN"

    # ────────────────────────────────────────────────────────
    # 內部：訊號決策
    # ────────────────────────────────────────────────────────
    def _decide(self, sig_type: SignalType, position_side: int) -> Optional[SignalType]:
        """
        把策略訊號轉成「在目前持倉下實際要執行的動作」。
        過濾掉無意義的動作（例如已空手卻要平倉、已持多卻又要開多）。
        """
        if sig_type == SignalType.HOLD:
            return None

        if sig_type == SignalType.OPEN_LONG:
            # 空手才開多；持空時先反手（視為平空再開多，這裡簡化為平空）
            if position_side == 0:
                return SignalType.OPEN_LONG
            if position_side < 0:
                return SignalType.CLOSE_SHORT  # 先平空，下一訊號再開多
            return None  # 已持多

        if sig_type == SignalType.OPEN_SHORT:
            if not self.allow_short:
                # 不允許做空時，視為平多訊號
                return SignalType.CLOSE_LONG if position_side > 0 else None
            if position_side == 0:
                return SignalType.OPEN_SHORT
            if position_side > 0:
                return SignalType.CLOSE_LONG
            return None  # 已持空

        if sig_type == SignalType.CLOSE_LONG:
            return SignalType.CLOSE_LONG if position_side > 0 else None

        if sig_type == SignalType.CLOSE_SHORT:
            return SignalType.CLOSE_SHORT if position_side < 0 else None

        return None

    def _safe_generate(self, window: "pd.DataFrame") -> Optional[Signal]:
        """呼叫策略 generate，吞掉暖機階段可能的例外（回傳 None）。"""
        try:
            return self.strategy.generate(window)
        except Exception:
            # 策略在暖機不足等情況可能丟例外；回測階段忽略並視為 HOLD
            return None

    # ────────────────────────────────────────────────────────
    # 內部：成交與部位管理
    # ────────────────────────────────────────────────────────
    def _apply_slippage(self, price: float, sig_type: SignalType) -> float:
        """依方向加上滑價：買入往上、賣出往下，模擬不利成交。"""
        if self.slippage_pct <= 0:
            return price
        adj = price * self.slippage_pct / 100.0
        if sig_type in (SignalType.OPEN_LONG, SignalType.CLOSE_SHORT):
            return price + adj   # 買進方向，價格略高
        return price - adj       # 賣出方向，價格略低

    def _execute_signal(
        self, sig_type, symbol, ts, fill_px,
        position_side, entry_price, quantity, cash, entry_time, trades,
    ):
        """
        執行一個（已決策過的）訊號的開倉/平倉。
        回傳更新後的部位狀態 tuple。
        """
        closed = False

        if sig_type == SignalType.OPEN_LONG and position_side == 0:
            # 全倉買進：以現金扣手續費後可買到的數量
            qty = self._affordable_qty(cash, fill_px)
            fee = qty * fill_px * self.fee_rate
            cash = cash - qty * fill_px - fee
            position_side, entry_price, quantity, entry_time = 1, fill_px, qty, ts
            stop_price = self._calc_stop(1, fill_px)
            return position_side, entry_price, quantity, cash, entry_time, stop_price, closed

        if sig_type == SignalType.OPEN_SHORT and position_side == 0:
            qty = self._affordable_qty(cash, fill_px)
            fee = qty * fill_px * self.fee_rate
            # 做空：賣出取得現金（簡化模型，保證金視同全額）
            cash = cash + qty * fill_px - fee
            position_side, entry_price, quantity, entry_time = -1, fill_px, qty, ts
            stop_price = self._calc_stop(-1, fill_px)
            return position_side, entry_price, quantity, cash, entry_time, stop_price, closed

        if sig_type == SignalType.CLOSE_LONG and position_side > 0:
            cash = self._close_position(
                symbol, ts, fill_px, position_side, entry_price,
                quantity, cash, entry_time, trades, reason="signal",
            )
            return 0, 0.0, 0.0, cash, None, 0.0, True

        if sig_type == SignalType.CLOSE_SHORT and position_side < 0:
            cash = self._close_position(
                symbol, ts, fill_px, position_side, entry_price,
                quantity, cash, entry_time, trades, reason="signal",
            )
            return 0, 0.0, 0.0, cash, None, 0.0, True

        # 無動作，原樣返回
        stop_price = self._calc_stop(position_side, entry_price) if position_side != 0 else 0.0
        return position_side, entry_price, quantity, cash, entry_time, stop_price, closed

    def _affordable_qty(self, cash: float, price: float) -> float:
        """以全部現金（含手續費）可買到的最大數量。"""
        if price <= 0:
            return 0.0
        # cash = qty*price + qty*price*fee_rate  =>  qty = cash / (price*(1+fee))
        return max(0.0, cash / (price * (1.0 + self.fee_rate)))

    def _calc_stop(self, side: int, entry_price: float) -> float:
        """依方向計算停損價。多單往下、空單往上。"""
        if self.stop_loss_pct <= 0 or entry_price <= 0:
            return 0.0
        delta = entry_price * self.stop_loss_pct / 100.0
        return entry_price - delta if side > 0 else entry_price + delta

    @staticmethod
    def _check_stop(side: int, stop_price: float, high: float, low: float):
        """
        判斷本根 K 棒是否觸發停損。
        多單：最低價跌破停損 → 於停損價出場。
        空單：最高價漲破停損 → 於停損價出場。
        回傳 (是否觸發, 出場價)。
        """
        if stop_price <= 0:
            return False, 0.0
        if side > 0 and low <= stop_price:
            return True, stop_price
        if side < 0 and high >= stop_price:
            return True, stop_price
        return False, 0.0

    def _close_position(
        self, symbol, ts, exit_px, position_side, entry_price,
        quantity, cash, entry_time, trades, reason,
    ) -> float:
        """平掉目前部位，更新現金，並記錄一筆交易。回傳新現金。"""
        exit_fee = quantity * exit_px * self.fee_rate
        entry_notional = quantity * entry_price

        if position_side > 0:
            # 平多：賣出取得現金
            cash = cash + quantity * exit_px - exit_fee
            gross = (exit_px - entry_price) * quantity
            side_str = "LONG"
        else:
            # 平空：買回償還，現金扣除買回金額
            cash = cash - quantity * exit_px - exit_fee
            gross = (entry_price - exit_px) * quantity
            side_str = "SHORT"

        # 進場時的手續費（出場端在這裡計入 exit_fee，進場端重算一次以入帳）
        entry_fee = entry_notional * self.fee_rate
        total_fee = entry_fee + exit_fee
        pnl = gross - total_fee
        return_pct = (pnl / entry_notional) if entry_notional > 0 else 0.0

        trades.append(_Trade(
            symbol=symbol,
            side=side_str,
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=ts,
            exit_price=exit_px,
            quantity=quantity,
            fee=total_fee,
            pnl=pnl,
            return_pct=return_pct,
            reason=reason,
        ))
        return cash

    @staticmethod
    def _mark_to_market(cash, position_side, quantity, entry_price, close_px) -> float:
        """
        逐根估算當前總權益。
            多單：現金 + 持倉市值
            空單：現金 - 回補成本（賣空已先入現金，未實現損益=（進場-現價）*量）
            空手：現金
        """
        if position_side > 0:
            return cash + quantity * close_px
        if position_side < 0:
            # 開空時 cash 已含賣出所得；要回補需花 quantity*close_px
            return cash - quantity * close_px
        return cash

    @staticmethod
    def _trades_to_df(trades: "list[_Trade]") -> "pd.DataFrame":
        """把內部交易紀錄轉成 DataFrame（含 pnl 欄供 metrics 計算）。"""
        cols = [
            "symbol", "side", "entry_time", "entry_price",
            "exit_time", "exit_price", "quantity", "fee",
            "pnl", "return_pct", "reason",
        ]
        if not trades:
            return pd.DataFrame(columns=cols)
        rows = [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_time": t.entry_time,
                "entry_price": t.entry_price,
                "exit_time": t.exit_time,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "fee": t.fee,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
                "reason": t.reason,
            }
            for t in trades
        ]
        return pd.DataFrame(rows, columns=cols)
