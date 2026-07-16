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
# v2:輸出到 v2/pinterest(對齊電商 v2 商品線 + REDESIGN_SPEC_product 視覺 token)
OUT = REPO_ROOT / "quant-service" / "output" / "ecommerce_ready" / "v2" / "pinterest"
OUT.mkdir(parents=True, exist_ok=True)
MASCOT = PROJECT_ROOT / "assets" / "mascot"

W, H = 1000, 1500                                              # Pinterest 建議 2:3 直式
BASE_BG = (11, 14, 20)                                         # #0B0E14 v2 主背景(近黑帶藍)

FONT_BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msjh.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
FONT_REG = [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]

# v2 視覺 token(REDESIGN_SPEC_product §2.1):暗金 gold=#C9A227 / gold-hi=#E3B93E,
# 台股漲紅 #FF5C5C(up)/ 跌綠 #33D69F(dn)。marketing accent 用暗金 gold 系為主。
ACCENTS = {"gold": (227, 185, 62), "green": (51, 214, 159),
           "red": (255, 92, 92), "blue": (90, 184, 255)}
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
    # 台股慣例:漲=紅(up #FF5C5C)、跌=綠(dn #33D69F)——與西方相反,對齊 v2 視覺 token
    up, dn, cw = (255, 92, 92), (51, 214, 159), step * 0.5
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


# ── 電商 v2 商品線(旗艦訂閱為主位的四層漏斗),對應 5 張 pin。價格 = config.py 事實來源。
#    內容全是「商品是什麼/內含/給誰」,不含捏造績效/勝率/報酬數字。「介紹 ≠ 推薦」。──
PINS = [
    # 旗艦訂閱(視覺主位,暗金 gold)
    {"slug": "旗艦_台股全市場週報", "accent": "gold", "mascot": "neutral",
     "l1": "台股全市場", "l2": "每週幫你掃一遍",
     "kicker": "旗艦訂閱 · 台股全市場週報 · 每週更新",
     "bullets": ["全市場強弱掃描 + 34 板塊輪動", "法人週籌碼 + 估值位階雷達",
                 "真實訊號追蹤(含輸單,不挑不藏)", "介紹 ≠ 推薦,email + Telegram 直送"],
     "price": "NT$99–149 / 月"},

    # L2 core:全市場回測數據包
    {"slug": "數據包_全市場回測", "accent": "gold", "mascot": "smug",
     "l1": "1770 檔台股", "l2": "回測數據一次打包",
     "kicker": "全市場回測數據包 · 一次買斷",
     "bullets": ["adaptive + 多空 + Sharpe 合併 CSV", "淨報酬/回撤/勝率/起訖日/最終權益",
                 "方法與清洗過程全公開,附摘要 PDF", "歷史快照,非即時、非可交易訊號"],
     "price": "NT$990 一次買斷"},

    # L2 core:權值股體檢合輯
    {"slug": "體檢_權值股合輯", "accent": "red", "mascot": "neutral",
     "l1": "權值股體檢", "l2": "長期真相攤開看",
     "kicker": "台股權值股體檢合輯 · 深度數據手冊",
     "bullets": ["含息還原總報酬、最大回撤、最長套牢", "2008/2020/2022 三次崩盤韌性",
                 "單筆 vs 定投 vs 0050、估值位階", "只做誠實體檢,不喊多空不報明牌"],
     "price": "NT$1280 一次買斷"},

    # L1 tripwire:定投追蹤模板
    {"slug": "入門_定投追蹤模板", "accent": "green", "mascot": "happy",
     "l1": "存股定投", "l2": "先看數據再決定",
     "kicker": "台股定投追蹤模板 · 低價入門",
     "bullets": ["Excel/CSV 定投模板,自動算平均成本", "10 年真對照:All-in vs 定投 vs 0050",
                 "含息還原,數字取自體檢引擎實算", "工具不是明牌,不含任何買賣訊號"],
     "price": "NT$99"},

    # 國際 EN:數據包英版
    {"slug": "EN_quant_data_pack", "accent": "blue", "mascot": "neutral",
     "l1": "Taiwan Stocks", "l2": "Quant Data Pack (EN)",
     "kicker": "Taiwan whole-market backtest data · English",
     "bullets": ["Full-market backtest workbook (CSV)", "Adaptive + long/short + Sharpe merged",
                 "Rare: Taiwan-market data for global quants", "Educational, not financial advice"],
     "price": "US$35", "cta": "Free sample → get the full data pack"},
]


def make_pin(cfg: dict) -> Path:
    accent = ACCENTS.get(cfg.get("accent", "gold"), ACCENTS["gold"])
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
