"""
協調層 — TradingCoordinator 與各 agent 包裝。

設計理念（多 agent runtime）：
把交易流程拆成五個職責單一的 agent，全部對著 core.interfaces 的抽象寫，
具體實作由建構子注入（依賴反轉），方便單獨測試與替換：

    DataAgent      抓主資料源 K 棒 + 交叉比對源比價（背離則回報暫停）
    StrategyAgent  把 K 棒 DataFrame 餵給 Strategy 產生 Signal
    RiskAgent      用 RiskManager 把 Signal 核可成 Order，並檢查停損停利
    ExecutionAgent 用 Executor 送單（dry_run 時注入 PaperExecutor）
    MonitorAgent   更新並輸出當前持倉/權益等監控資訊

主迴圈（run_once）：
    取資料 → 交叉比對(背離→暫停) → 先檢查停損停利 → 產訊號 → 風控核可 → 執行 → 監控更新

這個檔案不依賴任何具體交易所/策略實作，只依賴 interfaces 抽象，
因此可在其他模組尚未完成時就獨立 import 與測試。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - 缺套件時給清楚錯誤
    raise ImportError(
        "缺少 pandas 套件，請先安裝：pip install pandas>=2.1.0"
    ) from exc

from core.interfaces import (
    Candle,
    DataFeed,
    Executor,
    Order,
    OrderStatus,
    Position,
    RiskManager,
    Signal,
    SignalType,
    Strategy,
)
from risk.position_tracker import PositionTracker

# 簡易日誌：優先用 loguru，缺套件時回退標準 logging，確保可獨立 import
try:  # pragma: no cover - 取決於環境
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("orchestrator")


# ────────────────────────────────────────────────────────────
# 資料交叉比對結果
# ────────────────────────────────────────────────────────────
@dataclass
class CrossCheckResult:
    """主資料源與交叉比對源的比價結果。"""

    primary_price: float
    cross_price: Optional[float]
    divergence_pct: float = 0.0   # 兩源價差百分比
    diverged: bool = False        # 是否超過容忍值（背離 → 暫停交易）
    reason: str = ""


# ────────────────────────────────────────────────────────────
# DataAgent：抓資料 + 交叉比對
# ────────────────────────────────────────────────────────────
class DataAgent:
    """負責取得 K 棒資料，並（若有交叉源）比對最新價是否背離。"""

    def __init__(
        self,
        primary: DataFeed,
        symbol: str,
        interval: str,
        cross_check: Optional[DataFeed] = None,
        divergence_tolerance_pct: float = 0.5,
        cross_symbol: Optional[str] = None,
    ) -> None:
        self.primary = primary
        self.cross_check = cross_check
        self.symbol = symbol
        self.cross_symbol = cross_symbol or symbol
        self.interval = interval
        self.divergence_tolerance_pct = divergence_tolerance_pct

    def fetch_history(self, limit: int) -> pd.DataFrame:
        """取得主資料源歷史 K 棒（含暖機長度）。"""
        return self.primary.get_historical(self.symbol, self.interval, limit)

    def latest_candle(self) -> Candle:
        """取得主資料源最新一根已收盤 K 棒。"""
        return self.primary.get_latest(self.symbol, self.interval)

    def cross_check_price(self, primary_price: float) -> CrossCheckResult:
        """比對交叉源最新價與主源價差。

        若無交叉源，視為不背離（diverged=False）。
        """
        if self.cross_check is None:
            return CrossCheckResult(
                primary_price=primary_price,
                cross_price=None,
                reason="未設定交叉比對源，略過比對",
            )

        try:
            cross_candle = self.cross_check.get_latest(self.cross_symbol, self.interval)
            cross_price = cross_candle.close
        except Exception as exc:  # 交叉源失敗不應中斷交易，但須記錄
            logger.warning(f"交叉比對源取價失敗：{exc!r}，本根略過比對")
            return CrossCheckResult(
                primary_price=primary_price,
                cross_price=None,
                reason=f"交叉源取價失敗：{exc!r}",
            )

        if primary_price == 0:
            divergence_pct = 0.0
        else:
            divergence_pct = abs(primary_price - cross_price) / abs(primary_price) * 100.0

        diverged = divergence_pct > self.divergence_tolerance_pct
        reason = (
            f"主源 {primary_price:.6g} vs 交叉源 {cross_price:.6g}，"
            f"價差 {divergence_pct:.3f}%（容忍 {self.divergence_tolerance_pct:.3f}%）"
        )
        if diverged:
            reason = "背離：" + reason
        return CrossCheckResult(
            primary_price=primary_price,
            cross_price=cross_price,
            divergence_pct=divergence_pct,
            diverged=diverged,
            reason=reason,
        )


# ────────────────────────────────────────────────────────────
# StrategyAgent：產訊號
# ────────────────────────────────────────────────────────────
class StrategyAgent:
    """把 K 棒 DataFrame 餵給策略，產生最新訊號。"""

    def __init__(self, strategy: Strategy) -> None:
        self.strategy = strategy

    @property
    def warmup_bars(self) -> int:
        return self.strategy.warmup_bars()

    def generate(self, df: pd.DataFrame) -> Signal:
        """產生訊號；資料不足時回傳 HOLD 而非報錯。"""
        needed = self.strategy.warmup_bars()
        if df is None or len(df) < needed:
            have = 0 if df is None else len(df)
            return Signal(
                type=SignalType.HOLD,
                symbol=getattr(self.strategy, "name", "?"),
                timestamp=datetime.now(),
                price=float(df["close"].iloc[-1]) if have else 0.0,
                reason=f"暖機不足（需要 {needed} 根，目前 {have} 根）",
            )
        return self.strategy.generate(df)


# ────────────────────────────────────────────────────────────
# RiskAgent：核可下單 + 停損停利
# ────────────────────────────────────────────────────────────
class RiskAgent:
    """用 RiskManager 把訊號轉成核可後的 Order，並檢查停損停利。"""

    def __init__(self, risk_manager: RiskManager) -> None:
        self.risk_manager = risk_manager

    def approve(self, signal: Signal, position: Position, equity: float) -> Optional[Order]:
        """回傳核可後的 Order；風控否決則回 None。"""
        if signal.type == SignalType.HOLD:
            return None
        return self.risk_manager.evaluate(signal, position, equity)

    def check_stops(self, position: Position, candle: Candle) -> Optional[Order]:
        """檢查停損停利，需要平倉時回傳平倉 Order。"""
        if position.size == 0:
            return None
        return self.risk_manager.check_stops(position, candle)


# ────────────────────────────────────────────────────────────
# ExecutionAgent：下單
# ────────────────────────────────────────────────────────────
class ExecutionAgent:
    """用 Executor 送單；dry_run 旗標只影響日誌標記，實際是否模擬由注入的
    Executor 決定（dry_run 時 main.py 會注入 PaperExecutor）。"""

    def __init__(self, executor: Executor, dry_run: bool = True) -> None:
        self.executor = executor
        self.dry_run = dry_run

    def execute(self, order: Order) -> Order:
        tag = "[DRY-RUN]" if self.dry_run else "[LIVE]"
        logger.info(
            f"{tag} 送單 {order.side.value} {order.symbol} qty={order.quantity} "
            f"price={order.price if order.price is not None else 'MKT'}"
        )
        result = self.executor.submit(order)
        logger.info(
            f"{tag} 回報 status={result.status.value} "
            f"filled={result.filled_qty}@{result.avg_fill_price}"
        )
        return result

    def position(self, symbol: str) -> Position:
        return self.executor.get_position(symbol)

    def balance(self, asset: str) -> float:
        return self.executor.get_balance(asset)


# ────────────────────────────────────────────────────────────
# MonitorAgent：監控
# ────────────────────────────────────────────────────────────
@dataclass
class MonitorState:
    """監控快照。"""

    last_update: Optional[datetime] = None
    position: Optional[Position] = None
    equity: float = 0.0
    last_price: float = 0.0
    last_signal: Optional[SignalType] = None
    paused: bool = False
    pause_reason: str = ""
    loop_count: int = 0
    orders_sent: int = 0
    history: list = field(default_factory=list)


class MonitorAgent:
    """收集並輸出 runtime 監控資訊。可注入 sink 函式自訂輸出（預設用 logger）。"""

    def __init__(self, sink: Optional[Callable[[MonitorState], None]] = None) -> None:
        self.state = MonitorState()
        self._sink = sink

    def update(
        self,
        *,
        position: Position,
        equity: float,
        last_price: float,
        last_signal: Optional[SignalType] = None,
        paused: bool = False,
        pause_reason: str = "",
        order_sent: bool = False,
    ) -> None:
        self.state.last_update = datetime.now()
        self.state.position = position
        self.state.equity = equity
        self.state.last_price = last_price
        self.state.last_signal = last_signal
        self.state.paused = paused
        self.state.pause_reason = pause_reason
        self.state.loop_count += 1
        if order_sent:
            self.state.orders_sent += 1

        if self._sink is not None:
            self._sink(self.state)
        else:
            self._default_log()

    def _default_log(self) -> None:
        s = self.state
        pos_desc = "空手"
        if s.position is not None and s.position.size != 0:
            direction = "多" if s.position.size > 0 else "空"
            pos_desc = (
                f"{direction} {abs(s.position.size)}@{s.position.entry_price} "
                f"PnL={s.position.unrealized_pnl:.4f}"
            )
        flag = "  [暫停]" if s.paused else ""
        logger.info(
            f"監控#{s.loop_count}{flag} 價={s.last_price:.6g} 權益={s.equity:.4f} "
            f"持倉={pos_desc} 訊號={s.last_signal.value if s.last_signal else '-'} "
            f"已送單={s.orders_sent}"
        )
        if s.paused and s.pause_reason:
            logger.warning(f"暫停原因：{s.pause_reason}")


# ────────────────────────────────────────────────────────────
# TradingCoordinator：runtime 協調者
# ────────────────────────────────────────────────────────────
class TradingCoordinator:
    """組合各 agent，驅動交易主迴圈。

    參數（皆為 interfaces 抽象 / 設定值，由 main.py 注入具體實作）：
        data_feed: 主資料源（DataFeed）
        strategy:  策略（Strategy）
        risk_manager: 風控（RiskManager）
        executor:  執行（Executor，dry_run 時為 PaperExecutor）
        symbol / interval / base_asset / quote_asset: 交易標的設定
        cross_feed: 可選的交叉比對資料源（DataFeed）
        divergence_tolerance_pct: 背離容忍百分比
        dry_run: 是否為模擬模式（影響日誌標記）
        monitor: 可選自訂 MonitorAgent
        poll_interval_sec: 主迴圈輪詢間隔秒數（量產可改由排程觸發）
    """

    def __init__(
        self,
        *,
        data_feed: DataFeed,
        strategy: Strategy,
        risk_manager: RiskManager,
        executor: Executor,
        symbol: str,
        interval: str,
        base_asset: str = "BTC",
        quote_asset: str = "USDT",
        cross_feed: Optional[DataFeed] = None,
        divergence_tolerance_pct: float = 0.5,
        cross_symbol: Optional[str] = None,
        dry_run: bool = True,
        monitor: Optional[MonitorAgent] = None,
        poll_interval_sec: float = 5.0,
        state_path: Optional[str] = None,
        max_slippage_pct: float = 0.5,
        alert: Optional[Callable[[str, str], None]] = None,
        reconcile_every: int = 20,
        reconcile_tolerance: float = 1e-6,
        max_consecutive_failures: int = 3,
        max_backoff_sec: float = 300.0,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.base_asset = base_asset
        self.quote_asset = quote_asset
        self.dry_run = dry_run
        self.poll_interval_sec = poll_interval_sec
        self.max_slippage_pct = max_slippage_pct

        # 告警出口（level, msg）：未注入時退回 logger。可接 Monitor.alert / ntfy / Telegram。
        self._alert = alert
        # 對帳：每 N 次成功 run_once 對一次「本地 tracker vs 交易所實際持倉」
        self._reconcile_every = max(0, int(reconcile_every))
        self._reconcile_tolerance = float(reconcile_tolerance)
        # 連續失敗退避告警：資料源/網路長掛時不再靜默空轉
        self._max_consecutive_failures = max(1, int(max_consecutive_failures))
        self._max_backoff_sec = float(max_backoff_sec)
        self._consecutive_failures = 0

        # 部位/損益的單一真相來源（修復停損 entry_price=0 與已實現損益沒接線）。
        # 持久化到 .state/，重啟後沿用部位與最近處理的 K 棒，避免重複下單。
        _sp = state_path or str(
            __import__("pathlib").Path(".state") / f"{symbol.replace('/', '_')}_state.json"
        )
        self.tracker = PositionTracker.load(_sp)

        # 組裝各 agent（依賴反轉：全對抽象）
        self.data_agent = DataAgent(
            primary=data_feed,
            symbol=symbol,
            interval=interval,
            cross_check=cross_feed,
            divergence_tolerance_pct=divergence_tolerance_pct,
            cross_symbol=cross_symbol,
        )
        self.strategy_agent = StrategyAgent(strategy)
        # 依資料源明示的 forming 語意對齊策略 drop_forming，消除「策略假設 vs 資料源
        # 實際」不一致造成的訊號延遲/前視偏差（#7）。僅在兩端都支援時才動。
        if hasattr(strategy, "drop_forming") and hasattr(data_feed, "last_is_forming"):
            forming = bool(data_feed.last_is_forming())
            if getattr(strategy, "drop_forming", None) != forming:
                logger.info(
                    f"依資料源 last_is_forming={forming} 對齊策略 drop_forming "
                    f"(原 {getattr(strategy, 'drop_forming', None)})"
                )
                strategy.drop_forming = forming
        self.risk_agent = RiskAgent(risk_manager)
        self.execution_agent = ExecutionAgent(executor, dry_run=dry_run)
        self.monitor_agent = monitor or MonitorAgent()

        self._running = False
        # 暖機 + 緩衝，確保指標計算所需資料足夠
        self._history_limit = max(self.strategy_agent.warmup_bars * 2, 100)
        # 重啟後從持久化狀態還原「最近處理過的 K 棒」，避免把同一根當新單重跑
        self._last_bar_ts: Optional[datetime] = None
        if self.tracker.last_bar_ts:
            try:
                self._last_bar_ts = datetime.fromisoformat(self.tracker.last_bar_ts)
            except Exception:
                self._last_bar_ts = None
        self._stopped_this_bar = False

    # ── classmethod 工廠：直接從 AppConfig 組裝 ──
    @classmethod
    def from_config(
        cls,
        config,
        *,
        data_feed: DataFeed,
        strategy: Strategy,
        risk_manager: RiskManager,
        executor: Executor,
        cross_feed: Optional[DataFeed] = None,
        monitor: Optional[MonitorAgent] = None,
        poll_interval_sec: float = 5.0,
        alert: Optional[Callable[[str, str], None]] = None,
    ) -> "TradingCoordinator":
        """用 config.AppConfig 的欄位組裝 coordinator，省去手動拆欄位。

        alert:（選填）告警出口 fn(level, msg)。出國無人看管時，main 可在此
        傳入一個推 ntfy/Telegram 的函式，對帳背離與連續失敗就會推到手機。
        未傳則退回 logger。
        """
        return cls(
            data_feed=data_feed,
            strategy=strategy,
            risk_manager=risk_manager,
            executor=executor,
            symbol=config.trading.symbol,
            interval=config.trading.interval,
            base_asset=config.trading.base_asset,
            quote_asset=config.trading.quote_asset,
            cross_feed=cross_feed,
            divergence_tolerance_pct=config.data.divergence_tolerance_pct,
            dry_run=config.dry_run,
            monitor=monitor,
            poll_interval_sec=poll_interval_sec,
            alert=alert,
        )

    # ── 主迴圈：單次 tick ──
    def run_once(self) -> MonitorState:
        """執行一次完整流程：

        取資料 → 交叉比對 → 停損停利 → 產訊號 → 風控 → 執行 → 監控更新
        回傳本次的 MonitorState 快照。
        """
        order_sent = False
        last_signal_type: Optional[SignalType] = None

        # 1) 取資料
        df = self.data_agent.fetch_history(self._history_limit)
        latest = self.data_agent.latest_candle()
        last_price = latest.close
        bar_ts = latest.timestamp

        # 2) 交叉比對（背離 → 暫停本根，不交易）
        cc = self.data_agent.cross_check_price(last_price)
        # 部位以追蹤器為「權威來源」（含真實 entry_price，停損才有效）；
        # 權益市值化（現金 + 持倉市值），使回撤保護能納入浮虧
        position = self.tracker.get(self.symbol, mark_price=last_price)
        equity = self._equity_mtm(position, last_price)

        if cc.diverged:
            logger.warning(f"資料背離，暫停本根交易：{cc.reason}")
            self.monitor_agent.update(
                position=position,
                equity=equity,
                last_price=last_price,
                paused=True,
                pause_reason=cc.reason,
            )
            return self.monitor_agent.state

        # 3) 停損停利（優先於新進場訊號）
        stopped = False
        stop_order = self.risk_agent.check_stops(position, latest)
        if stop_order is not None:
            logger.info(f"觸發停損/停利平倉：{stop_order.side.value} {stop_order.quantity}")
            self._prep_order(stop_order, last_price, bar_ts, "STOP")
            executed = self.execution_agent.execute(stop_order)
            order_sent = True
            self._account_fill(executed, last_price)          # 記帳 + 回報已實現損益
            position = self.tracker.get(self.symbol, mark_price=last_price)
            equity = self._equity_mtm(position, last_price)
            stopped = True

        # 4) 產訊號
        signal = self.strategy_agent.generate(df)
        last_signal_type = signal.type

        # 5+6) 風控核可 + 執行（停損當根不再反手開新倉 → 離場冷卻）
        if stopped and signal.type in (SignalType.OPEN_LONG, SignalType.OPEN_SHORT):
            logger.info("本根已觸發停損，跳過新開倉（離場冷卻，避免停損當根立即被反手抵銷）。")
        else:
            approved = self.risk_agent.approve(signal, position, equity)
            if approved is not None:
                self._prep_order(approved, last_price, bar_ts, signal.type.value)
                executed = self.execution_agent.execute(approved)
                order_sent = True
                self._account_fill(executed, last_price)
                position = self.tracker.get(self.symbol, mark_price=last_price)
                equity = self._equity_mtm(position, last_price)
            elif signal.type != SignalType.HOLD:
                logger.info(f"風控否決訊號 {signal.type.value}：{signal.reason}")

        # 持久化「本根已處理」，重啟後不會重跑同一根
        try:
            self.tracker.mark_bar(bar_ts.isoformat())
        except Exception:
            pass

        # 7) 監控更新
        self.monitor_agent.update(
            position=position,
            equity=equity,
            last_price=last_price,
            last_signal=last_signal_type,
            order_sent=order_sent,
        )
        return self.monitor_agent.state

    # ── 下單前處理：帶參考價（供 paper 成交與 live 滑價保護）＋ 冪等 client_order_id ──
    def _prep_order(self, order: Order, ref_price: float, bar_ts, action: str) -> None:
        order.raw = {**(order.raw or {}), "ref_price": ref_price}
        if not order.client_order_id:
            try:
                ts = bar_ts.strftime("%Y%m%d%H%M%S")
            except Exception:
                ts = "na"
            sym = self.symbol.replace("_", "").replace("/", "")
            # 同一根 K 棒 + 同一動作 → 同一 id；重試/當機重啟時交易所端可去重，避免重複下單
            order.client_order_id = f"{sym}-{ts}-{action}"[:32]

    # ── 成交記帳：更新部位追蹤器，平倉/減倉時把已實現損益回報給風控 ──
    def _account_fill(self, executed: Optional[Order], ref_price: float) -> None:
        if executed is None:
            return
        filled = float(executed.filled_qty or 0.0)
        if executed.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) and filled <= 0:
            if executed.status == OrderStatus.REJECTED:
                logger.warning(f"訂單未成交（{executed.status.value}），不記帳：{executed.raw}")
            else:
                logger.warning(
                    f"訂單狀態未確認成交（{executed.status.value}，filled={filled}），暫不記帳，"
                    "請確認交易所實際狀態以免部位失真。"
                )
            return
        qty = filled if filled > 0 else float(executed.quantity or 0.0)
        px = executed.avg_fill_price if (executed.avg_fill_price and executed.avg_fill_price > 0) else ref_price
        realized = self.tracker.record_fill(executed.symbol, executed.side, qty, px)
        if realized:
            rm = getattr(self.risk_agent, "risk_manager", None)
            if rm is not None and hasattr(rm, "register_realized_pnl"):
                rm.register_realized_pnl(realized)
                logger.info(
                    f"已實現損益回報 {realized:+.4f}（當日累計 "
                    f"{getattr(rm, 'daily_realized_pnl', 0.0):+.4f}）"
                )

    def _emit_alert(self, level: str, msg: str) -> None:
        """統一告警出口：有注入 alert 就用（可接 ntfy/Telegram/Monitor），否則記 log。"""
        try:
            if self._alert is not None:
                self._alert(level.upper(), msg)
                return
        except Exception:  # 告警管道失效不可拖垮主迴圈
            logger.exception("alert 出口發送失敗，退回 log")
        lvl = level.upper()
        (logger.error if lvl in ("ERROR", "CRITICAL") else logger.warning)(f"[{lvl}] {msg}")

    def _reconcile(self) -> bool:
        """對帳：本地 tracker 持倉 vs 交易所實際持倉。背離超過容忍值即告警。

        回傳 True=一致 / False=背離（或查詢失敗）。只告警不自動平倉——自動動作
        本身也是風險；無人看管時「推 ntfy 讓 Carson 知道」才是這裡的目的。
        """
        try:
            local = self.tracker.get(self.symbol).size
            actual = self.execution_agent.position(self.symbol).size
        except Exception as exc:  # noqa: BLE001
            self._emit_alert("ERROR", f"對帳查詢失敗（{self.symbol}）：{exc!r}")
            return False
        if abs(local - actual) > self._reconcile_tolerance:
            self._emit_alert(
                "CRITICAL",
                f"持倉背離！本地追蹤={local} vs 交易所實際={actual}"
                f"（{self.symbol}）。請人工核對，避免重複下單或停損失準。",
            )
            return False
        return True

    def _equity_mtm(self, position: Position, last_price: float) -> float:
        """市值化權益 = 計價幣現金餘額 + 持倉市值（size * mark）。

        原本只用 quote 現金餘額，現貨持倉中現金會偏低、且完全看不到浮虧；
        改為市值化後，風控的當日回撤判斷才能納入未實現損益（見
        risk_manager.daily_loss_limit_hit）。空手時等同純現金餘額。
        """
        cash = self.execution_agent.balance(self.quote_asset)
        size = getattr(position, "size", 0.0) or 0.0
        return cash + size * (last_price or 0.0)

    def _is_new_bar(self, candle: Candle) -> bool:
        """以最新 K 棒 timestamp 判斷是否進到新一根（避免同一根重複下單）。"""
        ts = candle.timestamp
        if self._last_bar_ts is None or ts != self._last_bar_ts:
            self._last_bar_ts = ts
            return True
        return False

    # ── 主迴圈：持續運行 ──
    def run(
        self,
        max_iterations: Optional[int] = None,
        max_loops: Optional[int] = None,
    ) -> None:
        """啟動主迴圈。每偵測到一根新 K 棒就跑一次 run_once。

        參數
        ----
        max_iterations: 可選，限制最多執行幾次 run_once（即幾根新 K 棒）；None 為無限。
        max_loops: 可選，限制主迴圈總輪詢次數（含「沒有新 K 棒」的空轉）。
                   主要供測試／避免在資料源不前進時無限空轉；None 為無限。
        """
        self._running = True
        iterations = 0
        loops = 0
        mode = "DRY-RUN（模擬，不真送單）" if self.dry_run else "LIVE（實盤）"
        logger.info(
            f"TradingCoordinator 啟動：{self.symbol} {self.interval} 模式={mode} "
            f"交叉比對={'啟用' if self.data_agent.cross_check else '停用'}"
        )
        # 啟動先對帳一次：本地持久化部位 vs 交易所實際持倉
        self._reconcile()
        try:
            while self._running:
                loops += 1
                sleep_for = self.poll_interval_sec
                try:
                    latest = self.data_agent.latest_candle()
                    if self._is_new_bar(latest):
                        self.run_once()
                        iterations += 1
                        # 週期性對帳（每 N 根新 K 棒）
                        if self._reconcile_every and iterations % self._reconcile_every == 0:
                            self._reconcile()
                    else:
                        logger.debug("尚無新 K 棒，等待中…")
                    self._consecutive_failures = 0   # 成功一輪 → 重置失敗計數
                except Exception as exc:  # 單根錯誤不應使整個 bot 崩潰
                    self._consecutive_failures += 1
                    logger.exception(
                        f"主迴圈本根發生例外（連續第 {self._consecutive_failures} 次），"
                        f"已捕捉並續跑：{exc!r}"
                    )
                    # 指數退避，避免資料源長掛時高速空轉；達門檻即告警（出國無人看管必要）
                    backoff = self.poll_interval_sec * (2 ** min(self._consecutive_failures, 10))
                    sleep_for = min(max(backoff, self.poll_interval_sec), self._max_backoff_sec)
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        self._emit_alert(
                            "ERROR",
                            f"主迴圈連續失敗 {self._consecutive_failures} 次"
                            f"（{self.symbol}），退避 {sleep_for:.0f}s。最近錯誤：{exc!r}",
                        )

                if max_iterations is not None and iterations >= max_iterations:
                    logger.info(f"達到 max_iterations={max_iterations}，停止主迴圈。")
                    break
                if max_loops is not None and loops >= max_loops:
                    logger.info(f"達到 max_loops={max_loops}，停止主迴圈。")
                    break

                self._sleep(sleep_for)
        except KeyboardInterrupt:
            logger.info("收到中斷訊號（Ctrl-C），優雅停止。")
        finally:
            self._running = False
            logger.info("TradingCoordinator 已停止。")

    @staticmethod
    def _sleep(seconds: float) -> None:
        """可被測試 monkeypatch 的睡眠包裝。"""
        if seconds > 0:
            time.sleep(seconds)

    def stop(self) -> None:
        """請求停止主迴圈（下一次迴圈條件檢查時生效）。"""
        self._running = False
