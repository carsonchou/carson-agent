"""
設定載入器 — 讀取並驗證 config.yaml。

行為：
- 優先讀 config/config.yaml；
- 若不存在則回退讀 config/config.example.yaml 並印出警告；
- 用 pydantic 模型（models.AppConfig）驗證後回傳結構化設定物件；
- 同時支援以環境變數覆寫敏感金鑰（PIONEX_API_KEY / PIONEX_API_SECRET），
  方便在不寫進檔案的情況下注入金鑰。
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Optional, Union

try:
    import yaml
except ImportError as exc:  # pragma: no cover - 缺套件時給清楚錯誤
    raise ImportError(
        "缺少 pyyaml 套件，請先安裝：pip install pyyaml>=6.0"
    ) from exc

from .models import AppConfig

# config 目錄（本檔所在目錄）
_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _CONFIG_DIR / "config.yaml"
_EXAMPLE_CONFIG = _CONFIG_DIR / "config.example.yaml"


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    """決定要讀哪個設定檔。

    - 若呼叫端明確指定 path，就用它（不存在則報錯）。
    - 否則優先用 config.yaml；不存在則回退 config.example.yaml 並警告。
    """
    if path is not None:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的設定檔不存在：{p}")
        return p

    if _DEFAULT_CONFIG.exists():
        return _DEFAULT_CONFIG

    if _EXAMPLE_CONFIG.exists():
        warnings.warn(
            f"找不到 {_DEFAULT_CONFIG.name}，回退使用範本 {_EXAMPLE_CONFIG.name}。"
            "請複製成 config.yaml 並填入你的金鑰後再實盤使用。",
            stacklevel=2,
        )
        return _EXAMPLE_CONFIG

    raise FileNotFoundError(
        f"找不到設定檔：{_DEFAULT_CONFIG} 或 {_EXAMPLE_CONFIG} 皆不存在。"
    )


def _apply_env_overrides(raw: dict) -> dict:
    """以環境變數覆寫敏感欄位（金鑰），避免把金鑰寫進檔案。"""
    pionex = raw.setdefault("pionex", {})
    if os.getenv("PIONEX_API_KEY"):
        pionex["api_key"] = os.environ["PIONEX_API_KEY"]
    if os.getenv("PIONEX_API_SECRET"):
        pionex["api_secret"] = os.environ["PIONEX_API_SECRET"]

    # 允許用環境變數強制開關 dry_run（安全考量：寧可多一道保險）
    env_dry = os.getenv("TRADING_DRY_RUN")
    if env_dry is not None:
        raw["dry_run"] = env_dry.strip().lower() in {"1", "true", "yes", "on"}
    return raw


def load_config(path: Optional[Union[str, Path]] = None) -> AppConfig:
    """載入並驗證設定，回傳 AppConfig。

    參數
    ----
    path: 可選，明確指定設定檔路徑。None 時走預設解析邏輯
          （config.yaml → 回退 config.example.yaml）。

    回傳
    ----
    AppConfig：通過驗證的結構化設定物件。

    例外
    ----
    FileNotFoundError：找不到任何設定檔。
    pydantic.ValidationError：設定欄位不合法（型別錯、未知欄位等）。
    """
    config_path = _resolve_config_path(path)

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"設定檔格式錯誤（最外層必須是 mapping）：{config_path}")

    raw = _apply_env_overrides(raw)

    # pydantic 驗證：欄位型別 / 未知欄位 / 範圍皆在此把關
    config = AppConfig(**raw)

    # 載入時安全提醒：實盤但金鑰未填 → 警告
    if not config.dry_run and not config.pionex.has_credentials:
        warnings.warn(
            "dry_run=false 但 Pionex 金鑰似乎未填（仍為範本佔位值）。"
            "實盤前請確認金鑰正確。",
            stacklevel=2,
        )

    return config
