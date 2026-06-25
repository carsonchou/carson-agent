"""
進入點 — 組裝各層並啟動交易協調者。

流程：
    1. 解析命令列旗標（--config / --backtest / --max-iterations / --once）
    2. 載入並驗證設定（config.load_config）
    3. 依設定組裝具體實作：
         - DataFeed：主資料源（Pionex）+ 可選交叉源（TradingView）
         - Strategy：依 config.strategy.name 建立
         - RiskManager：依 config.risk 建立
         - Executor：dry_run=True → PaperExecutor（模擬，不真送單）
                     dry_run=False → 實盤 Executor（Pionex）
    4. 一般模式：建立 TradingCoordinator 並 run()
       --backtest 模式：改跑回測引擎

設計重點：
- 對具體實作採「延遲匯入（lazy import）」並包成工廠函式，
  缺套件或缺模組時給清楚的中文錯誤訊息，且不影響本檔被 import。
- 嚴格尊重 dry_run：唯有明確 dry_run=False 才會啟用實盤 Executor。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# 匯入根設定：專案內部混用兩種寫法
#   - `from core.interfaces import ...`（需要 trading_bot 目錄本身在 sys.path）
#   - `from trading_bot.core.interfaces import ...`（需要 trading_bot 之父目錄在 sys.path）
# 因此同時把兩者都加入 sys.path，讓所有模組都能正確解析。
_ROOT = Path(__file__).resolve().parent          # .../trading_bot
_PARENT = _ROOT.parent                            # .../（trading_bot 之父）
for _p in (str(_ROOT), str(_PARENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import AppConfig, load_config  # noqa: E402
from core.interfaces import DataFeed, Executor, RiskManager, Strategy  # noqa: E402

try:  # 日誌：優先 loguru，缺則回退標準 logging
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("main")


# ────────────────────────────────────────────────────────────
# 具體實作工廠（延遲匯入，缺件給清楚錯誤）
# ────────────────────────────────────────────────────────────
def build_data_feed(config: AppConfig) -> DataFeed:
    """建立主資料源（Pionex）。"""
    try:
        from data.pionex_feed import PionexFeed
    except ImportError as exc:
        raise ImportError(
            "無法匯入主資料源 data.pionex_feed.PionexFeed。"
            f"請確認 data 模組已就緒、相依套件已安裝。原始錯誤：{exc!r}"
        ) from exc
    return PionexFeed(base_url=config.pionex.base_url)


def build_cross_feed(config: AppConfig) -> Optional[DataFeed]:
    """建立交叉比對資料源（TradingView）。失敗時回 None（交叉比對為加分而非必要）。"""
    source = (config.data.cross_check or "").strip().lower()
    if not source or source in {"none", "off", "disabled"}:
        return None
    if source in {"tradingview", "tv", "tvdatafeed"}:
        try:
            # 交叉源實作位置可能尚未定案，嘗試常見模組路徑
            try:
                from data.tradingview_feed import TradingViewFeed  # type: ignore
            except ImportError:
                from data.tv_feed import TradingViewFeed  # type: ignore
            return TradingViewFeed()
        except Exception as exc:  # 交叉源失敗不應擋住主流程
            logger.warning(
                f"交叉比對源（TradingView）建立失敗，將停用交叉比對：{exc!r}"
            )
            return None
    logger.warning(f"未知的交叉比對源設定：{source!r}，停用交叉比對。")
    return None


def build_strategy(config: AppConfig) -> Strategy:
    """依設定建立策略。優先用工廠/註冊表，否則嘗試已知策略類別。"""
    name = (config.strategy.name or "").strip().lower()
    params = config.strategy.params or {}

    # 1) 若策略子套件提供統一工廠，優先使用
    try:
        from strategy import create_strategy  # type: ignore

        return create_strategy(name, **params)
    except Exception:
        pass

    # 2) 退而求其次：依名稱對應已知策略類別
    if name in {"supertrend", "super_trend"}:
        try:
            from strategy.supertrend import SuperTrendStrategy  # type: ignore

            return SuperTrendStrategy(**params)
        except ImportError as exc:
            raise ImportError(
                "找不到 SuperTrend 策略實作（strategy.supertrend.SuperTrendStrategy）"
                "且 strategy.create_strategy 不可用。請確認 strategy 模組已就緒。"
                f"原始錯誤：{exc!r}"
            ) from exc

    raise ValueError(
        f"未知策略名稱：{config.strategy.name!r}。"
        "請在 strategy 模組提供對應實作，或調整 config.strategy.name。"
    )


def build_risk_manager(config: AppConfig) -> RiskManager:
    """依風控設定建立 RiskManager。

    實作位置為 risk.risk_manager.BasicRiskManager，其建構子吃一個
    風控設定 dict（risk_config），含 position_pct / stop_loss_pct /
    max_daily_loss_pct / max_position_pct 欄位。
    """
    r = config.risk
    risk_config = {
        "position_pct": r.position_pct,
        "stop_loss_pct": r.stop_loss_pct,
        "max_daily_loss_pct": r.max_daily_loss_pct,
        "max_position_pct": r.max_position_pct,
    }

    try:
        from risk.risk_manager import BasicRiskManager  # type: ignore
    except ImportError:
        try:
            from risk import BasicRiskManager  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "找不到風控實作（risk.risk_manager.BasicRiskManager）。"
                f"請確認 risk 模組已就緒。原始錯誤：{exc!r}"
            ) from exc

    # 風控當日狀態持久化路徑（與 tracker state 同目錄），盤中重啟沿用當日回撤計數
    _risk_state = str(
        Path(".state") / f"{config.trading.symbol.replace('/', '_')}_risk.json"
    )
    return BasicRiskManager(
        risk_config, symbol=config.trading.symbol, state_path=_risk_state
    )


def build_executor(config: AppConfig, data_feed: Optional[DataFeed] = None) -> Executor:
    """建立執行器。

    安全核心：dry_run=True（預設）→ 一律使用 PaperExecutor（紙上模擬），
    絕不會把訂單送到真實交易所。唯有 dry_run 明確為 False 才啟用實盤 Executor。
    """
    # execution 模組提供工廠 build_executor(config)：
    #   dry_run=true  → PaperExecutor（永不觸網）
    #   dry_run=false → LiveExecutor（連線 Pionex，且金鑰未設妥會 raise ValueError）
    # 工廠同時支援 dict / 物件屬性的 config，這裡直接餵 AppConfig。
    try:
        from execution import build_executor as _build_executor  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "找不到 execution.build_executor。請確認 execution 模組已就緒。"
            f"原始錯誤：{exc!r}"
        ) from exc

    if config.dry_run:
        logger.info("dry_run=true → 使用 PaperExecutor（模擬交易，不會真的送單）。")
    else:
        logger.warning("dry_run=false → 啟用實盤 LiveExecutor，訂單將送往 Pionex！")
        if not config.pionex.has_credentials:
            raise RuntimeError(
                "dry_run=false 但 Pionex 金鑰未設定（仍為範本佔位值）。"
                "請於 config.yaml 或環境變數 PIONEX_API_KEY/PIONEX_API_SECRET 填入後再實盤。"
            )

    return _build_executor(config)


# ────────────────────────────────────────────────────────────
# 組裝 + 啟動：即時交易
# ────────────────────────────────────────────────────────────
def build_coordinator(config: AppConfig, poll_interval_sec: float = 5.0):
    """組裝完整的 TradingCoordinator（即時交易）。"""
    from orchestrator import TradingCoordinator

    data_feed = build_data_feed(config)
    cross_feed = build_cross_feed(config)
    strategy = build_strategy(config)
    risk_manager = build_risk_manager(config)
    executor = build_executor(config, data_feed=data_feed)

    coordinator = TradingCoordinator.from_config(
        config,
        data_feed=data_feed,
        strategy=strategy,
        risk_manager=risk_manager,
        executor=executor,
        cross_feed=cross_feed,
        poll_interval_sec=poll_interval_sec,
    )
    return coordinator


def run_live(config: AppConfig, args: argparse.Namespace) -> int:
    """啟動即時交易主迴圈。"""
    coordinator = build_coordinator(config, poll_interval_sec=args.poll_interval)
    if args.once:
        logger.info("--once：只跑一次 run_once 後結束。")
        coordinator.run_once()
        return 0
    coordinator.run(max_iterations=args.max_iterations)
    return 0


# ────────────────────────────────────────────────────────────
# 回測模式
# ────────────────────────────────────────────────────────────
def run_backtest(config: AppConfig, args: argparse.Namespace) -> int:
    """跑回測。

    流程：先用資料源抓歷史 K 棒 DataFrame，再把 DataFrame 餵給回測引擎。
    回測引擎 BacktestEngine(strategy, ...).run(df, interval=..., print_summary=...)
    自帶停損(stop_loss_pct)，這裡把 config.risk.stop_loss_pct 帶入引擎建構子。
    """
    logger.info("=== 回測模式（--backtest）===")
    data_feed = build_data_feed(config)
    strategy = build_strategy(config)

    try:
        from backtest.engine import BacktestEngine  # type: ignore
    except ImportError:
        try:
            from backtest import BacktestEngine  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "找不到回測引擎（backtest.engine.BacktestEngine）。"
                f"請確認 backtest 模組已就緒。原始錯誤：{exc!r}"
            ) from exc

    # 1) 抓歷史 K 棒（回測資料）
    logger.info(
        f"抓取歷史 K 棒：{config.trading.symbol} {config.trading.interval} "
        f"x {args.backtest_bars} 根"
    )
    df = data_feed.get_historical(
        config.trading.symbol, config.trading.interval, args.backtest_bars
    )

    # 2) 建立引擎並回測（停損百分比沿用風控設定）
    engine = BacktestEngine(
        strategy=strategy,
        stop_loss_pct=config.risk.stop_loss_pct,
    )
    result = engine.run(
        df,
        interval=config.trading.interval,
        print_summary=True,
    )

    logger.info("─── 回測結果 ───")
    logger.info(f"總報酬       : {result.total_return:.2%}")
    logger.info(f"Sharpe       : {result.sharpe:.3f}")
    logger.info(f"Calmar       : {result.calmar:.3f}")
    logger.info(f"最大回撤     : {result.max_drawdown:.2%}")
    logger.info(f"勝率         : {result.win_rate:.2%}")
    logger.info(f"獲利因子     : {result.profit_factor:.3f}")
    logger.info(f"交易筆數     : {result.num_trades}")
    return 0


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="Pionex 自動交易機器人 — 多 agent 協調 runtime。",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="設定檔路徑（預設自動找 config/config.yaml，否則回退 config.example.yaml）。",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="改跑回測模式（而非即時交易）。",
    )
    parser.add_argument(
        "--backtest-bars",
        type=int,
        default=1000,
        help="回測使用的歷史 K 棒數（預設 1000）。",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="即時模式最大 tick 次數（測試用，預設無限）。",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="即時模式只跑一次 run_once 後結束。",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="即時模式輪詢間隔秒數（預設 5 秒）。",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)

    # 1) 載入設定
    try:
        config = load_config(args.config)
    except Exception as exc:
        logger.error(f"載入設定失敗：{exc!r}")
        return 2

    logger.info(
        f"設定載入完成：symbol={config.trading.symbol} interval={config.trading.interval} "
        f"strategy={config.strategy.name} dry_run={config.dry_run}"
    )

    # 2) 分派模式
    try:
        if args.backtest:
            return run_backtest(config, args)
        return run_live(config, args)
    except KeyboardInterrupt:
        logger.info("使用者中斷，結束。")
        return 0
    except Exception as exc:
        logger.exception(f"執行失敗：{exc!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
