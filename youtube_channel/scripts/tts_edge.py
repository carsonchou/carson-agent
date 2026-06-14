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
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import edge_tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "zh-TW-YunJheNeural"


async def _synth(text: str, voice: str, rate: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))


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

    if args.out:
        out = Path(args.out)
    else:
        name = src.name
        name = name[:-10] if name.endswith(".voice.txt") else src.stem
        out = PROJECT_ROOT / "output" / f"{name}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    last_err = None
    for attempt in range(4):
        try:
            asyncio.run(_synth(text, args.voice, args.rate, out))
            if out.exists() and out.stat().st_size > 0:
                print(f"[ok] 配音完成：{out}（{out.stat().st_size/1024:.0f} KB）voice={args.voice} chars={len(text)}")
                return 0
            raise RuntimeError("輸出檔為空")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[warn] 第 {attempt+1}/4 次失敗：{exc}", file=sys.stderr)

    print(f"[FATAL] 配音失敗（網路？）：{last_err}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
