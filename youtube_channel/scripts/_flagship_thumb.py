#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:旗艦長片 16:9 橫式縮圖(make_cover 產的是 Shorts 直式,長片會被裁爛)。
重用 make_thumbnails 的暗色終端背景元件,主視覺 = 89.1% 大數字 + 全市場數據卡。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
GOLD = (255, 209, 102)
RED = (255, 96, 96)
WHITE = (248, 252, 255)
BG = (10, 14, 22)

def F(size, bold=True):
    for name in ("msjhbd.ttc", "msjh.ttc"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
# 細網格
for x in range(0, W, 64):
    d.line([(x, 0), (x, H)], fill=(18, 24, 36), width=1)
for y in range(0, H, 64):
    d.line([(0, y), (W, y)], fill=(18, 24, 36), width=1)
# 左緣金條 + 頂部品牌
d.rectangle([0, 0, 10, H], fill=GOLD)
d.text((36, 24), "量化阿森 | Carson Quant · 全市場實測", font=F(30), fill=GOLD)
# 主標(兩行,白)
d.text((36, 90), "台股 1580 檔", font=F(88), fill=WHITE)
d.text((36, 200), "全部定投 10 年", font=F(88), fill=WHITE)
d.rectangle([40, 316, 560, 326], fill=GOLD)
# 巨大紅字結論
d.text((36, 356), "89.1%", font=F(190), fill=RED)
d.text((44, 570), "輸給無腦買 0050", font=F(56), fill=WHITE)
# 右側數據卡
cx0, cy0, cx1, cy1 = 760, 120, 1240, 640
d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=18, fill=(16, 22, 34), outline=(*GOLD, ), width=2)
for i, c in enumerate([(255, 90, 90), (255, 200, 60), (90, 220, 140)]):
    d.ellipse([cx0+22+i*28, cy0+20, cx0+40+i*28, cy0+38], fill=c)
d.text((cx0+26, cy0+58), "全市場定投分佈(10年)", font=F(30), fill=WHITE)
rows = [("贏過 0050", "10.9%", GOLD),
        ("輸給 0050", "89.1%", RED),
        ("十年仍賠錢", "22.6%", RED),
        ("中位數報酬", "+57%", WHITE),
        ("0050 同期", "+346%", GOLD)]
yy = cy0 + 116
for label, val, col in rows:
    d.text((cx0+30, yy), label, font=F(30, False), fill=(170, 182, 200))
    d.text((cx1-30, yy), val, font=F(40), fill=col, anchor="ra")
    yy += 78
d.text((cx0+26, cy1-34), "※歷史回測,不代表未來", font=F(20, False), fill=(120, 130, 150))
# 底部
d.text((36, H-52), "1925 檔全掃描 · 含息還原 · 方法全公開", font=F(28), fill=(170, 182, 200))

out = ROOT / "assets" / "thumbnails" / "L_台股1580檔全部定投10年891的人輸給無腦買00.jpg"
img.save(out, quality=92)
print(f"[ok] 16:9 旗艦縮圖 -> {out.name}")
