"""名冊層 —— 訂閱者名冊閉環（旗艦訂閱軌的生命線）。

Portaly/Whop/LS 的訂閱成立/續訂/取消/退款事件 → 維護 ecommerce_subscribers.json，
週報寄送名單由 export_active() 從名冊自動導出（給 Phase 2a 週報引擎吃）。
取消/退款正確把訂閱者移出 active，續訂更新到期日與層級。

── 名冊 schema（ecommerce_subscribers.json，dict，email 小寫為 key）──────────────
{
  "<email_lower>": {
    "email":        str,            # 原始大小寫 email
    "name":         str,
    "platform":     str,            # portaly / whop / lemonsqueezy / gumroad
    "tier":         str,            # basic / full / full_annual / unknown
    "status":       str,            # active / cancelled
    "started_at":   iso8601,        # 首次訂閱成立時間
    "renewed_at":   iso8601|null,   # 最近一次續訂/扣款成功時間
    "cancelled_at": iso8601|null,   # 取消/退款移出時間
    "current_period_end": iso8601|null,  # 本期到期日（平台有給才有）
    "last_order_id": str,
    "amount":       float,          # 最近一期金額
    "currency":     str,
    "events": [ {"kind","at","order_id","amount","currency"} ]   # 稽核軌，去重後 append
  }
}
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .events import EventKind
from .ledger import _LOCK, load_json, save_json_atomic

# 導出週報名單時，層級的排序權重（完整版看得到深度層，基礎版只看 ★section）。
TIER_RANK = {"basic": 1, "full": 2, "full_annual": 3, "unknown": 0}


def _now() -> str:
    return datetime.now().isoformat()


def _append_event(entry: dict, ev) -> None:
    """把事件記進稽核軌；同 (kind, order_id) 只記一次（webhook 重送去重）。"""
    log = entry.setdefault("events", [])
    sig = (ev.kind.value, ev.order_id)
    if any((e.get("kind"), e.get("order_id")) == sig for e in log):
        return
    log.append({"kind": ev.kind.value, "at": _now(), "order_id": ev.order_id,
                "amount": ev.amount, "currency": ev.currency})


def apply_event(path: Path, ev) -> dict:
    """把一個訂閱生命週期事件套進名冊，回傳更新後的該筆訂閱者 entry。

    SUB_NEW   → 建/復活為 active，記 started_at、tier、period_end。
    SUB_RENEW → 續訂：更新 renewed_at / tier / period_end / 金額，狀態拉回 active。
    SUB_CANCEL/REFUND → 移出 active（status=cancelled，記 cancelled_at），保留歷史不刪。
    非訂閱事件（一次性 SALE 等）不動名冊，回 {}。
    """
    if not (ev.is_subscription or ev.kind == EventKind.REFUND):
        return {}
    email = (ev.email or "").strip()
    if not email:
        return {}
    key = email.lower()
    with _LOCK:
        book = load_json(path, {})
        if not isinstance(book, dict):
            book = {}
        entry = book.get(key) or {
            "email": email, "name": ev.name, "platform": ev.platform,
            "tier": ev.tier, "status": "cancelled", "started_at": None,
            "renewed_at": None, "cancelled_at": None, "current_period_end": None,
            "last_order_id": "", "amount": ev.amount, "currency": ev.currency,
            "events": [],
        }
        entry["name"] = ev.name or entry.get("name", "")
        entry["platform"] = ev.platform
        entry["last_order_id"] = ev.order_id or entry.get("last_order_id", "")

        if ev.kind == EventKind.SUB_NEW:
            entry["status"] = "active"
            entry["started_at"] = entry.get("started_at") or _now()
            entry["renewed_at"] = _now()
            entry["cancelled_at"] = None
            entry["tier"] = ev.tier or entry.get("tier", "")
            entry["current_period_end"] = ev.period_end
            entry["amount"] = ev.amount
            entry["currency"] = ev.currency
        elif ev.kind == EventKind.SUB_RENEW:
            entry["status"] = "active"
            entry["started_at"] = entry.get("started_at") or _now()
            entry["renewed_at"] = _now()
            entry["cancelled_at"] = None
            if ev.tier:
                entry["tier"] = ev.tier          # 允許升/降級
            entry["current_period_end"] = ev.period_end or entry.get("current_period_end")
            entry["amount"] = ev.amount
            entry["currency"] = ev.currency
        else:  # SUB_CANCEL / REFUND → 移出名單
            entry["status"] = "cancelled"
            entry["cancelled_at"] = _now()

        _append_event(entry, ev)
        book[key] = entry
        save_json_atomic(path, book)
        return entry


def export_active(path: Path, tier: str | None = None) -> list[dict]:
    """導出週報寄送名單（給 Phase 2a 週報引擎吃）：只回 status=active 的訂閱者。

    tier=None 回全部 active；tier="full" 只回完整版及以上（full/full_annual）——
    對應週報 §完整 section 只寄完整版訂閱者的分層寄送。每筆回 {email,name,tier,platform}。

    ── 介面契約（消費端：ecommerce/weekly_report_v2.py 的 load_send_list）───────────
    本函式是名冊寄送名單的**單一事實來源**；weekly_report_v2.load_send_list(tier) 直接
    呼叫本函式(import 不到才走等價本地讀取)。回傳形狀 {email,name,tier,platform} 與
    tier 分層語意(TIER_RANK：basic<full<full_annual)兩端必須一致，改動請同步兩側。
    整合測試：youtube_channel/scripts 之外，quant-service/ecommerce/tests/
    test_integration_send_list.py 驗 export→load 對得上。
    """
    book = load_json(path, {})
    if not isinstance(book, dict):
        return []
    want_rank = TIER_RANK.get(tier, 0) if tier else 0
    out, unknowns = [], []
    for entry in book.values():
        if not isinstance(entry, dict) or entry.get("status") != "active":
            continue
        raw_tier = entry.get("tier", "unknown")
        # 🔴 unknown 保底成 basic:他付了錢、名冊也 active,tier 判不出來是**我們**的
        # 問題(classify_tier 靠金額+幣別猜,而 Portaly 欄位本來就標「暫定待校準」——
        # 金額以分為單位/幣別寫 NTD/首月促銷價/欄位名猜錯 都會落到 unknown)。
        # 舊行為:unknown rank=0 < basic(1) → basic 與 full 兩張名單**都**排除他 →
        # **付 149/月永遠收不到任何一期**,而 HTTP 200/名冊 active//health +1/金流有帳/
        # 開通信全部照常回報成功,零 log。收了錢卻什麼都不給,是最不可接受的一種失敗。
        # 新行為:少給一段 section 的傷害,遠小於一期都收不到 → 保底寄 basic。
        # 但不給 full(不因判不出來就送出完整版),並在下面吵出來讓人去校準。
        eff_rank = TIER_RANK.get(raw_tier, 0) or TIER_RANK["basic"]
        if raw_tier not in TIER_RANK or raw_tier == "unknown":
            unknowns.append(entry.get("email", "?"))
        if tier and eff_rank < want_rank:
            continue
        out.append({
            "email": entry.get("email", ""), "name": entry.get("name", ""),
            "tier": raw_tier, "platform": entry.get("platform", ""),
        })
    if unknowns:
        # 零告警是這個 codebase 反覆中招的病根(HUNT_silent_failures 的結論):
        # fail-safe(對) + 零告警(錯) + 只測有利方向(所以沒人發現)。這裡一定要留痕跡。
        print(f"[subscribers] ⚠️ {len(unknowns)} 位付費 active 訂閱者 tier 判不出來,"
              f"已保底寄基礎版(不含完整版 section)。請校準 classify_tier 並手動改名冊 "
              f"tier 欄位:{', '.join(unknowns[:5])}{' …' if len(unknowns) > 5 else ''}")
    out.sort(key=lambda r: (-TIER_RANK.get(r["tier"], 0), r["email"].lower()))
    return out


def count_active(path: Path) -> int:
    book = load_json(path, {})
    if not isinstance(book, dict):
        return 0
    return sum(1 for e in book.values()
               if isinstance(e, dict) and e.get("status") == "active")
