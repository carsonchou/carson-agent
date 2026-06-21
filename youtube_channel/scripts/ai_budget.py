#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_budget.py — Anthropic API 省錢守門人。

用法（其他腳本 import）：
    from ai_budget import call_ai, budget_ok

直接執行看今日用量：
    python scripts/ai_budget.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
USAGE_FILE = ROOT / "STUDIO" / "ai_usage.json"
TW = timezone(timedelta(hours=8))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# 每日上限（可在 boss_directives.json 覆蓋）
DEFAULT_LIMITS = {
    "claude-haiku-4-5-20251001": 80,   # 便宜，放寬一點
    "claude-sonnet-4-6":         15,   # 較貴，每天最多 15 次
    "claude-opus-4-8":            3,   # 超貴，幾乎不讓用
}

# 每個 token 的美元成本（per token，非 per million）
COST_PER_TOKEN = {
    "claude-haiku-4-5-20251001":  {"in": 0.80e-6, "out": 4.00e-6},
    "claude-sonnet-4-6":          {"in": 3.00e-6, "out": 15.00e-6},
    "claude-opus-4-8":            {"in": 15.00e-6, "out": 75.00e-6},
}
USD_TO_TWD = 32


def _today() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_limits() -> dict:
    try:
        d = json.loads((ROOT / "STUDIO" / "boss_directives.json").read_text(encoding="utf-8"))
        overrides = d.get("ai_daily_limits", {})
        return {**DEFAULT_LIMITS, **overrides}
    except Exception:
        return DEFAULT_LIMITS


def budget_ok(model: str) -> bool:
    """回傳今天這個 model 是否還有配額。"""
    limits = _get_limits()
    limit = limits.get(model, 10)
    data = _load()
    today = _today()
    used = data.get(today, {}).get(model, {}).get("calls", 0)
    if used >= limit:
        print(f"[budget] {model} 今日已達上限 {limit} 次（已用 {used}），跳過。", file=sys.stderr)
        return False
    return True


def _record(model: str, in_tokens: int, out_tokens: int) -> None:
    data = _load()
    today = _today()
    day = data.setdefault(today, {})
    m = day.setdefault(model, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "est_twd": 0.0})
    m["calls"] += 1
    m["in_tokens"] += in_tokens
    m["out_tokens"] += out_tokens
    cost = COST_PER_TOKEN.get(model, {"in": 3e-6, "out": 15e-6})
    m["est_twd"] = round(
        (m["in_tokens"] * cost["in"] + m["out_tokens"] * cost["out"]) * USD_TO_TWD, 4
    )
    _save(data)


def call_ai(prompt: str, model: str, max_tokens: int = 800, temperature: float = 0) -> str | None:
    """呼叫 Anthropic API，有預算才打；回傳 response text 或 None。"""
    if not API_KEY:
        return None
    if not budget_ok(model):
        return None
    import requests
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        text = body["content"][0]["text"]
        usage = body.get("usage", {})
        _record(model, usage.get("input_tokens", len(prompt) // 4),
                usage.get("output_tokens", len(text) // 4))
        return text
    except Exception as exc:
        print(f"[budget] API 呼叫失敗：{str(exc)[:80]}", file=sys.stderr)
        return None


def report() -> None:
    data = _load()
    if not data:
        print("尚無用量記錄。")
        return
    limits = _get_limits()
    total_twd = 0.0
    for day in sorted(data.keys(), reverse=True)[:7]:
        print(f"\n── {day} ──")
        day_twd = 0.0
        for model, m in data[day].items():
            limit = limits.get(model, "?")
            est = m.get("est_twd", 0)
            day_twd += est
            bar = "█" * m["calls"] + "░" * max(0, (limit if isinstance(limit, int) else 0) - m["calls"])
            print(f"  {model:<35} {m['calls']:>3}/{limit} 次  {m['in_tokens']:>7} in  "
                  f"{m['out_tokens']:>6} out  NT${est:.2f}  [{bar[:20]}]")
        print(f"  小計：NT${day_twd:.2f}")
        total_twd += day_twd
    print(f"\n7 日合計：NT${total_twd:.2f}")


if __name__ == "__main__":
    report()
