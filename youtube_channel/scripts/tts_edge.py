#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts_edge.py — 免費・無限量配音引擎（微軟 Edge TTS）。

吃 output/<slug>.voice.txt → output/<slug>.mp3，與 tts_pipeline.py 同檔名約定，
make_video.py 可直接沿用。需網路，但完全免費、無字數上限——適合每日量產。

預設聲音 zh-TW-YunJheNeural（台灣男聲，沉穩顧問感）。
其他可選：zh-TW-HsiaoChenNeural(女)、zh-CN-YunxiNeural(陸男)、zh-CN-YunyangNeural(播報男)。

用法：
  python scripts\\tts_edge.py output\\<slug>.voice.txt
  python scripts\\tts_edge.py output\\<slug>.voice.txt --voice zh-CN-YunyangNeural --rate +10%
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import edge_tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "zh-TW-YunJheNeural"
# 機房 IP 常被微軟間歇節流（「No audio received」）；多次重試 + 退避 + 語音輪替＝接近 100% 成片。
FALLBACK_VOICES = ["zh-TW-HsiaoChenNeural", "zh-TW-HsiaoYuNeural",
                   "zh-CN-YunyangNeural", "zh-CN-YunxiNeural"]
MAX_ATTEMPTS = 12

# 關鍵情緒詞加重（標點停頓法）：Edge TTS 對中文 SSML emphasis/prosody 實測「不支援」——
# 標籤會被當字面念出來（<emphasis level='strong'>賠光…</> 音檔比純文字長 2.4 倍），故不走 SSML。
# 改在關鍵詞前補一個頓號，製造「頓一下、再砸重點」的語氣停頓＝聽感上的重音。
# 預設保守：可用環境變數 TTS_EMPHASIS=0 關閉；只加前側一個頓號、只處理每詞首次出現、全篇最多 4 處，
# 且前一字已是標點就不加、任何例外一律回原文——絕不讓這增強弄壞或拖長配音。
_EMPHASIS_WORDS = ("賠光", "歸零", "爆倉", "血本無歸", "割韭菜", "韭菜", "被割",
                   "假的", "詐騙", "騙局", "慘賠", "一無所有", "全賠")
_PAUSE = "、"
_NO_PAUSE_BEFORE = "。！？，、；：「」『』（）…、 \n\t"


def _emphasize(text: str) -> str:
    """關鍵情緒詞前補頓號製造重音停頓（保守·可 TTS_EMPHASIS=0 關）。任何狀況出錯都回原文，絕不弄壞配音。"""
    import os
    if os.environ.get("TTS_EMPHASIS", "1").strip() == "0" or not text:
        return text
    try:
        out = text
        used = 0
        for w in _EMPHASIS_WORDS:
            if used >= 4:
                break
            idx = out.find(w)
            if idx <= 0:  # 找不到(-1)或就在開頭(前面沒東西可頓)都跳過
                continue
            if out[idx - 1] in _NO_PAUSE_BEFORE:
                continue  # 前面已有標點/停頓，不重複加
            out = out[:idx] + _PAUSE + out[idx:]
            used += 1
        return out
    except Exception:
        return text


async def _synth(text: str, voice: str, rate: str, out_path: Path) -> list:
    """串流合成:一邊寫音檔,一邊擷取 WordBoundary 真實時間戳(供字幕精準同步)。
    回傳 [{"t":秒,"d":秒,"text":詞}]。串流失敗則退回 .save(無時間戳,回 [])——絕不讓字幕同步需求弄壞配音。"""
    marks = []
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                ct = chunk.get("type")
                if ct == "audio" and chunk.get("data"):
                    f.write(chunk["data"])
                elif ct in ("SentenceBoundary", "WordBoundary"):
                    # offset/duration 單位為 100 奈秒(1e7=1 秒)。zh-TW 實測吐 SentenceBoundary(句級);
                    # 也一併收 WordBoundary(若該語音有吐)。供字幕真實對齊。
                    marks.append({"t": round(chunk.get("offset", 0) / 1e7, 3),
                                  "d": round(chunk.get("duration", 0) / 1e7, 3),
                                  "text": chunk.get("text", ""), "type": ct})
        if out_path.exists() and out_path.stat().st_size > 0:
            return marks
        raise RuntimeError("串流輸出為空")
    except Exception:
        # 退回最穩的 save(可能因串流被節流),此時無逐字時間戳
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(out_path))
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("voice_txt", help="output/<slug>.voice.txt 路徑")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default="+8%", help="語速，如 +8% / -5%")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.voice_txt)
    if not src.is_absolute():
        src = PROJECT_ROOT / src
    if not src.exists():
        print(f"[FATAL] 找不到配音稿：{src}", file=sys.stderr)
        return 2
    text = src.read_text(encoding="utf-8").strip()
    if not text:
        print("[FATAL] 配音稿為空。", file=sys.stderr)
        return 2
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from tts_text import normalize
        text = normalize(text)  # 數字/%/小數→口語念法、長句斷句
    except Exception:
        pass

    text = _emphasize(text)  # 關鍵情緒詞前補頓號＝聽感重音（保守·出錯回原文·TTS_EMPHASIS=0 可關）

    if args.out:
        out = Path(args.out)
    else:
        name = src.name
        name = name[:-10] if name.endswith(".voice.txt") else src.stem
        out = PROJECT_ROOT / "output" / f"{name}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 語音輪替清單：主聲音先試，連續失敗就換備援聲音（避開單一聲音被節流）。
    voices = [args.voice] + [v for v in FALLBACK_VOICES if v != args.voice]
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        voice = voices[(attempt // 3) % len(voices)]  # 每 3 次換一個聲音
        try:
            words = asyncio.run(_synth(text, voice, args.rate, out))
            if out.exists() and out.stat().st_size > 0:
                # 寫逐字時間戳 sidecar(供 make_video 精準字幕);串流被節流退回 .save 時 words 為空,靜默略過。
                if words:
                    try:
                        import json as _json
                        wt = out.parent / f"{out.stem}.wordtimes.json"
                        wt.write_text(_json.dumps(words, ensure_ascii=False), encoding="utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                print(f"[ok] 配音完成：{out}（{out.stat().st_size/1024:.0f} KB）voice={voice} chars={len(text)} 詞時戳={len(words)} 第{attempt+1}次")
                return 0
            raise RuntimeError("輸出檔為空")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[warn] 第 {attempt+1}/{MAX_ATTEMPTS} 次失敗（voice={voice}）：{exc}", file=sys.stderr)
            time.sleep(min(1.5 * (attempt + 1), 8.0))  # 退避等待，避免持續撞節流

    print(f"[FATAL] 配音失敗（網路/節流？）：{last_err}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
