"""vision.py — 個股體檢「庫存截圖辨識」:一張圖片 → 股票代號清單(prototype)。

為什麼獨立成一檔:quant-service/webhook 原本完全沒有 LLM/vision 呼叫(唯一相關的
youtube_channel/scripts/llm.py 是另一個專案的純文字 completion 模組,不跨專案相依)。
這裡刻意寫成最小、自足的一支,只靠 quant-service/.env 既有且已儲值的
OPENROUTER_API_KEY(llm.py 註解:「Carson 已儲值」,08-04 起已在用),不申請新的付費管道。

模型選 anthropic/claude-sonnet-4.5(OpenRouter 代管,走一般付費 API 呼叫——不是借用
Claude Code 本身的登入/OAuth,那條路只給互動用、拿來跑後端服務屬於違反 ToS 的自動化,
見 memory anthropic-billing-api-vs-oauth)。原本用 google/gemini-2.5-flash 較便宜,但實測
「用名稱推算代號」這條路徑連續兩版都出包——先把「凱基台灣TOP50」誤猜成完全不同的
0050,加了明確防呆範例(連正確代號 009816 都寫進 prompt)後,還是穩定地把它抄成
00916/009186 之類的錯誤數字。換過 openai/gpt-4o 先驗證是模型問題不是功能問題(3/3
穩定答對);後來發現 claude-sonnet-4.5 其實原本就答對,只是回應被包在 ```json``` 這種
markdown code fence 裡,舊的 json.loads(txt) 直接炸掉被誤判成失敗——修好 fence 剝除後
兩種案例(名稱推算/畫面本來就印代號)各測 3 次全部正確,改用它當預設模型。
之後要再換模型只改 STOCK_CHECKUP_VISION_MODEL 環境變數。

2026-09-19 再出包:上面那次修的 _FENCE_RE 是錨定 ^```...```$,只涵蓋「整段回應就是
fence」。實測發現模型有時會在 fence 前面先加一段中文說明(「這是XX,代號是XX」)才接
```json```,錨定版本比對失敗,退回把整段(含說明文字)丟給 json.loads(),得到
`Expecting value: line 1 column 1 (char 0)`。改成不錨定的 search()、再加一層「沒 fence
就找 {...}」的備援,兩種情況都能剝出乾淨的 JSON。

2026-09-19 同日第二次:獨立驗證抓到上面那版只處理「一個 fence」,沒處理「多個
fence」——模型偶爾會先給範例/草稿 fence 才接真正答案,`.search()` 非貪婪比對只抓
到第一個,一樣炸出跟修復前一模一樣的錯誤;更壞的是如果草稿 fence 剛好也是合法
JSON,會**靜默回傳錯的股票代號**、完全不報錯。改成 `_parse_codes_payload()`:蒐集
全部 fence,由後往前找第一個能成功解析的——模型的自我修正一律是後面蓋掉前面。
"""
from __future__ import annotations

import base64
import json
import os
import re

import requests

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_CODE_RE = re.compile(r"^[0-9A-Z]{4,6}$")
# 不能錨定 ^...$:模型有時會在 fence 前面加一段說明文字(例如「這是XX,代號是XX」)
# 才接 ```json ... ```,錨定版本會整段連說明文字一起丟給 json.loads() 而炸掉。
_FENCE_RE = re.compile(r"```(?:[a-zA-Z]*)\s*\n?(.*?)\n?```", re.DOTALL)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

_PROMPT = (
    "這是一張台股券商 App 的庫存(持股)畫面截圖。請找出畫面中每一檔股票的「股票代號」"
    "(4~6碼英數字,台股常見4碼數字如2330、006208等)。\n"
    "有些畫面只印公司或基金「名稱」、沒有印代號(例如「凱基台灣TOP50」)。這種情況下,"
    "如果你確定該名稱對應的官方台股代號,可以直接填入代號;如果不確定是哪一檔或名稱太模糊"
    "(可能對到多檔、或你沒把握),就跳過那一檔不要猜。\n"
    "特別小心:名稱裡出現的數字不代表股票代號,不要因為數字長得像就套用知名代號——例如"
    "「凱基台灣TOP50」名稱裡有「50」,但它跟代號 0050(元大台灣50)是完全不同的兩檔基金,"
    "正確代號是 009816。名稱推算一定要對到「發行商+完整主題」都吻合的那一檔,只要有任何"
    "混淆可能就跳過不猜。\n"
    "只輸出 JSON 物件,格式:{\"codes\": [\"2330\", \"2603\"]}。\n"
    "規則:\n"
    "- 只列股票代號,不要公司名稱、不要其他文字。\n"
    "- 不管是直接看到還是靠名稱推算出來的代號,只要不確定就不要瞎猜,寧可漏掉不要編造。\n"
    "- 依畫面由上到下的順序列出,去除重複。\n"
    "- 若完全看不出任何股票代號,回傳 {\"codes\": []}。"
)


class VisionError(RuntimeError):
    """辨識失敗(缺金鑰/API 錯誤/回應格式不對)。呼叫端轉成 HTTP 錯誤給前端,不靜默吞掉。"""


def _parse_codes_payload(txt: str) -> dict:
    """從模型回應裡挑出「最終答案」那段 JSON。

    模型常常不是只給一個 fence:可能先給格式範例、草稿、思考過程,才接真正答案,
    甚至前面的草稿也剛好是合法 JSON(見 vision.py 2026-09-19 補記)。一律採用
    「由後往前找,第一個能成功解析成 dict 的 fence」——模型的自我修正永遠是後面
    蓋掉前面,不會反過來。找不到任何合法 fence 才退回全文找 {...} 或整段硬解。
    """
    fences = list(_FENCE_RE.finditer(txt))
    for m in reversed(fences):
        try:
            data = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    obj = _JSON_OBJ_RE.search(txt)
    if obj:
        return json.loads(obj.group(0))
    return json.loads(txt)


def _model() -> str:
    return os.environ.get("STOCK_CHECKUP_VISION_MODEL", "anthropic/claude-sonnet-4.5").strip()


def _key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def extract_codes(image_bytes: bytes, content_type: str, max_codes: int) -> list[str]:
    """丟一張庫存截圖進去,回傳去重、格式驗證過的股票代號清單(至多 max_codes 檔)。

    空清單是合法結果(模型判斷「圖裡沒有可辨識的代號」),與拋 VisionError(服務本身
    失敗)要分得開——呼叫端據此決定要顯示「請改手動輸入」還是「重試」。
    """
    key = _key()
    if not key:
        raise VisionError("辨識服務未設定(缺 OPENROUTER_API_KEY)")
    mime = (content_type or "").split(";")[0].strip() or "image/png"
    if not mime.startswith("image/"):
        raise VisionError(f"檔案類型看起來不是圖片:{mime}")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    body = {
        "model": _model(),
        "max_tokens": 800,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    }
    try:
        r = requests.post(_OPENROUTER_URL,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=body, timeout=60)
    except requests.RequestException as exc:
        raise VisionError(f"辨識服務連線失敗:{exc}") from exc
    if r.status_code != 200:
        detail = r.text
        try:
            detail = ((r.json() or {}).get("error") or {}).get("message") or r.text
        except Exception:  # noqa: BLE001
            pass
        raise VisionError(f"辨識服務錯誤:{str(detail)[:200]}〔HTTP {r.status_code}〕")

    try:
        txt = (r.json()["choices"][0]["message"]["content"] or "").strip()
        raw_codes = _parse_codes_payload(txt).get("codes") or []
    except Exception as exc:  # noqa: BLE001
        raise VisionError(f"辨識結果格式不正確,無法解析:{exc}") from exc

    seen: list[str] = []
    for c in raw_codes:
        code = str(c or "").strip().upper()
        if code and _CODE_RE.match(code) and code not in seen:
            seen.append(code)
        if len(seen) >= max_codes:
            break
    return seen
