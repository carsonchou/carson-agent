#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性:第三支旗艦長片(高股息ETF全家族 vs 0050 對決)16:9 橫式縮圖。
重用第一/二支旗艦縮圖(_flagship_thumb.py/_flagship_thumb2.py)的暗色終端背景元件，
主視覺 = 7/7(高股息ETF家族含息還原總報酬全數落後0050) + 家族對決數據卡。"""
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
# 左緣紅條(這支主打「全輸」，用紅) + 頂部品牌
d.rectangle([0, 0, 10, H], fill=RED)
d.text((36, 24), "量化阿森 | Carson Quant · 高股息全家族實測", font=F(28), fill=GOLD)
# 主標(兩行,白)
d.text((36, 88), "高股息ETF全家族", font=F(66), fill=WHITE)
d.text((36, 176), "vs 0050 對決", font=F(66), fill=WHITE)
d.rectangle([40, 268, 560, 278], fill=RED)
# 巨大紅字結論
d.text((36, 300), "7/7", font=F(200), fill=RED)
d.text((44, 520), "全數落後0050", font=F(52), fill=WHITE)
d.text((44, 590), "配得多不代表賺得多", font=F(34), fill=(170, 182, 200))
# 右側數據卡
cx0, cy0, cx1, cy1 = 760, 90, 1240, 650
d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=18, fill=(16, 22, 34), outline=GOLD, width=2)
for i, c in enumerate([(255, 90, 90), (255, 200, 60), (90, 220, 140)]):
    d.ellipse([cx0 + 22 + i * 28, cy0 + 20, cx0 + 40 + i * 28, cy0 + 38], fill=c)
d.text((cx0 + 26, cy0 + 58), "高股息 vs 市值型(含息還原)", font=F(25), fill=WHITE)
rows = [("0056 12.5年", "413% vs 1050%", RED),
        ("00940 上市至今", "38% vs 189%", RED),
        ("配息再投入缺口", "家族僅市值型1/5", RED),
        ("殖利率×總報酬", "相關係數僅0.48", GOLD),
        ("防守力·最大回撤", "高股息普遍較小", GREEN)]
yy = cy0 + 112
for label, val, col in rows:
    d.text((cx0 + 30, yy), label, font=F(24, False), fill=(170, 182, 200))
    d.text((cx1 - 30, yy), val, font=F(28), fill=col, anchor="ra")
    yy += 92
d.text((cx0 + 26, cy1 - 30), "※歷史回測,不代表未來", font=F(19, False), fill=(120, 130, 150))
# 底部
d.text((36, H - 52), "11檔高股息ETF全掃描 · 含息還原 · 方法全公開", font=F(26), fill=(170, 182, 200))

out = ROOT / "assets" / "thumbnails" / "L_高股息ETF全家族vs0050對決7檔全數落後配息多.jpg"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, quality=92)
print(f"[ok] 16:9 旗艦縮圖(第三支) -> {out.name}")
