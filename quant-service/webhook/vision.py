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

2026-09-19 同日第三次:獨立驗證又抓到兩個洞——① 「由後往前找第一個能解析成 dict
的」沒檢查那個 dict 有沒有 `codes` 欄位,如果最後一個 fence 剛好是不相關的合法
JSON(例如 `{"foo":"bar"}`),會靜默回傳 `[]`,把前面真正的答案丟掉;② fence 內容
如果自己包含巢狀反引號,`_FENCE_RE` 的邊界比對會被打亂,連帶讓「由後往前」在有更
早草稿 fence 存在時選錯。兩個洞都是同一種病:**用正規式猜 fence 邊界,本質上猜不
完**。改用「直接掃大括號配對(字串內的括號不計)抓出所有語法完整的 JSON 物件」,
完全不管有沒有 ``` 包住,並且只接受「有 `codes` 欄位且是 list」的候選——不相關的
合法 JSON 不會再被誤選。同時在 prompt 加一句明講「只能輸出一個 JSON、不要草稿」,
從源頭降低模型輸出多個候選的機率(見 `_PROMPT`)。

殘留風險(有意接受、非漏改):如果模型真的先給完整正確答案、又在後面加一段同樣
帶 `codes` 欄位的不相關內容,「取最後一個」仍可能選錯——這是內容本身有歧義,不是
正規式能解的問題,靠上面加的 prompt 限制降低發生率,而非在解析層強行消歧。
"""
from __future__ import annotations

import base64
import json
import os
import re

import requests

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_CODE_RE = re.compile(r"^[0-9A-Z]{4,6}$")

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
    "- 若完全看不出任何股票代號,回傳 {\"codes\": []}。\n"
    "- 直接給最終答案,只能輸出一個 JSON 物件:不要先給格式範例、不要草稿、不要展示"
    "「修正前/修正後」兩個版本——如果你需要重新確認答案,把舊的答案丟掉,只留最終這一份。"
)


class VisionError(RuntimeError):
    """辨識失敗(缺金鑰/API 錯誤/回應格式不對)。呼叫端轉成 HTTP 錯誤給前端,不靜默吞掉。"""


def _iter_json_objects(txt: str):
    """依序找出 txt 裡所有語法完整的最外層 {...} 物件(字串內的括號不計)。

    不靠 ``` fence 邊界定位——fence 內容如果自己包含巢狀反引號,正規式對 fence
    邊界的猜測會被打亂(見 vision.py 2026-09-19 第三次補記)。直接掃大括號配對,
    對字串本身有沒有被 fence 包住完全不敏感。
    """
    n = len(txt)
    i = 0
    while i < n:
        if txt[i] == "{":
            depth = 0
            in_str = False
            escape = False
            start = i
            j = i
            while j < n:
                c = txt[j]
                if in_str:
                    if escape:
                        escape = False
                    elif c == "\\":
                        escape = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            yield txt[start:j + 1]
                            i = j
                            break
                j += 1
            # else(找到字尾都沒配對成功):不中斷整個掃描,只放棄這個 `{`,
            # 從下一個字元繼續找——否則文字裡任何一個孤兒 `{`(範例、擬碼、
            # 被截斷的說明)會讓後面明明完整的 JSON 物件整段消失不見。
        i += 1


def _parse_codes_payload(txt: str) -> dict:
    """從模型回應裡挑出「最終答案」那個 JSON 物件。

    掃出全部語法完整的 JSON 物件候選,由後往前找第一個「能解析成 dict 且有
    codes 欄位(list)」的——模型的自我修正一律是後面蓋掉前面,而且只認有
    codes 欄位的,排除掉跟答案無關但剛好也合法的 JSON(例如格式範例本身)。
    找不到任何合格候選時,退回整段硬解,讓原始例外訊息說明真正壞在哪。
    """
    for candidate in reversed(list(_iter_json_objects(txt))):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("codes"), list):
            return data
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
