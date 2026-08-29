#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts_kokoro.py — 免費・離線神經 TTS（Kokoro-82M + misaki 中文 G2P）。

吃 output/<slug>.voice.txt → output/<slug>.mp3，與 tts_edge.py 同檔名約定，可無痛替換。
永久免費、無字數上限、CPU 即可跑（~4x 即時）。需在「3.11 專用 venv」執行（kokoro-onnx 需 onnxruntime≥1.20，3.9 裝不了）。

模型檔位置：環境變數 KOKORO_DIR 或預設 <專案>/models/{kokoro-v1.0.onnx, voices-v1.0.bin}
聲音：design_system.json 的 kokoro_voice（預設 zm_yunxi 男聲）。

用法：python tts_kokoro.py output/<slug>.voice.txt [--voice zm_yunxi] [--out path] [--speed 1.0]
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "STUDIO" / "design_system.json"
MODEL_DIR = Path(os.environ.get("KOKORO_DIR", str(ROOT / "models")))
DEFAULT_VOICE = "zm_yunxi"
MAX_CHARS = 120  # 每塊上限，避免超過 Kokoro 音素長度上限；按句切再合併


def _cfg():
    voice, speed = DEFAULT_VOICE, 1.0
    try:
        d = json.loads(DESIGN.read_text(encoding="utf-8"))
        voice = d.get("kokoro_voice") or voice
        speed = float(d.get("kokoro_speed", d.get("voice_speed", 1.0)))
    except Exception:
        pass
    return voice, speed


def _chunks(text: str):
    """依中文標點/換行切句，再把短句併到 ~MAX_CHARS，兼顧發音穩定與語氣連貫。"""
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    buf, out = "", []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) <= MAX_CHARS:
            buf += p
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out or [text]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("voice_txt")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--speed", type=float, default=None)
    args = ap.parse_args()

    src = Path(args.voice_txt)
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        print(f"[FATAL] 找不到配音稿：{src}", file=sys.stderr); return 2
    text = src.read_text(encoding="utf-8").strip()
    if not text:
        print("[FATAL] 配音稿為空。", file=sys.stderr); return 2
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from tts_text import normalize
        text = normalize(text)  # 數字/%→口語、斷句，與 edge/minimax 一致
    except Exception:
        pass

    voice, speed = _cfg()
    if args.voice:
        voice = args.voice
    if args.speed:
        speed = args.speed
    out = Path(args.out) if args.out else ROOT / "output" / (
        (src.name[:-10] if src.name.endswith(".voice.txt") else src.stem) + ".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)

    onnx = MODEL_DIR / "kokoro-v1.0.onnx"
    voices = MODEL_DIR / "voices-v1.0.bin"
    if not onnx.exists() or not voices.exists():
        print(f"[FATAL] 找不到模型檔：{onnx} / {voices}", file=sys.stderr); return 2

    try:
        import numpy as np
        import soundfile as sf
        from kokoro_onnx import Kokoro
        from misaki import zh
    except Exception as e:
        print(f"[FATAL] 套件缺失（需在 3.11 kokoro venv 跑）：{e}", file=sys.stderr); return 2

    k = Kokoro(str(onnx), str(voices))
    g2p = zh.ZHG2P()
    sr = None
    audio = []
    for i, ch in enumerate(_chunks(text)):
        try:
            ps, _ = g2p(ch)
            if not ps:
                continue
            samples, sr = k.create(ps, voice=voice, speed=speed, is_phonemes=True)
            audio.append(samples)
        except Exception as e:
            print(f"[warn] 第 {i+1} 塊合成失敗：{repr(e)[:160]}", file=sys.stderr)
    if not audio or sr is None:
        print("[FATAL] Kokoro 全部塊合成失敗。", file=sys.stderr); return 3

    import numpy as np
    sil = np.zeros(int(sr * 0.18), dtype=audio[0].dtype)
    full = audio[0]
    for a in audio[1:]:
        full = np.concatenate([full, sil, a])

    wav = Path(tempfile.gettempdir()) / (out.stem + ".kok.wav")
    sf.write(str(wav), full, sr)
    # wav → mp3（pipeline 統一吃 mp3）
    # 🔴 2026-08-29:先寫 .part 再原子改名,理由同 tts_edge 的紅字——ffmpeg 直接寫最終路徑時,
    # 轉檔那幾秒 output/{slug}.mp3 是個「格式合法、內容不全」的檔;渲染迴圈只看
    # `mp3.exists()` 就會撿走,渲出來的片跟半截音檔自洽 → 三道截斷閘門全部看不見。
    # (edge 引擎那邊實測過真的會撞上:中美晶5483 少掉 23% 的旁白。)
    _part = out.with_suffix(out.suffix + ".part")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                        "-b:a", "128k", str(_part)], check=True)
        os.replace(str(_part), str(out))
        wav.unlink(missing_ok=True)
    except Exception as e:
        print(f"[FATAL] ffmpeg 轉 mp3 失敗：{e}", file=sys.stderr); return 3

    if out.exists() and out.stat().st_size > 0:
        print(f"[ok] Kokoro 配音完成：{out}（{out.stat().st_size/1024:.0f} KB）voice={voice} chars={len(text)}")
        return 0
    print("[FATAL] 輸出檔為空。", file=sys.stderr); return 3


if __name__ == "__main__":
    raise SystemExit(main())
