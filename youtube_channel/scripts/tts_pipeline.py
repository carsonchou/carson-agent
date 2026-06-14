#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_pipeline.py — ElevenLabs 文字轉語音 (TTS) Pipeline
=====================================================

頻道：量化阿森｜Carson Quant（faceless 全自動 YouTube 產線）

用途
----
吃一份「純配音稿」.txt（由 generate_script.py 產出），呼叫 ElevenLabs API
逐段合成語音，合併成單一 mp3，輸出到 output/，供剪輯階段使用。

依賴 (Dependencies)
-------------------
    pip install requests pydub

- requests：呼叫 ElevenLabs REST API（HTTP）。
- pydub   ：合併多段 mp3（解碼後重新編碼，避免直接 binary 串接造成的
            時間戳/seek 問題）。**pydub 需要系統安裝 ffmpeg**。
            * Windows 安裝 ffmpeg：
                - 下載 https://www.gyan.dev/ffmpeg/builds/ 的 release-full
                - 解壓後把 bin\\ffmpeg.exe 所在資料夾加入 PATH，或用
                  `winget install Gyan.FFmpeg`
            * 若環境無 ffmpeg，本程式會自動回退（fallback）為「直接 binary
              串接 mp3 frames」。串接法不需要 ffmpeg、零依賴，但對少數播放器
              的進度條/seek 可能略不精準（對 YouTube 上傳與多數剪輯軟體無影響）。
              可用 --concat-mode 強制指定串接法。

ElevenLabs 計費說明
-------------------
ElevenLabs 以「字元數 (characters)」計費，與秒數無關。--dry-run 會列出每段
字元數、總字元數，以及依 --price-per-1k 估算的成本，方便小預算控管
（本頻道預算：每月 < US$30）。

環境變數
--------
    ELEVENLABS_API_KEY   你的 ElevenLabs API key（必填，除非 --dry-run）

與 generate_script.py 的對接（檔名約定）
----------------------------------------
generate_script.py 產出「純配音稿」純文字檔，固定命名為：
    output/<slug>.voice.txt           （例：output/派網網格教學.voice.txt）

本 pipeline 預設輸出：
    output/<同 stem，去掉 .voice>.mp3  （例：output/派網網格教學.mp3）

也就是輸入 `xxx.voice.txt` → 輸出 `output/xxx.mp3`。可用 --out 覆寫。

設定檔
------
不指定 --config 時，預設自動讀取專案根目錄的 channel_config.json，
從其中的 "tts" 區塊取得 voice_id / model_id / max_chars 等預設值。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "[FATAL] 缺少 requests 套件。請執行： pip install requests pydub\n"
    )
    raise


# --------------------------------------------------------------------------- #
# 常數 / 預設值
# --------------------------------------------------------------------------- #

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

# 專案根目錄 = 本檔案所在的 scripts/ 的上一層 (youtube_channel/)；
# 用 pathlib 從 __file__ 推導，避免寫死絕對路徑，專案搬移也不會壞。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "channel_config.json"

DEFAULT_MODEL_ID = "eleven_multilingual_v2"   # 多語模型，繁中發音佳
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"     # ElevenLabs 公版 voice (Rachel)；
                                              # 正式上線請在 channel_config.json
                                              # 的 "tts".voice_id 換成頻道固定的
                                              # 繁中 voice profile。
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# ElevenLabs 單次請求字元上限（保守值；官方上限隨方案/模型而異，取保守 2500）
DEFAULT_MAX_CHARS = 2500

# 預設估價（USD / 1000 chars）。ElevenLabs 各方案不同，這只是 dry-run 估算用，
# 可用 --price-per-1k 覆寫成你方案的實際單價。
DEFAULT_PRICE_PER_1K = 0.30

# 重試設定
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE = 2.0   # 指數退避底數：等待 = base ** attempt（秒）
DEFAULT_TIMEOUT = 120        # 單次 HTTP 請求逾時（秒）


# --------------------------------------------------------------------------- #
# 設定載入
# --------------------------------------------------------------------------- #

def load_config(config_path: Optional[Path]) -> dict:
    """讀取 channel_config.json（若存在）。CLI 參數優先級高於設定檔。"""
    if config_path is None:
        return {}
    if not config_path.exists():
        print(f"[INFO] 找不到設定檔 {config_path}，改用預設值/CLI 參數。")
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        # 支援把 TTS 設定放在頂層或巢狀於 "tts" 鍵下
        if isinstance(cfg, dict) and "tts" in cfg and isinstance(cfg["tts"], dict):
            return cfg["tts"]
        return cfg if isinstance(cfg, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[WARN] 讀取設定檔 {config_path} 失敗：{exc}，改用預設值。")
        return {}


# --------------------------------------------------------------------------- #
# 文字讀取與分段
# --------------------------------------------------------------------------- #

def read_script(path: Path) -> str:
    """讀取純配音稿（UTF-8，容忍 BOM）。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到配音稿：{path}")
    text = path.read_text(encoding="utf-8-sig")
    text = text.strip()
    if not text:
        raise ValueError(f"配音稿是空的：{path}")
    return text


def split_text(text: str, max_chars: int) -> List[str]:
    """
    將長稿切成不超過 max_chars 的分段。

    切割策略（盡量在語意邊界斷開，避免句子被硬切）：
      1. 先用「段落（空行）」切。
      2. 段落仍過長 → 用句末標點（。！？；…!?.; 與換行）切句。
      3. 單句仍過長（極端情況）→ 硬切。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必須為正整數")

    # 統一換行
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    def add_piece(piece: str) -> None:
        """把一個 piece 放進 buffer，必要時先 flush。piece 本身保證 <= max_chars。"""
        nonlocal buf
        if not piece:
            return
        # +1 估個換行/空白接縫
        if buf and len(buf) + len(piece) + 1 > max_chars:
            flush()
        if buf:
            buf = f"{buf}\n{piece}"
        else:
            buf = piece

    for para in paragraphs:
        if len(para) <= max_chars:
            add_piece(para)
            continue

        # 段落過長 → 切句
        sentences = split_sentences(para)
        for sent in sentences:
            if len(sent) <= max_chars:
                add_piece(sent)
            else:
                # 單句仍過長 → 硬切
                for hard in hard_split(sent, max_chars):
                    add_piece(hard)

    flush()
    return chunks


def split_sentences(para: str) -> List[str]:
    """以中英文句末標點切句，保留標點。"""
    # 在句末標點後插入分隔符再切
    marked = re.sub(r"([。！？；…!?;]+)", r"\1\x00", para)
    parts = [s.strip() for s in marked.split("\x00") if s.strip()]
    return parts if parts else [para.strip()]


def hard_split(s: str, max_chars: int) -> List[str]:
    """最後手段：等長硬切（盡量在空白處切，否則直接切）。"""
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            # 嘗試往回找空白，避免切在字中間（對中文影響小，對英文較友善）
            window = s[i:end]
            sp = window.rfind(" ")
            if sp > max_chars * 0.6:  # 只在靠後段找到空白才回退
                end = i + sp + 1
        out.append(s[i:end].strip())
        i = end
    return [c for c in out if c]


# --------------------------------------------------------------------------- #
# ElevenLabs API 呼叫（含重試 / 指數退避）
# --------------------------------------------------------------------------- #

def synthesize_chunk(
    chunk: str,
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    max_retries: int,
    backoff_base: float,
    timeout: int,
    stability: float,
    similarity_boost: float,
) -> bytes:
    """
    合成單一分段，回傳 mp3 bytes。失敗時指數退避重試。
    對 429 / 5xx 重試；對 4xx（401/422 等）視為不可重試，直接拋出清楚錯誤。
    """
    url = f"{API_BASE}/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": chunk,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
        },
    }

    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=timeout
            )
        except requests.exceptions.RequestException as exc:
            last_err = f"網路例外：{exc}"
            if attempt < max_retries:
                wait = backoff_base ** attempt
                print(f"    [retry {attempt + 1}/{max_retries}] {last_err} "
                      f"→ {wait:.1f}s 後重試")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"合成失敗（網路）：{last_err}（已重試 {max_retries} 次）"
            ) from exc

        if resp.status_code == 200:
            if not resp.content:
                last_err = "API 回傳 200 但內容為空"
            else:
                return resp.content

        # 不可重試的客戶端錯誤
        elif resp.status_code in (400, 401, 403, 422):
            detail = _extract_error_detail(resp)
            hint = ""
            if resp.status_code == 401:
                hint = "（檢查 ELEVENLABS_API_KEY 是否正確/有效）"
            elif resp.status_code == 422:
                hint = "（檢查 voice_id / model_id 是否正確，或字元數超限）"
            raise RuntimeError(
                f"合成失敗（HTTP {resp.status_code}）{hint}：{detail}"
            )

        # 可重試：429 限流 / 5xx 伺服器錯誤
        elif resp.status_code == 429 or resp.status_code >= 500:
            detail = _extract_error_detail(resp)
            last_err = f"HTTP {resp.status_code}：{detail}"
        else:
            last_err = f"HTTP {resp.status_code}：{_extract_error_detail(resp)}"

        # 走到這裡代表需要重試
        if attempt < max_retries:
            # 尊重 Retry-After（若有）
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = float(retry_after)
            else:
                wait = backoff_base ** attempt
            print(f"    [retry {attempt + 1}/{max_retries}] {last_err} "
                  f"→ {wait:.1f}s 後重試")
            time.sleep(wait)
        else:
            raise RuntimeError(
                f"合成失敗：{last_err}（已重試 {max_retries} 次）"
            )

    # 理論上不會到這裡
    raise RuntimeError(f"合成失敗：{last_err}")


def _extract_error_detail(resp: "requests.Response") -> str:
    """嘗試從 ElevenLabs 錯誤回應萃取可讀訊息。"""
    try:
        data = resp.json()
        if isinstance(data, dict):
            det = data.get("detail", data)
            if isinstance(det, dict):
                return det.get("message") or json.dumps(det, ensure_ascii=False)
            return str(det)
        return str(data)
    except (ValueError, json.JSONDecodeError):
        return (resp.text or "")[:300]


# --------------------------------------------------------------------------- #
# 合併 mp3
# --------------------------------------------------------------------------- #

def merge_mp3(segments: List[bytes], out_path: Path, concat_mode: bool) -> str:
    """
    合併多段 mp3 → 單一檔案。
    回傳實際採用的合併方式字串（供日誌）。

    - concat_mode=False（預設）：優先用 pydub（需 ffmpeg）重新解碼編碼合併，
      若 pydub/ffmpeg 不可用則自動回退 binary 串接。
    - concat_mode=True：強制 binary 串接（零依賴）。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not concat_mode:
        try:
            return _merge_with_pydub(segments, out_path)
        except Exception as exc:  # noqa: BLE001 — 任何 pydub/ffmpeg 問題都回退
            print(f"[WARN] pydub 合併失敗（{exc}），回退為 binary 串接。")

    return _merge_concat(segments, out_path)


def _merge_with_pydub(segments: List[bytes], out_path: Path) -> str:
    import io
    from pydub import AudioSegment  # 延遲匯入：只有走這條路才需要 pydub/ffmpeg

    combined = AudioSegment.empty()
    gap = AudioSegment.silent(duration=250)  # 段落間 0.25s 停頓，聽感更自然
    for idx, seg in enumerate(segments):
        audio = AudioSegment.from_file(io.BytesIO(seg), format="mp3")
        if idx > 0:
            combined += gap
        combined += audio
    combined.export(out_path, format="mp3")
    return "pydub (ffmpeg)"


def _merge_concat(segments: List[bytes], out_path: Path) -> str:
    with out_path.open("wb") as fh:
        for seg in segments:
            fh.write(seg)
    return "binary concat"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def derive_output_path(input_path: Path, out_dir: Path) -> Path:
    """
    依檔名約定推導輸出路徑：
        xxx.voice.txt → out_dir/xxx.mp3
        xxx.txt       → out_dir/xxx.mp3
    """
    stem = input_path.name
    for suffix in (".voice.txt", ".txt"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        stem = input_path.stem
    return out_dir / f"{stem}.mp3"


def run(args: argparse.Namespace) -> int:
    # 不指定 --config 時，預設讀專案根目錄的 channel_config.json（若存在），
    # 以便自動套用頻道固定的 voice_id 等 TTS 設定。
    if args.config:
        config_path: Optional[Path] = Path(args.config)
    elif DEFAULT_CONFIG_PATH.exists():
        config_path = DEFAULT_CONFIG_PATH
    else:
        config_path = None
    cfg = load_config(config_path)

    voice_id = args.voice_id or cfg.get("voice_id") or DEFAULT_VOICE_ID
    model_id = args.model_id or cfg.get("model_id") or DEFAULT_MODEL_ID
    max_chars = args.max_chars or int(cfg.get("max_chars", DEFAULT_MAX_CHARS))
    stability = args.stability if args.stability is not None else float(
        cfg.get("stability", 0.5))
    similarity = args.similarity if args.similarity is not None else float(
        cfg.get("similarity_boost", 0.75))
    price_per_1k = args.price_per_1k if args.price_per_1k is not None else float(
        cfg.get("price_per_1k", DEFAULT_PRICE_PER_1K))

    input_path = Path(args.input)

    # 讀稿 + 分段
    try:
        text = read_script(input_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[FATAL] {exc}")
        return 2

    chunks = split_text(text, max_chars)
    total_chars = sum(len(c) for c in chunks)

    # 輸出路徑
    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    out_path = Path(args.out) if args.out else derive_output_path(input_path, out_dir)

    # 印出分段計畫
    print("=" * 64)
    print(f"輸入稿     : {input_path}")
    print(f"輸出 mp3   : {out_path}")
    print(f"voice_id   : {voice_id}")
    print(f"model_id   : {model_id}")
    print(f"每段上限   : {max_chars} chars")
    print(f"分段數     : {len(chunks)}")
    print(f"總字元數   : {total_chars} chars")
    est_cost = total_chars / 1000.0 * price_per_1k
    print(f"預估成本   : ~US${est_cost:.4f}  "
          f"(@ US${price_per_1k:.3f}/1k chars)")
    print("=" * 64)
    for i, c in enumerate(chunks, 1):
        preview = c[:50].replace("\n", " ")
        print(f"  [{i:>3}/{len(chunks)}] {len(c):>5} chars | {preview}…")
    print("=" * 64)

    if args.dry_run:
        print("[DRY-RUN] 未呼叫 API、未產生任何檔案。")
        return 0

    # 取得 API key
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("[FATAL] 環境變數 ELEVENLABS_API_KEY 未設定。"
              "請先設定後再執行（或用 --dry-run 試跑）。")
        print("  PowerShell:  $env:ELEVENLABS_API_KEY = 'sk_xxx'")
        return 3

    # 逐段合成
    segments: List[bytes] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"[{i}/{len(chunks)}] 合成中… ({len(chunk)} chars)")
        try:
            audio = synthesize_chunk(
                chunk,
                api_key=api_key,
                voice_id=voice_id,
                model_id=model_id,
                max_retries=args.max_retries,
                backoff_base=args.backoff_base,
                timeout=args.timeout,
                stability=stability,
                similarity_boost=similarity,
            )
        except RuntimeError as exc:
            print(f"[FATAL] 第 {i} 段 {exc}")
            print("  → 已中止；先前段落未寫出。請修正後重跑。")
            return 4
        segments.append(audio)
        print(f"    完成（{len(audio)} bytes）")

    # 合併輸出
    print(f"合併 {len(segments)} 段 → {out_path} …")
    try:
        method = merge_mp3(segments, out_path, concat_mode=args.concat_mode)
    except OSError as exc:
        print(f"[FATAL] 寫出 mp3 失敗：{exc}")
        return 5

    size_kb = out_path.stat().st_size / 1024.0
    print("=" * 64)
    print(f"[OK] 完成！")
    print(f"  檔案     : {out_path}")
    print(f"  大小     : {size_kb:.1f} KB")
    print(f"  合併方式 : {method}")
    print(f"  總字元   : {total_chars} chars (~US${est_cost:.4f})")
    print("=" * 64)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tts_pipeline.py",
        description="ElevenLabs TTS pipeline：純配音稿 .txt → 合併 mp3。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "input",
        help="純配音稿 .txt 路徑（generate_script.py 產出，建議 *.voice.txt）",
    )
    p.add_argument(
        "-o", "--out",
        default=None,
        help="輸出 mp3 完整路徑（預設依檔名約定推導到 output/）",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help=f"輸出資料夾（預設 {DEFAULT_OUTPUT_DIR}）",
    )
    p.add_argument(
        "--config",
        default=None,
        help="channel_config.json 路徑（提供 voice_id/model_id 等預設；"
             "預設自動讀專案根目錄的 channel_config.json）",
    )
    p.add_argument("--voice-id", default=None, help="覆寫 voice_id")
    p.add_argument(
        "--model-id", default=None,
        help=f"覆寫 model_id（預設 {DEFAULT_MODEL_ID}）",
    )
    p.add_argument(
        "--max-chars", type=int, default=None,
        help=f"每段字元上限（預設 {DEFAULT_MAX_CHARS}）",
    )
    p.add_argument(
        "--stability", type=float, default=None,
        help="voice stability 0~1（預設 0.5）",
    )
    p.add_argument(
        "--similarity", type=float, default=None,
        help="similarity_boost 0~1（預設 0.75）",
    )
    p.add_argument(
        "--price-per-1k", type=float, default=None,
        help=f"估價 USD/1000 chars（dry-run 用，預設 {DEFAULT_PRICE_PER_1K}）",
    )
    p.add_argument(
        "--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
        help="每段最大重試次數（指數退避）",
    )
    p.add_argument(
        "--backoff-base", type=float, default=DEFAULT_BACKOFF_BASE,
        help="指數退避底數（等待秒數 = base ** attempt）",
    )
    p.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help="單次 HTTP 請求逾時（秒）",
    )
    p.add_argument(
        "--concat-mode", action="store_true",
        help="強制用 binary 串接合併 mp3（不需 ffmpeg/pydub）",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="不呼叫 API，只印出分段、字元數與預估成本",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n[ABORT] 使用者中斷。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
