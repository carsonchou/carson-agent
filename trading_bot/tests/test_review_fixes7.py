"""
ntfy 告警接線驗證（main.build_alert）。

涵蓋：
  - 未設 topic → 回 None（告警僅記 log）。
  - 設 topic → 回 callable，推到正確 ntfy URL，等級對應 Priority/Tags。
  - 環境變數 TRADING_NTFY_TOPIC 覆寫 config。
  - poster 失敗時 alert 不拋例外（不可拖垮主迴圈）。

執行：cd trading_bot && python tests/test_review_fixes7.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # trading_bot/

import main as app  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"PASS  {name}")
    else:
        _failed += 1
        print(f"FAIL  {name}")


def _clear_env():
    for k in ("TRADING_NTFY_TOPIC", "TRADING_NTFY_SERVER"):
        os.environ.pop(k, None)


def _cfg(topic="", server="https://ntfy.sh"):
    return SimpleNamespace(notify=SimpleNamespace(ntfy_topic=topic, ntfy_server=server))


def test_no_topic_returns_none():
    _clear_env()
    check("未設 topic → build_alert 回 None", app.build_alert(_cfg("")) is None)


def test_topic_posts_to_ntfy():
    _clear_env()
    captured = {}

    def poster(url, data, headers):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers

    alert = app.build_alert(_cfg("carsonquant-bot-x7"), poster=poster)
    check("設 topic → 回 callable", callable(alert))
    alert("CRITICAL", "持倉背離！")
    check("推到正確 ntfy URL", captured.get("url") == "https://ntfy.sh/carsonquant-bot-x7")
    check("訊息 body 正確(utf-8)", captured.get("data") == "持倉背離！".encode("utf-8"))
    check("CRITICAL → Priority=urgent", captured["headers"].get("Priority") == "urgent")
    check("Title 帶等級", "CRITICAL" in captured["headers"].get("Title", ""))


def test_env_overrides_config():
    _clear_env()
    os.environ["TRADING_NTFY_TOPIC"] = "env-topic"
    captured = {}
    alert = app.build_alert(_cfg("config-topic"),
                            poster=lambda u, d, h: captured.update(url=u))
    alert("INFO", "hi")
    _clear_env()
    check("env TRADING_NTFY_TOPIC 覆寫 config",
          captured.get("url") == "https://ntfy.sh/env-topic")


def test_alert_never_raises():
    _clear_env()

    def boom(url, data, headers):
        raise RuntimeError("ntfy down")

    alert = app.build_alert(_cfg("t"), poster=boom)
    try:
        alert("ERROR", "x")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("poster 失敗時 alert 不拋例外", ok)


if __name__ == "__main__":
    test_no_topic_returns_none()
    test_topic_posts_to_ntfy()
    test_env_overrides_config()
    test_alert_never_raises()
    print(f"\n=== {_passed}/{_passed + _failed} 通過 ===")
    sys.exit(1 if _failed else 0)
