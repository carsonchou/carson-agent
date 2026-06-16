#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telegram_command.py — 【手機遠端指令·Telegram】老闆在 Telegram 對 bot 打字，雲端執行+回覆。

安全：只聽『授權的 chat_id』（design_system 的 telegram_chat_id），其他人傳訊一律忽略
→ 只有老闆本人能遙控，免費又有真正的鎖（比公開 ntfy 安全）。
指令解析重用 ntfy_command.handle（全功能：狀態/補產/上架/門檻/整理/退件/各部門/排程囤片…）。
TOKEN 放雲端環境變數 TELEGRAM_BOT_TOKEN（run.sh source .env）。已處理的 update 用 offset 去重。
用法：python scripts/telegram_command.py   （排程每幾分鐘跑）
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
DESIGN = STUDIO / "design_system.json"
OFFSET = STUDIO / "telegram_offset.json"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass
from ntfy_command import handle, HELP  # 重用全功能指令路由


def _allowed_chat():
    try:
        return str(json.loads(DESIGN.read_text(encoding="utf-8")).get("telegram_chat_id", "")).strip()
    except Exception:
        return ""


def _offset():
    try:
        return int(json.loads(OFFSET.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        return 0


def _save_offset(o):
    try:
        OFFSET.write_text(json.dumps({"offset": o}), encoding="utf-8")
    except Exception:
        pass


def _api(method, **params):
    import requests
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/{method}", params=params, timeout=25)
    return r.json()


def _send(chat_id, text):
    _api("sendMessage", chat_id=chat_id, text=text[:3900])


def main() -> int:
    if not TOKEN:
        print("[info] 未設 TELEGRAM_BOT_TOKEN，Telegram 指令未啟用。"); return 0
    allowed = _allowed_chat()
    off = _offset()
    try:
        res = _api("getUpdates", offset=off, timeout=0, allowed_updates='["message"]')
        updates = res.get("result", [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] getUpdates 失敗：{e}", file=sys.stderr); return 0
    did, last = 0, off
    for u in updates:
        last = max(last, u.get("update_id", 0) + 1)
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if not text or not chat_id:
            continue
        if not allowed:
            # 還沒綁定主人：只回報 chat_id 供綁定，不執行任何動作（安全）
            _send(chat_id, f"尚未綁定主人。你的 chat_id 是：{chat_id}\n（請把這個 id 設給管理者鎖定後才會聽指令）")
            continue
        if chat_id != allowed:
            continue  # 非授權對話，靜默忽略（安全）
        result = handle(text)
        _send(chat_id, result if result else ("沒聽懂這個指令。\n" + HELP))
        if result:
            log_ops("Telegram指令", f"{text[:20]} → 已執行")
            did += 1
    _save_offset(last)
    print(f"[ok] Telegram 指令：處理 {did} 則。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
