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


def make_intro_template():
    """品牌固定片頭底圖(1920x1080)：漸層+淡網格+底部強調條+頂部品牌小字。
    中央刻意留白，交給 render_brand_intro 在渲染時壓上該片標題。存 assets/brand/intro_template.png。"""
    W, H = 1920, 1080
    img = gradient(W, H).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    ac = ACCENT
    step = 120
    for gx in range(0, W, step):
        d.line([(gx, 0), (gx, H)], fill=(*ac, 14), width=1)
    for gy in range(0, H, step):
        d.line([(0, gy), (W, gy)], fill=(*ac, 14), width=1)
    # 中央偏上柔和光暈（給標題襯底、又不擋字）
    cx, cy = W // 2, int(H * 0.42)
    for rr, a in ((520, 12), (380, 16), (250, 22)):
        d.ellipse([cx - rr, cy - int(rr * 0.6), cx + rr, cy + int(rr * 0.6)], fill=(*ac, a))
    # 底部強調條 + 頂部品牌小字
    d.rectangle([0, H - 10, W, H], fill=ac)
    center_text(d, cx, 56, "量化阿森 · Carson Quant", font(46), WHITE, stroke=3)
    p = OUT / "intro_template.png"
    img.convert("RGB").save(p, "PNG")
    print(f"[ok] {p.name} {W}x{H}")
    return p


def make_logo():
    """透明底品牌 logo(512x512)：深色圓角方底+金色上升箭頭+「量」字。供 render_brand_intro 貼右上角。"""
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = S // 2
    d.rounded_rectangle([40, 40, S - 40, S - 40], radius=90, fill=(12, 20, 44, 235), outline=ACCENT, width=10)
    d.line([(150, 340), (230, 262), (300, 312), (382, 200)], fill=ACCENT, width=22, joint="curve")
    d.polygon([(382, 200), (338, 210), (378, 246)], fill=ACCENT)
    center_text(d, cx, 300, "量", font(150), WHITE, stroke=5)
    p = OUT / "logo.png"
    img.save(p, "PNG")
    print(f"[ok] {p.name} {S}x{S} (透明底)")
    return p


def _draw_mascot(expr):
    """畫一隻簡單量化機器人(圓角方臉+天線+反應爐核心)，依 expr 換表情。回傳 1024x1024 透明 PIL Image。
    expr: neutral / happy / panic / smug。暗金 HUD 美學。**placeholder，最終需真美術替換。**"""
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = S // 2, int(S * 0.44)
    hw, hh = int(S * 0.30), int(S * 0.26)
    face = [cx - hw, cy - hh, cx + hw, cy + hh]
    body = (18, 26, 46, 255)
    edge = ACCENT + (255,)
    # 表情主色調(panic 偏紅框)
    frame = (231, 76, 60, 255) if expr == "panic" else edge
    d.rounded_rectangle(face, radius=int(S * 0.09), fill=body, outline=frame, width=14)
    # 天線
    ax0 = cy - hh
    d.line([(cx, ax0), (cx, ax0 - int(S * 0.09))], fill=edge, width=10)
    d.ellipse([cx - 16, ax0 - int(S * 0.09) - 16, cx + 16, ax0 - int(S * 0.09) + 16], fill=edge)
    # 眼睛
    eoff = int(S * 0.12)
    ey = cy - int(S * 0.03)
    er = int(S * 0.045)
    lx, rx = cx - eoff, cx + eoff
    eye_col = (235, 244, 255, 255)
    if expr == "panic":
        # 驚恐：大圈空心眼
        for x in (lx, rx):
            d.ellipse([x - er - 6, ey - er - 6, x + er + 6, ey + er + 6], outline=(255, 120, 120, 255), width=10)
            d.ellipse([x - er // 2, ey - er // 2, x + er // 2, ey + er // 2], fill=(255, 120, 120, 255))
    elif expr == "happy":
        # 開心：彎月上弧眼
        for x in (lx, rx):
            d.arc([x - er, ey - er, x + er, ey + er], start=200, end=340, fill=eye_col, width=14)
    elif expr == "smug":
        # 得意：半瞇眼(下弧)
        for x in (lx, rx):
            d.arc([x - er, ey - er, x + er, ey + er], start=20, end=160, fill=eye_col, width=14)
    else:
        # 中性：實心圓眼
        for x in (lx, rx):
            d.ellipse([x - er, ey - er, x + er, ey + er], fill=eye_col)
    # 嘴
    my = cy + int(S * 0.10)
    mw = int(S * 0.11)
    if expr == "happy":
        d.arc([cx - mw, my - int(S * 0.05), cx + mw, my + int(S * 0.05)], start=20, end=160, fill=edge, width=12)
    elif expr == "panic":
        d.ellipse([cx - int(mw * 0.5), my - int(S * 0.02), cx + int(mw * 0.5), my + int(S * 0.05)], outline=(255, 120, 120, 255), width=10)
    elif expr == "smug":
        d.arc([cx - mw, my - int(S * 0.03), cx + int(mw * 0.4), my + int(S * 0.03)], start=20, end=160, fill=edge, width=12)
    else:
        d.line([(cx - int(mw * 0.6), my), (cx + int(mw * 0.6), my)], fill=edge, width=10)
    # 反應爐核心(下巴下方胸口)
    coreY = cy + hh + int(S * 0.09)
    for rr, col in ((72, (ACCENT[0], ACCENT[1], ACCENT[2], 55)),
                    (46, (ACCENT[0], ACCENT[1], ACCENT[2], 120)),
                    (24, (255, 255, 255, 255))):
        d.ellipse([cx - rr, coreY - rr, cx + rr, coreY + rr], fill=col)
    return img


def make_mascot():
    """產 4 張吉祥物 placeholder(透明底 1024x1024)到 assets/mascot/。**placeholder，最終需真美術替換。**"""
    mdir = ROOT / "assets" / "mascot"
    mdir.mkdir(parents=True, exist_ok=True)
    for expr in ("neutral", "happy", "panic", "smug"):
        p = mdir / f"{expr}.png"
        _draw_mascot(expr).save(p, "PNG")
        print(f"[ok] mascot/{p.name} 1024x1024 (透明底·placeholder)")
    return mdir


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only in (None, "avatar"):
        make_avatar()
    if only in (None, "banner"):
        make_banner()
    if only in (None, "intro", "intro_template"):
        make_intro_template()
    if only in (None, "logo"):
        make_logo()
    if only in (None, "mascot"):
        make_mascot()
    print("完成。")


if __name__ == "__main__":
    main()
