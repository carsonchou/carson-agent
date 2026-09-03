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
        # 🔴 **沒接管這件事要留痕。** 靜默 return 的後果是「所有 Anthropic
        #    呼叫直接打出去」,而外面看起來跟「shim 正常運作」一模一樣。
        #    一個沒有訊號的旁路,等 Carson 儲值之後就是靜默燒錢。
        import sys
        print("⚠️ _llm_shim 未接管:沒有 OPENROUTER_API_KEY。"
              "所有 Anthropic 呼叫會直接打出去(帳戶有錢就會扣款)。",
              file=sys.stderr)
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
        # 🔴 **這裡不准 fail-open。** 舊版把 URL 判斷包在 try 裡,任何例外都
        #    掉進 `except: pass` 再落到 `_orig_post` —— 也就是**真打
        #    api.anthropic.com**。現在 Anthropic 帳戶是空的,所以它只是大聲
        #    失敗;而 Carson 哪天隨手儲值,這條就**反轉成靜默燒真錢**,
        #    而且失效訊號是「不再報錯」—— 最難發現的那一種。
        #    同一段碼安不安全,不該由帳戶餘額決定。
        #
        #    所以把兩條路分開:**不是 Anthropic 的請求照常放行**(那是這個
        #    shim 存在的前提,不能擋);**該改道卻失敗的,raise,絕不回退**。
        if not (isinstance(url, str)
                and "api.anthropic.com/v1/messages" in url):
            return _orig_post(url, *a, **kw)
        try:
            if True:
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
                # 🔴 空回應不准包成假 200。`_FakeResp(None)` 的 raise_for_status
                #    回 None、status_code 是 200 —— 呼叫端會以為成功,拿到 None
                #    再往下走,錯在別的地方才爆。空就是失敗,當場說。
                if not txt:
                    raise RuntimeError("llm.complete 回空值")
                return _FakeResp(txt)
        except Exception as e:
            # 改道失敗 → **中止**。不回退、函式底部也不留任何落到
            # `_orig_post` 的縫 —— 少一個 return 就等於少一條靜默燒錢的路。
            #
            # 🔴 但只 raise 不夠:呼叫端有 `except Exception: action = None`
            #    這種寫法(control_center.py:819-827),會把這個例外整個吞掉,
            #    於是改道失敗在那條路徑上是**隱形**的。raise 是給程式看的,
            #    stderr 是給人看的,兩個都要。
            import sys as _s
            print(f"⛔ _llm_shim 改道失敗,已中止(不回退打 Anthropic):{e}",
                  file=_s.stderr, flush=True)
            raise RuntimeError(
                f"⛔ LLM 改道失敗,而且**不回退打 Anthropic**:{e}\n"
                f"   回退等於在 Carson 儲值之後靜默燒真錢,而失效訊號是"
                f"「不再報錯」。要打 Anthropic 請明確拿掉這個 shim。") from e

    requests.post = _patched_post
    requests._llm_shim_installed = True


install()
