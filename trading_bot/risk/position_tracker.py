"""
部位追蹤器（PositionTracker）— 風控的「單一真相來源」。

為什麼需要它：
    實盤 LiveExecutor.get_position() 只能查現貨餘額，拿不到「進場均價」
    （entry_price 永遠是 0），導致：
      1) check_stops 因 entry_price<=0 永遠不觸發 → 停損失效。
      2) 沒有人回報已實現損益 → 當日虧損上限恆為 0 → 回撤保護失效。
    本追蹤器在每筆成交時自行記帳（加權進場均價 + 已實現損益），
    成為停損與當日損益的權威來源；並可持久化，重啟後不會把同一根 K 棒
    當新單重跑（搭配 coordinator 的 last_bar_ts 持久化）。

職責單一：只記帳，不下單、不碰交易所、不依賴任何具體交易所實作。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.interfaces import Position, Side


@dataclass
class TrackedPosition:
    symbol: str
    size: float = 0.0          # 正=多, 負=空, 0=空手
    entry_price: float = 0.0   # 加權進場均價


@dataclass
class PositionTracker:
    """以成交回報維護各標的部位與當日已實現損益，可選擇持久化到檔案。"""

    state_path: Optional[Path] = None
    positions: dict = field(default_factory=dict)   # symbol -> TrackedPosition
    realized_pnl_total: float = 0.0
    last_bar_ts: Optional[str] = None               # 最近處理過的 K 棒 timestamp（ISO 字串）

    # ── 成交記帳：回傳本次成交「實現」的損益（平倉/減倉才有，開倉/加倉為 0）──
    def record_fill(self, symbol: str, side, qty: float, price: float) -> float:
        """記錄一筆成交，更新部位並回傳本次已實現損益（獲利為正、虧損為負）。

        side: Side.BUY / Side.SELL（或其字串值）。qty/price 須為正數。
        """
        if qty is None or price is None or qty <= 0 or price <= 0:
            return 0.0
        s = side.value if isinstance(side, Side) else str(side)
        delta = qty if s == Side.BUY.value else -qty

        pos = self.positions.get(symbol) or TrackedPosition(symbol=symbol)
        realized = 0.0
        old_size = pos.size

        if old_size == 0 or (old_size > 0) == (delta > 0):
            # 開倉或同向加倉：重算加權均價，無已實現損益
            new_size = old_size + delta
            if new_size != 0:
                total_cost = pos.entry_price * abs(old_size) + price * abs(delta)
                pos.entry_price = total_cost / abs(new_size)
            pos.size = new_size
        else:
            # 反向：先平掉（部分或全部），多出來的反向開新倉
            closing = min(abs(delta), abs(old_size))
            # 多單平倉獲利 = (賣價-進場價)；空單平倉獲利 = (進場價-買價)
            direction = 1.0 if old_size > 0 else -1.0
            realized = (price - pos.entry_price) * closing * direction
            self.realized_pnl_total += realized

            new_size = old_size + delta
            if abs(new_size) < 1e-12:
                pos.size = 0.0
                pos.entry_price = 0.0
            elif (new_size > 0) != (old_size > 0):
                # 翻倉：剩餘量以本次成交價為新均價
                pos.size = new_size
                pos.entry_price = price
            else:
                # 部分平倉：均價不變，數量減少
                pos.size = new_size

        if abs(pos.size) < 1e-12:
            pos.size = 0.0
            pos.entry_price = 0.0
        self.positions[symbol] = pos
        self._save()
        return realized

    def get(self, symbol: str, mark_price: float = 0.0) -> Position:
        """回傳 core.interfaces.Position（含 entry_price 與未實現損益）。"""
        pos = self.positions.get(symbol)
        if pos is None or pos.size == 0:
            return Position(symbol=symbol, size=0.0, entry_price=0.0, unrealized_pnl=0.0)
        upnl = 0.0
        if mark_price > 0 and pos.entry_price > 0:
            direction = 1.0 if pos.size > 0 else -1.0
            upnl = (mark_price - pos.entry_price) * abs(pos.size) * direction
        return Position(symbol=symbol, size=pos.size, entry_price=pos.entry_price, unrealized_pnl=upnl)

    def mark_bar(self, ts: str) -> None:
        self.last_bar_ts = ts
        self._save()

    # ── 持久化 ──
    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            data = {
                "realized_pnl_total": self.realized_pnl_total,
                "last_bar_ts": self.last_bar_ts,
                "positions": {
                    k: {"size": v.size, "entry_price": v.entry_price}
                    for k, v in self.positions.items()
                },
            }
            Path(self.state_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.state_path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            # 持久化失敗不可中斷交易，但記帳仍在記憶體中有效
            pass

    @classmethod
    def load(cls, state_path) -> "PositionTracker":
        """從檔案載回（重啟用）；檔案不存在或損毀則回傳空追蹤器。"""
        p = Path(state_path)
        t = cls(state_path=p)
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                t.realized_pnl_total = float(d.get("realized_pnl_total", 0.0))
                t.last_bar_ts = d.get("last_bar_ts")
                for k, v in (d.get("positions", {}) or {}).items():
                    t.positions[k] = TrackedPosition(
                        symbol=k, size=float(v.get("size", 0.0)),
                        entry_price=float(v.get("entry_price", 0.0)),
                    )
            except Exception:
                pass
        return t
