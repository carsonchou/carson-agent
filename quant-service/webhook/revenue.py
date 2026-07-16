"""分幣別記帳層 —— 橋接 finance_dept.add_entry（schema 單一真相來源）。

一次性商品記 etype="product"、訂閱記 etype="newsletter"（電子報訂閱，revenue_dashboard 分線看得到）。
退款走負值沖銷，讓退款不再把原始收入永久留在報表。幣別原樣傳給 add_entry（分幣別加總，
絕不混加 TWD/USD）。SUB_CANCEL 不記帳（取消≠退款，只停未來扣款）。

依賴注入：settings.revenue_adder 若非 None 就用它（測試傳假函式，不寫真 finance.json）；
否則 lazy import youtube_channel/scripts/finance_dept.add_entry。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import YT_SCRIPTS
from .events import EventKind, POSITIVE_KINDS


def _default_adder():
    if str(YT_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(YT_SCRIPTS))
    import finance_dept  # noqa: E402
    return finance_dept.add_entry


def record(ev, settings, refund: bool = False) -> None:
    """記一筆收入或退款沖銷。只有進帳事件(POSITIVE_KINDS)或 refund=True 才記；
    SUB_CANCEL/IGNORED 不記帳。"""
    if not refund and ev.kind not in POSITIVE_KINDS:
        return
    adder = settings.revenue_adder or _default_adder()
    etype = "newsletter" if ev.is_subscription else "product"
    currency = (ev.currency or "").upper() or "USD"
    signed = -abs(ev.amount) if refund else ev.amount
    tag = "REFUND 退款沖銷 " if refund else ""
    note = (f"{tag}{ev.platform} {currency}{signed:.2f} "
            f"order={ev.order_id} {ev.product}").strip()
    try:
        adder(etype, signed, note=note, platform=ev.platform,
              stream=etype, currency=currency)
    except Exception as e:  # noqa: BLE001
        print(f"[revenue] {'退款沖銷' if refund else '記帳'}失敗 {ev.event_key}: {e}")
