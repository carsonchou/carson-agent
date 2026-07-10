#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_cta_card.py — 產「訂閱量化阿森 YouTube」片尾卡(給 IG/TikTok 版接尾用 + YT 長片片尾)。

暗色卡(Carson 偏好暗色 UI)+ 暗金品牌色 + 克制發光。
  · make()            → assets/cta_yt_endcard.png       1080x1920(直式，Shorts 主力格式)
  · make_horizontal()  → assets/cta_yt_endcard_16x9.png   1920x1080(橫式，B6：長片 16:9 用，
    同一套暗色訂閱卡設計，避免直式卡被 append_yt_cta.py 硬 scale 成長片比例時整個拉伸變形)
產一次存檔可重用;不存在才產。字型沿用 make_video 的 _load_font。
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
DEST = ROOT / "assets" / "cta_yt_endcard.png"
DEST_16X9 = ROOT / "assets" / "cta_yt_endcard_16x9.png"


def _font(size, bold=True):
    try:
        import make_video as mv
        return mv._load_font(size, bold=bold)
    except Exception:
        from PIL import ImageFont
        return ImageFont.load_default()


def make(dest: Path = DEST, force: bool = False) -> Path:
    if dest.exists() and not force:
        return dest
    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (10, 12, 16))  # 深近黑
    d = ImageDraw.Draw(img)
    # 暗金漸層底(克制)
    for y in range(H):
        t = y / H
        r = int(10 + 24 * t); g = int(12 + 18 * t); b = int(16 + 8 * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    gold = (212, 175, 90)
    white = (238, 238, 238)
    gray = (150, 150, 155)

    def center(text, y, font, fill):
        bb = d.textbbox((0, 0), text, font=font)
        w = bb[2] - bb[0]
        d.text(((W - w) // 2, y), text, font=font, fill=fill)

    # 紅色 YouTube 播放鈕示意(圓角矩形+三角)
    bx0, by0, bx1, by1 = W // 2 - 120, 560, W // 2 + 120, 720
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=36, fill=(200, 40, 40))
    d.polygon([(W // 2 - 30, 610), (W // 2 - 30, 670), (W // 2 + 40, 640)], fill=white)

    center("看完了？", 840, _font(64, bold=False), gray)
    center("訂閱 量化阿森", 940, _font(104), gold)
    center("YouTube 搜尋「量化阿森」", 1090, _font(58), white)
    center("每日更新 · 完整版看這裡 🔔", 1200, _font(50, bold=False), gray)
    center("不喊單 · 只認數據 · 幫你避雷", 1320, _font(44, bold=False), (110, 110, 115))

    # 克制發光:文字層 blur 疊加
    glow = img.filter(ImageFilter.GaussianBlur(6))
    img = Image.blend(img, glow, 0.18)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


def make_horizontal(dest: Path = DEST_16X9, force: bool = False) -> Path:
    """B6：16:9 橫式片尾卡，同一套暗色訂閱卡設計語言，佈局改左圖右字(適合長片收尾滿版)。"""
    if dest.exists() and not force:
        return dest
    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), (10, 12, 16))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(10 + 24 * t); g = int(12 + 18 * t); b = int(16 + 8 * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    gold = (212, 175, 90)
    white = (238, 238, 238)
    gray = (150, 150, 155)

    def left(text, y, font, fill, x0=200):
        d.text((x0, y), text, font=font, fill=fill)

    # 左側：紅色 YouTube 播放鈕示意
    cx, cy = 420, H // 2
    bx0, by0, bx1, by1 = cx - 130, cy - 90, cx + 130, cy + 90
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=36, fill=(200, 40, 40))
    d.polygon([(cx - 32, cy - 55), (cx - 32, cy + 55), (cx + 46, cy)], fill=white)

    # 右側：文字堆疊(垂直置中)
    x0 = 660
    left("看完了？", cy - 220, _font(52, bold=False), gray, x0)
    left("訂閱 量化阿森", cy - 140, _font(96), gold, x0)
    left("YouTube 搜尋「量化阿森」", cy - 20, _font(50), white, x0)
    left("每日更新 · 完整版看這裡 🔔", cy + 70, _font(42, bold=False), gray, x0)
    left("不喊單 · 只認數據 · 幫你避雷", cy + 150, _font(38, bold=False), (110, 110, 115), x0)

    glow = img.filter(ImageFilter.GaussianBlur(6))
    img = Image.blend(img, glow, 0.18)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


if __name__ == "__main__":
    force = "--force" in sys.argv
    p = make(force=force)
    print(f"[cta_card] {'重產' if force else '確認'}片尾卡(直式):{p}（{p.stat().st_size // 1024} KB）")
    p16 = make_horizontal(force=force)
    print(f"[cta_card] {'重產' if force else '確認'}片尾卡(16:9):{p16}（{p16.stat().st_size // 1024} KB）")
