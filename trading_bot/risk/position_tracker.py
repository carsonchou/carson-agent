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

記帳精度（#6）：
    內部 size / entry_price / realized 全程以 ``decimal.Decimal`` 運算，
    消除 float 長期重複累加與加權均價重算的累積漂移（停損價與當日損益基準
    都建立在 entry_price 上，漂移會系統性偏移）。輸入 float 以 Decimal(str(x))
    轉成乾淨十進位；對外（get / record_fill 回傳）仍是 float，下游零改動；
    持久化以字串保存以保精度。

職責單一：只記帳，不下單、不碰交易所、不依賴任何具體交易所實作。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from core.interfaces import Position, Side

logger = logging.getLogger("position_tracker")

_ZERO = Decimal("0")
_EPS = Decimal("1e-12")


def _D(x) -> Decimal:
    """把任意數值轉成乾淨的 Decimal（透過 str，避免帶入 float 二進位雜訊）。"""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class TrackedPosition:
    symbol: str
    size: Decimal = _ZERO          # 正=多, 負=空, 0=空手
    entry_price: Decimal = _ZERO   # 加權進場均價


@dataclass
class PositionTracker:
    """以成交回報維護各標的部位與當日已實現損益，可選擇持久化到檔案。"""

    state_path: Optional[Path] = None
    positions: dict = field(default_factory=dict)   # symbol -> TrackedPosition
    realized_pnl_total: Decimal = _ZERO
    last_bar_ts: Optional[str] = None               # 最近處理過的 K 棒 timestamp（ISO 字串）
    # 多 agent / async 同時回報成交時，序列化對 positions 與 realized 的讀寫，
    # 避免 read-modify-write 交錯造成部位漂移、損益重複或漏計。RLock 允許
    # record_fill → _save 巢狀取鎖。compare/repr 排除，不影響 dataclass 等值與序列化。
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    # ── 成交記帳：回傳本次成交「實現」的損益（平倉/減倉才有，開倉/加倉為 0）──
    def record_fill(self, symbol: str, side, qty: float, price: float) -> float:
        """記錄一筆成交，更新部位並回傳本次已實現損益（獲利為正、虧損為負）。

        side: Side.BUY / Side.SELL（或其字串值）。qty/price 須為正數。
        """
        if qty is None or price is None or qty <= 0 or price <= 0:
            # 非法成交不可靜默吞掉：部位可能已在交易所變動，悄悄丟棄會讓
            # 內部 state 與交易所持倉分歧（部位漂移）。記 warning 供告警追蹤。
            logger.warning(
                "record_fill 收到非法成交並略過：symbol=%s side=%s qty=%r price=%r",
                symbol, side, qty, price,
            )
            return 0.0
        with self._lock:
            s = side.value if isinstance(side, Side) else str(side)
            q = _D(qty)
            px = _D(price)
            delta = q if s == Side.BUY.value else -q

            pos = self.positions.get(symbol) or TrackedPosition(symbol=symbol)
            realized = _ZERO
            old_size = pos.size

            if old_size == 0 or (old_size > 0) == (delta > 0):
                # 開倉或同向加倉：重算加權均價，無已實現損益
                new_size = old_size + delta
                if new_size != 0:
                    total_cost = pos.entry_price * abs(old_size) + px * abs(delta)
                    pos.entry_price = total_cost / abs(new_size)
                pos.size = new_size
            else:
                # 反向：先平掉（部分或全部），多出來的反向開新倉
                closing = min(abs(delta), abs(old_size))
                # 多單平倉獲利 = (賣價-進場價)；空單平倉獲利 = (進場價-買價)
                direction = Decimal(1) if old_size > 0 else Decimal(-1)
                realized = (px - pos.entry_price) * closing * direction
                self.realized_pnl_total += realized

                new_size = old_size + delta
                if abs(new_size) < _EPS:
                    pos.size = _ZERO
                    pos.entry_price = _ZERO
                elif (new_size > 0) != (old_size > 0):
                    # 翻倉：剩餘量以本次成交價為新均價
                    pos.size = new_size
                    pos.entry_price = px
                else:
                    # 部分平倉：均價不變，數量減少
                    pos.size = new_size

            if abs(pos.size) < _EPS:
                pos.size = _ZERO
                pos.entry_price = _ZERO
            self.positions[symbol] = pos
            self._save()
            return float(realized)

    def get(self, symbol: str, mark_price: float = 0.0) -> Position:
        """回傳 core.interfaces.Position（含 entry_price 與未實現損益）。對外為 float。"""
        with self._lock:
            pos = self.positions.get(symbol)
            if pos is None or pos.size == 0:
                return Position(symbol=symbol, size=0.0, entry_price=0.0, unrealized_pnl=0.0)
            upnl = _ZERO
            mark = _D(mark_price)
            if mark > 0 and pos.entry_price > 0:
                direction = Decimal(1) if pos.size > 0 else Decimal(-1)
                upnl = (mark - pos.entry_price) * abs(pos.size) * direction
            return Position(
                symbol=symbol, size=float(pos.size),
                entry_price=float(pos.entry_price), unrealized_pnl=float(upnl),
            )

    def mark_bar(self, ts: str) -> None:
        with self._lock:
            self.last_bar_ts = ts
            self._save()

    # ── 持久化（以字串保存 Decimal 精度）──
    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            data = {
                "realized_pnl_total": str(self.realized_pnl_total),
                "last_bar_ts": self.last_bar_ts,
                "positions": {
                    k: {"size": str(v.size), "entry_price": str(v.entry_price)}
                    for k, v in self.positions.items()
                },
            }
            path = Path(self.state_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            # 原子寫入：先寫同目錄 temp 檔再 os.replace 置換，避免寫到一半當機
            # 留下半損毀的 state.json（重啟會把部位當孤兒、停損消失）。
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, path)
        except Exception:
            # 持久化失敗不可中斷交易（記帳仍在記憶體有效），但必須記 error 告警，
            # 不再靜默吞掉——磁碟滿/權限錯會讓重啟後遺失部位與 last_bar_ts。
            logger.error("PositionTracker 持久化失敗：%s", self.state_path, exc_info=True)

    @classmethod
    def load(cls, state_path) -> "PositionTracker":
        """從檔案載回（重啟用）；檔案不存在或損毀則回傳空追蹤器。

        相容舊格式（數字）與新格式（字串），一律經 Decimal(str(...)) 轉乾淨十進位。
        """
        p = Path(state_path)
        t = cls(state_path=p)
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                t.realized_pnl_total = _D(d.get("realized_pnl_total", 0))
                t.last_bar_ts = d.get("last_bar_ts")
                for k, v in (d.get("positions", {}) or {}).items():
                    t.positions[k] = TrackedPosition(
                        symbol=k, size=_D(v.get("size", 0)),
                        entry_price=_D(v.get("entry_price", 0)),
                    )
            except Exception:
                # state 檔損毀：回退空追蹤器以免擋住啟動，但必須大聲記 error。
                # 靜默歸零＝重啟後忘了自己有持倉（持倉變孤兒、停損消失），
                # 比報錯更危險；上層應據此告警並人工核對交易所實際持倉。
                logger.error(
                    "PositionTracker 載入失敗（state 檔可能損毀），回退空追蹤器："
                    "%s — 請人工核對交易所實際持倉！", p, exc_info=True,
                )
        return t
