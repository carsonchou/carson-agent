"""設定層 —— 密鑰 / 路徑 / SKU 目錄 / 訂閱層級 / 免責。

Settings 走依賴注入：app.build_app(settings) 可傳自訂 Settings（測試用 tmp 路徑、
關閉真實記帳/寄信）。Settings.from_env() 讀環境變數組正式設定。

SKU 對照(SKU_CATALOG)與訂閱層級(SUBSCRIPTION_TIERS)對齊
docs/ecommerce/REDESIGN_SPEC_business.md 的商品線（L1 tripwire / L2 core / 旗艦訂閱）。
交付信的商品對照因此是「讀 config」而非 hardcode——新增 SKU 只改這張表。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .events import EventKind

# ── 路徑：記帳/名冊與 finance.json 同置 youtube_channel/STUDIO（revenue_dashboard 讀得到）──
_HERE = Path(__file__).resolve().parent                 # quant-service/webhook
_QS = _HERE.parent                                      # quant-service
_ROOT = _QS.parent                                      # repo root
YT_STUDIO = _ROOT / "youtube_channel" / "STUDIO"
YT_SCRIPTS = _ROOT / "youtube_channel" / "scripts"

DISCLAIMER = ("本內容為程式化的歷史數據彙整與教學，只做「事實介紹」，不是投資建議、"
              "不喊單、不報明牌；歷史數據非未來保證，投資有風險，據此進出盈虧自負。")


# ── SKU 目錄（config 驅動交付；對齊 REDESIGN_SPEC 商品線）───────────────────────
# match：命中商品名的關鍵字（中英大小寫皆比對）；kind：one_time / subscription；
# dl_env：下載連結環境變數名（未設 → 交付信帶 placeholder，不寄假連結）。
SKU_CATALOG: list[dict] = [
    {"sku_id": "T1_dca_tracker",     "kind": "one_time",
     "match": ["定投", "定期定額", "dca tracker", "dca"], "dl_env": "ECOMMERCE_DL_T1"},
    {"sku_id": "T2_single_checkup",  "kind": "one_time",
     "match": ["單檔體檢", "單檔", "single-stock health", "single stock health"],
     "dl_env": "ECOMMERCE_DL_T2"},
    {"sku_id": "C1_fullmarket_pack", "kind": "one_time",
     "match": ["全市場回測", "回測數據包", "backtest pack", "full-market backtest"],
     "dl_env": "ECOMMERCE_DL_C1"},
    {"sku_id": "C2_checkup_bundle",  "kind": "one_time",
     "match": ["體檢合輯", "權值股體檢", "health-check bundle", "blue-chip health"],
     "dl_env": "ECOMMERCE_DL_C2"},
    {"sku_id": "SUB_weekly",         "kind": "subscription",
     "match": ["週報", "全市場週報", "weekly", "訂閱", "subscription"], "dl_env": ""},
]

# 訂閱層級分類：先比幣別、再取最接近的金額（容差 = 絕對 20 或相對 25%）。
# 對齊 REDESIGN_SPEC 定價：基礎 NT$99/US$9、完整 NT$149/US$15、完整年繳 NT$1290/US$129。
SUBSCRIPTION_TIERS: list[dict] = [
    {"tier": "basic",       "TWD": 99,   "USD": 9},
    {"tier": "full",        "TWD": 149,  "USD": 15},
    {"tier": "full_annual", "TWD": 1290, "USD": 129},
]


def resolve_sku(product: str, kind: EventKind) -> dict:
    """商品名 → SKU 目錄項。命中 kind=subscription 的項優先給訂閱事件；
    找不到回一個 unknown 佔位（交付仍走 placeholder，不會漏交付但會標記未知）。"""
    p = (product or "").lower()
    want_sub = kind in (EventKind.SUB_NEW, EventKind.SUB_RENEW, EventKind.SUB_CANCEL)
    for entry in SKU_CATALOG:
        is_sub = entry["kind"] == "subscription"
        if want_sub != is_sub:
            continue
        if any(m.lower() in p for m in entry["match"]):
            return entry
    # 次輪：不分 kind 再撈一次（容錯：訂閱商品名沒帶「週報」等字時仍能對到）
    for entry in SKU_CATALOG:
        if any(m.lower() in p for m in entry["match"]):
            return entry
    return {"sku_id": "unknown", "kind": "subscription" if want_sub else "one_time",
            "match": [], "dl_env": ""}


def classify_tier(amount: float, currency: str) -> str:
    """訂閱金額 → 層級字串。比幣別後取最近金額（容差 abs 20 / rel 25%）；否則 unknown。"""
    cur = (currency or "USD").upper()
    best, best_gap = "unknown", None
    for t in SUBSCRIPTION_TIERS:
        ref = t.get(cur)
        if ref is None:
            continue
        gap = abs(float(amount) - ref)
        if gap <= max(20.0, ref * 0.25) and (best_gap is None or gap < best_gap):
            best, best_gap = t["tier"], gap
    return best


def download_url_for(sku_id: str) -> Optional[str]:
    """查該 SKU 的下載連結（環境變數）。未設 → None（交付信帶 placeholder，不寄假連結）。"""
    for entry in SKU_CATALOG:
        if entry["sku_id"] == sku_id and entry.get("dl_env"):
            v = os.getenv(entry["dl_env"], "").strip()
            return v or None
    return None


@dataclass
class Settings:
    """一份設定 = 一組路徑 + 密鑰 + 注入點。正式走 from_env()，測試可手工組。"""
    # 路徑（記帳簿/顧客簿/訂閱名冊）
    sales_ledger: Path = field(default_factory=lambda: YT_STUDIO / "ecommerce_sales.json")
    customers_book: Path = field(default_factory=lambda: YT_STUDIO / "ecommerce_customers.json")
    subscribers_book: Path = field(default_factory=lambda: YT_STUDIO / "ecommerce_subscribers.json")
    # 密鑰（未設 → 該平台 fail-closed 503）
    gumroad_seller_id: str = ""
    gumroad_ping_token: str = ""
    portaly_secret: str = ""
    lemonsqueezy_secret: str = ""
    whop_secret: str = ""
    # 通知
    ntfy_topic: str = "carsonquant-hc-9k3x7m2q"
    # 注入點（測試把這兩個換成假的，就不會真記帳/真寄信）
    revenue_adder: Optional[Callable] = None   # 預設 None → revenue.py lazy import finance_dept
    email_sender: Optional[Callable] = None    # 預設 None → delivery.py 用 smtplib
    ntfy_poster: Optional[Callable] = None     # 預設 None → delivery.py 用 httpx；測試注入假的不打外網
    dry_run: bool = True                       # 預設不真寄信（延續 placeholder/dry_run 紀律）

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gumroad_seller_id=os.getenv("GUMROAD_SELLER_ID", "").strip(),
            gumroad_ping_token=os.getenv("GUMROAD_PING_TOKEN", "").strip(),
            portaly_secret=os.getenv("PORTALY_WEBHOOK_SECRET", "").strip(),
            lemonsqueezy_secret=os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "").strip(),
            whop_secret=os.getenv("WHOP_WEBHOOK_SECRET", "").strip(),
            ntfy_topic=os.getenv("NTFY_TOPIC", "carsonquant-hc-9k3x7m2q"),
            # 真實發送要 SMTP_USER/PASS 齊備才關 dry_run（缺憑證強制 dry_run，不誤寄）
            dry_run=not (os.getenv("SMTP_USER") and os.getenv("SMTP_PASS")),
        )
