"""
SMC（Smart Money Concepts，智能資金概念）策略。

核心觀念（全部可由 OHLCV 推導，無需額外資料源）：
- **市場結構（Market Structure）**：以分形擺盪點（swing high/low）描述趨勢骨架。
  - **BOS（Break of Structure，結構突破）**：收盤突破前一個同向擺盪高/低 → 趨勢延續。
  - **CHoCH（Change of Character，性格轉變）**：第一次「逆當前趨勢」的結構突破 → 趨勢翻轉。
- **FVG（Fair Value Gap，公允價值缺口）**：三根 K 的失衡區
  （多頭：low[i] > high[i-2]；空頭：high[i] < low[i-2]），常被視為「智能資金」回補區。
- **訂單塊（Order Block）**：推動結構突破前的最後一根反向 K，回測該區常獲支撐/壓力。

進出場（在單一倉位、訊號驅動引擎下的務實版）：
- 進場：偵測到「順結構方向」的 BOS / 由反轉而來的 CHoCH，發 OPEN_LONG / OPEN_SHORT。
  可選 require_fvg：要求近期存在同向 FVG 才進場（提高訊號品質、減少假突破）。
- 出場：反向 CHoCH（結構翻轉）→ 反向訊號；硬性停損交由引擎/風控（chandelier 式百分比停損）。

避免重繪：只用「已收盤」K 棒；擺盪點需等右側 confirm_bars 根確認後才成立，
generate() 內部丟棄最後一根 forming K，方向一旦確認即固定。
"""
from __future__ import annotations

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError("strategy.smc 需要 pandas 與 numpy，請先安裝。") from exc

from core.interfaces import Signal, SignalType

from .base import BaseStrategy


class SMCStrategy(BaseStrategy):
    """
    SMC 市場結構策略（BOS / CHoCH + 可選 FVG 確認）。

    參數
    ----
    swing_lookback : 分形擺盪點左右各看幾根（越大越宏觀、訊號越少）。預設 3。
    confirm_bars   : 擺盪點右側需確認的根數（=swing_lookback，確保非重繪）。
    require_fvg    : 是否要求同向 FVG 才進場（提高品質、減少假突破）。預設 True。
    fvg_lookback   : 往回找幾根內是否有同向 FVG。預設 10。
    entry_on       : "bos"（任何順勢結構突破都進）或 "choch"（只在趨勢翻轉時進）。預設 "bos"。
    symbol         : 交易標的。
    """

    def __init__(
        self,
        swing_lookback: int = 3,
        require_fvg: bool = True,
        fvg_lookback: int = 10,
        entry_on: str = "bos",
        symbol: str = "",
        drop_forming: bool = True,
    ) -> None:
        if swing_lookback < 1:
            raise ValueError(f"swing_lookback 必須 >= 1，收到 {swing_lookback}")
        if entry_on not in ("bos", "choch"):
            raise ValueError(f"entry_on 必須是 'bos' 或 'choch'，收到 {entry_on!r}")

        self.name = "smc"
        self.swing_lookback = int(swing_lookback)
        self.confirm_bars = int(swing_lookback)
        self.require_fvg = bool(require_fvg)
        self.fvg_lookback = int(fvg_lookback)
        self.entry_on = entry_on
        self.symbol = symbol
        self.drop_forming = drop_forming

    # ── 暖機需求 ──
    def warmup_bars(self) -> int:
        """需足夠 K 棒建立擺盪結構：左右 lookback + FVG 回看 + 緩衝。"""
        return max(30, self.swing_lookback * 6 + self.fvg_lookback + 5)

    # ── 主流程 ──
    def generate(self, df: "pd.DataFrame") -> "Signal":
        symbol = self.symbol or self._infer_symbol(df)

        if df is None or len(df) == 0:
            return Signal(type=SignalType.HOLD, symbol=symbol, timestamp=_now(), price=0.0,
                          reason="無資料")

        closed = self._closed_df(df, drop_last=self.drop_forming)
        if not self._has_enough(closed):
            return self._hold(closed if len(closed) else df, symbol,
                              reason=f"暖機不足（需 {self.warmup_bars()} 根，現有 {len(closed)}）")

        structure = self._analyze_structure(closed)
        event = structure["event"]          # 'bull_bos' / 'bear_bos' / 'bull_choch' / 'bear_choch' / None
        trend = structure["trend"]          # 1 多 / -1 空 / 0 未定
        meta = {
            "trend": trend,
            "event": event,
            "last_swing_high": structure["last_sh"],
            "last_swing_low": structure["last_sl"],
            "has_bull_fvg": structure["has_bull_fvg"],
            "has_bear_fvg": structure["has_bear_fvg"],
        }

        # 事件只在「最後一根已收盤 K」發生時才視為新訊號（避免回放舊事件）
        if event is None:
            return self._hold(closed, symbol,
                              reason=f"無結構事件（趨勢={_trend_str(trend)}）")

        # 進場模式過濾
        is_bull_event = event in ("bull_bos", "bull_choch")
        is_bear_event = event in ("bear_bos", "bear_choch")
        if self.entry_on == "choch":
            is_bull_event = event == "bull_choch"
            is_bear_event = event == "bear_choch"
            if not (is_bull_event or is_bear_event):
                return self._hold(closed, symbol, reason=f"非 CHoCH 事件（{event}）跳過")

        # FVG 同向確認（可選）
        if self.require_fvg:
            if is_bull_event and not structure["has_bull_fvg"]:
                return self._hold(closed, symbol, reason="多頭結構但近期無多頭 FVG，跳過")
            if is_bear_event and not structure["has_bear_fvg"]:
                return self._hold(closed, symbol, reason="空頭結構但近期無空頭 FVG，跳過")

        if is_bull_event:
            return self._signal(closed, SignalType.OPEN_LONG, symbol,
                                reason=f"SMC 多頭 {event}（結構突破做多）", meta=meta)
        if is_bear_event:
            return self._signal(closed, SignalType.OPEN_SHORT, symbol,
                                reason=f"SMC 空頭 {event}（結構突破做空）", meta=meta)

        return self._hold(closed, symbol, reason=f"結構事件 {event} 未轉成訊號")

    # ────────────────────────────────────────────────────────────
    # 市場結構分析
    # ────────────────────────────────────────────────────────────
    def _analyze_structure(self, df: "pd.DataFrame") -> dict:
        """
        以分形擺盪點重建市場結構，回傳最後一根已收盤 K 是否觸發 BOS/CHoCH。

        作法（非重繪）：
        1. 找出所有「已確認」擺盪高/低（右側需 confirm_bars 根確認）。
        2. 依時間掃描收盤價，維護 last_swing_high / last_swing_low 與目前 trend。
        3. 當最後一根收盤 K 突破前一同向擺盪點 → 記錄事件（順勢=BOS、逆勢=CHoCH）。
        """
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        n = len(df)
        L = self.swing_lookback

        # 1) 確認的擺盪點索引（分形：中心點為左右各 L 根的極值）
        is_sh = np.zeros(n, dtype=bool)
        is_sl = np.zeros(n, dtype=bool)
        for i in range(L, n - L):
            window_h = high[i - L:i + L + 1]
            window_l = low[i - L:i + L + 1]
            if high[i] == window_h.max() and (high[i] > high[i - L:i]).all() and (high[i] >= high[i + 1:i + L + 1]).all():
                is_sh[i] = True
            if low[i] == window_l.min() and (low[i] < low[i - L:i]).all() and (low[i] <= low[i + 1:i + L + 1]).all():
                is_sl[i] = True

        # 2) 依序掃描，維護結構狀態
        last_sh = np.nan      # 最近「已確認」擺盪高的價位
        last_sl = np.nan      # 最近「已確認」擺盪低的價位
        trend = 0
        event = None

        # 擺盪點在 index i 要到 i+L 才算「確認」，故在時間 t 只能用 t-L 以前確認的擺盪點
        confirmed_sh_price = np.nan
        confirmed_sl_price = np.nan

        for t in range(n):
            # 把「在 t 時點已確認」的擺盪點納入（中心 index = t-L）
            c = t - L
            if c >= 0:
                if is_sh[c]:
                    confirmed_sh_price = high[c]
                if is_sl[c]:
                    confirmed_sl_price = low[c]

            prev_sh = confirmed_sh_price
            prev_sl = confirmed_sl_price

            ev = None
            # 突破最近確認擺盪高 → 多方結構
            if not np.isnan(prev_sh) and close[t] > prev_sh:
                ev = "bull_choch" if trend < 0 else "bull_bos"
                trend = 1
            # 突破最近確認擺盪低 → 空方結構
            elif not np.isnan(prev_sl) and close[t] < prev_sl:
                ev = "bear_choch" if trend > 0 else "bear_bos"
                trend = -1

            # 只保留「最後一根已收盤 K」上發生的事件作為訊號
            if t == n - 1:
                event = ev
            last_sh = prev_sh
            last_sl = prev_sl

        # 3) FVG 偵測（近 fvg_lookback 根內是否有同向缺口）
        has_bull_fvg = False
        has_bear_fvg = False
        start = max(2, n - self.fvg_lookback)
        for i in range(start, n):
            # 多頭 FVG：第 i 根 low 高於第 i-2 根 high（中間留下未成交缺口）
            if low[i] > high[i - 2]:
                has_bull_fvg = True
            # 空頭 FVG：第 i 根 high 低於第 i-2 根 low
            if high[i] < low[i - 2]:
                has_bear_fvg = True

        return {
            "event": event,
            "trend": trend,
            "last_sh": float(last_sh) if not np.isnan(last_sh) else None,
            "last_sl": float(last_sl) if not np.isnan(last_sl) else None,
            "has_bull_fvg": has_bull_fvg,
            "has_bear_fvg": has_bear_fvg,
        }

    # ── helper ──
    @staticmethod
    def _infer_symbol(df: "pd.DataFrame") -> str:
        if df is not None:
            sym = getattr(df, "attrs", {}).get("symbol")
            if sym:
                return str(sym)
            if "symbol" in getattr(df, "columns", []):
                vals = df["symbol"].dropna()
                if len(vals):
                    return str(vals.iloc[-1])
        return ""


def _trend_str(t: int) -> str:
    return "多" if t > 0 else "空" if t < 0 else "未定"


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
