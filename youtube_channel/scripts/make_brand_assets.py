#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_brand_assets.py — 生成品牌大頭貼(800x800) + 頻道橫幅(2048x1152)。

存到 assets/brand/。大頭貼/橫幅無法用 API 設定，請在 Studio→自訂→個人資料 上傳。
橫幅關鍵內容置於中央安全區(各裝置都看得到)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"
OUT.mkdir(parents=True, exist_ok=True)

NAVY_TOP = (12, 20, 44)
NAVY_BOT = (30, 48, 92)
ACCENT = (255, 209, 102)  # 品牌暗金 #FFD166——與 STUDIO/design_system.json accent_palette[0]（make_video.pick_accent
                          # 鎖色來源）同一個值，B5：縮圖/banner/logo/intro 全線統一，不再各自一種黃
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
    """品牌固定片頭底圖：直式 1080x1920(頻道主力是 Shorts，原生比例貼合、不被 render_brand_intro
    的 resize 拉伸變形；render() 傳 16:9 長片時仍會被等比外的 resize 撐開，但長片占比小，可接受)。
    漸層+淡網格+背景折線箭頭核心符號(暗金、低透明度，呼應品牌，不搶標題)+底部強調條+頂部品牌小字。
    中央刻意留白，交給 render_brand_intro 在渲染時壓上該片標題。存 assets/brand/intro_template.png。"""
    W, H = 1080, 1920
    img = gradient(W, H).convert("RGBA")
    ac = ACCENT
    # 注意：PIL 的 ImageDraw 直接畫在既有 RGBA 圖上時 fill 的 alpha 不會與底圖混合(會整像素覆寫，
    # 半透明會變成實色色塊)——所有半透明元素一律先畫在獨立透明圖層，再用 alpha_composite 疊上去。
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    step = 90
    for gx in range(0, W, step):
        od.line([(gx, 0), (gx, H)], fill=(*ac, 12), width=1)
    for gy in range(0, H, step):
        od.line([(0, gy), (W, gy)], fill=(*ac, 12), width=1)
    # 中央偏上柔和光暈（給標題襯底、又不擋字）
    cx = W // 2
    cy = int(H * 0.40)
    for rr, a in ((420, 10), (300, 14), (200, 20)):
        od.ellipse([cx - rr, cy - int(rr * 0.75), cx + rr, cy + int(rr * 0.75)], fill=(*ac, a))
    img.alpha_composite(overlay)
    # 背景折線箭頭核心符號(低透明度，置中偏下，襯在標題文字之後、不搶戲——與 logo/avatar 同一視覺語言)
    base_y = int(H * 0.62)
    scale = 1.55
    pts = [(cx + int((x - 256) * scale), base_y + int((y - 256) * scale))
           for x, y in ((120, 330), (200, 260), (260, 300), (320, 210), (392, 130))]
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(pts, fill=(*ac, 46), width=26, joint="curve")
    tip = (pts[-1][0] + int(34 * scale), pts[-1][1] - int(34 * scale))
    gd.line([pts[-1], tip], fill=(*ac, 46), width=26)
    gd.polygon([tip, (tip[0] - 40, tip[1] + 10), (tip[0] - 4, tip[1] + 44)], fill=(*ac, 46))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2)))
    # 底部強調條 + 頂部品牌小字(不透明,直接畫在 img 上沒問題)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, H - 10, W, H], fill=ac)
    center_text(d, cx, 64, "量化阿森 · Carson Quant", font(40), WHITE, stroke=3)
    p = OUT / "intro_template.png"
    img.convert("RGB").save(p, "PNG")
    print(f"[ok] {p.name} {W}x{H}")
    return p


def make_logo():
    """透明底品牌 logo(512x512)：Carson 定案的品牌核心符號＝數據/折線箭頭(暗金量化質感)，
    machine 吉祥物退居影片內配角、不再當頻道 logo(2026-07 定案)。純符號、無文字，貼小尺寸(如
    render_brand_intro 右上角 13% 寬)也清楚可讀。深色圓角方底 + 粗金折線圖(先跌後噴出)+ 箭頭。"""
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([28, 28, S - 28, S - 28], radius=96, fill=(11, 17, 36, 240), outline=ACCENT, width=12)
    # 折線圖：低→高→回檔→噴出，比 avatar 更粗更滿框(小尺寸縮圖仍清楚)
    pts = [(120, 330), (200, 260), (260, 300), (320, 210), (392, 130)]
    d.line(pts, fill=ACCENT, width=30, joint="curve")
    for x, y in pts:  # 每個轉折點補圓點，折線感更明確(避免縮小後糊成一條線)
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=ACCENT)
    # 箭頭尖(終點延伸,比末端轉折點更外面一點，指向右上)
    tip = (426, 96)
    d.line([pts[-1], tip], fill=ACCENT, width=30)
    d.polygon([tip, (tip[0] - 46, tip[1] + 8), (tip[0] - 6, tip[1] + 50)], fill=ACCENT)
    p = OUT / "logo.png"
    img.save(p, "PNG")
    print(f"[ok] {p.name} {S}x{S} (透明底·折線箭頭符號)")
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
