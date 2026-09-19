#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumb3.py — 三支氛圍片縮圖。

## 兩個設計決定的依據(審核 R4 實測)
1. **挑幀不能只看覆蓋率**:要看「偏離底色 > 80 的像素比例」——那才是縮圖尺寸下
   還看得見的內容。slate 這項只有 0.31%(ink 7.28% / tea 19.65%),用覆蓋率挑
   會挑到一片看不清的霧。
2. **暗底主題不能直接抽幀當縮圖**:slate 本體 mean 48,手機上滑過去幾乎全黑。
   縮圖另外做調亮曲線 + 提飽和(只動縮圖,不動影片本體——影片要暗才助眠)。

版式極簡:氛圍類縮圖畫面就是賣點,文字越少越好;統一版式 = 品牌識別。
"""
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent

VIDEOS = {
    "B": {"file": "final_B.mp4", "label": "SLEEP", "sub": "1 HOUR · DARK SCREEN",
          "dark": True},
    "C": {"file": "final_C.mp4", "label": "GENTLE RAIN", "sub": "1 HOUR · RAIN & INK",
          "dark": False},
    "A": {"file": "final_A.mp4", "label": "DEEP FOCUS", "sub": "1 HOUR · INK IN WATER",
          "dark": False},
}
CAND_MINS = (4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 58)


def grab(key, video, mins):
    out = ROOT / f"_cand_{key}_{mins}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(mins * 60),
                    "-i", str(ROOT / video), "-frames:v", "1", str(out)], check=True)
    return out


def visible_score(png):
    """縮圖尺寸下真正看得見的內容比例(偏離底色 > 80),而非單純覆蓋率。"""
    g = np.asarray(Image.open(png).convert("L"), np.float32)
    return float((np.abs(g - np.median(g)) > 80).mean())


def punch(img, dark):
    """縮圖專用調子。影片本體不動——它要暗才助眠;縮圖要亮才有人點。"""
    a = np.asarray(img, np.float32) / 255.0
    if dark:
        a = a ** 0.62                       # 提中間調(暗部拉起來最多)
        a = np.clip((a - 0.06) * 1.22, 0, 1)  # 黑點微降 + 對比
    else:
        a = np.clip((a - 0.5) * 1.10 + 0.5, 0, 1)
    out = Image.fromarray((a * 255).astype(np.uint8))
    return ImageEnhance.Color(out).enhance(1.35 if dark else 1.15)


def font(size):
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(key, cfg):
    cands = []
    for m in CAND_MINS:
        try:
            p = grab(key, cfg["file"], m)
        except subprocess.CalledProcessError:
            continue                        # 片長不足就跳過該時點
        cands.append((visible_score(p), m, p))
    if not cands:
        print(f"  {key}: 抽不到候選幀,跳過")
        return
    score, mins, best = max(cands, key=lambda c: c[0])

    img = punch(Image.open(best).convert("RGB"), cfg["dark"])
    d = ImageDraw.Draw(img)
    W, H = img.size
    fg = (238, 240, 245) if cfg["dark"] else (30, 32, 38)
    # 文字底下壓一層極淡的暗/亮幕,保證任何畫面上都讀得到。
    # 用漸層不用矩形:硬邊在縮圖上是一條明顯的橫線(實測可見)。
    band = 380
    a = np.zeros((H, W), np.float32)
    ramp = np.linspace(0.0, 1.0, band, dtype=np.float32) ** 1.6
    a[H - band:] = ramp[:, None]
    peak = 78 if cfg["dark"] else 96
    veil = np.zeros((H, W, 4), np.uint8)
    veil[..., :3] = 0 if cfg["dark"] else 255
    veil[..., 3] = (a * peak).astype(np.uint8)
    img = Image.alpha_composite(img.convert("RGBA"),
                                Image.fromarray(veil, "RGBA")).convert("RGB")
    d = ImageDraw.Draw(img)
    f_big, f_sm = font(112), font(46)
    x, y = 92, H - 292
    d.text((x, y), cfg["label"], font=f_big, fill=fg)
    d.rectangle([x + 4, y + 152, x + 470, y + 158], fill=fg)
    d.text((x + 4, y + 180), cfg["sub"], font=f_sm, fill=fg)
    out = ROOT / f"thumb_{key}.png"
    img.save(out)
    g = np.asarray(img.convert("L"), np.float32)
    print(f"  {out.name}  取 {mins} 分處(可見內容 {score*100:.2f}%)  "
          f"縮圖亮度 {g.mean():.0f}")
    for _, _, p in cands:
        p.unlink(missing_ok=True)


if __name__ == "__main__":
    for key, cfg in VIDEOS.items():
        if (ROOT / cfg["file"]).exists():
            make(key, cfg)
        else:
            print(f"  {cfg['file']} 尚未產出,跳過")
