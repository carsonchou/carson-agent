#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pinterest_pin_generator.py — 電商 Pinterest pin 圖產生器(2:3 直式 1000x1500 JPG)。

復用 make_thumbnails.py 的暗色「交易終端」視覺語言(細網格 + 種子穩定 K 線 + accent 指標線
+ 品牌 pill + 深色數據面板),改成 Pinterest 建議的 2:3 直式比例。對應電商計畫 S1-S3 商品與
頻道主題(台股/量化)。風格延續 Carson 偏好的暗色低調質感。

誠信鐵則(承襲產線):pin 上只放「商品是什麼/內含什麼/給誰」的描述與『商品定價』(那是真實售價,
非績效宣稱),絕不放捏造的轉換率/報酬率/勝率數字。「介紹≠推薦」。

用法:
  python pinterest_pin_generator.py            # 產全部示例 pin 到 output/ecommerce_ready/pinterest/
  python pinterest_pin_generator.py --only S1  # 只產某個 SKU 的 pin
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
REPO_ROOT = PROJECT_ROOT.parent                                # carson-agent/
OUT = REPO_ROOT / "quant-service" / "output" / "ecommerce_ready" / "pinterest"
OUT.mkdir(parents=True, exist_ok=True)
MASCOT = PROJECT_ROOT / "assets" / "mascot"

W, H = 1000, 1500                                              # Pinterest 建議 2:3 直式
BASE_BG = (9, 12, 20)                                          # 近黑深色終端底(同縮圖引擎)

FONT_BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msjh.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
FONT_REG = [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]

ACCENTS = {"yellow": (255, 209, 102), "green": (88, 224, 140),
           "red": (255, 96, 96), "blue": (90, 184, 255)}
CHANNEL = "量化阿森｜Carson Quant"


def font(size: int, bold: bool = True):
    for c in (FONT_BOLD if bold else FONT_REG):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:  # noqa: BLE001
                pass
    return ImageFont.load_default()


def _seed_vals(seed, n, lo, hi):
    """由 seed 生 n 個 [lo,hi) 穩定偽隨機值(同 slug 永遠同一條 K 線,不靠全域 random)。"""
    out = []
    val = int.from_bytes(hashlib.md5((seed or "x").encode("utf-8")).digest()[:8], "big")
    for _ in range(n):
        val = (val * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        out.append(lo + (val >> 11) / float(1 << 53) * (hi - lo))
    return out


def terminal_bg(accent, seed="x"):
    """直式深色『交易終端』背景:細網格 + 種子穩定 K 線(落在下半部)+ accent 指標線
    + 上方濃暗化(保標題可讀)。同 make_thumbnails.terminal_bg 的語彙,改直式版面。"""
    img = Image.new("RGB", (W, H), BASE_BG)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 9), width=1)
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 9), width=1)
    # K 線畫在下半部(H*0.62~H*0.98),讓上方留給標題卡
    n = 40
    step = W / n
    r = _seed_vals(seed, n, -1.0, 1.0)
    prices, p = [], 0.5
    for v in r:
        p = min(0.92, max(0.08, p + v * 0.09))
        prices.append(p)
    top, bot = H * 0.60, H * 0.985
    span = bot - top
    up, dn, cw = (34, 200, 128), (228, 78, 90), step * 0.5
    pts, prev = [], prices[0]
    for i, p in enumerate(prices):
        cx = step * i + step / 2
        mid = bot - p * span
        col = up if p >= prev else dn
        prev = p
        body = 14 + abs(r[i]) * 22
        wick = body / 2 + 8 + abs(r[i]) * 14
        d.line([(cx, mid - wick), (cx, mid + wick)], fill=(*col, 66), width=2)
        d.rectangle([cx - cw / 2, mid - body / 2, cx + cw / 2, mid + body / 2], fill=(*col, 66))
        pts.append((cx, mid))
    if len(pts) > 1:
        d.line(pts, fill=(*accent, 80), width=3, joint="curve")
    # 上濃下淡暗化(1px 高漸層拉伸),讓標題區更沉、K 線區透出來
    grad = Image.new("L", (1, H))
    gp = grad.load()
    for y in range(H):
        gp[0, y] = int(210 * max(0.0, 1 - y / (H * 0.62)))
    return Image.composite(Image.new("RGB", (W, H), BASE_BG), img, grad.resize((W, H)))


def fit_font(text, max_w, start, min_size):
    """自動縮字級讓 text 寬度 ≤ max_w。"""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    s = start
    while s > min_size:
        f = font(s, True)
        b = probe.textbbox((0, 0), text, font=f, stroke_width=3)
        if b[2] - b[0] <= max_w:
            return f
        s -= 4
    return font(min_size, True)


def _paste_mascot(img, mood="neutral", target_h=300):
    """右下角貼吉祥物(品牌一致)。裁掉透明邊。失敗回 None。"""
    try:
        cand = [MASCOT / f"{mood}.png", MASCOT / "neutral.png", MASCOT / "smug.png"]
        path = next((p for p in cand if p.exists()), None)
        if not path:
            return None
        m = Image.open(path).convert("RGBA")
        bb = m.getchannel("A").getbbox()
        if bb:
            m = m.crop(bb)
        scale = target_h / m.height
        nw = max(1, int(m.width * scale))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        m = m.resize((nw, target_h), resample)
        x = W - nw - 44
        y = H - target_h - 210
        img.paste(m, (x, y), m)
        return x
    except Exception:  # noqa: BLE001
        return None


def _brand_pill(d, accent, y=54):
    """上方品牌 pill:深色玻璃 + accent 圓點 + 頻道名。"""
    tagf = font(34, bold=True)
    tb = d.textbbox((0, 0), CHANNEL, font=tagf)
    th = tb[3] - tb[1]
    ph = th + 30
    pw = (tb[2] - tb[0]) + 78
    x = 60
    d.rounded_rectangle([x, y, x + pw, y + ph], radius=14, fill=(8, 11, 18, 210),
                        outline=(*accent, 120), width=1)
    cyd = y + ph // 2
    d.ellipse([x + 22, cyd - 8, x + 38, cyd + 8], fill=accent)
    d.text((x + 56, y + ph // 2 - th // 2 - tb[1]), CHANNEL, font=tagf, fill=(224, 231, 244))
    return y + ph


def _draw_content_card(d, accent, kicker, bullets, y0):
    """中段深色資訊面板:小標(kicker,accent)+ 條列賣點(白/灰)。回下緣 y。"""
    x0, x1 = 60, W - 60
    pad = 40
    kf = font(30, bold=True)
    bf = font(38, bold=True)
    line_h = 74
    card_h = pad + 46 + 24 + len(bullets) * line_h + pad - 20
    d.rounded_rectangle([x0 + 6, y0 + 10, x1 + 6, y0 + 10 + card_h], radius=24, fill=(0, 0, 0, 110))
    d.rounded_rectangle([x0, y0, x1, y0 + card_h], radius=24, fill=(16, 21, 33), outline=(46, 56, 80), width=2)
    d.rectangle([x0, y0 + 24, x0 + 8, y0 + card_h - 24], fill=accent)
    y = y0 + pad
    d.text((x0 + pad, y), kicker, font=kf, fill=accent)
    y += 58
    for b in bullets:
        d.ellipse([x0 + pad, y + 16, x0 + pad + 14, y + 30], fill=accent)
        d.text((x0 + pad + 34, y), b, font=bf, fill=(233, 239, 249))
        y += line_h
    return y0 + card_h


def _cta_bar(d, accent, price, cta="免費領工具 → 訂閱解鎖全部"):
    """底部低調暗帶:accent 左緣 + 價格牌(上)+ CTA 白字(下,分行避免重疊)。"""
    bar_h = 172
    d.rectangle([0, H - bar_h, W, H], fill=(8, 11, 18, 230))
    d.rectangle([0, H - bar_h, 12, H], fill=accent)
    d.line([(0, H - bar_h), (W, H - bar_h)], fill=(*accent, 150), width=2)
    # 價格牌(accent 外框 pill,上行)
    pf = font(46, bold=True)
    pb = d.textbbox((0, 0), price, font=pf)
    pw = pb[2] - pb[0]
    px0, py0 = 50, H - bar_h + 24
    d.rounded_rectangle([px0, py0, px0 + pw + 44, py0 + (pb[3] - pb[1]) + 30],
                        radius=12, fill=(*accent, 30), outline=(*accent, 200), width=2)
    d.text((px0 + 22, py0 + 14 - pb[1]), price, font=pf, fill=accent)
    # CTA 白字(下行,與價格牌分行)
    d.text((50, H - 34), cta, font=font(30, bold=True), fill=(214, 222, 236), anchor="lm")


# ── 電商計畫 S1-S3 + 頻道主題,對應 pin。內容全是「商品是什麼/內含/給誰」,不含捏造績效數字 ──
PINS = [
    {"slug": "S1_台股訂閱週報", "accent": "green", "mascot": "neutral",
     "l1": "台股全市場", "l2": "每週幫你掃一遍",
     "kicker": "台股掃描 + 個股體檢週報 · 訂閱制",
     "bullets": ["全市場強弱掃描,每週更新", "個股體檢:基本面+價格 13 組事實/檔",
                 "介紹 ≠ 推薦,只給你事實不報明牌", "email + Telegram 私訊直送"],
     "price": "NT$99–149 / 月"},

    {"slug": "S2_回測數據包", "accent": "yellow", "mascot": "smug",
     "l1": "1841 檔台股", "l2": "回測數據一次打包",
     "kicker": "全市場回測數據包 · 一次買斷",
     "bullets": ["全市場歷史回測 CSV,自己隨意分析", "個股體檢手冊 + 定投檢查表",
                 "方法全公開,資料清洗過程透明", "非投資建議,是給你自己驗證的工具"],
     "price": "NT$149–990"},

    {"slug": "S3_intl_workbook", "accent": "blue", "mascot": "neutral",
     "l1": "Taiwan Stocks", "l2": "Quant Data Pack (EN)",
     "kicker": "Taiwan market quant data · English edition",
     "bullets": ["Full-market backtest workbook (CSV)", "Per-stock checkup: 13 fundamental facts",
                 "Rare: Taiwan-market data for global quants", "Educational, not financial advice"],
     "price": "US$9–29", "cta": "Free sample → get the full data pack"},

    {"slug": "T1_個股體檢系列", "accent": "yellow", "mascot": "neutral",
     "l1": "一檔一集", "l2": "台股個股體檢",
     "kicker": "頻道主題 · 免費看,深度數據磁鐵",
     "bullets": ["含息還原總報酬、最大回撤、套牢期", "20 年一檔一檔真數據攤開給你看",
                 "不喊多空,只做誠實的體檢報告", "看完想要原始數據 → 訂閱解鎖"],
     "price": "免費上片 · 數據包另售"},

    {"slug": "T2_定投脈絡", "accent": "green", "mascot": "happy",
     "l1": "存股定投", "l2": "先看數據再決定",
     "kicker": "頻道主題 · 定期定額 vs 一次買進",
     "bullets": ["一次 All in / 定期定額 / 長抱,數據對照", "跌破年線擇時到底有沒有用?回測給你看",
                 "0050 / 0056 / 00878 全攤開", "工具免費領,完整檢查表訂閱解鎖"],
     "price": "免費領檢查表"},
]


def make_pin(cfg: dict) -> Path:
    accent = ACCENTS.get(cfg.get("accent", "yellow"), ACCENTS["yellow"])
    img = terminal_bg(accent, seed=cfg["slug"])
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, 12, H], fill=accent)                    # 左緣 accent 直條

    bottom = _brand_pill(d, accent, y=54)

    # 主標兩行(自動縮字級不溢出;陰影 + 細描邊)
    max_w = W - 130
    y = bottom + 60
    f1 = fit_font(cfg["l1"], max_w, start=118, min_size=64)
    d.text((64, y + 5), cfg["l1"], font=f1, fill=(0, 0, 0, 165))
    d.text((60, y), cfg["l1"], font=f1, fill=accent, stroke_width=3, stroke_fill=(6, 9, 15))
    b1 = d.textbbox((60, y), cfg["l1"], font=f1, stroke_width=3)
    d.rectangle([64, b1[3] + 12, 64 + min(max_w, b1[2] - 60), b1[3] + 22], fill=accent)
    y2 = b1[3] + 44
    f2 = fit_font(cfg["l2"], max_w, start=104, min_size=56)
    d.text((64, y2 + 5), cfg["l2"], font=f2, fill=(0, 0, 0, 165))
    d.text((60, y2), cfg["l2"], font=f2, fill=(238, 244, 253), stroke_width=3, stroke_fill=(6, 9, 15))
    b2 = d.textbbox((60, y2), cfg["l2"], font=f2, stroke_width=3)

    # 中段資訊卡
    card_bottom = _draw_content_card(d, accent, cfg["kicker"], cfg["bullets"], b2[3] + 60)

    # 吉祥物(卡片與底條之間的右側空檔)
    _paste_mascot(img, mood=cfg.get("mascot", "neutral"), target_h=280)

    # 底部 CTA + 價格
    _cta_bar(d, accent, cfg["price"], cta=cfg.get("cta", "免費領工具 → 訂閱解鎖全部"))

    out = OUT / f"pin_{cfg['slug']}.jpg"
    img.save(out, "JPEG", quality=92)
    kb = out.stat().st_size / 1024
    print(f"[ok] {out.name}  ({W}x{H}, {kb:.0f} KB)")
    return out


def main() -> int:
    only = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--only":
        only = sys.argv[2]
    n = 0
    for cfg in PINS:
        if only and only not in cfg["slug"]:
            continue
        make_pin(cfg)
        n += 1
    print(f"完成 {n} 張 pin,輸出目錄:{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
