#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_cover.py — 高質感 Shorts/縮圖封面產生器（量化阿森品牌）。

兩種風格（依主題自動選，可輪替）：
  · tech：科技吉祥物機器人（霓虹眼 + 終端網格 + 發光字）→ 原理/教學/概念題
  · real：真人手機 App 實測畫面（崩盤紅光 + 綠勢 + 紅圈）→ 結果/實測/帳戶題

流程：Haiku 從標題/旁白抽「狠話 kicker / 主標 / 鉤子(含金色關鍵字) / 數據標 / 漲跌情緒 / 英文場景詞」
      → 免金鑰 Pollinations(Flux) 生主題場景圖 → 疊精緻文字 → 1080x1920 JPG。
AI 生圖或 API 失敗 → 退回 make_video 的 K 線卡保底（不開天窗）。

用法：
  python make_cover.py --slug S_xxx --title "標題" [--narration "旁白"] [--style tech|real|auto] [--out path]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)
TMP = ROOT / "assets" / "_cover_tmp"
TMP.mkdir(parents=True, exist_ok=True)
W, H = 1080, 1920
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = "claude-haiku-4-5-20251001"
BRAND = "量化阿森 · Carson Quant"

BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"]
REG = [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
       "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
       "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]


def F(s, b=True):
    for c in (BOLD if b else REG):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, s)
            except Exception:
                pass
    return ImageFont.load_default()


# ───────────────────────── 情緒色盤 ─────────────────────────
def _palette(sentiment):
    """依漲跌情緒回傳 (accent, glow, scrim_col, kicker_col, data_border)。"""
    if sentiment == "down":
        # 崩盤冷調：深紅 + 冰藍暗角
        return (
            (220, 50, 60),       # accent — 紅
            (200, 30, 40, 130),  # glow
            (8, 6, 10),          # scrim base
            (255, 160, 165),     # kicker text
            (230, 60, 70, 255),  # data border
        )
    else:
        # 獲利暖調：青綠 + 深海藍暗角
        return (
            (54, 230, 200),      # accent — 青綠
            (30, 200, 180, 130), # glow
            (4, 10, 16),         # scrim base
            (120, 240, 220),     # kicker text
            (54, 230, 200, 255), # data border
        )


# ───────────────────────── 場景模板庫 ─────────────────────────
# 依主題關鍵字 map 到更精緻的英文場景前綴，後面再拼通用品質後綴
_SCENE_QUALITY = (
    "cinematic lighting, octane render, depth of field, 8k ultra detail, "
    "premium dark navy teal palette, moody atmosphere, anamorphic lens flare"
)

_SCENE_MAP = [
    # (關鍵字 tuple, scene_prefix)
    (("崩盤", "爆倉", "大跌", "暴跌", "破產"),
     "dramatic cinematic photo of a crypto trading screen in red freefall, "
     "shattered glass effect, emergency red light flooding a dark trading desk, "
     "panic atmosphere, scattered papers"),
    (("定投", "DCA", "每月", "每週", "長期"),
     "serene top-down flat lay of a smartphone showing steady upward dollar-cost-averaging chart, "
     "minimalist dark marble desk, single gold coin gleaming, calm confident mood"),
    (("網格", "Grid", "grid", "區間"),
     "futuristic holographic grid trading matrix floating in dark space, "
     "cyan laser grid lines, glowing nodes at intersections, abstract geometric precision"),
    (("回測", "backtest", "歷史", "模擬", "10年", "5年"),
     "dramatic split-screen: left side shows historical market chaos, right side shows "
     "clean profit equity curve glowing green, time-travel portal effect, dark studio"),
    (("派網", "Pionex", "pionex", "機器人", "自動"),
     "sleek dark smartphone floating in dark space displaying a professional crypto trading bot "
     "dashboard with glowing teal metrics, robotic arm gently touching the screen, premium product shot"),
    (("質押", "借錢", "槓桿", "借貸"),
     "close-up cinematic of golden coins being used as collateral, "
     "dark bank vault atmosphere, green digital loan approval screen reflected on coins"),
    (("比較", "vs", "哪個", "選擇", "適合"),
     "dramatic cinematic duel composition, two glowing holographic trading strategies "
     "facing each other in dark arena, electric energy between them, versus split"),
    (("ETF", "0050", "006208", "指數", "大盤"),
     "elegant top-down of diversified investment portfolio visualization, "
     "glowing bar chart rising steadily, dark premium background, long-term wealth theme"),
]


def _build_scene_prompt(title, scene_en_ai, sentiment):
    """挑最貼題的模板；AI 有給 scene_en 就融合，否則純用模板。"""
    title_lower = (title or "").lower()
    for kws, prefix in _SCENE_MAP:
        if any(k in (title or "") or k.lower() in title_lower for k in kws):
            base = prefix
            break
    else:
        # 無命中 → 用 AI 給的或通用
        base = scene_en_ai or "professional crypto trading setup with glowing monitors in dark studio"

    mood = "cold blue desaturated color grade" if sentiment == "down" else "rich teal warm highlights"
    return f"{base}, {mood}, {_SCENE_QUALITY}, vertical 9:16"


# ───────────────────────── 文字推導 ─────────────────────────
_REAL_KW = ("實測", "結果", "帳戶", "30天", "天後", "回測", "賺", "虧", "績效", "報酬", "實盤", "公開")


def _heuristic(title):
    t = re.sub(r"[（(].*?[)）]", "", title or "").strip()
    return {
        "kicker": "量化交易實測",
        "headline": t[:10] or "你不知道的真相",
        "hook_pre": "結果", "hook_key": "讓人意外", "hook_post": "？",
        "data": "", "sentiment": "up",
        "scene_en": "futuristic trading robot, glowing chart",
        "style": "real" if any(k in (title or "") for k in _REAL_KW) else "tech",
    }


def derive(title, narration=""):
    fb = _heuristic(title)
    if not any(os.environ.get(_k,"").strip() for _k in ("OPENROUTER_API_KEY","ANTHROPIC_API_KEY","DEEPSEEK_API_KEY","GEMINI_API_KEY","GROQ_API_KEY")):
        return fb
    prompt = (
        "你是量化交易頻道的縮圖文案。讀標題與旁白，輸出 JSON（繁中、不誇大不保證收益）。"
        "★務必極短有力，嚴守字數上限，太長會爆版：\n"
        '{"kicker":"頂部小字情境(≤13字,如\'比特幣崩盤·18萬人爆倉\')",'
        '"headline":"主標狠話(≤9字,衝擊反差,如\'全場爆倉它沒事\'\'虧損中反而賺\')",'
        '"hook_pre":"鉤子前段(≤5字)","hook_key":"金色強調關鍵詞(2-3字)","hook_post":"鉤子後段(≤3字,常是問號)",'
        '"//note":"hook_pre+hook_key+hook_post 三段合起來必須≤9字、像\'它為什麼還在|賺|？\'或\'結果竟然|賺爆|了\'",'
        '"data":"亮點數據短語(≤7字,如\'逆勢+8.6%\'\'終值5.8倍\',無合適可空)",'
        '"sentiment":"up或down(結論賺/正面=up,崩跌/虧=down)",'
        '"scene_en":"AI生圖英文場景補充詞(10字內,主體特徵,如 shattered phone screen red candles / cute robot celebrating profit)",'
        '"style":"real(結果/實測/帳戶/績效類)或tech(原理/教學/概念/比較類)"}\n'
        f"標題：{title}\n旁白：{(narration or '')[:500]}"
    )
    try:
        import requests
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": AI_MODEL, "max_tokens": 400, "temperature": 0.4,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=50)
        r.raise_for_status()
        d = json.loads(re.search(r"\{.*\}", r.json()["content"][0]["text"], re.S).group(0))
        for k, v in fb.items():
            d.setdefault(k, v)
        if d.get("style") not in ("real", "tech"):
            d["style"] = fb["style"]
        if d.get("sentiment") not in ("up", "down"):
            d["sentiment"] = "up"
        # 硬截斷保險（防爆框）
        d["headline"] = str(d.get("headline", ""))[:10]
        d["kicker"] = str(d.get("kicker", ""))[:14]
        _dat = str(d.get("data", "")).strip()
        d["data"] = _dat if (re.search(r"\d", _dat) and len(_dat) <= 8) else ""
        pre, key, post = str(d.get("hook_pre", "")), str(d.get("hook_key", "")), str(d.get("hook_post", ""))
        key = key[:4]
        if len(pre) + len(key) + len(post) > 10:
            pre = pre[:max(0, 10 - len(key) - len(post))]
        d["hook_pre"], d["hook_key"], d["hook_post"] = pre, key, post
        return d
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Haiku 文案失敗，用保底：{str(e)[:70]}", file=sys.stderr)
        return fb


# ───────────────────────── AI 生圖（Pollinations Flux，免金鑰） ─────────────────────────
def _poll(prompt, seed, dest, tries=3):
    """生圖，含 429/暫態錯誤的重試＋退避，避免量產時被限流而退回保底卡。"""
    import time
    u = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
         + f"?width=720&height=1280&model=flux&nologo=true&seed={seed}")
    last = ""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=90).read()
            if len(data) < 4000:
                last = "回傳過小"
            else:
                dest.write_bytes(data)
                return Image.open(dest).convert("RGB")
        except Exception as e:  # noqa: BLE001
            last = str(e)[:70]
        if attempt < tries - 1:
            time.sleep(4 * (attempt + 1) + 2)  # 退避：6s, 10s
    print(f"[warn] AI 生圖 {tries} 次失敗：{last}", file=sys.stderr)
    return None


def _seed(slug):
    return int(hashlib.md5((slug or "x").encode("utf-8")).hexdigest(), 16) % 100000


def _cover(im):
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)))
    return im.crop(((im.width - W) // 2, (im.height - H) // 2,
                    (im.width - W) // 2 + W, (im.height - H) // 2 + H))


# ───────────────────────── 視覺工具 ─────────────────────────
def _spaced(d, xy, t, f, fill, gap, a="lm"):
    ws = [d.textbbox((0, 0), ch, font=f)[2] for ch in t]
    tot = sum(ws) + gap * (len(t) - 1)
    x = xy[0] - (tot / 2 if a == "mm" else 0)
    for ch, w in zip(t, ws):
        d.text((x, xy[1]), ch, font=f, fill=fill, anchor="lm")
        x += w + gap


def _glow(b, xy, t, f, fill, g, gr=16, a="mm", sw=0, sf=(0, 0, 0)):
    l = Image.new("RGBA", b.size, (0, 0, 0, 0))
    ImageDraw.Draw(l).text(xy, t, font=f, fill=g, anchor=a)
    b.alpha_composite(l.filter(ImageFilter.GaussianBlur(gr)))
    ImageDraw.Draw(b).text(xy, t, font=f, fill=fill, anchor=a, stroke_width=sw, stroke_fill=sf)


def _scrim(img, top_h, bot_y, col=(5, 9, 14)):
    """四角漸層暗角，上下各一塊。"""
    v = Image.new("L", (1, H), 0)
    px = v.load()
    for y in range(H):
        a = 0
        if y < top_h:
            a = int(220 * (top_h - y) / top_h)
        elif y > bot_y:
            a = int(235 * (y - bot_y) / (H - bot_y))
        px[0, y] = a
    o = Image.new("RGBA", (W, H), (*col, 0))
    o.putalpha(v.resize((W, H)))
    img.alpha_composite(o)


def _vignette(img, strength=180):
    """四周圓形暗角，增加電影感。"""
    vgn = Image.new("L", (W, H), 0)
    px = vgn.load()
    cx, cy = W / 2, H / 2
    max_r = (cx ** 2 + cy ** 2) ** 0.5
    for y in range(H):
        for x in range(0, W, 4):  # 4px 步長加速
            r = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            fade = r / max_r
            a = int(strength * (fade ** 1.6))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = min(255, a)
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dark.putalpha(vgn)
    img.alpha_composite(dark)


def _frosted_panel(img, y0, y1, col=(10, 16, 24), alpha=185, accent=None, border_top=True):
    """毛玻璃資訊板：深色半透明矩形 + 頂部細線點綴。"""
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rectangle([0, y0, W, y1], fill=(*col, alpha))
    if border_top and accent:
        pd.line([(0, y0), (W, y0)], fill=(*accent[:3], 180), width=2)
    img.alpha_composite(panel)


def _separator(d, y, accent, pad=80):
    """細水平分隔線 + 兩端小菱形裝飾。"""
    d.line([(pad, y), (W - pad, y)], fill=(*accent[:3], 90), width=1)
    for cx in (pad, W - pad):
        d.polygon([(cx, y - 5), (cx + 5, y), (cx, y + 5), (cx - 5, y)],
                  fill=(*accent[:3], 160))


def _fit(d, t, max_w, start, mn=44):
    s = start
    while s > mn:
        if d.textbbox((0, 0), t, font=F(s))[2] <= max_w:
            return F(s)
        s -= 4
    return F(mn)


GOLD = (228, 192, 108)
GOLD_DARK = (180, 140, 60)
INK = (236, 242, 250)
MUT = (165, 176, 196)
RED_ACCENT = (230, 60, 70)
TEAL_ACCENT = (54, 230, 200)


def _hook(d, img, txt, y, hf, box=None, glow_col=None):
    pre, key, post = txt
    w1 = d.textbbox((0, 0), pre, font=hf)[2]
    w2 = d.textbbox((0, 0), key, font=hf)[2]
    w3 = d.textbbox((0, 0), post, font=hf)[2]
    x0 = (W - (w1 + w2 + w3)) // 2
    if box == "yellow":
        b = d.textbbox((W // 2, y), pre + key + post, font=hf, anchor="mm")
        bx0 = max(28, b[0] - 36); bx1 = min(W - 28, b[2] + 36)
        # 金色漸層框（用兩層疊出漸層感）
        d.rounded_rectangle([bx0 - 2, b[1] - 18, bx1 + 2, b[3] + 24], radius=26,
                             fill=(200, 160, 20, 255))
        d.rounded_rectangle([bx0, b[1] - 16, bx1, b[3] + 22], radius=24,
                             fill=(255, 216, 32, 255))
        d.text((x0, y), pre, font=hf, fill=(14, 13, 10), anchor="lm")
        d.text((x0 + w1, y), key, font=hf, fill=(140, 60, 5), anchor="lm")
        d.text((x0 + w1 + w2, y), post, font=hf, fill=(14, 13, 10), anchor="lm")
    else:
        if glow_col:
            _glow(img, (W // 2, y), pre + key + post, hf, (0, 0, 0, 0), glow_col, gr=18)
        d2 = ImageDraw.Draw(img, "RGBA")
        d2.text((x0, y), pre, font=hf, fill=INK, anchor="lm", stroke_width=2, stroke_fill=(6, 16, 20))
        d2.text((x0 + w1, y), key, font=hf, fill=GOLD, anchor="lm", stroke_width=2, stroke_fill=(6, 16, 20))
        d2.text((x0 + w1 + w2, y), post, font=hf, fill=INK, anchor="lm", stroke_width=2, stroke_fill=(6, 16, 20))


# ───────────────────────── 風格合成 ─────────────────────────
def compose_tech(base, t):
    sent = t.get("sentiment", "up")
    accent, glow_rgba, scrim_col, kicker_col, data_border = _palette(sent)

    img = _cover(base).convert("RGBA")

    # 終端網格線（低透明度，依情緒色）
    d = ImageDraw.Draw(img, "RGBA")
    grid_col = (*accent[:3], 15)
    for g in range(0, W, 65):
        d.line([(g, 0), (g, H)], fill=grid_col, width=1)
    for g in range(0, H, 65):
        d.line([(0, g), (W, g)], fill=grid_col, width=1)

    # 上下漸層 scrim + 四周電影暗角
    _scrim(img, 420, 1380, scrim_col)
    _vignette(img, strength=160)

    # ── 頂部 kicker 區 ──
    _frosted_panel(img, 60, 230, col=scrim_col, alpha=160, accent=accent, border_top=False)
    d = ImageDraw.Draw(img, "RGBA")
    # kicker 小字 + 霓虹光暈
    _glow(img, (W // 2, 148), t["kicker"], F(46), (*kicker_col, 255), glow_rgba, gr=12)

    # ── 主標 headline（最大字，中央偏上）──
    hline_y = 360
    hf_main = _fit(d, t["headline"], W - 100, 98)
    _glow(img, (W // 2, hline_y), t["headline"], hf_main,
          (240, 252, 255, 255), glow_rgba, gr=16, sw=3, sf=(4, 16, 20))

    # 主標下細分隔線
    d = ImageDraw.Draw(img, "RGBA")
    _separator(d, hline_y + 80, accent, pad=100)

    # ── 數據標（右側毛玻璃卡片）──
    if t.get("data") and re.search(r"\d", t["data"]):
        gf = F(56)
        gb = d.textbbox((W - 230, 720), t["data"], font=gf, anchor="mm")
        # 卡片邊框 + 填色
        d.rounded_rectangle([gb[0] - 28, gb[1] - 18, gb[2] + 28, gb[3] + 18],
                             radius=16, fill=(4, 20, 24, 210),
                             outline=data_border, width=3)
        _glow(img, (W - 230, 720), t["data"], gf, (*accent[:3], 255), glow_rgba, gr=10)

    # ── 底部毛玻璃鉤子板 ──
    _frosted_panel(img, 1450, 1680, col=scrim_col, alpha=200, accent=accent, border_top=True)
    d = ImageDraw.Draw(img, "RGBA")
    hf_hook = _fit(d, t["hook_pre"] + t["hook_key"] + t["hook_post"], W - 80, 106)
    _hook(d, img, (t["hook_pre"], t["hook_key"], t["hook_post"]), 1568, hf_hook,
          glow_col=(*accent[:3], 200))

    # ── 品牌浮水印 ──
    _frosted_panel(img, 1730, 1860, col=scrim_col, alpha=140, accent=None, border_top=True)
    d = ImageDraw.Draw(img, "RGBA")
    # 品牌左側小菱形點綴
    bx = (W - sum(d.textbbox((0, 0), ch, font=F(36))[2] for ch in BRAND)
          - 8 * (len(BRAND) - 1)) // 2
    d.polygon([(bx - 22, 1795), (bx - 14, 1795 - 8),
               (bx - 6, 1795), (bx - 14, 1795 + 8)],
              fill=(*accent[:3], 220))
    _spaced(ImageDraw.Draw(img, "RGBA"), (W // 2, 1795), BRAND, F(36),
            (*kicker_col[:3], 220), 8, "mm")

    return img.convert("RGB")


def compose_real(base, t):
    sent = t.get("sentiment", "up")
    accent, glow_rgba, scrim_col, kicker_col, data_border = _palette(sent)

    img = _cover(base).convert("RGBA")

    # 上下漸層 scrim + 電影暗角
    _scrim(img, 440, 1350, scrim_col)
    _vignette(img, strength=150)

    # ── 頂部 kicker 區（毛玻璃帶）──
    _frosted_panel(img, 55, 235, col=scrim_col, alpha=175, accent=accent, border_top=False)
    d = ImageDraw.Draw(img, "RGBA")
    # 情緒色細線 + kicker
    d.line([(80, 95), (W - 80, 95)], fill=(*accent[:3], 120), width=1)
    d.text((W // 2, 165), t["kicker"], font=F(46), fill=(*kicker_col, 255), anchor="mm")

    # ── 主標（大字 + 情緒光暈）──
    hline_y = 370
    hf_main = _fit(d, t["headline"], W - 100, 98)
    if sent == "down":
        _glow(img, (W // 2, hline_y), t["headline"], hf_main,
              (248, 248, 255, 255), (255, 50, 60, 140), gr=16, sw=3, sf=(20, 6, 8))
    else:
        _glow(img, (W // 2, hline_y), t["headline"], hf_main,
              (248, 252, 255, 255), (40, 220, 190, 130), gr=16, sw=3, sf=(6, 20, 18))

    # 主標下分隔線
    d = ImageDraw.Draw(img, "RGBA")
    _separator(d, hline_y + 85, accent, pad=90)

    # ── 底部資訊板（毛玻璃面板 + 黃底鉤子 + 數據 + 品牌）──
    _frosted_panel(img, 1400, 1920, col=scrim_col, alpha=210, accent=accent, border_top=True)
    d = ImageDraw.Draw(img, "RGBA")

    # 鉤子（黃底按鈕風格）
    hf_hook = _fit(d, t["hook_pre"] + t["hook_key"] + t["hook_post"], W - 90, 110)
    _hook(d, img, (t["hook_pre"], t["hook_key"], t["hook_post"]), 1530, hf_hook, box="yellow")

    # 數據標（毛玻璃卡片 or 實測文字）
    d = ImageDraw.Draw(img, "RGBA")
    _separator(d, 1620, accent, pad=120)

    if t.get("data") and re.search(r"\d", t["data"]):
        # 數據卡片（居中小卡）
        df = F(46, False)
        label = f"真實帳戶 · {t['data']}"
        db = d.textbbox((W // 2, 1680), label, font=df, anchor="mm")
        d.rounded_rectangle([db[0] - 20, db[1] - 10, db[2] + 20, db[3] + 10],
                             radius=10, fill=(*scrim_col, 120), outline=(*accent[:3], 140), width=1)
        _spaced(d, (W // 2, 1680), label, df, (210, 222, 236, 255), 4, "mm")
    else:
        _spaced(d, (W // 2, 1680), "真實帳戶 · 實測拆解", F(44, False),
                (200, 215, 232, 255), 4, "mm")

    # 品牌
    _spaced(ImageDraw.Draw(img, "RGBA"), (W // 2, 1835), BRAND, F(38),
            (*kicker_col[:3], 190), 6, "mm")

    return img.convert("RGB")


# ───────────────────────── 主流程 ─────────────────────────
def make_cover(slug, title, narration="", style="auto", dest=None):
    dest = Path(dest) if dest else (OUT / f"{slug}.jpg")
    if not narration:
        try:
            vp = ROOT / "output" / f"{slug}.voice.txt"
            narration = vp.read_text(encoding="utf-8")[:600] if vp.exists() else ""
        except Exception:
            narration = ""
    t = derive(title, narration)
    if style in ("tech", "real"):
        t["style"] = style
    seed = _seed(slug)
    sent = t.get("sentiment", "up")
    scene_ai = t.get("scene_en", "")

    # ── 生圖 prompt：場景模板 + 情緒調色 + 品質標籤 ──
    if t["style"] == "real":
        chart = "green rising profit" if sent == "up" else "red crashing loss"
        scene = _build_scene_prompt(title, scene_ai, sent)
        prompt = (
            f"realistic cinematic photo, a hand holding a modern smartphone displaying "
            f"a crypto trading app with a glowing {chart} chart, {scene}, "
            f"dark background studio, {_SCENE_QUALITY}"
        )
    else:
        arrow = "glowing green upward arrow, success energy" if sent == "up" else "glowing red downward arrow, danger warning"
        scene = _build_scene_prompt(title, scene_ai, sent)
        prompt = (
            f"cute chibi 3D robot mascot, big round glowing eyes, chunky rounded body, "
            f"standing lower-left foreground, {arrow} on the right, "
            f"dark navy gradient studio background, soft cinematic rim light, "
            f"{scene}, {_SCENE_QUALITY}"
        )
    base = _poll(prompt, seed, TMP / f"{slug}_base.jpg")
    if base is None:
        try:
            import make_video as mv
            return mv.render_candle_card(W, H, big_text=t["headline"], watermark=BRAND,
                                         accent=(54, 230, 220), seed=slug, dest=dest)
        except Exception:
            base = Image.new("RGB", (W, H), (10, 14, 22))
    img = compose_real(base, t) if t["style"] == "real" else compose_tech(base, t)
    img.save(dest, "JPEG", quality=93)
    print(f"[ok] 封面 {dest.name}（style={t['style']}, sentiment={sent}）")
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--narration", default="")
    ap.add_argument("--style", default="auto", choices=["auto", "tech", "real"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    make_cover(a.slug, a.title, a.narration, a.style, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
