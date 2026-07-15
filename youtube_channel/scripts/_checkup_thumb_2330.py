#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:「個股體檢」系列 EP1(台積電2330)16:9 橫式縮圖。
仿 _flagship_thumb2.py 的暗色終端背景元件+右側數據卡風格。主視覺數字＝這集最震撼、
也是本系列差異化核心的那個數字:史上最長套牢期 10.7 年(創高→下個創高間隔十年多),
搭配 20 年翻 84 倍當對比張力(報酬很猛,但你要先熬過十年套牢——這才是體檢報告的重點)。
數字全部溯源自 STUDIO/stock_checkup_facts.json(checkup_long_horizon__2330 /
checkup_underwater__2330 / checkup_halvings__2330 / checkup_crash__2330__crisis2008)。
"""
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
# 細網格(暗色質感,同系列既有旗艦縮圖語彙)
for x in range(0, W, 64):
    d.line([(x, 0), (x, H)], fill=(18, 24, 36), width=1)
for y in range(0, H, 64):
    d.line([(0, y), (W, y)], fill=(18, 24, 36), width=1)

# 左緣紅條(這支主打「先痛後甜」,紅=痛，跟金色的報酬數字做張力對比) + 頂部品牌/系列名
d.rectangle([0, 0, 10, H], fill=RED)
d.text((36, 24), "量化阿森 | Carson Quant · 個股體檢 EP1", font=F(28), fill=GOLD)

# 主標(兩行,白)
d.text((36, 84), "台積電 2330", font=F(72), fill=WHITE)
d.text((36, 180), "20年翻84倍", font=F(60), fill=GOLD)

# 巨大紅字結論：主視覺數字＝套牢年數(差異化核心，不是報酬)
d.text((36, 268), "但要先熬", font=F(48), fill=WHITE)
d.text((36, 328), "10.7年", font=F(160), fill=RED)
d.text((48, 512), "史上最長套牢期", font=F(40), fill=WHITE)

# 右側數據卡
cx0, cy0, cx1, cy1 = 780, 110, 1240, 640
d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=18, fill=(16, 22, 34), outline=GOLD, width=2)
for i, c in enumerate([(255, 90, 90), (255, 200, 60), (90, 220, 140)]):
    d.ellipse([cx0 + 22 + i * 28, cy0 + 20, cx0 + 40 + i * 28, cy0 + 38], fill=c)
d.text((cx0 + 26, cy0 + 58), "體檢報告摘要(20年)", font=F(26), fill=WHITE)
rows = [
    ("含息還原總報酬", "8285%", GOLD),
    ("年化報酬", "24.8%", GOLD),
    ("最大回撤", "-46.5%", RED),
    ("最長套牢期", "10.7年", RED),
    ("單次腰斬", "-52.4%", RED),
]
yy = cy0 + 112
for label, val, col in rows:
    d.text((cx0 + 30, yy), label, font=F(25, False), fill=(170, 182, 200))
    d.text((cx1 - 30, yy), val, font=F(34), fill=col, anchor="ra")
    yy += 78
d.text((cx0 + 26, cy1 - 34), "※歷史回測,不代表未來", font=F(19, False), fill=(120, 130, 150))

# 底部
d.text((36, H - 52), "2000~2026 含息還原 · 資料清洗 · 方法全公開", font=F(26), fill=(170, 182, 200))

SLUG = "L_個股體檢EP1台積電233020年翻84倍但你要先熬"
out = ROOT / "assets" / "thumbnails" / f"{SLUG}.jpg"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, quality=92)
print(f"[ok] 16:9 個股體檢縮圖(EP1台積電) -> {out.name}")
