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


def _retry_after(body: str) -> float:
    """從 429 回應裡讀出「該等幾秒」。讀不到回 0(交給呼叫端用遞增退避)。

    Gemini 的 429 body 長這樣:
      "... limit: 20, model: gemini-2.5-flash\nPlease retry in 59.990786042s."
    也可能帶 RetryInfo: {"@type": ".../RetryInfo", "retryDelay": "59s"}
    """
    for pat in (r"retry in\s*([\d.]+)\s*s", r'"retryDelay"\s*:\s*"([\d.]+)s"'):
        m = re.search(pat, body or "", re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return 0.0


# 🔴 2026-07-30 產線全停事故的實測記錄(避免下次重走同一條死路)。
# 當天 OpenRouter 餘額用罄(-US$0.20),402 原文「This request requires more credits,
# or fewer max_tokens」——實測只有 max_tokens ≤ 約 200~400 的請求能過,而各部門
# 都用 1500~3500,等於選題/判斷/寫稿全停。
#
# 曾嘗試靠 fallback=gemini 免費層續命,**實測不可行**:
#   ①Gemini 429 本文寫 metric=generate_content_free_tier_requests、limit=20、
#     retryDelay 約 54s,且 max_tokens 200 與 3500 一樣被擋(是請求數限制,不是 token)。
#   ②一度以為「舊碼只等 24s、跨不過 60s 視窗」是根因,改成聽 API 給的秒數後仍 0/3 成功。
#   ③關鍵反證:**靜置 80 秒完全不發任何請求**,再打一次仍 429(retry_in 36.8s)
#     → 名額不是被自己的重試佔掉的,等更久拿不到。
# ⚠️ 2026-07-30 16:10 追加更正:上面 ③ 那條反證的**解讀**當時是錯的。
#   「靜置 80 秒仍 429」不是因為名額被搶,是因為 Gemini 的**每日**免費額度已用罄
#   ——那種狀態下等多久都沒用。而台灣 15:00(=美西午夜)它每日重置,產線就自己活了
#   (實測 15:00 後 llm.complete(3500) 連續 4/4 成功,每次約 4~5 秒)。
#   我把一個**週期性耗盡**讀成了**永久性不足**。
# 現在已知的完整圖像:
#   ·Gemini 免費層 ≈ 每分鐘 20 次請求(全工作室共用),外加一個每日總量。
#   ·低頻使用可行;**批次必掛**——實測連續產 12 支縮圖文案時整批退回保底。
#   ·每日額度耗盡後要等台灣 15:00 才恢復。今天約 06:33 斷(即前一日 15:00 起撐約 15 小時)。
# 結論(維持不改退避):在「每分鐘 20 次 + 18 個部門」的條件下,長等只會讓工作互相堵住;
#   快速失敗讓下一輪 cron 再試才對。要全速穩定運轉,還是得儲值主供應商。


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
        if r.status_code == 429:  # 免費版限流→短退避重試(4/8/12s)
            # 🔴 2026-07-30 我在同一天把這段改了三次,最後回到原點。把過程寫下來,
            # 是為了讓下一個人(或下一個我)**不要再試第四次**。
            #
            # 三次的經過:
            #  ①早上改成「聽 API 給的 retry in Ns、最長等 70s」→ 實測產線路徑 0/3 → 回退。
            #  ②晚上發現①的測試是在 Gemini「每日額度用罄」時段跑的(那種狀態等多久都不會過),
            #    於是認為①其實是對的、只是測錯時機 → 改回長等(加上「只允許一次」的界限)。
            #  ③再測:**靜置 75 秒後仍 0/3,每次卡 60 秒才失敗** → 回退到原本的短退避。
            #
            # 為什麼最後選短退避(這是**證據**不是偏好):
            #  ·拿得出「有成本」的證據:額度耗盡時,長等讓每次失敗從 24s 變成 60s(慢 2.5 倍),
            #    而且完全沒有換到成功。
            #  ·拿不出「有效益」的證據:我唯一一次「靜置 70s 後成功」無法排除是當下額度剛好夠,
            #    測不出是長等的功勞。**有成本、無可證的效益 → 不留。**
            #
            # 這個 provider 的可觀測性問題才是根因:429 的 retryDelay 在「每分鐘視窗滿」和
            # 「每日額度用罄」兩種完全不同的狀態下長得一模一樣(都給 20~55 秒),
            # 從外部無法分辨,所以任何退避策略都是在盲測。真正的解法是儲值主供應商,
            # 不是在這裡調秒數。**別再調這裡了。**
            #
            # ⚠️ 另記:我做上述實驗時連打了 22 次去塞滿視窗,那些請求都算在產線共用的
            #    免費額度上——當晚剩餘時間產線因此沒有 LLM。**壓測共用資源要算它的產線成本。**
            last = "429 rate limit"
            time.sleep(4 * (t + 1)); continue
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
