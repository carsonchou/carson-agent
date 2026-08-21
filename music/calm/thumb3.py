#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumb3.py — 三支氛圍片縮圖:從成片抽最美的一幀 + 極簡文字。

氛圍類縮圖的行規跟主頻道相反:畫面本身就是賣點,文字越少越好。
統一版式 = 品牌識別:左下角小字標籤 + 細分隔線 + 時長徽章。
抽幀策略:取 30/35/40 分鐘三個候選,選「墨水覆蓋面積」最大的那幀
(畫面最豐富的時刻,而不是剛注入的空白期)。
"""
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent

VIDEOS = {
    "A": {"file": "final_A.mp4", "label": "DEEP FOCUS", "sub": "1 HOUR · INK IN WATER",
          "dark_text": True},
    "B": {"file": "final_B.mp4", "label": "SLEEP", "sub": "1 HOUR · DARK SCREEN",
          "dark_text": False},
    "C": {"file": "final_C.mp4", "label": "GENTLE RAIN", "sub": "1 HOUR · RAIN & INK",
          "dark_text": True},
}


def grab(video, mins):
    out = ROOT / f"_cand_{video}_{mins}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(mins * 60),
                    "-i", str(ROOT / video), "-frames:v", "1", str(out)], check=True)
    return out


def ink_coverage(png, dark_theme):
    a = np.asarray(Image.open(png).convert("L"), np.float32) / 255.0
    # 亮底:墨=偏暗處;暗底:墨=偏亮處
    return float((a < 0.75).mean()) if not dark_theme else float((a > 0.30).mean())


def font(size):
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(key, cfg):
    dark_theme = not cfg["dark_text"]        # 暗底片配亮字
    best, score = None, -1.0
    for m in (30, 35, 40):
        p = grab(cfg["file"], m)
        s = ink_coverage(p, dark_theme)
        if s > score:
            best, score = p, s
    img = Image.open(best).convert("RGB")
    d = ImageDraw.Draw(img)
    W, H = img.size
    fg = (30, 32, 38) if cfg["dark_text"] else (238, 240, 245)
    f_big, f_sm = font(110), font(46)
    x, y = 90, H - 300
    d.text((x, y), cfg["label"], font=f_big, fill=fg)
    d.rectangle([x + 4, y + 150, x + 460, y + 156], fill=fg)
    d.text((x + 4, y + 178), cfg["sub"], font=f_sm, fill=fg)
    out = ROOT / f"thumb_{key}.png"
    img.save(out)
    print(f"  {out.name}  覆蓋率 {score:.2f}  來源 {best.name}")
    for m in (30, 35, 40):
        (ROOT / f"_cand_{cfg['file'].split('.')[0].split('_')[1]}_{m}.png").unlink(missing_ok=True)


if __name__ == "__main__":
    for key, cfg in VIDEOS.items():
        if (ROOT / cfg["file"]).exists():
            make(key, cfg)
        else:
            print(f"  {cfg['file']} 不存在,跳過")
