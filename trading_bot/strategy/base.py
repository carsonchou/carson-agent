"""
策略共用基底。

提供策略類別共用的便利方法（暖機檢查、取已收盤 K 棒、組裝訊號…），
讓具體策略（如 SuperTrendStrategy）專注在「翻轉判斷」本身。

繼承自 core.interfaces.Strategy，函式簽章完全遵守合約。
"""
from __future__ import annotations

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError("strategy.base 需要 pandas，請先安裝：pip install pandas") from exc

from core.interfaces import Signal, SignalType, Strategy


class BaseStrategy(Strategy):
    """
    策略基底：封裝重繪防護與訊號組裝。

    子類別至少需要：
      - 設定 self.name
      - 實作 generate(df)
      - 實作 warmup_bars()
    可善用本類別提供的 helper。
    """

    name: str = "base"

    # ── 重繪防護：只用已收盤 K 棒 ──
    def _closed_df(self, df: "pd.DataFrame", drop_last: bool = True) -> "pd.DataFrame":
        """
        回傳「只含已收盤 K 棒」的 DataFrame。

        實務上資料源最後一根常是「未收盤(forming)」K 棒，會隨價格跳動，
        若拿來判斷會造成重繪。預設丟掉最後一根以確保穩定。

        若呼叫端已自行保證 df 全為收盤 K 棒，可傳 drop_last=False。
        """
        if df is None or len(df) == 0:
            return df
        if drop_last and len(df) >= 1:
            return df.iloc[:-1]
        return df

    def _has_enough(self, df: "pd.DataFrame") -> bool:
        """暖機檢查：資料是否足夠產生有效訊號。"""
        return df is not None and len(df) >= self.warmup_bars()

    # ── 訊號工廠 ──
    def _signal(
        self,
        df: "pd.DataFrame",
        sig_type: "SignalType",
        symbol: str,
        *,
        confidence: float = 1.0,
        size_pct: float | None = None,
        reason: str = "",
        meta: dict | None = None,
    ) -> "Signal":
        """以最後一根（已收盤）K 棒為參考，組裝 Signal。"""
        last = df.iloc[-1]
        ts = df.index[-1]
        # index 若非時間型別，退而以 last 內的 timestamp 欄位
        if not hasattr(ts, "to_pydatetime") and "timestamp" in df.columns:
            ts = last["timestamp"]
        price = float(last["close"])
        return Signal(
            type=sig_type,
            symbol=symbol,
            timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            price=price,
            confidence=confidence,
            size_pct=size_pct,
            reason=reason,
            meta=meta or {},
        )

    def _hold(self, df: "pd.DataFrame", symbol: str, reason: str = "") -> "Signal":
        """無動作訊號。"""
        return self._signal(df, SignalType.HOLD, symbol, reason=reason)

    # ── 介面要求（子類別覆寫）──
    def generate(self, df: "pd.DataFrame") -> "Signal":  # pragma: no cover - 抽象
        raise NotImplementedError

    def warmup_bars(self) -> int:  # pragma: no cover - 抽象
        raise NotImplementedError
