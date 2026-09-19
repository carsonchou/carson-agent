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

# ── .env 載入 ────────────────────────────────────────────────────────────────
QS_ENV = _QS / ".env"                                   # quant-service/.env（相對本檔定位）


def _load_env(envf: Path = QS_ENV) -> bool:
    """把 quant-service/.env 逐行併進 os.environ；回傳「那個檔在不在」。

    為什麼要有這支（2026-07-16 修）：上線手冊叫 Carson 把密鑰填 `quant-service/.env`，
    但整個 webhook 樹**沒有任何人讀那個檔** → from_env() 六把密鑰全拿空字串 →
    四平台 verify 一律 fail-closed 回 503、dry_run 鎖死永不寄交付信，而且**全程不報錯**
    （Carson 只會看到「沒人買」）。(VERIFY_REPORT_runbook B1)

    定位靠 `Path(__file__)` 不靠 cwd：uvicorn 從 repo root 起、pytest 從 quant-service 起，
    兩種 cwd 都要讀得到同一個檔。

    紀律：`setdefault` = **已存在的環境變數優先**，.env 不覆蓋它——正式部署可用真環境
    變數蓋過檔案值（同 youtube_channel 各腳本 _load_env() 的既有慣例）。
    不引新依賴（python-dotenv 未必裝）：略過空行/`#` 註解，值去成對引號。
    """
    if not envf.exists():
        return False
    for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":   # 去成對引號，不動值內引號
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)
    return True


# import 時就載：from_env() 與 download_url_for() 都在這之後才讀 os.getenv，兩者都吃得到。
_ENV_LOADED = _load_env()

# 啟動摘要要盯的鑰匙（只報有無，絕不報值）
_REPORT_KEYS: list[tuple[str, list[str]]] = [
    ("平台密鑰", ["GUMROAD_SELLER_ID", "GUMROAD_PING_TOKEN", "PORTALY_WEBHOOK_SECRET",
                  "LEMONSQUEEZY_WEBHOOK_SECRET", "WHOP_WEBHOOK_SECRET"]),
    ("交付信 SMTP", ["SMTP_USER", "SMTP_PASS"]),
    ("下載連結", ["ECOMMERCE_DL_T1", "ECOMMERCE_DL_T2", "ECOMMERCE_DL_T3", "ECOMMERCE_DL_T4",
                  "ECOMMERCE_DL_C1", "ECOMMERCE_DL_C2"]),
]


def env_report_lines() -> list[str]:
    """啟動摘要：每把鑰匙 SET / MISSING。**只印有無，永遠不印值**（密鑰不進主控台/log）。

    治「靜默失敗」：Carson 起 webhook 時一眼看得出哪把是空的，不必等平台送了單、
    收到 503、錢掉了才發現。缺哪把會怎樣見 docs/ecommerce/GO_LIVE_RUNBOOK.md §2。
    """
    where = "已載入" if _ENV_LOADED else "不存在 → 只吃現有環境變數"
    lines = [f"[webhook] .env: {QS_ENV} ({where})"]
    for label, keys in _REPORT_KEYS:
        got = "  ".join(f"{k}={'SET' if os.getenv(k, '').strip() else 'MISSING'}" for k in keys)
        lines.append(f"[webhook] {label}: {got}")
    dry = not (os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"))
    lines.append(f"[webhook] dry_run={dry} "
                 + ("(SMTP 未齊 → 交付信不會真寄)" if dry else "(SMTP 齊備 → 交付信會真寄)"))
    return lines


# ── SKU 目錄（config 驅動交付；對齊 REDESIGN_SPEC 商品線）───────────────────────
# match：命中商品名的關鍵字（中英大小寫皆比對）；kind：one_time / subscription；
# dl_env：下載連結環境變數名（未設 → 交付信帶 placeholder，不寄假連結）。
SKU_CATALOG: list[dict] = [
    {"sku_id": "T1_dca_tracker",     "kind": "one_time",
     "match": ["定投", "定期定額", "dca tracker", "dca"], "dl_env": "ECOMMERCE_DL_T1"},
    {"sku_id": "T2_single_checkup",  "kind": "one_time",
     "match": ["單檔體檢", "單檔", "single-stock health", "single stock health"],
     "dl_env": "ECOMMERCE_DL_T2"},
    # T4 必須排在 T3 前面:resolve_sku 是子字串比對,T4 商品名「個股體檢多檔組合(最多50檔)」
    # 也含 T3 的「多檔組合」,排後面會被 T3 先吃掉。
    {"sku_id": "T4_multi_checkup_50", "kind": "one_time",
     "match": ["最多50檔", "50檔", "multi-stock health 50", "up to 50"],
     "dl_env": "ECOMMERCE_DL_T4"},
    {"sku_id": "T3_multi_checkup",   "kind": "one_time",
     "match": ["多檔體檢", "多檔組合", "multi-stock health", "multi stock health"],
     "dl_env": "ECOMMERCE_DL_T3"},
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
#
# 🔴 定價**一律從 ecommerce/config.py 的 SUBSCRIPTION 導出**，本檔不自己養一份。
# 為什麼（2026-07-17 端到端測試抓到）：本檔原本硬寫 basic TWD 99 / full USD 15 /
# annual USD 129，而 Carson 把 basic 降成 49、full USD 改 9、annual 停售之後，
# **兩張表靜默分岔** → 付 49 的基礎版訂閱者 classify_tier 判 unknown
# （|49-99|=50 > 容差 24.75）→ 名冊 tier 全錯。若不是 subscribers.export_active
# 剛好有「unknown 保底寄 basic」的防線接住，**每一個付 49 的人都會一封都收不到**。
# 這與 landing 把價格寫死在 HTML 是同型病：多個事實來源 + 不同步時零告警。
# 導出後，改 ecommerce/config.py 一處，這裡自動跟上；分岔在結構上不可能發生。
def _tiers_from_single_source() -> list[dict]:
    import sys
    _E = str(_QS / "ecommerce")
    if _E not in sys.path:
        sys.path.insert(0, _E)
    import config as _ecom          # quant-service/ecommerce/config.py
    s = _ecom.SUBSCRIPTION
    out = []
    for key, tier in (("basic", "basic"), ("full", "full"), ("annual", "full_annual")):
        t = s.get(key) or {}
        if t.get("enabled") is False:
            continue                # 停售的層級不參與分類（annual 目前暫緩）
        twd = t.get("ntd_month") or t.get("ntd_year")
        usd = t.get("usd_month") or t.get("usd_year")
        if twd or usd:
            out.append({"tier": tier, "TWD": twd, "USD": usd})
    if not out:
        raise RuntimeError("SUBSCRIPTION 導不出任何層級——定價來源壞了，寧可炸也不要靜默判錯 tier")
    return out


SUBSCRIPTION_TIERS: list[dict] = _tiers_from_single_source()


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
