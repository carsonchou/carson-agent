"""記帳簿層 —— ecommerce_sales.json 銷售/退款簿 + event_key 去重 + 原子寫入。

webhook 是 at-least-once：同一筆事件平台可能重送。用 event_key 去重(成交/續訂各自唯一、
退款用專屬 :refund 鍵)，確保重送不會重複記帳、重複沖銷。寫檔走唯一 tmp + os.replace 原子替換
(對齊 studio_common 併發安全慣例)，並用行程內鎖序列化「讀-改-寫」。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save_json_atomic(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _has_key(ledger: list, key: str) -> bool:
    return any(isinstance(r, dict) and r.get("event_key") == key for r in ledger)


def append_sale(path: Path, ev) -> bool:
    """記一筆成交/續訂。回 True=新記錄已寫入、False=重複事件已略過（去重）。"""
    with _LOCK:
        ledger = load_json(path, [])
        if _has_key(ledger, ev.event_key):
            return False
        ledger.append({
            "event_key": ev.event_key, "kind": ev.kind.value, "platform": ev.platform,
            "order_id": ev.order_id, "email": ev.email, "name": ev.name,
            "product": ev.product, "sku_id": ev.sku_id, "tier": ev.tier,
            "amount": ev.amount, "currency": ev.currency,
            "received_at": datetime.now().isoformat(), "delivered": False,
        })
        save_json_atomic(path, ledger)
        return True


def mark_delivered(path: Path, event_key: str) -> None:
    with _LOCK:
        ledger = load_json(path, [])
        for r in ledger:
            if isinstance(r, dict) and r.get("event_key") == event_key:
                r["delivered"] = True
                r["delivered_at"] = datetime.now().isoformat()
        save_json_atomic(path, ledger)


def append_refund(path: Path, ev) -> bool:
    """記一筆退款（負值）。用專屬 event_key+':refund' 去重。回 True=新沖銷、False=重複略過。"""
    refund_key = ev.event_key + ":refund"
    with _LOCK:
        ledger = load_json(path, [])
        if _has_key(ledger, refund_key):
            return False
        ledger.append({
            "event_key": refund_key, "kind": "refund", "platform": ev.platform,
            "order_id": ev.order_id, "email": ev.email,
            "amount": -abs(ev.amount), "currency": ev.currency,
            "type": "refund", "received_at": datetime.now().isoformat(),
        })
        save_json_atomic(path, ledger)
        return True
