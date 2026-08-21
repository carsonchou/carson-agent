#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""community_card.py — 產「今日體檢重點卡」:給 YouTube 社群貼文用的方形深色數據卡。

## 為什麼(2026-08-22)
社群貼文是訂閱者 feed 的第二觸點(影片之外唯一能主動出現在訂閱者首頁的東西),
而且對非訂閱者也會出現在頻道「社群」tab。本頻道 0 篇貼文 = 這個管道閒置。
卡片內容全部來自**當日發布的體檢片的真實事實**(fact 庫同一份),不是另寫文案
——溯源鐵律照舊,卡上每個數字都查得到出處。

## 設計
1080x1080(社群貼文最佳),沿用頻道深色語言(近黑底/K線紋理/克制 bloom,
與 channel_banner_v2 同款)。結構:股名代號 → 三個關鍵數字 → 一句誠信簽名 → 頻道名。

## 輸出
STUDIO/community_cards/<date>_<code>.png + 同名 .txt(貼文文字,含影片連結)。
發布由 community_post.py 負責(Playwright;API 不支援社群貼文)。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
OUT = STUDIO / "community_cards"


def _font(sz, bold=True):
    from PIL import ImageFont
    for p in ([r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msjh.ttc"]
              if bold else [r"C:\Windows\Fonts\msjh.ttc"]):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            pass
    return ImageFont.load_default()


def _latest_checkup():
    """今天(或最近)發布的體檢片:回 (slug, vid, code, name)。"""
    info_p = STUDIO / "_true_views.json"
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    best = None
    for slug, vid in led.items():
        if "個股體檢" not in slug or not slug.startswith("L_") or "系列" in slug:
            continue
        d = (info.get(vid) or {}).get("d", "")
        m = re.search(r"(\d{4})", slug)
        if not (d and m):
            continue
        if best is None or d > best[0]:
            best = (d, slug, vid, m.group(1))
    return best  # (date, slug, vid, code)


def build(out_dir=OUT) -> Path | None:
    from PIL import Image, ImageDraw, ImageFilter
    import random

    got = _latest_checkup()
    if not got:
        print("找不到已發布的體檢片")
        return None
    pub_d, slug, vid, code = got
    facts = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    lh = (facts.get(f"checkup_long_horizon__{code}") or {}).get("claim", "")
    uw = (facts.get(f"checkup_underwater__{code}") or {}).get("claim", "")
    meta = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8")) \
        .get("by_code", {}).get(code, {})
    name = meta.get("name") or code
    # 三個關鍵數字(全部真實可溯源;抓不到就少放,不編)
    stats = []
    m = re.search(r"總報酬\s*(-?[\d.]+)%", lh)
    if m:
        stats.append(("總報酬", f"{float(m.group(1)):+,.1f}%"))
    m = re.search(r"年化\s*(-?[\d.]+)%", lh)
    if m:
        stats.append(("年化", f"{float(m.group(1)):+.1f}%"))
    m = re.search(r"最大回撤\s*(-[\d.]+)%", lh)
    if m:
        stats.append(("最大回撤", f"{m.group(1)}%"))
    m = re.search(r"等了\s*([\d.]+)\s*年", uw)
    if m and len(stats) >= 3:
        stats[2] = ("最長套牢", f"{m.group(1)} 年")
    if len(stats) < 2:
        print(f"{code} 事實不足,不產卡(不編數字)")
        return None
    yrs = re.search(r"([\d.]+)\s*年含息還原", lh)
    period = f"近 {yrs.group(1)} 年・含息還原" if yrs else "長期回測・含息還原"

    W = H = 1080
    img = Image.new("RGB", (W, H), (9, 12, 20))
    d = ImageDraw.Draw(img)
    rnd = random.Random(hash(code) & 0xffff)
    for x in range(0, W, 54):
        d.line([(x, 0), (x, H)], fill=(15, 20, 31), width=1)
    for y in range(0, H, 54):
        d.line([(0, y), (W, y)], fill=(15, 20, 31), width=1)
    base_y = H * 0.86
    py = base_y
    for i in range(26):
        x = int(i * W / 26)
        yv = base_y - i * 2.2 - rnd.uniform(-26, 26)
        c = (22, 42, 35) if rnd.random() > 0.42 else (42, 24, 28)
        d.rectangle([x + 4, min(py, yv) - 12, x + 22, max(py, yv) + 12], fill=c)
        py = yv

    d.text((70, 66), "今日體檢", font=_font(40, False), fill=(120, 200, 255))
    d.text((70, 130), f"{name}", font=_font(108), fill=(240, 244, 252))
    d.text((70 + d.textlength(name, font=_font(108)) + 28, 186),
           f"({code})", font=_font(52, False), fill=(150, 158, 175))
    d.text((70, 268), period, font=_font(34, False), fill=(120, 128, 146))

    y0 = 400
    for i, (lab, val) in enumerate(stats[:3]):
        y = y0 + i * 160
        d.text((70, y), lab, font=_font(40, False), fill=(150, 158, 175))
        # 顏色語意:負面看**標籤**不只看負號——「最長套牢 13.5 年」沒有負號
        # 但它是風險數字,畫綠色會傳達「這是好事」(第一版實際犯了這個錯)。
        neg = val.startswith("-") or any(k in lab for k in ("回撤", "套牢", "腰斬"))
        d.text((70, y + 52), val, font=_font(84),
               fill=(235, 120, 120) if neg else (120, 220, 170))
    d.text((70, 946), "不喊單・不報明牌・每個數字都能溯源",
           font=_font(30, False), fill=(120, 128, 146))
    d.text((70, 994), "量化阿森｜Carson Quant・完整體檢看今天的新片",
           font=_font(30, False), fill=(120, 200, 255))
    glow = img.filter(ImageFilter.GaussianBlur(5))
    img = Image.blend(img, glow, 0.18)

    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{date.today().isoformat()}_{code}.png"
    img.save(png)
    txt = out_dir / f"{date.today().isoformat()}_{code}.txt"
    lines = [f"📋 今日體檢:{name}({code})", ""]
    for lab, val in stats[:3]:
        lines.append(f"・{lab} {val}")
    lines += ["", f"這樣算好還算壞?完整拆解(含 vs 0050 對比)在今天的影片:",
              f"https://youtu.be/{vid}", "",
              "不喊單・不報明牌・每個數字都能溯源 #台股 #個股體檢"]
    txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"卡片:{png.name}\n文字:{txt.name}")
    return png


if __name__ == "__main__":
    raise SystemExit(0 if build() else 1)
