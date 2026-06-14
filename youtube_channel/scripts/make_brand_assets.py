#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_brand_assets.py — 生成品牌大頭貼(800x800) + 頻道橫幅(2048x1152)。

存到 assets/brand/。大頭貼/橫幅無法用 API 設定，請在 Studio→自訂→個人資料 上傳。
橫幅關鍵內容置於中央安全區(各裝置都看得到)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"
OUT.mkdir(parents=True, exist_ok=True)

NAVY_TOP = (12, 20, 44)
NAVY_BOT = (30, 48, 92)
ACCENT = (255, 210, 63)   # 品牌黃
WHITE = (240, 244, 255)

BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msjh.ttc"]


def font(size):
    for c in BOLD:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def gradient(w, h):
    base = Image.new("RGB", (w, h), NAVY_TOP)
    top = Image.new("RGB", (w, h), NAVY_BOT)
    mask = Image.new("L", (w, h))
    md = mask.load()
    for y in range(h):
        v = int(255 * (y / h))
        for x in range(w):
            md[x, y] = v
    return Image.composite(top, base, mask)


def center_text(d, cx, y, text, f, fill, stroke=4):
    b = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
    w = b[2] - b[0]
    d.text((cx - w // 2, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def make_avatar():
    S = 800
    img = gradient(S, S)
    d = ImageDraw.Draw(img)
    # 外圈強調環
    d.ellipse([18, 18, S - 18, S - 18], outline=ACCENT, width=16)
    # 上方向上箭頭(量化/成長意象)
    cx = S // 2
    d.line([(cx - 150, 300), (cx - 50, 230), (cx + 30, 285), (cx + 150, 175)], fill=ACCENT, width=20, joint="curve")
    d.polygon([(cx + 150, 175), (cx + 110, 180), (cx + 150, 215)], fill=ACCENT)  # 箭頭
    # 主字「量化阿森」兩行
    center_text(d, cx, 350, "量化", font(180), WHITE, stroke=6)
    center_text(d, cx, 540, "阿森", font(180), ACCENT, stroke=6)
    p = OUT / "avatar.png"
    img.save(p, "PNG")
    print(f"[ok] {p.name} {S}x{S}")
    return p


def make_banner():
    W, H = 2048, 1152
    img = gradient(W, H)
    d = ImageDraw.Draw(img)
    cx = W // 2
    # 安全區大約中央 1546x423；內容置中
    # 上方品牌名
    center_text(d, cx, 430, "量化阿森｜Carson Quant", font(150), WHITE, stroke=6)
    # 強調底線
    d.rectangle([cx - 560, 610, cx + 560, 622], fill=ACCENT)
    # 標語
    center_text(d, cx, 650, "把每一個交易策略拆給你看 · 用數據說話，不喊單", font(58), (190, 205, 230), stroke=3)
    # 四支柱小標
    center_text(d, cx, 740, "策略拆解 ·  派網實操 ·  風控心法 ·  回測實驗室", font(50), ACCENT, stroke=3)
    p = OUT / "banner.png"
    img.save(p, "PNG")
    print(f"[ok] {p.name} {W}x{H}")
    return p


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only in (None, "avatar"):
        make_avatar()
    if only in (None, "banner"):
        make_banner()
    print("完成。")


if __name__ == "__main__":
    main()
