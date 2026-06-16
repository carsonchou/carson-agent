#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts_minimax.py — MiniMax T2A 配音引擎（自然中文，付費）。

吃 output/<slug>.voice.txt → output/<slug>.mp3，與 tts_edge.py 同檔名約定，可無痛替換。
聲音/模型讀 STUDIO/design_system.json（voice_id / tts_model / voice_speed），方便隨時換聲音。
需環境變數 MINIMAX_API_KEY。

用法：python scripts/tts_minimax.py output/<slug>.voice.txt [--voice X] [--out path] [--speed 1.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.minimax.io/v1/t2a_v2"
DESIGN = ROOT / "STUDIO" / "design_system.json"
DEFAULT_VOICE = "Chinese (Mandarin)_Reliable_Executive"
DEFAULT_MODEL = "speech-2.8-hd"


def _cfg():
    """從 design_system.json 讀聲音設定（換聲音只要改那檔）。"""
    vid, model, speed = DEFAULT_VOICE, DEFAULT_MODEL, 1.0
    try:
        d = json.loads(DESIGN.read_text(encoding="utf-8"))
        vid = d.get("voice_id") or vid
        model = d.get("tts_model") or model
        speed = float(d.get("voice_speed", 1.0))
    except Exception:
        pass
    return vid, model, speed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("voice_txt")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--speed", type=float, default=None)
    args = ap.parse_args()

    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        print("[FATAL] 無 MINIMAX_API_KEY 環境變數。", file=sys.stderr)
        return 2
    src = Path(args.voice_txt)
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        print(f"[FATAL] 找不到配音稿：{src}", file=sys.stderr)
        return 2
    text = src.read_text(encoding="utf-8").strip()
    if not text:
        print("[FATAL] 配音稿為空。", file=sys.stderr)
        return 2
    try:
        from tts_text import normalize
        text = normalize(text)  # 數字/%/小數→口語念法、長句斷句，讓 TTS 念得對、斷得順
    except Exception:
        pass

    vid, model, speed = _cfg()
    if args.voice:
        vid = args.voice
    if args.speed:
        speed = args.speed
    if args.out:
        out = Path(args.out)
    else:
        name = src.name[:-10] if src.name.endswith(".voice.txt") else src.stem
        out = ROOT / "output" / f"{name}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)

    body = {
        "model": model, "text": text,
        "voice_setting": {"voice_id": vid, "speed": speed, "vol": 1, "pitch": 0},
        "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000},
    }
    last = None
    for i in range(5):
        try:
            r = requests.post(API, headers={"Authorization": "Bearer " + key,
                                            "Content-Type": "application/json"}, json=body, timeout=120)
            d = r.json()
            br = d.get("base_resp", {})
            if br.get("status_code") == 0 and d.get("data", {}).get("audio"):
                out.write_bytes(bytes.fromhex(d["data"]["audio"]))
                if out.stat().st_size > 0:
                    print(f"[ok] MiniMax 配音完成：{out}（{out.stat().st_size/1024:.0f} KB）voice={vid} chars={len(text)}")
                    return 0
            last = br or (r.text[:140])
            print(f"[warn] 第 {i+1}/5 次失敗：{last}", file=sys.stderr)
            # 餘額不足/聲音不存在等硬錯誤不必重試
            if isinstance(br, dict) and br.get("status_code") in (1008, 2054, 1004):
                break
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:140]
            print(f"[warn] 第 {i+1}/5 次例外：{last}", file=sys.stderr)
        time.sleep(min(2.0 * (i + 1), 8.0))
    print(f"[FATAL] MiniMax 配音失敗：{last}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
