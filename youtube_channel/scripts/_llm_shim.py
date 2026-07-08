#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_llm_shim.py — 全域攔截：把所有打 Anthropic messages API 的請求改道 OpenRouter(經 llm.py 路由)。

為什麼：工作室 ~20 支部門腳本各自 `requests.post("https://api.anthropic.com/v1/messages", ...)`，
Anthropic 沒錢就全部失敗。與其一支支改，這裡 monkeypatch `requests.post`，
凡是打 Anthropic messages 的，改用 llm.complete(OpenRouter DeepSeek) 並回一個 Anthropic 形狀的假 Response，
讓各腳本原本的 `r.json()["content"][0]["text"]` / `r.raise_for_status()` 照常運作，零改動。

由 sitecustomize.py 在直譯器啟動時自動 import 啟用。只有設了 OPENROUTER_API_KEY 才接管，否則原樣放行。
"""
from __future__ import annotations
import os


def install():
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        return  # 沒設 OpenRouter 就不接管，維持原本 Anthropic 行為
    try:
        import requests
    except Exception:
        return
    if getattr(requests, "_llm_shim_installed", False):
        return
    _orig_post = requests.post

    class _FakeResp:
        def __init__(self, text):
            self._text = text
            self.status_code = 200
        @property
        def text(self):
            return self._text
        def raise_for_status(self):
            return None
        def json(self):
            # 同時相容 Anthropic 形狀(content[0].text)與 OpenAI 形狀(choices[0].message.content)
            return {"content": [{"text": self._text}],
                    "choices": [{"message": {"content": self._text}}]}

    def _patched_post(url, *a, **kw):
        try:
            if isinstance(url, str) and "api.anthropic.com/v1/messages" in url:
                body = kw.get("json") or {}
                msgs = body.get("messages") or []
                parts = []
                if body.get("system"):
                    parts.append(str(body["system"]))
                for m in msgs:
                    c = m.get("content")
                    if isinstance(c, str):
                        parts.append(c)
                    elif isinstance(c, list):  # anthropic content blocks
                        parts += [b.get("text", "") for b in c if isinstance(b, dict)]
                prompt = "\n".join(p for p in parts if p)
                mx = int(body.get("max_tokens") or 1500)
                # 轉傳 json_mode / temperature(原本被丟棄→JSON任務失去強制JSON多燒重試、評分失去低溫)
                jm = bool(body.get("response_format")) or ("JSON" in prompt) or ("json" in prompt)
                tp = body.get("temperature")
                import llm  # 執行時才 import(此時 scripts/ 已在 sys.path)
                txt = llm.complete(prompt, mx, json_mode=jm, temperature=tp)
                return _FakeResp(txt)
        except Exception:
            pass  # 出事就退回原本(真打 Anthropic)，不讓 shim 拖垮
        return _orig_post(url, *a, **kw)

    requests.post = _patched_post
    requests._llm_shim_installed = True


install()
