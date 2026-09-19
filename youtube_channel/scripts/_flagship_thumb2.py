#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:第二支旗艦長片(飆股的下場)16:9 橫式縮圖。
重用第一支旗艦縮圖(_flagship_thumb.py)的暗色終端背景元件，主視覺 = 60%（追飆股3年後賠錢比例）
+ 唐鋒 -89.9% 慘案數字，右側數據卡放distribution摘要。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
GOLD = (255, 209, 102)
RED = (255, 96, 96)
GREEN = (110, 231, 168)
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
# 左緣紅條(這支主打慘賠，用紅不用金，跟第一支做出視覺區隔) + 頂部品牌
d.rectangle([0, 0, 10, H], fill=RED)
d.text((36, 24), "量化阿森 | Carson Quant · 21年210檔全樣本", font=F(28), fill=GOLD)
# 主標(兩行,白)
d.text((36, 88), "每年飆股 Top10", font=F(80), fill=WHITE)
d.text((36, 192), "追進去抱 3 年", font=F(80), fill=WHITE)
d.rectangle([40, 300, 560, 310], fill=RED)
# 巨大紅字結論
d.text((36, 336), "60%", font=F(200), fill=RED)
d.text((44, 560), "的人倒賠出場", font=F(52), fill=WHITE)
# 右側數據卡
cx0, cy0, cx1, cy1 = 760, 110, 1240, 640
d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=18, fill=(16, 22, 34), outline=GOLD, width=2)
for i, c in enumerate([(255, 90, 90), (255, 200, 60), (90, 220, 140)]):
    d.ellipse([cx0+22+i*28, cy0+20, cx0+40+i*28, cy0+38], fill=c)
d.text((cx0+26, cy0+58), "追高飆股 3 年後(21年210檔)", font=F(26), fill=WHITE)
rows = [("中位數報酬", "-19.3%", RED),
        ("三年後倒賠", "60%", RED),
        ("最慘·唐鋒", "-89.9%", RED),
        ("最猛·利勤", "+777.1%", GREEN),
        ("同期0050", "+49.3%", GOLD)]
yy = cy0 + 112
for label, val, col in rows:
    d.text((cx0+30, yy), label, font=F(28, False), fill=(170, 182, 200))
    d.text((cx1-30, yy), val, font=F(38), fill=col, anchor="ra")
    yy += 78
d.text((cx0+26, cy1-34), "※歷史回測,不代表未來", font=F(19, False), fill=(120, 130, 150))
# 底部
d.text((36, H-52), "2002~2022 全年度前10名 · 含息還原 · 方法全公開", font=F(26), fill=(170, 182, 200))

out = ROOT / "assets" / "thumbnails" / "L_台股每年飆股Top10追3年60的人倒賠21年210檔.jpg"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, quality=92)
print(f"[ok] 16:9 旗艦縮圖(第二支) -> {out.name}")
