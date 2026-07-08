#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm.py — 共用 LLM 路由：一個介面、多家供應商，換模型只改環境變數。

為什麼：Anthropic API 餘額用完會讓整個工作室停擺。改用「主供應商＋自動退回」架構，
主力走便宜/免費的（Groq gpt-oss / DeepSeek / Gemini），失敗才退回 Anthropic。

設定（環境變數，皆可選）：
  LLM_PROVIDER   主供應商，預設 "groq"（可 groq/deepseek/gemini/anthropic）
  LLM_FALLBACK   退回供應商，預設 "anthropic"
  LLM_MODEL      覆寫主供應商的模型名（不設則用各家預設）
  GROQ_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY

用法：
  import llm
  text = llm.complete(prompt, max_tokens=3500)     # 回純文字
"""
from __future__ import annotations
import os
import re
import time
import requests

# 各供應商：OpenAI 相容端點(Groq/DeepSeek/Gemini 都支援) + Anthropic 原生
_OPENAI_COMPAT = {
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", "deepseek/deepseek-chat"),
    "groq":     ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",     "openai/gpt-oss-120b"),
    "deepseek": ("https://api.deepseek.com/chat/completions",       "DEEPSEEK_API_KEY", "deepseek-chat"),
    "gemini":   ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY", "gemini-2.5-flash"),
}
_ANTHROPIC = ("https://api.anthropic.com/v1/messages", "ANTHROPIC_API_KEY", "claude-haiku-4-5-20251001")


def _key(envname: str) -> str:
    return os.environ.get(envname, "").strip()


def _strip_think(t: str) -> str:
    """推理模型(如 qwen3)會吐 <think>…</think>，去掉只留正文。"""
    return re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()


def _call_openai_compat(provider, prompt, max_tokens, model=None, tries=3, json_mode=False, temperature=None):
    url, envk, default_model = _OPENAI_COMPAT[provider]
    key = _key(envk)
    if not key:
        raise RuntimeError(f"{provider}: 缺 {envk}")
    mdl = model or default_model
    body = {"model": mdl, "max_tokens": max_tokens,
            "temperature": 0.8 if temperature is None else temperature,  # 評分等任務可傳低溫(近決定性、不亂漂)
            "messages": [{"role": "user", "content": prompt}]}
    if json_mode:  # 強制只吐合格 JSON（Groq/DeepSeek/Gemini OpenAI 相容端點都支援）
        body["response_format"] = {"type": "json_object"}
    last = None
    for t in range(tries):
        r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                        "Content-Type": "application/json"}, json=body, timeout=150)
        if r.status_code == 429:  # 免費版限流→退避重試
            last = f"429 rate limit"; time.sleep(4 * (t + 1)); continue
        if r.status_code != 200:
            raise RuntimeError(f"{provider} HTTP {r.status_code}: {r.text[:140]}")
        msg = r.json()["choices"][0]["message"]
        txt = (msg.get("content") or "") or (msg.get("reasoning") or "")
        return _strip_think(txt)
    raise RuntimeError(f"{provider}: {last}（重試 {tries} 次仍限流）")


def _call_anthropic(prompt, max_tokens, model=None, temperature=None):
    url, envk, default_model = _ANTHROPIC
    key = _key(envk) or _key("ANTHROPIC_KEY")
    if not key:
        raise RuntimeError("anthropic: 缺 ANTHROPIC_API_KEY")
    payload = {"model": model or default_model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None:
        payload["temperature"] = temperature
    r = requests.post(url, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"}, json=payload, timeout=150)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _one(provider, prompt, max_tokens, model=None, json_mode=False, temperature=None):
    if provider in _OPENAI_COMPAT:
        return _call_openai_compat(provider, prompt, max_tokens, model, json_mode=json_mode, temperature=temperature)
    if provider == "anthropic":
        return _call_anthropic(prompt, max_tokens, model, temperature=temperature)  # Anthropic 靠 prompt 約束 JSON
    raise RuntimeError(f"未知供應商：{provider}")


def _cache_path(key: str):
    import pathlib
    d = pathlib.Path(os.environ.get("LLM_CACHE_DIR") or (pathlib.Path(__file__).resolve().parent.parent / "STUDIO" / "llm_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d / (key + ".txt")


def complete(prompt: str, max_tokens: int = 3500, json_mode: bool = False, temperature=None) -> str:
    """主供應商→失敗退回 fallback。回純文字。全失敗才 raise。
    json_mode=True 時對相容端點開啟 response_format 強制合格 JSON。
    temperature=None 用預設 0.8(創意);評分/判斷類任務可傳 ~0 求穩定。
    近決定性任務(temperature<=0.2)結果穩定→加磁碟快取,同 prompt 免重打(省評分/分類/重試)。"""
    primary = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    fallback = os.environ.get("LLM_FALLBACK", "anthropic").strip().lower()
    model = os.environ.get("LLM_MODEL", "").strip() or None
    # ── 磁碟快取(僅低溫近決定性任務;可設 LLM_NO_CACHE=1 關閉)──
    cacheable = temperature is not None and temperature <= 0.2 and not os.environ.get("LLM_NO_CACHE")
    ck = None
    if cacheable:
        import hashlib
        ck = hashlib.sha256(f"{primary}|{model}|{max_tokens}|{json_mode}|{temperature}|{prompt}".encode("utf-8")).hexdigest()[:32]
        try:
            cp = _cache_path(ck)
            if cp.exists():
                return cp.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    chain, seen = [], set()
    for p in (primary, fallback):
        if p and p not in seen:
            seen.add(p); chain.append(p)
    errs = []
    for i, prov in enumerate(chain):
        try:
            out = _one(prov, prompt, max_tokens, model if i == 0 else None, json_mode, temperature)
            if cacheable and ck and out:
                try:
                    _cache_path(ck).write_text(out, encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
            return out
        except Exception as e:  # noqa: BLE001
            errs.append(f"{prov}: {str(e)[:120]}")
    raise RuntimeError("所有 LLM 供應商都失敗：" + " | ".join(errs))


if __name__ == "__main__":  # 自測
    import sys
    print(f"PROVIDER={os.environ.get('LLM_PROVIDER','groq')} FALLBACK={os.environ.get('LLM_FALLBACK','anthropic')}")
    print(complete("用繁體中文回一句「路由測試成功」就好。", 50)[:200])
