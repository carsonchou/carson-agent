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
# 推理型模型:思考過程佔用 max_tokens,額度太小會回空字串(見 _call_openai_compat 的實測註解)
_REASONING_MODELS = ("gpt-oss", "deepseek-r1", "qwq", "o1", "o3")
_REASONING_MIN_TOKENS = 1000    # 實測 gpt-oss-120b:300 不夠、900 夠
_MAX_TOKENS_CAP = 8000          # 加倍重試的上限,免得無限往上加
# 超過這個估算 token 數就算「大請求」,改把桶比較大的供應商排前面(見 complete() 的分流說明)。
# 中文約 1 字 1 token,這裡用 1.1 保守估;10,000 大約是 Groq 免費層 12,000 桶扣掉安全邊際。
_BIG_REQUEST_TOKENS = 10000

_OPENAI_COMPAT = {
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", "deepseek/deepseek-chat"),
    # 🔴 2026-08-04 預設模型 openai/gpt-oss-120b → llama-3.3-70b-versatile。
    # 這不是換個口味,是**解除整條產線的產能瓶頸**。
    #
    # 症狀:produce_batch 每天要產 5 支長片,實測近五天只產出 5→1→1→2→0 支,
    # 08-03 整天 0 支。實跑診斷:4 次嘗試 8 次重試**全部 429**,產出 0。
    #
    # 根因:Groq 免費層的限制是 **每分鐘 8,000 tokens**(x-ratelimit-limit-tokens=8000,
    # 690ms 重置;每日請求數 1000 反而很寬鬆)。而 gpt-oss-120b 是**推理型模型**——
    # 它把大量 token 花在我們**丟掉不用**的 reasoning 欄位上,那些 token 一樣吃這個桶。
    #
    # 同一個提示實測(2026-08-04):
    #   散文 150字旁白 : gpt-oss 花 1000 token 產出 **0 字**(全燒在推理)/ llama 224 token 產出 265 字
    #   產線 JSON 判斷 : gpt-oss **485** token / llama **65** token,兩者結構都正確
    # → 每分鐘 8,000 的桶下,JSON 任務是 16 次 vs 120 次的差別。
    #
    # 品質驗證:llama 輸出**零簡體字**、JSON 欄位正確、且不再吐英文思考過程
    #   (順帶根治「旁白冒出英文」——見下方 content/reasoning 那段的說明)。
    # 要換回推理型模型前,先想清楚它會把每分鐘額度燒在你丟掉的東西上。
    "groq":     ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",     "llama-3.3-70b-versatile"),
    "deepseek": ("https://api.deepseek.com/chat/completions",       "DEEPSEEK_API_KEY", "deepseek-chat"),
    "gemini":   ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY", "gemini-2.5-flash"),
    # 🔴 2026-08-01 本機 Ollama(OpenAI 相容端點)。**零成本、零限流、不用網路**——
    # 加它的原因是很具體的:當天 OpenRouter 餘額用罄(402)、Gemini 免費層每分鐘 20 次
    # 且每日會用罄,結果是**7 支已渲染好的長片卡在「未評分」**(評分失敗 → status=unrated
    # → daily_publish fail-closed → 永遠不會發布),而且沒有任何告警。
    # 評分是「判斷/分類」不是創意寫作,本機模型完全夠用(同 memory api-credits-frugal
    # 「分類工作用便宜模型、創意才用貴的」)。**創意寫稿仍走雲端**,別用本機模型寫稿。
    # key 欄位刻意留空字串:Ollama 是本機服務、不驗金鑰。下面 _call_openai_compat 對
    # 空 envk 會跳過金鑰檢查(而不是要求我們去 .env 塞一個假 key 騙過檢查)。
    #
    # ⚠️ 模型大小是被機器逼出來的,不是隨便選的:這台是筆電,**RTX 4050 Laptop 只有 4GB
    #    VRAM**,而 qwen2.5:7b(Q4)要 4.2GB → 塞不進顯卡 → 退回 CPU,而當下可用記憶體
    #    只剩 0.4GB(Chrome 吃掉大半)→ 整台開始硬碟交換,連 80 token 的請求都 >90 秒無回應。
    #    改用 3b(約 2GB)才裝得進 VRAM。**別再把 7b 以上的模型設成預設**,除非換機器。
    # ⚠️ 更重要的原則:本機模型會**跟影片渲染搶同一份記憶體/顯卡**,而渲染是這條產線的
    #    核心功能(記憶 yt-healthcheck-concurrency:曾有渲染程序把 15.7GB 吃到 0.4GB 的事故)。
    #    所以本機路只當**離線保險**,不當主力;主力應該是雲端免費層(如 Groq,額度遠大於
    #    Gemini 的每分鐘 20 次,且不佔本機資源)。
    "ollama":   ("http://localhost:11434/v1/chat/completions", "", "qwen2.5:3b"),
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


def _call_openai_compat(provider, prompt, max_tokens, model=None, tries=3, json_mode=False,
                        temperature=None, _retried_longer=False):
    url, envk, default_model = _OPENAI_COMPAT[provider]
    key = _key(envk) if envk else ""
    # envk 為空 = 該供應商不需金鑰(目前只有本機 Ollama)。其餘一律仍要 key,
    # 免得雲端供應商因為環境變數沒設就靜默用空 key 去打、拿到看不懂的 401。
    if envk and not key:
        raise RuntimeError(f"{provider}: 缺 {envk}")
    mdl = model or default_model
    # 推理型模型的思考過程也吃 max_tokens,額度太小會「還沒開始寫答案就被截斷」(見下方實測)。
    # 實測 gpt-oss-120b:300 不夠、900 夠 → 給 1000 的地板。呼叫端有十幾個、不少只給 400~800,
    # 與其逐一去改(漏一個就再壞一次),不如在這裡統一保底。
    if any(m in mdl.lower() for m in _REASONING_MODELS):
        max_tokens = max(max_tokens, _REASONING_MIN_TOKENS)
    body = {"model": mdl, "max_tokens": max_tokens,
            "temperature": 0.8 if temperature is None else temperature,  # 評分等任務可傳低溫(近決定性、不亂漂)
            "messages": [{"role": "user", "content": prompt}]}
    if json_mode:  # 強制只吐合格 JSON（Groq/DeepSeek/Gemini OpenAI 相容端點都支援）
        body["response_format"] = {"type": "json_object"}
        # ⚠️ 2026-08-03:Groq(以及 OpenAI 相容端點的 json_object 模式)**規定訊息裡必須
        # 出現 "json" 這個字**,否則直接 HTTP 400:
        #   'messages' must contain the word 'json' in some form, to use 'response_format'
        # 實測時事部因此連續三班(02:00/06:01/09:35)「所有 LLM 供應商都失敗」→ 該部門整天
        # 產出 0。這種錯誤和「模型判斷不出來」在上層長得一樣,查不到真因。
        # 修在這裡而不是叫各部門改文案:呼叫端有十幾個,漏一個就再壞一次,而且沒有任何一層
        # 會告訴你是漏了哪個字。
        if "json" not in prompt.lower():
            body["messages"][0]["content"] = prompt + "\n\n（請直接輸出 JSON 物件，不要有其他文字。）"
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
            # 🔴 2026-08-03 把「真正的原因」提到訊息最前面。
            # 實測產線連續三班 400,ops_log 只留下:
            #   所有 LLM 供應商都失敗:groq: groq HTTP 400: {"error":{"message":"Failed to vali
            # ——55 個字的樣板把 70 字的截斷視窗吃光,原因剛好被切掉。各部門有 34 處
            # `str(exc)[:70]` 這類截斷,改不完也不該改(下一個人還會再加一處);
            # 正解是**讓前 70 個字就有資訊量**:把 API 回的 error.message 抽出來擺前面,
            # 樣板往後放。一處修好,34 個呼叫端全部受惠。
            detail = r.text
            try:
                detail = ((r.json() or {}).get("error") or {}).get("message") or r.text
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"{str(detail)[:400]}〔{provider} HTTP {r.status_code}〕")
        j = r.json()
        choice = j["choices"][0]
        msg = choice["message"]
        txt = msg.get("content") or ""
        # 🔴 2026-08-03 拆掉 `or msg.get("reasoning")` 的退路。
        #
        # 現行主力 groq 的預設模型 openai/gpt-oss-120b 是**推理型模型**:思考過程會佔用
        # max_tokens,而且放在獨立的 `reasoning` 欄位。實測同一個提示:
        #   max_tokens=300 → finish_reason=length、content='' 、reasoning 裝著整段英文思考
        #   max_tokens=900 → finish_reason=stop  、content='投資台股定期定額,穩健累積財富…'
        # 也就是 token 不夠時,模型**還沒開始寫答案就被截斷**。
        #
        # 舊碼在 content 空時退回 reasoning,等於把「模型的英文自言自語」當成答案送出去,
        # 一路寫進旁白稿——先前那支旁白冒出英文、被渲染閘門擋下的片就是這樣來的。
        # 拿思考過程冒充答案比誠實失敗糟得多:失敗會換下一個供應商,冒充則靜靜污染成品。
        if not txt.strip():
            if choice.get("finish_reason") == "length" and not _retried_longer:
                # 純粹是預算不夠,不是模型不會答 → 加倍重試一次(見上方實測)
                return _call_openai_compat(provider, prompt, min(max_tokens * 3, _MAX_TOKENS_CAP),
                                           model, tries, json_mode, temperature,
                                           _retried_longer=True)
            raise RuntimeError(f"{provider}: 回應為空(finish_reason={choice.get('finish_reason')}),"
                               f"換下一個供應商")
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
    # ── 依請求大小分流(2026-08-04)────────────────────────────────────────────
    # Groq 免費層的限制是「每分鐘 token 桶」,而且**單一請求的 (輸入+max_tokens) 也必須
    # 塞得進那個桶**(llama-3.3-70b = 12,000)。實測長片產稿的提示是 **14,500~17,100 字**
    # (中文約 1 字 1 token)→ 光提示就撐爆,Groq 直接回 `Request too large`,不是慢是沒送出去。
    # 這就是長片產能長期 1~2 支/日、08-03 整天 0 支的根因。
    #
    # 但**小請求**(JSON 判斷、評分、分類)在 Groq 上又快又省(實測同一個判斷 llama 65 tokens
    # vs gpt-oss 485)。所以不該一刀切換供應商,該**照請求大小分流**:
    #   小請求 → Groq 優先(快、額度多),Gemini 當備援
    #   大請求 → **直接走 Gemini**(免費層的桶大得多),不要先去 Groq 撞一次必死的牆
    # 順序反轉之後,兩邊的免費額度才不會互相排擠——原本小請求把 Gemini 的每日額度耗光,
    # 輪到長片時只剩 Groq,而 Groq 又吃不下。
    #
    # ⚠️ 這只是把兩個免費層用好,**沒有變出額度**。長片提示 ~14k tokens 這件事本身,
    #    在任何免費層都是勉強的;真正的解法是主供應商儲值(見 memory 的 429 段落結論)。
    _big = (len(prompt) // 1.1 + max_tokens) > _BIG_REQUEST_TOKENS
    order = (fallback, primary) if (_big and fallback) else (primary, fallback)
    chain, seen = [], set()
    for p in order:
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
