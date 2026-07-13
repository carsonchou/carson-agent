#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_cover.py — 高質感 Shorts/縮圖封面產生器（量化阿森品牌）。

2026-07 B4 全面重製：淘汰舊版「AI 生圖·手拿手機紅光走勢圖」cliché（同一模子、且會把
「真實帳戶」字樣蓋在 AI 算圖上、不誠實）。改成純程式繪製的「暗色 + 數據卡（仿 macOS
視窗顯示回測數字 + 免責）」風格，收斂到頻道最好那張(『我給機器人1萬跑30天』)的設計語言：
  · 背景：深色交易終端（細網格 + 種子穩定 K 線走勢帶），不再打 Pollinations 生圖 API
    （不再有「同一姿勢的手/手機」問題、不再受限流/超時、離線可跑、100% 是自家視覺語言）
  · 數據卡：只有 style=real(結果/實測類) 才顯示；優先用 backtest_cards.json 的真回測數字
    （label=「真回測」），否則用 AI/啟發式抽出的示意數字但誠實標「示意回測」——
    誠信鐵則：「真實帳戶／真回測」字樣只准蓋在真數據上，絕不蓋在示意/AI 算圖上。
  · style=tech(原理/教學/概念類) 不強塞數字卡，只留 kicker+headline+hook+品牌，同一套
    暗色語言但不編造數據。
  · 品牌浮水印/kicker 固定高對比淺色，不再跟著 sentiment 變成深底看不到的粉紅字。

流程：llm.complete(共用路由，走 OpenRouter，失敗退回鏈同其他腳本；或啟發式保底) 從標題/旁白抽
      「頂部小字 kicker / 主標 headline / 鉤子(前+金字+後) / 亮點數據 data / 漲跌情緒 sentiment /
      適用 style」→ 純 PIL 合成 → 1080x1920 JPG。
      2026-07 B6：淘汰直打 Anthropic API(常 400 失敗只能退保底)，改走產線共用 llm.py。

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
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "assets" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1080, 1920
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


# ───────────────────────── 品牌強調色（統一走 design_system.json）─────────────────────────
GOLD = (255, 209, 102)              # 內建保底暗金 #FFD166——讀不到 design_system.json 時退回這個值
GOLD_DARK = (176, 138, 58)
INK = (236, 242, 250)
MUT = (165, 176, 196)
RED_ACCENT = (230, 60, 70)
TEAL_ACCENT = (54, 230, 200)
BASE_BG = (9, 12, 20)


def _load_accent():
    """從 design_system.json 讀品牌唯一強調色(accent_hex，暗金)。B7(2026-07)：縮圖強調色不再依漲跌
    切換成青綠/紅(那是舊「情緒色盤」_palette 的產物，導致每支片邊框/pill 顏色隨機、品牌識別度低)，
    改統一收斂成金色；漲跌語意改只留給 _draw_vertical_card 裡數字本身的 pct_color(紅跌/綠漲)。
    讀不到就退回內建 GOLD 常數，並記 log(不 crash)。"""
    try:
        cfg = json.loads((ROOT / "STUDIO" / "design_system.json").read_text(encoding="utf-8"))
        hexv = str(cfg.get("accent_hex", "")).lstrip("#")
        if len(hexv) == 6:
            return tuple(int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 讀不到 design_system.json accent_hex，退回內建暗金：{str(e)[:70]}", file=sys.stderr)
    return GOLD


ACCENT = _load_accent()             # 品牌唯一強調色：縮圖邊框/分隔線/pill/kicker 底線全部吃這個
BRAND_TEXT = (*ACCENT, 235)         # 浮水印/kicker 字：金色、留一點透明(暗色克制、不刺眼)


def _scrim_tone(sentiment):
    """背景暗角底色隨漲跌微調——只是極不顯眼的暗色差異，不是可見強調色，
    真正會被看到的品牌強調色一律走上面的 ACCENT(金)，不受漲跌影響。"""
    return (8, 6, 10) if sentiment == "down" else (4, 10, 16)


# ───────────────────────── 文字推導 ─────────────────────────
_REAL_KW = ("實測", "結果", "帳戶", "30天", "天後", "回測", "賺", "虧", "績效", "報酬", "實盤", "公開")


def _smart_cut(t: str, limit: int = 10) -> str:
    """保底標題斷句:優先在標點處斷,絕不切在數字/英文單字中間。

    2026-07-13 實案:LLM 文案失敗退保底時,舊的 `t[:10]` 把
    「年化只差7趴?多拉10年後 0050 跟 0056 報酬缺口竟這麼大」
    切成「年化只差7趴?多拉1」——「多拉1」語意破碎(切在數字 10 的中間),縮圖就這樣出街。
    """
    t = (t or "").strip()
    if not t or len(t) <= limit:
        return t
    # ① 優先:第一個標點前的完整子句,長度合格就用它(語意完整,最好看)
    for m in re.finditer(r"[?？!！,，、。:：|｜·]", t):
        seg = t[:m.start()].strip()
        if seg and len(seg) <= limit:
            return seg
    # ② 沒有合適標點 → 硬切,但退回到不會切斷「數字/英文」token 的位置
    cut = limit
    def _tok(ch):  # 數字或英數(同一個 token 的字元,不可從中間切開)
        return ch.isdigit() or (ch.isascii() and ch.isalnum())
    while cut > 2 and cut < len(t) and _tok(t[cut - 1]) and _tok(t[cut]):
        cut -= 1
    seg = t[:cut].strip()
    # ③ 再清掉尾巴的「懸空連接詞/助詞」——切在這些字上語意會斷在半空:
    #    「0050定期定額vs」「台積電跌破500元該」。清到剩實詞為止。
    _DANGLE = ("vs", "VS", "與", "跟", "和", "或", "的", "該", "竟", "卻", "是", "在",
               "對", "從", "把", "被", "讓", "就", "才", "又", "也", "更", "而", "並", "還")
    changed = True
    while changed and len(seg) > 2:
        changed = False
        for d_ in _DANGLE:
            if seg.endswith(d_):
                seg = seg[: -len(d_)].strip()
                changed = True
                break
    return seg


def _heuristic(title):
    t = re.sub(r"[（(].*?[)）]", "", title or "").strip()
    return {
        "kicker": "量化交易實測",
        "headline": _smart_cut(t, 10) or "你不知道的真相",
        "hook_pre": "結果", "hook_key": "讓人意外", "hook_post": "？",
        "data": "", "sentiment": "up",
        "style": "real" if any(k in (title or "") for k in _REAL_KW) else "tech",
    }


def derive(title, narration=""):
    fb = _heuristic(title)
    if not any(os.environ.get(_k, "").strip() for _k in
               ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")):
        return fb
    prompt = (
        "你是量化交易頻道的縮圖文案。讀標題與旁白，輸出 JSON（繁中、不誇大不保證收益）。"
        "★務必極短有力，嚴守字數上限，太長會爆版：\n"
        '{"kicker":"頂部小字情境(≤13字,如\'比特幣崩盤·18萬人爆倉\')",'
        '"headline":"主標狠話(≤9字,衝擊反差,如\'全場爆倉它沒事\'\'虧損中反而賺\')",'
        '"hook_pre":"鉤子前段(≤5字)","hook_key":"金色強調關鍵詞(2-3字)","hook_post":"鉤子後段(≤3字,常是問號)",'
        '"//note":"hook_pre+hook_key+hook_post 三段合起來必須≤9字、像\'它為什麼還在|賺|？\'或\'結果竟然|賺爆|了\'",'
        '"data":"亮點數據短語(≤7字,如\'+8.6%\'\'5.8倍\',只放數字，無合適可空)",'
        '"sentiment":"up或down(結論賺/正面=up,崩跌/虧=down)",'
        '"style":"real(結果/實測/帳戶/績效類)或tech(原理/教學/概念/比較類)"}\n'
        f"標題：{title}\n旁白：{(narration or '')[:500]}"
    )
    try:
        import llm  # 共用路由：主供應商(OpenRouter)→失敗退回 fallback，換模型只改 env，同其他腳本
        txt = llm.complete(prompt, max_tokens=400, temperature=0.4)
        d = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        for k, v in fb.items():
            d.setdefault(k, v)
        if d.get("style") not in ("real", "tech"):
            d["style"] = fb["style"]
        if d.get("sentiment") not in ("up", "down"):
            d["sentiment"] = "up"
        # 硬截斷保險（防爆框）——用 _smart_cut 而非裸 [:N]，LLM 偶爾也會回超長句，
        # 裸切一樣會切在數字/英文中間出「多拉1」這種破碎字(2026-07-13 實案)。
        d["headline"] = _smart_cut(str(d.get("headline", "")), 10)
        d["kicker"] = _smart_cut(str(d.get("kicker", "")), 14)
        _dat = str(d.get("data", "")).strip()
        d["data"] = _dat if (re.search(r"\d", _dat) and len(_dat) <= 8) else ""
        pre, key, post = str(d.get("hook_pre", "")), str(d.get("hook_key", "")), str(d.get("hook_post", ""))
        key = key[:4]
        if len(pre) + len(key) + len(post) > 10:
            pre = pre[:max(0, 10 - len(key) - len(post))]
        d["hook_pre"], d["hook_key"], d["hook_post"] = pre, key, post
        return d
    except Exception as e:  # noqa: BLE001
        print(f"[warn] LLM 文案失敗，用保底：{str(e)[:70]}", file=sys.stderr)
        return fb


def _seed(slug):
    return int(hashlib.md5((slug or "x").encode("utf-8")).hexdigest(), 16) % 100000


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
    """細水平分隔線 + 兩端小菱形裝飾。注意：直接 draw 在既有 RGBA 圖上不會做半透明混合(整像素覆寫)，
    這裡是細線/小圖標，一律用不透明色(視覺上仍是細線，不影響觀感)。"""
    d.line([(pad, y), (W - pad, y)], fill=(*accent[:3], 255), width=1)
    for cx in (pad, W - pad):
        d.polygon([(cx, y - 5), (cx + 5, y), (cx, y + 5), (cx - 5, y)],
                  fill=(*accent[:3], 255))


def _fit(d, t, max_w, start, mn=44):
    s = start
    while s > mn:
        if d.textbbox((0, 0), t, font=F(s))[2] <= max_w:
            return F(s)
        s -= 4
    return F(mn)


def _hook(d, img, txt, y, hf, box=None, glow_col=None):
    pre, key, post = txt
    w1 = d.textbbox((0, 0), pre, font=hf)[2]
    w2 = d.textbbox((0, 0), key, font=hf)[2]
    w3 = d.textbbox((0, 0), post, font=hf)[2]
    x0 = (W - (w1 + w2 + w3)) // 2
    if box == "yellow":
        b = d.textbbox((W // 2, y), pre + key + post, font=hf, anchor="mm")
        bx0 = max(28, b[0] - 36); bx1 = min(W - 28, b[2] + 36)
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


# ───────────────────────── 暗色交易終端背景（取代 AI 生圖） ─────────────────────────
def _market_bg(accent, seed="x", tall_band=False):
    """深色『交易終端』直式背景：細網格 + 種子穩定 K 線走勢帶 + accent 指標線。
    純程式繪製、零網路依賴——徹底移除舊版「AI 生圖手拿手機」cliché 的來源。
    tall_band=True(tech 風格、無數據卡可填版面)時走勢帶拉高蓋住中段，避免大片空白。"""
    img = Image.new("RGB", (W, H), BASE_BG)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 54):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 9), width=1)
    for y in range(0, H, 54):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 9), width=1)
    try:
        import make_thumbnails as mt
        seed_vals = mt._seed_vals
    except Exception:  # noqa: BLE001
        def seed_vals(sd, n, lo, hi):
            val = int.from_bytes(hashlib.md5((sd or "x").encode("utf-8")).digest()[:8], "big")
            out = []
            for _ in range(n):
                val = (val * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
                out.append(lo + (val >> 11) / float(1 << 53) * (hi - lo))
            return out
    n = 40
    band_top = int(H * 0.30) if tall_band else int(H * 0.56)
    band_bot = int(H * 0.95)
    step = W / n
    r = seed_vals(seed, n, -1.0, 1.0)
    prices, p = [], 0.5
    for v in r:
        p = min(0.92, max(0.08, p + v * 0.09))
        prices.append(p)
    span = band_bot - band_top
    up, dn, cw = (34, 200, 128), (228, 78, 90), step * 0.5
    pts, prev = [], prices[0]
    for i, p in enumerate(prices):
        cx = step * i + step / 2
        mid = band_bot - p * span
        col = up if p >= prev else dn
        prev = p
        body = 10 + abs(r[i]) * 16
        wick = body / 2 + 6 + abs(r[i]) * 10
        d.line([(cx, mid - wick), (cx, mid + wick)], fill=(*col, 55), width=2)
        d.rectangle([cx - cw / 2, mid - body / 2, cx + cw / 2, mid + body / 2], fill=(*col, 55))
        pts.append((cx, mid))
    if len(pts) > 1:
        d.line(pts, fill=(*accent, 65), width=3, joint="curve")
    return img


# ───────────────────────── 誠實數據卡（只在有真/示意數字時才畫，見 compose_datacard） ─────────────────────────
def _pick_card(slug, title, t):
    """誠信鐵則：優先用 backtest_cards.json 的真回測數字(label=真回測)；否則用示意數字但誠實標
    「示意回測」——絕不把『真實帳戶/真回測』字樣蓋在 AI 算圖或憑空編的數字上(B4④)。"""
    try:
        import make_thumbnails as mt
        real = mt._real_card(slug, title)
        if real:
            real = dict(real)
            real["label"] = "真回測"
            return real
    except Exception:  # noqa: BLE001
        pass
    sent = t.get("sentiment", "up")
    raw = (t.get("data") or "").strip()
    digits = re.search(r"[\d.]+", raw)
    if digits:
        val = digits.group(0)
        pct = f"{'+' if sent == 'up' else '-'}{val.lstrip('+-')}"
        if "%" not in pct and "倍" not in pct:
            pct += "%"
    else:
        pct = "+82.4%" if sent == "up" else "-32.0%"
    return {
        "label": "示意回測", "strat": "策略回測（示意）",
        "metric": "回測總報酬（含回撤，示意）",
        "pct": pct, "pct_color": "red" if sent == "down" else "green",
        "mdd": "最大回撤　示意值", "range": "※非真實逐筆回測結果",
        "note": "※示意回測，非真實獲利保證",
    }


def _draw_vertical_card(img, card, accent):
    """仿 macOS 視窗的暗色回測卡（直式），視覺語言對齊
    assets/thumbnails/我給機器人1萬跑30天_結果公開.jpg 這張頻道最好的縮圖。"""
    PANEL, BORDER = (16, 21, 33), (46, 56, 80)
    INK2, GREY = (233, 239, 249), (138, 150, 174)
    GREEN, RED = (38, 214, 134), (240, 86, 96)
    pct = card.get("pct", "+82.4%")
    pc = (card.get("pct_color") or ("red" if str(pct).strip().startswith("-") else "green")).lower()
    PCT_COL = RED if pc == "red" else GREEN
    x0, y0, x1, y1 = 90, 640, W - 90, 1500
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0 + 8, y0 + 16, x1 + 8, y1 + 16], radius=28, fill=(0, 0, 0, 120))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x0, y0, x1, y1], radius=28, fill=PANEL, outline=BORDER, width=2)
    px = x0 + 40
    for i, cc in enumerate([(240, 86, 96), (255, 184, 40), (38, 214, 134)]):
        d.ellipse([px + i * 30, y0 + 34, px + i * 30 + 18, y0 + 34 + 18], fill=cc)
    d.text((px, y0 + 96), card.get("strat", "策略回測"), font=F(38), fill=INK2)
    lbl = card.get("label", "回測")
    lf = F(30)
    lb = d.textbbox((0, 0), lbl, font=lf); lw = lb[2] - lb[0]
    pill_box = [x1 - lw - 76, y0 + 88, x1 - 40, y0 + 88 + (lb[3] - lb[1]) + 20]
    # 半透明玻璃底：PIL 在既有 RGBA 圖上直接 draw 半透明 fill 不會與底圖混合(會整像素覆寫成實色，
    # 文字同色蓋上去會消失)——一律先畫在獨立透明圖層，再 alpha_composite 疊上去(同 make_brand_assets 修法)。
    pill_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(pill_layer).rounded_rectangle(pill_box, radius=10, fill=(*accent[:3], 40))
    img.alpha_composite(pill_layer)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(pill_box, radius=10, outline=(*accent[:3], 255), width=1)
    d.text((pill_box[0] + 18, y0 + 96), lbl, font=lf, fill=(*accent[:3], 255))
    d.text((px, y0 + 168), card.get("metric", "回測總報酬（含回撤）"), font=F(30), fill=GREY)
    pf = F(140)
    d.text((px + 3, y0 + 218), pct, font=pf, fill=(0, 0, 0, 130))
    d.text((px, y0 + 214), pct, font=pf, fill=PCT_COL)
    d.line([(px, y0 + 430), (x1 - 46, y0 + 430)], fill=BORDER, width=2)
    ry = y0 + 462
    for label in (card.get("mdd", "最大回撤 -15.3%"), card.get("range", "夏普 4.8｜勝率 54%")):
        d.text((px, ry), label, font=F(34), fill=INK2)
        ry += 58
    d.text((px, y1 - 58), card.get("note", "※歷史回測，非未來獲利保證"), font=F(26, False), fill=GREY)


def _brand_footer(img, y):
    """底部品牌列：logo(左)+浮水印文字，整體置中排版——B7 新增品牌 logo 疊圖。
    logo 檔不存在或載入失敗時優雅退回純文字版(不 crash 整條產線)。"""
    f = F(36)
    d = ImageDraw.Draw(img, "RGBA")
    ws = [d.textbbox((0, 0), ch, font=f)[2] for ch in BRAND]
    text_w = sum(ws) + 6 * (len(BRAND) - 1)
    logo_img, logo_gap = None, 16
    logo_path = ROOT / "assets" / "brand" / "logo.png"
    if logo_path.exists():
        try:
            raw = Image.open(logo_path).convert("RGBA")
            logo_h = 48
            scale = logo_h / raw.height
            logo_img = raw.resize((max(1, int(raw.width * scale)), logo_h), Image.LANCZOS)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] logo 載入失敗({str(e)[:70]})，退回純文字浮水印", file=sys.stderr)
            logo_img = None
    total_w = text_w + (logo_img.width + logo_gap if logo_img else 0)
    x0 = W // 2 - total_w // 2
    if logo_img:
        img.alpha_composite(logo_img, (x0, y - logo_img.height // 2))
        x0 += logo_img.width + logo_gap
    d = ImageDraw.Draw(img, "RGBA")
    _spaced(d, (x0, y), BRAND, f, BRAND_TEXT, 6, "lm")


# ───────────────────────── 風格合成 ─────────────────────────
def compose_datacard(t, slug, title):
    """B4：全線收斂到「暗色 + 數據卡」風格。style=real 才畫回測卡(誠實標真/示意)；
    style=tech 只留 kicker/headline/hook/品牌(同一套暗色語言，不編數字)。"""
    sent = t.get("sentiment", "up")
    accent, scrim_col = ACCENT, _scrim_tone(sent)

    img = _market_bg(accent, seed=slug or title or "x", tall_band=(t.get("style") != "real")).convert("RGBA")
    _scrim(img, 470, 1330, scrim_col)
    _vignette(img, strength=140)

    # 頂部 kicker（固定高對比，不受 sentiment 影響——修浮水印/文字低對比 B5）
    _frosted_panel(img, 55, 235, col=scrim_col, alpha=185, accent=accent, border_top=False)
    d = ImageDraw.Draw(img, "RGBA")
    # 注意：直接在既有 RGBA 圖上 draw 半透明 fill 不會與底圖混合(見 _draw_vertical_card 註解)，
    # 這裡都是細裝飾線/小圖標，乾脆用完全不透明色(視覺上一樣是細線，不影響觀感、不踩雷)。
    d.line([(80, 95), (W - 80, 95)], fill=(*accent[:3], 255), width=1)
    d.text((W // 2, 165), t["kicker"], font=F(46), fill=BRAND_TEXT, anchor="mm")

    # 主標
    hline_y = 380
    hf_main = _fit(d, t["headline"], W - 100, 96)
    _glow(img, (W // 2, hline_y), t["headline"], hf_main,
          (248, 252, 255, 255), (*accent[:3], 130), gr=14, sw=3, sf=(6, 10, 16))
    d = ImageDraw.Draw(img, "RGBA")
    _separator(d, hline_y + 80, accent, pad=100)

    if t.get("style") == "real":
        card = _pick_card(slug, title, t)
        _draw_vertical_card(img, card, accent)

    # 底部鉤子(黃底按鈕) + 品牌浮水印+logo（金色統一，見 _brand_footer）
    _frosted_panel(img, 1560, 1790, col=scrim_col, alpha=210, accent=accent, border_top=True)
    d = ImageDraw.Draw(img, "RGBA")
    hf_hook = _fit(d, t["hook_pre"] + t["hook_key"] + t["hook_post"], W - 90, 100)
    _hook(d, img, (t["hook_pre"], t["hook_key"], t["hook_post"]), 1660, hf_hook, box="yellow")
    _brand_footer(img, 1745)

    return img.convert("RGB")


def _advisor_cutout_thumb():
    """借用 make_brand_assets 的顧問去背快取(assets/brand/advisor_cutout.png)，避免這裡重複寫一份
    rembg 邏輯。找不到來源就丟例外，呼叫端(compose_advisor)自行退回無人像版。"""
    import make_brand_assets as mba  # 延遲載入，只有真的要顧問變體才需要
    return mba.advisor_cutout()


def compose_advisor(t, slug, title):
    """顧問人物縮圖變體(2026-07 B3b 新增)：真人半身像(advisor_v4 去背)滿版當背景主體，
    上方壓 kicker/主標、下方壓黃底鉤子+品牌浮水印，仿競品「真人+大字」構圖，增加點擊 hook。
    **預設不啟用**——現有乾淨「數據卡」風(compose_datacard)仍是預設，這裡只是多一種可選變體
    增加縮圖多樣性；呼叫端要用得傳 variant="advisor"（見 make_cover()/CLI --variant）。"""
    sent = t.get("sentiment", "up")
    accent, scrim_col = ACCENT, _scrim_tone(sent)
    img = _market_bg(accent, seed=slug or title or "x", tall_band=True).convert("RGBA")

    try:
        cutout = _advisor_cutout_thumb()
        scale = (W * 1.06) / cutout.width  # 略寬於畫布，滿版出血、不留左右白邊
        pw, ph = max(1, int(cutout.width * scale)), max(1, int(cutout.height * scale))
        person = cutout.resize((pw, ph), Image.LANCZOS)
        px = (W - pw) // 2
        py = H - ph  # 底部對齊，頭頂上方留白給 kicker/主標
        # 暗金背光(頭肩後方)，呼應品牌金、增加主視覺質感
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gcx, gcy = W // 2, py + int(ph * 0.22)
        gd.ellipse([gcx - 480, gcy - 480, gcx + 480, gcy + 480], fill=(*GOLD, 70))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(110)))
        # 底部黃色鉤子面板本身有 alpha=222 的毛玻璃底，疊在人像胸口上仍可讀，不需額外柔化。
        img.alpha_composite(person, (px, py))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 顧問人像合成失敗({exc})，退回無人像版(仍會有 kicker/主標/鉤子)", file=sys.stderr)

    _scrim(img, 520, 1300, scrim_col)
    _vignette(img, strength=120)

    # 頂部 kicker
    _frosted_panel(img, 55, 235, col=scrim_col, alpha=185, accent=accent, border_top=False)
    d = ImageDraw.Draw(img, "RGBA")
    d.line([(80, 95), (W - 80, 95)], fill=(*accent[:3], 255), width=1)
    d.text((W // 2, 165), t["kicker"], font=F(46), fill=BRAND_TEXT, anchor="mm")

    # 主標(人像頭頂上方留白區)
    hline_y = 380
    hf_main = _fit(d, t["headline"], W - 100, 96)
    _glow(img, (W // 2, hline_y), t["headline"], hf_main,
          (248, 252, 255, 255), (*accent[:3], 150), gr=14, sw=3, sf=(6, 10, 16))
    d = ImageDraw.Draw(img, "RGBA")
    _separator(d, hline_y + 80, accent, pad=100)

    # 底部鉤子(黃底按鈕) + 品牌浮水印+logo，疊在人像胸口位置(毛玻璃面板保證可讀性)
    _frosted_panel(img, 1560, 1790, col=scrim_col, alpha=222, accent=accent, border_top=True)
    d = ImageDraw.Draw(img, "RGBA")
    hf_hook = _fit(d, t["hook_pre"] + t["hook_key"] + t["hook_post"], W - 90, 100)
    _hook(d, img, (t["hook_pre"], t["hook_key"], t["hook_post"]), 1660, hf_hook, box="yellow")
    _brand_footer(img, 1745)

    return img.convert("RGB")


# ───────────────────────── 主流程 ─────────────────────────
def make_cover(slug, title, narration="", style="auto", dest=None, variant="clean"):
    """variant="clean"(預設，不變) 走現有數據卡風 compose_datacard；variant="advisor" 走
    2026-07 B3b 新增的顧問真人像變體 compose_advisor(增加縮圖多樣性+真人 hook，非預設)。"""
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
    try:
        img = compose_advisor(t, slug, title) if variant == "advisor" else compose_datacard(t, slug, title)
        img.save(dest, "JPEG", quality=93)
        print(f"[ok] 封面 {dest.name}（style={t['style']}, sentiment={t.get('sentiment')}, variant={variant}）")
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] compose 失敗({exc})，退回 K 線卡保底", file=sys.stderr)
        try:
            import make_video as mv
            return mv.render_candle_card(W, H, big_text=t["headline"], watermark=BRAND,
                                         accent=GOLD, seed=slug, dest=dest)
        except Exception:
            return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--narration", default="")
    ap.add_argument("--variant", default="clean", choices=["clean", "advisor"])
    ap.add_argument("--style", default="auto", choices=["auto", "tech", "real"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    make_cover(a.slug, a.title, a.narration, a.style, a.out, a.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
