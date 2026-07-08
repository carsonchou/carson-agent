#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig_health_check.py — IG 自動發健康哨兵。

每天驗 IG token 是否還活著（graph.instagram.com/me）。只在「狀態從正常變壞」或
「壞→恢復」時推 ntfy 到健康頻道，不洗版、不誤報——只看 token 死活，不會被
正常的『每日上限 ~25/24h』那種發布失敗誤觸（那是預期內的，不該叫人）。

用途＝避免重演 2026-06-27「IG token 默默過期、拖好幾天沒人發現」。
排程建議：每天 8:00 / 21:00 跑。
ntfy topic：環境變數 IG_HEALTH_NTFY，預設健康頻道 carsonquant-hc-9k3x7m2q。
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "STUDIO" / "ig_health_state.json"
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
NTFY_TOPIC = os.environ.get("IG_HEALTH_NTFY", "carsonquant-hc-9k3x7m2q").strip()


def push_ntfy(title: str, body: str, tag: str = "rotating_light") -> bool:
    import requests
    if not NTFY_TOPIC:
        return False
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
                      headers={"Title": title, "Tags": tag}, timeout=20)
        return True
    except Exception:
        return False


def token_ok():
    """回 (True/False/None, info)。None=網路不確定,不誤報。"""
    if not TOKEN:
        return False, "缺 IG_ACCESS_TOKEN"
    import requests
    try:
        r = requests.get("https://graph.instagram.com/me",
                         params={"fields": "id,username", "access_token": TOKEN}, timeout=20)
        d = r.json()
        if "id" in d:
            return True, d.get("username", "")
        return False, str(d.get("error", {}).get("message", d))[:120]
    except Exception as e:  # noqa: BLE001
        return None, f"網路錯誤:{e}"


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown"}


def _save(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ok, info = token_ok()
    if ok is None:
        print(f"[health] 檢查不確定（{info}），略過不動狀態")
        return 0

    st = _load()
    prev = st.get("status", "unknown")
    now = "ok" if ok else "bad"
    st.update({"status": now, "last_check": int(time.time()),
               "token_user": info if ok else "", "last_info": str(info)})
    _save(st)
    print(f"[health] token={'OK(' + str(info) + ')' if ok else 'FAIL(' + str(info) + ')'} → {now}（前次 {prev}）")

    if now == "bad" and prev in ("ok", "unknown"):
        push_ntfy(
            "IG auto-post DOWN",
            "⚠️ IG 自動發出事了：token 失效（" + str(info) + "）。\n"
            "新片/補發會發不出去。\n\n"
            "修法：請 Claude 跑 revive 腳本重抓一把新 IG token 寫回雲端 .env（約 5 分鐘）。",
            tag="rotating_light")
        print("[health] 已推 ntfy 警報")
    elif now == "ok" and prev == "bad":
        push_ntfy("IG auto-post 恢復",
                  f"✅ IG 自動發已恢復（帳號 {info}）。", tag="white_check_mark")
        print("[health] 已推恢復通知")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
