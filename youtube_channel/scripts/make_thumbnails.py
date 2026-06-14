#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_thumbnails.py — 為 6 支影片產生品牌化 YouTube 縮圖 (1280x720 JPG)。

設計：深藍漸層底 + 高對比大字鉤子 + 強調色 + 頻道標。輸出到 assets/thumbnails/。
"""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "assets" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720

FONT_CANDIDATES_BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msjh.ttc"]
FONT_CANDIDATES_REG = [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc"]


def font(size: int, bold: bool = True):
    for c in (FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REG):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


# 每支：line1（強調色）、line2（白）、tag（底部條）、accent 顏色、角落大符號
THUMBS = [
    {"slug": "網格機器人能不能賺錢_原理風險與誰適合",
     "l1": "網格機器人", "l2": "真的能賺嗎？", "tag": "原理 × 風險 × 誰適合",
     "accent": (255, 210, 63), "mark": "?"},
    {"slug": "自動交易機器人實測企劃_規則先講死_EP0",
     "l1": "10萬 實測", "l2": "自動交易機器人", "tag": "規則先講死 ｜ EP.0",
     "accent": (88, 224, 140), "mark": "$"},
    {"slug": "玩網格90趴賠錢的關鍵參數_區間設定",
     "l1": "90% 玩網格", "l2": "都在賠錢", "tag": "問題出在這「1 個參數」",
     "accent": (255, 96, 96), "mark": "!"},
    {"slug": "派網Pionex是什麼_新手搞懂自動交易平台",
     "l1": "Pionex 派網", "l2": "到底是什麼？", "tag": "新手 5 分鐘搞懂自動交易",
     "accent": (90, 184, 255), "mark": "?"},
    {"slug": "DCA定投機器人vs網格機器人_哪個適合你",
     "l1": "定投 vs 網格", "l2": "你該選哪個？", "tag": "新手選擇指南",
     "accent": (255, 210, 63), "mark": "VS"},
    {"slug": "什麼是回測_沒回測別拿真錢碰",
     "l1": "沒回測過", "l2": "別拿真錢碰", "tag": "什麼是回測？量化思維核心",
     "accent": (255, 96, 96), "mark": "!"},
]

CHANNEL = "量化阿森｜Carson Quant"


def gradient_bg(c_top, c_bot):
    base = Image.new("RGB", (W, H), c_top)
    top = Image.new("RGB", (W, H), c_bot)
    mask = Image.new("L", (W, H))
    md = mask.load()
    for y in range(H):
        v = int(255 * (y / H))
        for x in range(W):
            md[x, y] = v
    return Image.composite(top, base, mask)


def draw_text_stroke(d, xy, text, fnt, fill, stroke=(0, 0, 0), sw=6, anchor=None):
    d.text(xy, text, font=fnt, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def make_one(cfg: dict):
    img = gradient_bg((14, 22, 46), (28, 44, 86))
    d = ImageDraw.Draw(img, "RGBA")
    accent = cfg["accent"]

    # 右側大型半透明符號（裝飾）
    mark_font = font(460, bold=True)
    d.text((W - 360, H // 2), cfg["mark"], font=mark_font, fill=(*accent, 46),
           anchor="mm", stroke_width=0)

    # 左側強調色直條
    d.rectangle([0, 0, 18, H], fill=accent)

    # 頻道標（左上 pill）
    tagf = font(38, bold=True)
    ct = CHANNEL
    tb = d.textbbox((0, 0), ct, font=tagf)
    pad = 18
    d.rounded_rectangle([60, 48, 60 + (tb[2] - tb[0]) + pad * 2, 48 + (tb[3] - tb[1]) + pad * 2],
                        radius=14, fill=(255, 255, 255, 28))
    d.text((60 + pad, 48 + pad - tb[1]), ct, font=tagf, fill=(220, 230, 245))

    # 主文兩行
    f1 = font(150, bold=True)
    f2 = font(150, bold=True)
    y = 200
    draw_text_stroke(d, (66, y), cfg["l1"], f1, fill=accent, sw=7)
    # 強調線
    b1 = d.textbbox((66, y), cfg["l1"], font=f1, stroke_width=7)
    d.rectangle([70, b1[3] + 6, 70 + min(620, b1[2] - 66), b1[3] + 20], fill=accent)
    y2 = b1[3] + 40
    draw_text_stroke(d, (66, y2), cfg["l2"], f2, fill=(245, 248, 255), sw=7)

    # 底部 tag 條
    tf = font(54, bold=True)
    bar_h = 96
    d.rectangle([0, H - bar_h, W, H], fill=(*accent, 235))
    tbb = d.textbbox((0, 0), cfg["tag"], font=tf)
    d.text((66, H - bar_h // 2 - (tbb[3] - tbb[1]) // 2 - tbb[1]), cfg["tag"],
           font=tf, fill=(12, 18, 38))

    out = OUT / f"{cfg['slug']}.jpg"
    img.save(out, "JPEG", quality=90)
    kb = out.stat().st_size / 1024
    print(f"[ok] {out.name}  ({kb:.0f} KB)")
    return out


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for cfg in THUMBS:
        if only and only not in cfg["slug"]:
            continue
        make_one(cfg)
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
