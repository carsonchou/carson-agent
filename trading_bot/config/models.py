"""
設定資料模型（pydantic）— 對應 config.yaml 各欄位。

這裡定義結構化、可驗證的設定物件。載入流程（loader.py）會把 YAML
讀進來並驗證成這些模型，讓其他模組用屬性存取而非 dict key，
打錯字會在啟動時就被擋下來。
"""
from __future__ import annotations

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError as exc:  # pragma: no cover - 缺套件時給清楚錯誤
    raise ImportError(
        "缺少 pydantic 套件，請先安裝：pip install pydantic>=2.5.0"
    ) from exc


class PionexConfig(BaseModel):
    """派網 Pionex API 連線設定。"""

    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://api.pionex.com"

    @property
    def has_credentials(self) -> bool:
        """是否填了看起來像真實金鑰的內容（非範本佔位字串）。"""
        placeholder = {"", "YOUR_PIONEX_API_KEY", "YOUR_PIONEX_API_SECRET"}
        return self.api_key not in placeholder and self.api_secret not in placeholder


class TradingConfig(BaseModel):
    """交易標的設定。"""

    symbol: str = "BTC_USDT"
    interval: str = "15M"
    base_asset: str = "BTC"
    quote_asset: str = "USDT"


class StrategyConfig(BaseModel):
    """策略名稱與參數。params 以 dict 傳給具體策略實作。"""

    name: str = "supertrend"
    params: dict = Field(default_factory=dict)


class RiskConfig(BaseModel):
    """風控參數（百分比皆以「%」為單位，例如 2.0 代表 2%）。"""

    position_pct: float = 100.0
    stop_loss_pct: float = 2.0
    max_daily_loss_pct: float = 10.0
    max_position_pct: float = 100.0

    @field_validator("position_pct", "stop_loss_pct", "max_daily_loss_pct", "max_position_pct")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("風控百分比不可為負數")
        return v


class DataConfig(BaseModel):
    """資料來源與交叉比對設定。"""

    primary: str = "pionex"
    cross_check: str = "tradingview"
    divergence_tolerance_pct: float = 0.5

    @field_validator("divergence_tolerance_pct")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("divergence_tolerance_pct 不可為負數")
        return v


class NotifyConfig(BaseModel):
    """通知設定（ntfy / Telegram / Discord webhook 等）。"""

    enabled: bool = False
    webhook_url: str = ""
    # ntfy 推播（出國無人看管時，對帳背離/連續失敗會推到手機）。
    # 留空則告警僅記 log；亦可用環境變數 TRADING_NTFY_TOPIC 覆寫。
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


class AppConfig(BaseModel):
    """整個應用程式的根設定物件。"""

    dry_run: bool = True
    pionex: PionexConfig = Field(default_factory=PionexConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)

    # pydantic v2：禁止未知欄位，打錯字直接報錯
    model_config = {"extra": "forbid"}
