"""顧客簿層 —— ecommerce_customers.json（email 為 key，記所有買家：一次性+訂閱）。

與訂閱名冊(subscribers.py)分工：名冊只管「還在訂閱的活躍寄送對象」，顧客簿記「歷來買過
任何東西的人」供行銷/LTV 分析。沿用 v1 紅線：⚠️不寫入 tg_leads.json——電商買家只有 email
無 TG chat_id，混入會造成 tg_magnet 失敗發送並污染轉換率；故此處只記錄，不做 TG 推播。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .ledger import _LOCK, load_json, save_json_atomic


def record(path: Path, ev) -> None:
    """記/更新一位顧客（進帳事件才記）。email→{orders 累計, 最近商品, src, tg_pushed=False}。"""
    email = (ev.email or "").strip().lower()
    if not email:
        return
    with _LOCK:
        book = load_json(path, {})
        if not isinstance(book, dict):
            book = {}
        entry = book.get(email) or {
            "first_seen": datetime.now().isoformat(), "orders": 0, "src": ev.platform}
        entry["orders"] = int(entry.get("orders", 0)) + 1
        entry["last_product"] = ev.product
        entry["last_order_at"] = datetime.now().isoformat()
        entry["name"] = ev.name or entry.get("name", "")
        entry["tg_pushed"] = False           # 無 chat_id，尚未做 TG 推播
        book[email] = entry
        save_json_atomic(path, book)
