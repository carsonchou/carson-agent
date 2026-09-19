"""事件模型層 —— 把四平台各異的 webhook 正規化成統一的內部事件。

正規化層(normalize.py)吐出 NormalizedEvent；業務層(service.py)只認這個型別，
不再碰各平台的欄位差異。EventKind 明確區分「一次性成交 / 訂閱三態 / 退款 / 略過」，
讓訂閱閉環(subscribers.py)與記帳(revenue.py)能對不同 kind 走不同分支。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class EventKind(str, Enum):
    SALE = "sale"              # 一次性商品成交（L1 tripwire / L2 core）
    SUB_NEW = "sub_new"        # 訂閱成立（旗艦週報首次訂閱）
    SUB_RENEW = "sub_renew"    # 訂閱續訂（每期扣款成功）
    SUB_CANCEL = "sub_cancel"  # 訂閱取消/到期失效（移出週報名單，不沖銷收入）
    REFUND = "refund"          # 退款/爭議（負值沖銷 + 移出名單）
    IGNORED = "ignored"        # 與金流/名冊無關的事件（不處理）


# 進帳的事件（要記正值收入 + 走交付/名冊）；SUB_CANCEL/REFUND/IGNORED 不在此列。
POSITIVE_KINDS = frozenset({EventKind.SALE, EventKind.SUB_NEW, EventKind.SUB_RENEW})
# 屬於訂閱生命週期的事件（要動名冊）。
SUBSCRIPTION_KINDS = frozenset(
    {EventKind.SUB_NEW, EventKind.SUB_RENEW, EventKind.SUB_CANCEL}
)


@dataclass
class NormalizedEvent:
    platform: str                       # gumroad / lemonsqueezy / whop / portaly
    kind: EventKind
    event_key: str                      # 去重鍵（平台唯一事件/訂單 id）
    email: str = ""
    name: str = ""
    product: str = ""
    amount: float = 0.0
    currency: str = "USD"
    order_id: str = ""
    sku_id: str = ""                    # 由 config.resolve_sku 填（交付對照用）
    tier: str = ""                      # 訂閱層級（basic/full/full_annual），由 config 填
    period_end: Optional[str] = None    # 訂閱本期到期日（平台有給才填）
    raw_event: str = ""                 # 平台原始 event 名（稽核用）

    @property
    def is_refund(self) -> bool:
        return self.kind == EventKind.REFUND

    @property
    def is_subscription(self) -> bool:
        return self.kind in SUBSCRIPTION_KINDS

    def as_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d
