#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_budget.py — Anthropic API 省錢中間層。

省錢邏輯：
  1. 快取（相同 model + prompt hash → 不重複付費）
  2. 用量追蹤（記每次 call 的 token 數 + 估算台幣）
  3. 不限制次數（限制會讓補產停掉）

其他腳本使用方式：
    from ai_budget import call_ai
    text = call_ai(prompt, model, max_tokens=400)

直接執行看本週用量：
    python scripts/ai_budget.py
"""
from __future__ import annotations

import hashlib
import json
import os
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
CACHE_FILE = ROOT / "STUDIO" / "ai_cache.json"
TW = timezone(timedelta(hours=8))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

CACHE_TTL_DAYS = 14  # 快取保留幾天

COST_PER_TOKEN = {
    "claude-haiku-4-5-20251001":  {"in": 0.80e-6, "out": 4.00e-6},
    "claude-sonnet-4-6":          {"in": 3.00e-6, "out": 15.00e-6},
    "claude-opus-4-8":            {"in": 15.00e-6, "out": 75.00e-6},
}
USD_TO_TWD = 32


def _today() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(TW).isoformat(timespec="seconds")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 快取 ─────────────────────────────────────────────────────────────────────

def _cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:20]


def _cache_get(model: str, prompt: str) -> str | None:
    cache = _load_json(CACHE_FILE, {})
    key = _cache_key(model, prompt)
    entry = cache.get(key)
    if not entry:
        return None
    # TTL 檢查
    try:
        saved = datetime.fromisoformat(entry["ts"])
        now = datetime.now(TW)
        if (now - saved).days > CACHE_TTL_DAYS:
            return None
    except Exception:
        return None
    return entry.get("text")


def _cache_set(model: str, prompt: str, text: str) -> None:
    cache = _load_json(CACHE_FILE, {})
    # 清理過期 entry（保持快取精簡）
    cutoff = datetime.now(TW)
    cache = {
        k: v for k, v in cache.items()
        if _days_old(v.get("ts", "")) <= CACHE_TTL_DAYS
    }
    key = _cache_key(model, prompt)
    cache[key] = {"ts": _now_iso(), "model": model, "text": text}
    _save_json(CACHE_FILE, cache)


def _days_old(ts_str: str) -> int:
    try:
        return (datetime.now(TW) - datetime.fromisoformat(ts_str)).days
    except Exception:
        return 9999


# ─── 用量記錄 ──────────────────────────────────────────────────────────────────

def _record(model: str, in_tokens: int, out_tokens: int, cached: bool = False) -> None:
    data = _load_json(USAGE_FILE, {})
    today = _today()
    day = data.setdefault(today, {})
    m = day.setdefault(model, {"calls": 0, "cached": 0, "in_tokens": 0, "out_tokens": 0, "est_twd": 0.0})
    m["calls"] += 1
    if cached:
        m["cached"] += 1
    else:
        m["in_tokens"] += in_tokens
        m["out_tokens"] += out_tokens
        cost = COST_PER_TOKEN.get(model, {"in": 3e-6, "out": 15e-6})
        m["est_twd"] = round(
            (m["in_tokens"] * cost["in"] + m["out_tokens"] * cost["out"]) * USD_TO_TWD, 4
        )
    _save_json(USAGE_FILE, data)


# ─── 主要介面 ──────────────────────────────────────────────────────────────────

def call_ai(prompt: str, model: str, max_tokens: int = 800,
            temperature: float = 0, use_cache: bool = True) -> str | None:
    """呼叫 Anthropic API，自動快取 + 記帳。回傳 response text 或 None。

    use_cache=False 強制不走快取（produce_batch 產腳本時用，因為每次要新內容）。
    """
    if not API_KEY:
        return None

    if use_cache:
        cached = _cache_get(model, prompt)
        if cached is not None:
            _record(model, 0, 0, cached=True)
            return cached

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
        in_tok = usage.get("input_tokens", max(1, len(prompt) // 4))
        out_tok = usage.get("output_tokens", max(1, len(text) // 4))
        _record(model, in_tok, out_tok, cached=False)
        if use_cache:
            _cache_set(model, prompt, text)
        return text
    except Exception as exc:
        print(f"[ai_budget] API 呼叫失敗：{str(exc)[:100]}", file=sys.stderr)
        return None


# ─── 報表 ──────────────────────────────────────────────────────────────────────

def report() -> None:
    data = _load_json(USAGE_FILE, {})
    cache = _load_json(CACHE_FILE, {})
    if not data:
        print("尚無用量記錄。")
        return

    total_twd = 0.0
    print(f"快取條目：{len(cache)} 筆（TTL {CACHE_TTL_DAYS} 天）\n")
    for day in sorted(data.keys(), reverse=True)[:7]:
        print(f"── {day} ──")
        day_twd = 0.0
        for model, m in sorted(data[day].items()):
            est = m.get("est_twd", 0.0)
            day_twd += est
            hit = m.get("cached", 0)
            real = m["calls"] - hit
            print(f"  {model:<35}  {real:>3} 次實呼叫  {hit:>3} 次快取命中"
                  f"  {m['in_tokens']:>7} in  {m['out_tokens']:>6} out"
                  f"  NT${est:.2f}")
        print(f"  小計：NT${day_twd:.2f}\n")
        total_twd += day_twd
    print(f"7 日合計：NT${total_twd:.2f}")


if __name__ == "__main__":
    report()
