#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_brand_assets.py — 生成品牌大頭貼(800x800) + 頻道橫幅(2048x1152)。

存到 assets/brand/。大頭貼/橫幅無法用 API 設定，請在 Studio→自訂→個人資料 上傳。
橫幅關鍵內容置於中央安全區(各裝置都看得到)。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"
OUT.mkdir(parents=True, exist_ok=True)
ADVISOR_SRC = OUT / "advisor.png"          # 正典顧問臉(2026-07 B3b：Carson 選定 advisor_v4)
ADVISOR_CUTOUT_CACHE = OUT / "advisor_cutout.png"  # 去背快取，避免每次重生都重跑 rembg

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


# ── 核心符號：折線箭頭(暗金) ──────────────────────────────────────────
# 2026-07 B6：Carson 定案 logo.png 的折線箭頭為品牌唯一核心符號，banner/avatar/intro
# 全部統一貼同一個 icon(深色圓角方底+金折線箭頭)，不再各自畫不同版本的箭頭，
# 確保三者(logo/banner/avatar)看起來像同一套。座標取自 make_logo() 512 畫布的相對位移。
ARROW_REL = [(-136, 74), (-56, 4), (4, 44), (64, -46), (136, -126)]
ARROW_TIP_REL = (170, -160)


def draw_arrow(d, cx, cy, scale=1.0, color=ACCENT, width=30, dot_r=9):
    """畫折線箭頭(低→高→回檔→噴出+箭頭尖)，與 make_logo() 完全同一形狀，只是可縮放/移動中心。"""
    pts = [(cx + int(x * scale), cy + int(y * scale)) for x, y in ARROW_REL]
    lw = max(2, int(width * scale))
    d.line(pts, fill=color, width=lw, joint="curve")
    r = max(1, int(dot_r * scale))
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    tip = (cx + int(ARROW_TIP_REL[0] * scale), cy + int(ARROW_TIP_REL[1] * scale))
    d.line([pts[-1], tip], fill=color, width=lw)
    d.polygon([tip, (tip[0] - int(46 * scale), tip[1] + int(8 * scale)),
               (tip[0] - int(6 * scale), tip[1] + int(50 * scale))], fill=color)
    return pts, tip


def draw_logo_icon(img, cx, cy, scale=1.0):
    """在 img(任意模式)貼上與 assets/brand/logo.png 同一視覺語言的品牌符號 icon：
    深色圓角方底 + 金折線箭頭。用獨立透明圖層畫好再 paste(用自己當 mask)貼上，
    確保圓角外的透明區不覆蓋底圖。回傳貼上的 icon 邊長(int)。"""
    S = max(1, int(512 * scale))
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    di = ImageDraw.Draw(icon)
    pad = max(1, int(28 * scale))
    di.rounded_rectangle([pad, pad, S - pad, S - pad], radius=max(1, int(96 * scale)),
                          fill=(11, 17, 36, 240), outline=ACCENT, width=max(2, int(12 * scale)))
    draw_arrow(di, S // 2, S // 2, scale=scale, width=30, dot_r=9)
    img.paste(icon, (cx - S // 2, cy - S // 2), icon)
    return S


def _advisor_photo():
    """讀正典顧問臉照片(assets/brand/advisor.png，RGB)。找不到就丟例外，呼叫端自行處理。"""
    if not ADVISOR_SRC.exists():
        raise FileNotFoundError(f"缺 {ADVISOR_SRC}——請先把選定的 advisor_vN.png 複製成 advisor.png")
    return Image.open(ADVISOR_SRC).convert("RGB")


def advisor_cutout(use_cache=True):
    """回傳顧問人像去背後的 RGBA(已裁到人形 bbox，無多餘透明邊)。
    優先用快取(assets/brand/advisor_cutout.png)，沒有才跑 rembg(模型載入慢，跑一次存起來)。
    rembg 不可用或失敗時退回原圖(不去背，呼叫端仍可用，只是會帶方形背景)。"""
    if use_cache and ADVISOR_CUTOUT_CACHE.exists():
        return Image.open(ADVISOR_CUTOUT_CACHE).convert("RGBA")
    im = _advisor_photo()
    try:
        from rembg import remove  # type: ignore
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        out = remove(buf.getvalue())
        cut = Image.open(io.BytesIO(out)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] rembg 去背失敗({exc})，用原圖(無去背)", file=sys.stderr)
        cut = im.convert("RGBA")
    bbox = cut.getbbox()
    if bbox:
        cut = cut.crop(bbox)
    try:
        cut.save(ADVISOR_CUTOUT_CACHE, "PNG")
    except Exception:
        pass
    return cut


def make_avatar():
    """800x800，頻道正式大頭貼＝顧問真人臉(2026-07 B3b 定案，Carson 選 advisor_v4)。
    箭頭符號**不再**當大頭貼(容易被圓形裁邊、且真人臉=治「AI 農場」味)——箭頭符號改保留在
    logo.png/浮水印/片頭當品牌 symbol，兩者分工。做法：從 advisor.png(768x768 半身工作站照)
    裁一個臉部置中的方形(裁掉部份身體，留夠邊，避免圓形裁邊切到臉)，加暗金環呼應品牌識別。"""
    S = 800
    photo = _advisor_photo()  # 768x768
    pw, ph = photo.size
    # 臉部置中裁切框：源圖是半身工作站照，臉落在上半部；經目視校正的裁切框(pw=ph=768時
    # 約為 480x480、y 從 15px 起)，臉部留有頭頂+下巴+肩膀邊，圓形裁邊也不會切到五官。
    crop_s = int(pw * 0.625)
    x0 = (pw - crop_s) // 2
    y0 = int(ph * 0.02)
    y0 = min(y0, ph - crop_s)
    face = photo.crop((x0, y0, x0 + crop_s, y0 + crop_s)).resize((S, S), Image.LANCZOS)
    img = face.convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    # 四角柔化暗角(照片邊角比中央暗一點，呼應品牌深色質感、也讓圓形裁邊過渡更自然)
    vgn = Image.new("L", (S, S), 0)
    vd = ImageDraw.Draw(vgn)
    vd.ellipse([-S * 0.35, -S * 0.35, S * 1.35, S * 1.35], fill=255)
    vgn = vgn.filter(ImageFilter.GaussianBlur(60))
    dark = Image.new("RGBA", (S, S), (*NAVY_TOP, 130))
    img = Image.composite(img.convert("RGBA"), Image.alpha_composite(img.convert("RGBA"), dark), vgn)
    d = ImageDraw.Draw(img, "RGBA")
    # 外圈品牌暗金環(跟 logo/banner 同色，識別度)
    d.ellipse([10, 10, S - 10, S - 10], outline=ACCENT, width=14)
    p = OUT / "avatar.png"
    img.convert("RGB").save(p, "PNG")
    print(f"[ok] {p.name} {S}x{S}(顧問真人臉，置中裁切)")
    return p


def make_banner():
    """2560x1440(YT 官方建議尺寸，安全區 1546x423 置中)：2026-07 B3b 重製──右側顧問真人臉
    (advisor_v4，去背)出血滿版增添真人感，左側收在安全區內的 icon(跟 logo.png 同一套折線箭頭
    symbol)+ 頻道名 + 定位語，維持跨裝置(電視/桌機/手機裁切)都看得到核心文字內容。"""
    W, H = 2560, 1440
    img = gradient(W, H).convert("RGBA")
    cx, cy = W // 2, H // 2

    # ── 右側：顧問真人臉去背，貼近右緣出血，營造「顧問走進畫面」的真人感 ──
    try:
        cutout = advisor_cutout()
        target_h = int(H * 0.97)
        scale = target_h / cutout.height
        pw, ph = max(1, int(cutout.width * scale)), target_h
        person = cutout.resize((pw, ph), Image.LANCZOS)
        # 跟品牌深藍做輕微色彩統一(乘色疊一層低透明度深藍，不蓋掉膚色細節)
        tint = Image.new("RGBA", person.size, (*NAVY_TOP, 46))
        person = Image.alpha_composite(person, tint)
        px = W - pw - 24  # 右側留一點邊，讓臉部落在安全區內(不整個貼到最右緣)
        # advisor_v4 去背後髮際線幾乎頂到裁切框頂(bbox 實測)，眼睛約在人像高度 25.5% 處。
        # 為了讓臉落在 YT 官方安全區(y:[cy-211,cy+211])內，把眼睛對齊 cy，寧可讓下半身(手/桌
        # 面反光)超出畫布下緣被裁掉，也要保臉部在安全區內(B3b：人臉是核心，不是身體)。
        EYE_RATIO = 0.255
        py = cy - int(ph * EYE_RATIO)
        # 人像背後暗金光暈，呼應品牌金
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gcx, gcy = px + pw // 2, py + int(ph * 0.30)
        gd.ellipse([gcx - 520, gcy - 520, gcx + 520, gcy + 520], fill=(*ACCENT, 60))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
        img.alpha_composite(person, (px, py))
        # 人像左緣往中央的柔化漸層，跟背景融合(不要看起來像硬貼的貼紙)
        fade_w = int(pw * 0.30)
        fade = Image.new("L", (W, H), 255)
        fd = fade.load()
        y_lo, y_hi = max(0, py), min(H, py + ph)
        x_lo, x_hi = max(0, px), min(W, px + fade_w)
        for xx in range(x_lo, x_hi):
            a = int(255 * (xx - px) / fade_w)
            for yy in range(y_lo, y_hi):
                fd[xx, yy] = min(fd[xx, yy], a)
        blend_bg = gradient(W, H).convert("RGBA")
        img = Image.composite(img, blend_bg, fade)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] banner 顧問人像合成失敗({exc})，退回純符號版", file=sys.stderr)

    # ── 左側：安全區內置中的 icon + 頻道名 + 定位語(核心文字，不隨人像出血區被裁) ──
    d = ImageDraw.Draw(img, "RGBA")
    text_cx = max(cx - 460, 507 + 380)  # 收在安全區左半，跟右側人像錯開不重疊
    icon_top = cy - 190
    icon_s = draw_logo_icon(img, text_cx, icon_top + 97, scale=0.34)
    d = ImageDraw.Draw(img, "RGBA")
    y = icon_top + icon_s + 16
    center_text(d, text_cx, y, "量化阿森｜Carson Quant", font(72), WHITE, stroke=5)
    y += 88
    d.rectangle([text_cx - 340, y + 8, text_cx + 340, y + 15], fill=ACCENT)
    y += 28
    center_text(d, text_cx, y, "用真回測拆穿割韭菜神話", font(38), (200, 214, 236), stroke=3)
    p = OUT / "banner.png"
    img.convert("RGB").save(p, "PNG")
    print(f"[ok] {p.name} {W}x{H}(顧問真人臉 + 箭頭符號 + 定位語)")
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
    # 2026-07 B6 polish：核心符號改「金色、置中、夠顯眼」(舊版低透明度 46/255 在深底上讀成灰
    # 色，且箭頭尖端往右外延但左側沒對應延伸，視覺重心偏右──改實色金 + 兩側延伸對齊 cx 置中)，
    # 擺在畫面下半部(標題文字壓中段偏上，箭頭+品牌字在下段當視覺主體填滿構圖，不搶標題)。
    # 形狀跟 logo.png 同一份 draw_arrow()，確保片頭跟 logo/banner/avatar 同一套視覺語言。
    arrow_cy = int(H * 0.70)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_arrow(ImageDraw.Draw(glow), cx, arrow_cy, scale=2.1, color=(*ac, 150), width=40, dot_r=15)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(img, "RGBA")
    draw_arrow(d, cx, arrow_cy, scale=2.1, color=(*ac, 255), width=28, dot_r=12)
    # 品牌字「量化阿森」實色金字，置於箭頭正下方，填滿下段構圖(修「構圖空」)
    center_text(d, cx, int(H * 0.855), "量化阿森", font(150), ac, stroke=6)
    # 底部強調條 + 頂部品牌小字(不透明,直接畫在 img 上沒問題)
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
    # 形狀由 draw_arrow() 統一產生(banner/avatar 的 draw_logo_icon 也是同一份)，確保三者同一套符號。
    draw_arrow(d, S // 2, S // 2, scale=1.0, width=30, dot_r=9)
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
