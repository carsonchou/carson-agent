# -*- coding: utf-8 -*-
"""抽幀 + contact sheet(人眼判「算不算同一張圖」用)。

用法: python sheet.py <mp4> <輸出jpg> [取樣秒數]

取樣規則與第三輪逐字相同(step/2 起跳、等間隔、8 欄、384×216 格),**只改一件事**:

🔴 時間戳黑底從格子左上角移到左下角。第三輪把它畫在 [x, y, x+96, y+20] ——
那正好蓋住畫面上緣 9% 的左側 25%,也就是段落大標題的起頭。督導在 after_1560.jpg 上
看到的「k面體檢」「寺有真實體驗」是**這塊黑底**蓋掉的,不是影片裡的字被裁掉
(同一張表上較短的標題起點在 x>96,完全沒事,就是證據)。量尺自己弄髒了被量的東西。

刻意**不做** scene detection / 像素差 —— 那量到的是「畫面有沒有動」,不是「這是不是
同一張來源圖」(揭露動畫每一格像素都在動,但來源圖只有一張)。判斷交給人眼。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

FF = "ffmpeg"
TW, TH, COLS = 384, 216, 8


def probe_dur(mp4):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(mp4)], text=True)
    return float(out.strip())


def main():
    mp4, dest = Path(sys.argv[1]), Path(sys.argv[2])
    step = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    dur = probe_dur(mp4)
    tmp = dest.parent / (dest.stem + "_frames")
    tmp.mkdir(parents=True, exist_ok=True)
    ts = [round(t, 2) for t in _frange(step / 2, dur, step)]
    for i, t in enumerate(ts):
        p = tmp / f"f{i:03d}_{t:07.2f}.jpg"
        if not p.exists():
            subprocess.run([FF, "-v", "error", "-ss", str(t), "-i", str(mp4),
                            "-frames:v", "1", "-q:v", "3", str(p)], check=True)
    rows = -(-len(ts) // COLS)
    sheet = Image.new("RGB", (TW * COLS, TH * rows), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(ts):
        p = tmp / f"f{i:03d}_{t:07.2f}.jpg"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB").resize((TW, TH))
        x, y = (i % COLS) * TW, (i // COLS) * TH
        sheet.paste(im, (x, y))
        d.rectangle([x, y + TH - 20, x + 96, y + TH - 1], fill=(0, 0, 0))   # 左下,不壓標題
        d.text((x + 4, y + TH - 16), f"{t:.0f}s", fill=(255, 220, 80))
        d.rectangle([x, y, x + TW - 1, y + TH - 1], outline=(60, 60, 60))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=88)
    print(f"{dest}  幀數={len(ts)} 片長={dur:.1f}s 取樣={step}s")


def _frange(a, b, s):
    while a < b:
        yield a
        a += s


if __name__ == "__main__":
    main()
