"""vision.py — 個股體檢「庫存截圖辨識」:一張圖片 → 股票代號清單(prototype)。

為什麼獨立成一檔:quant-service/webhook 原本完全沒有 LLM/vision 呼叫(唯一相關的
youtube_channel/scripts/llm.py 是另一個專案的純文字 completion 模組,不跨專案相依)。
這裡刻意寫成最小、自足的一支,只靠 quant-service/.env 既有且已儲值的
OPENROUTER_API_KEY(llm.py 註解:「Carson 已儲值」,08-04 起已在用),不申請新的付費管道。

模型選 vision-capable 的:google/gemini-2.5-flash,OpenRouter 上有代管、吃得動圖片、
價格低。準確率未知(prototype),之後要換模型只改 STOCK_CHECKUP_VISION_MODEL 環境變數。
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
    "只輸出 JSON 物件,格式:{\"codes\": [\"2330\", \"2603\"]}。\n"
    "規則:\n"
    "- 只列股票代號,不要公司名稱、不要其他文字。\n"
    "- 看不清楚或不確定的代號不要瞎猜,寧可漏掉不要編造。\n"
    "- 依畫面由上到下的順序列出,去除重複。\n"
    "- 若完全看不出任何股票代號,回傳 {\"codes\": []}。"
)


class VisionError(RuntimeError):
    """辨識失敗(缺金鑰/API 錯誤/回應格式不對)。呼叫端轉成 HTTP 錯誤給前端,不靜默吞掉。"""


def _model() -> str:
    return os.environ.get("STOCK_CHECKUP_VISION_MODEL", "google/gemini-2.5-flash").strip()


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
        txt = r.json()["choices"][0]["message"]["content"] or ""
        raw_codes = json.loads(txt).get("codes") or []
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
