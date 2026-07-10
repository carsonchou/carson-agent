#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_advisor.py — 生「量化阿森」頻道 AI 真人顧問形象候選圖(治「農場 vs 真人」)。

一次性工具(非產線 cron)。重用 gen_mascot.py 的 _gen_pollinations(免費 Pollinations
圖生 API,無金鑰)。生多張不同 seed / 構圖的候選,存到
assets/brand/advisor_candidates/advisor_v{n}.png,人工挑選後才會被正式資產採用
(本腳本只新增候選,不覆寫任何既有 brand 資產)。

誠信/合規提醒(務必落地,見任務回報):
  - 這是 AI 生成的「虛擬顧問形象」,不冒充任何真實存在的特定人物。
  - 頻道 about / 影片說明之後要加註 AI 輔助揭露(YouTube AI-generated content
    disclosure),別讓觀眾誤以為是真人出鏡未揭露。

用法:
  python scripts/gen_advisor.py            # 全生(6 張人像候選 + 2 張縮圖構圖候選)
  python scripts/gen_advisor.py --only-thumb   # 只生縮圖構圖候選
  python scripts/gen_advisor.py --n 4          # 只生前 N 張人像候選(除錯用)
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_mascot import _gen_pollinations  # noqa: E402  (重用既有免費生圖呼叫,不改該檔)

ASSETS = ROOT / "assets"
CANDIDATES = ASSETS / "brand" / "advisor_candidates"
CANDIDATES.mkdir(parents=True, exist_ok=True)

# ---- 共用氣質描述(冷靜、理性、數據派、非浮誇,呼應「不喊單只認數據」定位) ----
BASE_IDENTITY = (
    "Professional Taiwanese Asian male quantitative finance analyst, early-to-mid 30s, "
    "calm confident trustworthy expression, composed and understated demeanor — NOT "
    "flashy, NOT a hype salesman, no exaggerated grin, no thumbs-up, no money gestures. "
    "Dark modern studio background, softly blurred financial data screens and faint "
    "candlestick chart glow in the background, cinematic moody rim lighting with a subtle "
    "cool teal accent, wearing a dark minimalist blazer or dark turtleneck, no flashy "
    "jewelry or logos. Photorealistic portrait photography, 85mm lens look, shallow depth "
    "of field, sharp focus on the eyes, ultra detailed natural skin texture, high dynamic "
    "range, high quality, trustworthy data-driven quant advisor aesthetic."
)

# 人像候選:6 張,seed + 構圖/表情微調
PORTRAIT_VARIANTS = [
    # (idx, seed, extra clause)
    (1, 4101, "Straight-on head-and-shoulders portrait, direct eye contact with camera, "
              "neutral calm expression, symmetrical framing."),
    (2, 4102, "Slight three-quarter angle head-and-shoulders portrait, arms crossed just "
              "entering frame, composed serious expression, analytical gaze slightly off-camera."),
    (3, 4103, "Half-body portrait, standing, arms crossed, dark blazer, confident but "
              "reserved posture, dark studio backdrop with faint blue data glow."),
    (4, 4104, "Half-body portrait, seated at a dark desk with two blurred monitors showing "
              "faint chart lines behind him, hands loosely clasped on the desk, focused expression."),
    (5, 4105, "Close-up head portrait, subtle thoughtful half-smile (not a big grin), warm "
              "but restrained, soft rim light along jawline, dark background."),
    (6, 4106, "Head-and-shoulders portrait, slightly lower camera angle for authority, calm "
              "steady gaze, minimal dark turtleneck, cool color grading."),
]

# 縮圖構圖候選:人物偏一側,留大片空間放大字
THUMB_VARIANTS = [
    (1, 4201, "Thumbnail composition: subject positioned in the right third of the frame, "
              "facing toward camera-left, half-body, arms crossed, dark blazer, confident "
              "composed expression. Left two-thirds of the frame is empty dark gradient "
              "background with faint chart lines, reserved as clean negative space for bold "
              "text overlay. Vivid but not oversaturated, cinematic YouTube thumbnail lighting."),
    (2, 4202, "Thumbnail composition: subject positioned in the left third of the frame, "
              "facing toward camera-right, half-body, one hand gesturing subtly toward a "
              "floating translucent chart graphic, calm serious expression. Right two-thirds "
              "of the frame is empty dark gradient background reserved for bold text overlay. "
              "Cinematic YouTube thumbnail lighting, high contrast, not cartoonish."),
]


def _gen_one(prompt: str, seed: int, out_path: Path) -> bool:
    print(f"[gen] seed={seed} -> {out_path.relative_to(ROOT)} ...")
    try:
        raw = _gen_pollinations(prompt, seed)
    except Exception as ex:  # noqa: BLE001
        print(f"  [FAIL] seed={seed}: {ex}", file=sys.stderr)
        return False
    out_path.write_bytes(raw)
    print(f"  [ok] {len(raw)} bytes")
    return True


def gen_portraits(n: int | None = None):
    variants = PORTRAIT_VARIANTS if n is None else PORTRAIT_VARIANTS[:n]
    for idx, seed, clause in variants:
        prompt = BASE_IDENTITY + " " + clause
        out = CANDIDATES / f"advisor_v{idx}.png"
        _gen_one(prompt, seed, out)
        time.sleep(1)


def gen_thumbs():
    for idx, seed, clause in THUMB_VARIANTS:
        prompt = BASE_IDENTITY + " " + clause
        out = CANDIDATES / f"advisor_thumb_v{idx}.png"
        _gen_one(prompt, seed, out)
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-thumb", action="store_true", help="只生縮圖構圖候選")
    ap.add_argument("--only-portrait", action="store_true", help="只生人像候選")
    ap.add_argument("--n", type=int, default=None, help="只生前 N 張人像候選(除錯用)")
    a = ap.parse_args()

    if a.only_thumb:
        gen_thumbs()
    elif a.only_portrait:
        gen_portraits(a.n)
    else:
        gen_portraits(a.n)
        gen_thumbs()

    print(f"[done] 候選圖 -> {CANDIDATES.relative_to(ROOT)}")
    print("[提醒] AI 生成虛擬顧問形象,不冒充真實特定人物;頻道 about/影片說明"
          "之後要加註 AI 輔助揭露(YouTube AI-generated content disclosure)。")


if __name__ == "__main__":
    main()
