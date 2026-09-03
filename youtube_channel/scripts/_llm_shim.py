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
import sys


class ShimRouteFailed(RuntimeError):
    """改道 OpenRouter 失敗。**刻意讓它炸出來**,不回退到會計費的 Anthropic 路徑。"""


def _loud(msg, to_ops=True):
    """同時寫 stderr 與 ops log:只 raise 的話,呼叫端若有 blanket except 就又靜音了。

    to_ops=False 用於「每個 process 啟動都會講一次」的訊息(無 key 提示)——
    ~20 支腳本 × 每天多輪會把 ops_log 洗版,而洗版的警報等於沒有警報。
    那一類只寫 stderr(排程的 job log 收得到),真正的失敗才進 ops_log。
    """
    try:
        print(f"[_llm_shim] {msg}", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass
    if not to_ops:
        return
    try:
        from ops import log_ops  # noqa: PLC0415
        log_ops("LLM改道", msg[:180])
    except Exception:  # noqa: BLE001
        pass


def install():
    # 🔴 2026-09-03:沒 key 就靜默 return 不接管 —— 那個 process 會**直通 Anthropic**,
    # 和下面的回退路徑同一個問題(裸排程環境沒有 .env 時就是這樣)。至少要留一行痕跡,
    # 否則「shim 沒接管」和「shim 接管了而且沒事」在 log 裡長得一模一樣。
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        _loud("⚠️ 未設 OPENROUTER_API_KEY,shim **未接管** —— 本 process 打 Anthropic "
              "會直通真端點(帳戶有錢就會真的計費)", to_ops=False)
        return
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
        # 🔴 2026-09-03 這裡原本是 `except Exception: pass` 然後落到 `_orig_post`,
        # 也就是**真打 api.anthropic.com**。那個設計的安全性由**外部帳戶餘額**決定:
        #   帳戶空(現在) → 回退撞死端點 → 各 job log 大聲失敗 → 無害
        #   Carson 哪天隨手儲值 → 同一段碼變成:OpenRouter 一出錯,~20 支腳本
        #                        **靜默改打真 Anthropic 燒真錢**,
        #                        而失效訊號正是「不再報錯」—— 大聲失敗變安靜成功
        # 同一段程式碼安不安全,不該由一個沒人會通知我們的外部狀態決定。
        # 所以改成:改道失敗就**大聲炸**,絕不偷偷走會計費的路。
        if not (isinstance(url, str) and "api.anthropic.com/v1/messages" in url):
            return _orig_post(url, *a, **kw)      # 非 Anthropic 的請求原樣放行
        try:
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
            if not txt:
                # 空回應包成 status 200 的假 Response,呼叫端會在 r.json()["content"][0]["text"]
                # 拿到 None,然後死在一個**看起來和 LLM 無關**的 TypeError 上。
                # 觸發面窄(llm.py 空回應本來就會 raise),但誤導成本高 → 在這裡就講清楚。
                raise ShimRouteFailed("llm.complete 回空值(None/空字串)")
            return _FakeResp(txt)
        except Exception as e:  # noqa: BLE001
            _loud(f"🔴 改道 OpenRouter 失敗({e!r})——**不回退到 Anthropic**(那會計費)。"
                  "這一次呼叫直接失敗,請查 OPENROUTER_API_KEY / llm.py / 網路")
            raise ShimRouteFailed(
                f"OpenRouter 改道失敗,拒絕回退到會計費的 Anthropic 端點:{e!r}") from e
        raise ShimRouteFailed("改道路徑沒有回傳結果(不應發生)")   # 防漏底,同樣不回退

    requests.post = _patched_post
    requests._llm_shim_installed = True


install()
