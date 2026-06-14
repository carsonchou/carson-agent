"""
執行層（execution）套件。

對外公開：
  - PionexClient   : Pionex 私有 REST API 封裝
  - PionexAPIError : Pionex API 錯誤
  - LiveExecutor   : 實盤執行器
  - PaperExecutor  : 紙上模擬執行器
  - build_executor : 依 config.dry_run 決定執行器的工廠（dry_run=true 時回傳 PaperExecutor）
"""
from execution.executor import (
    LiveExecutor,
    PaperExecutor,
    build_executor,
)
from execution.pionex_client import PionexAPIError, PionexClient

# 備援下單管道（Playwright 網頁 UI）採延遲匯入：缺 playwright 時不影響本套件 import。
try:
    from execution.pionex_playwright_executor import (
        PionexPlaywrightExecutor,
        PionexPlaywrightError,
    )
except Exception:  # pragma: no cover - playwright 未安裝時優雅降級
    PionexPlaywrightExecutor = None  # type: ignore
    PionexPlaywrightError = None  # type: ignore

__all__ = [
    "PionexClient",
    "PionexAPIError",
    "LiveExecutor",
    "PaperExecutor",
    "build_executor",
    "PionexPlaywrightExecutor",
    "PionexPlaywrightError",
]
