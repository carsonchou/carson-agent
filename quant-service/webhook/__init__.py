"""量化阿森 電商金流 webhook v2（分層重寫）。

v1 的 quant-service/webhook_server.py 把四平台驗簽 / 記帳 / 交付全塞在單檔 599 行。
v2 拆成清楚的分層，每層可獨立單元測試、且每平台事件先正規化成統一內部事件再進業務層：

  verify.py       驗簽層     —— 四平台簽章驗證（fail-closed，密鑰未設→503）
  normalize.py    正規化層   —— 各平台 payload → NormalizedEvent（純函式，不碰密鑰）
  events.py       事件模型   —— NormalizedEvent dataclass + EventKind
  service.py      業務處理層 —— 去重 → 記帳 → 名冊 → 交付 → ntfy（統一入口）
  ledger.py       記帳簿層   —— 銷售/退款簿 + event_key 去重 + 原子寫入
  subscribers.py  名冊層     —— 訂閱者名冊閉環（成立/續訂/取消）+ 週報名單導出
  revenue.py      分幣別記帳 —— 橋接 finance_dept.add_entry（退款走負值沖銷）
  delivery.py     交付層     —— 交付信（config 驅動 SKU 對照、placeholder、dry_run）
  config.py       設定       —— 密鑰 / 路徑 / SKU 目錄 / 訂閱層級 / 免責
  app.py          路由       —— FastAPI，四平台 /sale-ping/* 串起各層

啟動：uvicorn quant-service.webhook.app:app --host 0.0.0.0 --port 8021
（v1 webhook_server.py 的接案 /order、/approve 端點屬另一系統，未動；其電商段由本 package 取代。）
"""
from .app import build_app, app  # noqa: F401
from .config import Settings  # noqa: F401
from .events import NormalizedEvent, EventKind  # noqa: F401
