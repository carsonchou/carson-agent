"""
SuperTrend 趨勢翻轉策略。

核心邏輯
--------
SuperTrend 軌道 = hl2 ± multiplier * ATR，趨勢方向(1/-1)翻轉即進出場：
  - 空翻多 (direction -1 → 1)：開多。若原本持空則先平空再開多。
  - 多翻空 (direction  1 → -1)：平多並開空。
本檔在「單一倉位狀態機」下，把翻轉對應成單一訊號：
  - 偵測到翻多 → 發 OPEN_LONG（語意：應持多）
  - 偵測到翻空 → 發 OPEN_SHORT（語意：應持空）
平倉（CLOSE_*）由風控/執行層依目前實際持倉與目標方向決定，
策略只負責表達「現在該站在哪一邊」與「剛剛發生翻轉」這件事。

避免重繪
--------
只看「已收盤」K 棒：generate() 內部丟棄最後一根 forming K 棒，
並以倒數兩根『已收盤』方向的變化判定翻轉，方向一旦收盤即固定。
"""
from __future__ import annotations

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "strategy.supertrend 需要 pandas，請先安裝：pip install pandas"
    ) from exc

from core.interfaces import Signal, SignalType

from .base import BaseStrategy
from .indicators import supertrend as supertrend_indicator


class SuperTrendStrategy(BaseStrategy):
    """
    依 SuperTrend 趨勢翻轉產生訊號的策略。

    參數
    ----
    atr_length : ATR 週期（預設 10）
    multiplier : ATR 倍數（預設 3.0）
    symbol     : 交易標的（用於組裝訊號；可於建構或由 df 推得，建議傳入）
    drop_forming : 是否丟棄最後一根未收盤 K 棒以避免重繪（預設 True）
    """

    def __init__(
        self,
        atr_length: int = 10,
        multiplier: float = 3.0,
        symbol: str = "",
        drop_forming: bool = True,
    ) -> None:
        if atr_length < 1:
            raise ValueError(f"atr_length 必須 >= 1，收到 {atr_length}")
        if multiplier <= 0:
            raise ValueError(f"multiplier 必須 > 0，收到 {multiplier}")

        self.name = "supertrend"
        self.atr_length = int(atr_length)
        self.multiplier = float(multiplier)
        self.symbol = symbol
        self.drop_forming = drop_forming

    # ── 暖機需求 ──
    def warmup_bars(self) -> int:
        """
        ATR(Wilder) 需 atr_length 根暖機，再加上：
          - +1 根用於 shift(prev_close)
          - +1 根用於比較『倒數兩根已收盤方向』判定翻轉
          - +1 根用於丟棄 forming K 棒（若啟用）
        取較寬鬆值，確保第一個訊號穩定。
        """
        extra = 3 if self.drop_forming else 2
        return self.atr_length + extra

    # ── 主流程 ──
    def generate(self, df: "pd.DataFrame") -> "Signal":
        """依當前資料產生最新訊號（避免重繪：只用已收盤 K 棒）。"""
        symbol = self.symbol or self._infer_symbol(df)

        if df is None or len(df) == 0:
            # 無資料：回 HOLD（用空殼避免崩潰）
            return Signal(
                type=SignalType.HOLD,
                symbol=symbol,
                timestamp=_now_safe(),
                price=0.0,
                reason="無資料",
            )

        # 1) 去掉最後一根未收盤 K 棒
        closed = self._closed_df(df, drop_last=self.drop_forming)

        # 2) 暖機檢查
        if not self._has_enough(closed) or len(closed) < 2:
            return self._hold(
                closed if len(closed) else df,
                symbol,
                reason=f"暖機不足（需 {self.warmup_bars()} 根，現有 {len(closed)} 根）",
            )

        # 3) 計算 SuperTrend 方向與軌道
        direction, line = supertrend_indicator(
            closed, length=self.atr_length, mult=self.multiplier
        )

        cur_dir = direction.iloc[-1]
        prev_dir = direction.iloc[-2]

        # 方向尚未成形（NaN）→ HOLD
        if pd.isna(cur_dir) or pd.isna(prev_dir):
            return self._hold(closed, symbol, reason="SuperTrend 方向暖機中")

        cur_dir = int(cur_dir)
        prev_dir = int(prev_dir)
        cur_line = float(line.iloc[-1])

        meta = {
            "direction": cur_dir,
            "prev_direction": prev_dir,
            "st_line": cur_line,
            "atr_length": self.atr_length,
            "multiplier": self.multiplier,
        }

        # 4) 翻轉判定
        if prev_dir == -1 and cur_dir == 1:
            # 空翻多 → 開多（執行/風控層會先平掉空單）
            return self._signal(
                closed,
                SignalType.OPEN_LONG,
                symbol,
                reason="SuperTrend 空翻多：開多",
                meta=meta,
            )
        if prev_dir == 1 and cur_dir == -1:
            # 多翻空 → 平多開空
            return self._signal(
                closed,
                SignalType.OPEN_SHORT,
                symbol,
                reason="SuperTrend 多翻空：平多開空",
                meta=meta,
            )

        # 5) 無翻轉：延續，回 HOLD（附帶當前方向供下游參考）
        return self._hold(
            closed,
            symbol,
            reason=f"SuperTrend 趨勢延續（方向={'多' if cur_dir == 1 else '空'}）",
        )

    # ── helper ──
    @staticmethod
    def _infer_symbol(df: "pd.DataFrame") -> str:
        """嘗試從 DataFrame attrs / 欄位推得 symbol，推不到則回空字串。"""
        if df is not None:
            sym = getattr(df, "attrs", {}).get("symbol")
            if sym:
                return str(sym)
            if "symbol" in getattr(df, "columns", []):
                vals = df["symbol"].dropna()
                if len(vals):
                    return str(vals.iloc[-1])
        return ""


def _now_safe():
    """取得目前時間（隔離 import，避免污染模組頂層）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
