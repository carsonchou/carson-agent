"""
即時監控面板（Monitor）。

職責：
    - 以 rich 在終端機繪製即時面板：持倉、未實現損益、今日盈虧、最近訊號。
    - 提供 alert(msg) 告警介面：先印出 / 記 log，並預留 webhook 串接點。

設計重點：
    - 純展示 / 通知層，不參與交易決策，可單獨 import 與測試。
    - rich / loguru 為選用相依；缺套件時給清楚錯誤或降級為純文字輸出。
    - 提供 update_*() 系列方法讓交易迴圈餵資料，render() 產生畫面，
      live() 啟動自動刷新（context manager）。

使用方式：
    >>> from trading_bot.risk import Monitor
    >>> mon = Monitor(title="Pionex Bot", dry_run=True)
    >>> mon.update_position(position)
    >>> mon.update_pnl(unrealized=12.3, daily=-4.5)
    >>> mon.record_signal(signal)
    >>> with mon.live():
    ...     ...  # 交易迴圈中持續 update_*，畫面自動刷新
"""
from __future__ import annotations

import logging
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Deque, Optional

# ── rich 為選用相依：缺套件時降級為純文字模式 ──
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - 視執行環境而定
    _RICH_AVAILABLE = False

# ── loguru 為選用相依：缺套件時退回標準 logging ──
try:
    from loguru import logger as _logger

    _LOGURU = True
except ImportError:  # pragma: no cover
    _logger = logging.getLogger("trading_bot.risk.monitor")
    if not _logger.handlers:
        logging.basicConfig(level=logging.INFO)
    _LOGURU = False


class Monitor:
    """終端機即時監控面板 + 告警介面。"""

    def __init__(
        self,
        title: str = "Trading Bot",
        *,
        dry_run: bool = True,
        max_signals: int = 8,
        webhook_sender: Optional[Callable[[str, str], None]] = None,
        refresh_per_second: int = 2,
    ) -> None:
        """
        參數
        ----
        title:
            面板標題。
        dry_run:
            是否為模擬模式（影響面板上的醒目標示）。
        max_signals:
            「最近訊號」保留筆數。
        webhook_sender:
            （選填）告警 webhook 發送函式，簽章為 ``fn(level, message)``。
            預留給 Telegram / Discord 等；未提供時 alert() 僅印出 / 記 log。
        refresh_per_second:
            live() 模式下的畫面刷新頻率。
        """
        self.title = title
        self.dry_run = dry_run
        self.refresh_per_second = refresh_per_second
        self._webhook_sender = webhook_sender

        # ── 即時狀態 ──
        self._position: Optional[Any] = None
        self._unrealized_pnl: float = 0.0
        self._daily_pnl: float = 0.0
        self._equity: float = 0.0
        self._last_price: Optional[float] = None
        self._status_note: str = ""
        self._recent_signals: Deque[Any] = deque(maxlen=max_signals)
        self._recent_alerts: Deque[tuple] = deque(maxlen=max_signals)

        self._console = Console() if _RICH_AVAILABLE else None
        self._live: Optional["Live"] = None

    # ────────────────────────────────────────────────────────────
    # 資料更新接口（交易迴圈呼叫）
    # ────────────────────────────────────────────────────────────
    def update_position(self, position: Any) -> None:
        """更新目前持倉（core.interfaces.Position）。"""
        self._position = position
        if position is not None and getattr(position, "unrealized_pnl", None) is not None:
            self._unrealized_pnl = position.unrealized_pnl

    def update_pnl(
        self,
        unrealized: Optional[float] = None,
        daily: Optional[float] = None,
    ) -> None:
        """更新未實現損益與今日盈虧。"""
        if unrealized is not None:
            self._unrealized_pnl = float(unrealized)
        if daily is not None:
            self._daily_pnl = float(daily)

    def update_equity(self, equity: float, last_price: Optional[float] = None) -> None:
        """更新權益與最新價格。"""
        self._equity = float(equity)
        if last_price is not None:
            self._last_price = float(last_price)

    def set_status(self, note: str) -> None:
        """設定狀態列文字（例如「資料背離，暫停交易」）。"""
        self._status_note = note

    def record_signal(self, signal: Any) -> None:
        """記錄一筆策略訊號到「最近訊號」清單。"""
        self._recent_signals.appendleft(signal)
        if self._live is not None:
            self._safe_refresh()

    # ────────────────────────────────────────────────────────────
    # 告警介面
    # ────────────────────────────────────────────────────────────
    def alert(self, msg: str, level: str = "INFO") -> None:
        """
        發送告警：印出 + 記 log，並嘗試送 webhook（若有設定）。

        參數
        ----
        msg:
            告警內容。
        level:
            INFO / WARNING / ERROR / CRITICAL。
        """
        ts = datetime.now()
        self._recent_alerts.appendleft((ts, level.upper(), msg))

        # 1) log
        self._log(level, msg)

        # 2) 終端印出（rich 時上色，否則純文字）
        prefix = f"[{ts:%H:%M:%S}] [{level.upper()}]"
        if self._console is not None and self._live is None:
            colour = {
                "INFO": "cyan",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold white on red",
            }.get(level.upper(), "white")
            self._console.print(f"[{colour}]{prefix} {msg}[/{colour}]")
        elif self._live is None:
            print(f"{prefix} {msg}")

        # 3) webhook（預留串接點，失敗不影響主流程）
        if self._webhook_sender is not None:
            try:
                self._webhook_sender(level.upper(), msg)
            except Exception as exc:  # pragma: no cover - 外部相依
                self._log("ERROR", f"webhook 發送失敗：{exc}")

        # 4) live 模式即時刷新面板
        if self._live is not None:
            self._safe_refresh()

    def _log(self, level: str, msg: str) -> None:
        """統一的 log 寫入（相容 loguru 與標準 logging）。"""
        lvl = level.upper()
        if _LOGURU:
            _logger.log(lvl if lvl in ("INFO", "WARNING", "ERROR", "CRITICAL") else "INFO", msg)
        else:
            getattr(_logger, lvl.lower(), _logger.info)(msg)

    # ────────────────────────────────────────────────────────────
    # 畫面繪製
    # ────────────────────────────────────────────────────────────
    def render(self) -> Any:
        """產生可供 rich 顯示的版面物件；無 rich 時回傳純文字字串。"""
        if not _RICH_AVAILABLE:
            return self._render_plain()

        layout = Layout()
        layout.split_column(
            Layout(self._panel_header(), size=3, name="header"),
            Layout(name="body"),
            Layout(self._panel_alerts(), size=8, name="alerts"),
        )
        layout["body"].split_row(
            Layout(self._panel_position(), name="position"),
            Layout(self._panel_signals(), name="signals"),
        )
        return layout

    def _panel_header(self) -> "Panel":
        mode = "[bold red]DRY-RUN（模擬）[/bold red]" if self.dry_run else "[bold green]LIVE（實盤）[/bold green]"
        note = f"  |  {self._status_note}" if self._status_note else ""
        body = Text.from_markup(
            f"{mode}   權益: {self._fmt_money(self._equity)}"
            f"   最新價: {self._fmt_num(self._last_price)}{note}"
        )
        return Panel(body, title=self.title, border_style="blue")

    def _panel_position(self) -> "Panel":
        table = Table(expand=True, show_header=True, header_style="bold")
        table.add_column("項目")
        table.add_column("數值", justify="right")

        pos = self._position
        if pos is None or getattr(pos, "size", 0) == 0:
            table.add_row("持倉", "[dim]空手[/dim]")
        else:
            size = getattr(pos, "size", 0.0)
            direction = "[green]多 LONG[/green]" if size > 0 else "[red]空 SHORT[/red]"
            table.add_row("標的", str(getattr(pos, "symbol", "-")))
            table.add_row("方向", direction)
            table.add_row("數量", self._fmt_num(abs(size)))
            table.add_row("進場價", self._fmt_num(getattr(pos, "entry_price", 0.0)))

        table.add_row("未實現損益", self._fmt_pnl(self._unrealized_pnl))
        table.add_row("今日盈虧", self._fmt_pnl(self._daily_pnl))
        return Panel(table, title="持倉 / 損益", border_style="cyan")

    def _panel_signals(self) -> "Panel":
        table = Table(expand=True, show_header=True, header_style="bold")
        table.add_column("時間", no_wrap=True)
        table.add_column("類型")
        table.add_column("價格", justify="right")
        table.add_column("說明", overflow="fold")

        if not self._recent_signals:
            table.add_row("-", "[dim]尚無訊號[/dim]", "-", "-")
        else:
            for sig in self._recent_signals:
                ts = getattr(sig, "timestamp", None)
                ts_str = ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else "-"
                stype = getattr(getattr(sig, "type", None), "value", str(getattr(sig, "type", "-")))
                table.add_row(
                    ts_str,
                    self._colour_signal(stype),
                    self._fmt_num(getattr(sig, "price", None)),
                    str(getattr(sig, "reason", "") or "-"),
                )
        return Panel(table, title="最近訊號", border_style="magenta")

    def _panel_alerts(self) -> "Panel":
        table = Table(expand=True, show_header=False, box=None)
        table.add_column("時間", no_wrap=True)
        table.add_column("等級", no_wrap=True)
        table.add_column("訊息", overflow="fold")
        if not self._recent_alerts:
            table.add_row("-", "-", "[dim]尚無告警[/dim]")
        else:
            for ts, level, msg in self._recent_alerts:
                table.add_row(f"{ts:%H:%M:%S}", self._colour_level(level), msg)
        return Panel(table, title="告警", border_style="yellow")

    # ── 純文字降級模式 ──
    def _render_plain(self) -> str:
        lines = []
        mode = "DRY-RUN（模擬）" if self.dry_run else "LIVE（實盤）"
        lines.append(f"=== {self.title} [{mode}] ===")
        lines.append(
            f"權益: {self._fmt_money(self._equity)}  最新價: {self._fmt_num(self._last_price)}"
        )
        pos = self._position
        if pos is None or getattr(pos, "size", 0) == 0:
            lines.append("持倉: 空手")
        else:
            size = getattr(pos, "size", 0.0)
            d = "多" if size > 0 else "空"
            lines.append(
                f"持倉: {getattr(pos, 'symbol', '-')} {d} "
                f"qty={self._fmt_num(abs(size))} entry={self._fmt_num(getattr(pos, 'entry_price', 0.0))}"
            )
        lines.append(f"未實現損益: {self._fmt_pnl(self._unrealized_pnl)}")
        lines.append(f"今日盈虧: {self._fmt_pnl(self._daily_pnl)}")
        if self._status_note:
            lines.append(f"狀態: {self._status_note}")
        lines.append("-- 最近訊號 --")
        if not self._recent_signals:
            lines.append("  （尚無）")
        for sig in self._recent_signals:
            stype = getattr(getattr(sig, "type", None), "value", str(getattr(sig, "type", "-")))
            lines.append(
                f"  {stype} @ {self._fmt_num(getattr(sig, 'price', None))} "
                f"{getattr(sig, 'reason', '') or ''}"
            )
        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────
    # Live（自動刷新）
    # ────────────────────────────────────────────────────────────
    @contextmanager
    def live(self):
        """
        以 context manager 啟動自動刷新面板。

        無 rich 時降級：進入/離開不啟動 Live，仍可呼叫 print_once() 手動輸出。
        """
        if not _RICH_AVAILABLE:
            # 降級：不啟動 Live，但仍輸出一次目前狀態
            print(self._render_plain())
            yield self
            return

        with Live(
            self.render(),
            console=self._console,
            refresh_per_second=self.refresh_per_second,
            screen=False,
        ) as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def refresh(self) -> None:
        """手動刷新 live 畫面（live 模式外為 no-op）。"""
        self._safe_refresh()

    def _safe_refresh(self) -> None:
        if self._live is not None:
            try:
                self._live.update(self.render())
            except Exception:  # pragma: no cover - 終端相依
                pass

    def print_once(self) -> None:
        """印出一次目前面板（適合非 live 的單次輸出 / log 紀錄）。"""
        if _RICH_AVAILABLE and self._console is not None:
            self._console.print(self.render())
        else:
            print(self._render_plain())

    # ────────────────────────────────────────────────────────────
    # 格式化輔助
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _fmt_num(v: Optional[float]) -> str:
        if v is None:
            return "-"
        try:
            return f"{float(v):,.4f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(v)

    @staticmethod
    def _fmt_money(v: Optional[float]) -> str:
        if v is None:
            return "-"
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def _fmt_pnl(self, v: float) -> str:
        """損益上色：正綠、負紅。"""
        try:
            val = float(v)
        except (TypeError, ValueError):
            return str(v)
        text = f"{val:+,.2f}"
        if not _RICH_AVAILABLE:
            return text
        colour = "green" if val > 0 else ("red" if val < 0 else "white")
        return f"[{colour}]{text}[/{colour}]"

    @staticmethod
    def _colour_signal(stype: str) -> str:
        if not _RICH_AVAILABLE:
            return stype
        mapping = {
            "OPEN_LONG": "[bold green]OPEN_LONG[/bold green]",
            "OPEN_SHORT": "[bold red]OPEN_SHORT[/bold red]",
            "CLOSE_LONG": "[green]CLOSE_LONG[/green]",
            "CLOSE_SHORT": "[red]CLOSE_SHORT[/red]",
            "HOLD": "[dim]HOLD[/dim]",
        }
        return mapping.get(stype, stype)

    @staticmethod
    def _colour_level(level: str) -> str:
        if not _RICH_AVAILABLE:
            return level
        mapping = {
            "INFO": "[cyan]INFO[/cyan]",
            "WARNING": "[yellow]WARNING[/yellow]",
            "ERROR": "[red]ERROR[/red]",
            "CRITICAL": "[bold white on red]CRITICAL[/bold white on red]",
        }
        return mapping.get(level, level)
