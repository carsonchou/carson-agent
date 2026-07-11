#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_thumbnails.py — 為 6 支影片產生品牌化 YouTube 縮圖 (1280x720 JPG)。

設計：深藍漸層底 + 高對比大字鉤子 + 強調色 + 頻道標。輸出到 assets/thumbnails/。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "assets" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)
# 真實 Pionex 截圖素材夾：Carson 丟後台/回測截圖進來，縮圖卡就自動改用真截圖+紅框（信任貨幣）；空則退回示意設計卡
SHOTS = PROJECT_ROOT / "assets" / "pionex_shots"
# 多幣真實回測卡（backtest_cards.py 產，trading_bot 直連 Pionex 真K棒跑出來的真數字）
CARDS_JSON = PROJECT_ROOT / "STUDIO" / "backtest_cards.json"

W, H = 1280, 720

FONT_CANDIDATES_BOLD = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msjh.ttc",
                        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
FONT_CANDIDATES_REG = [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
                       "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                       "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]


def font(size: int, bold: bool = True):
    for c in (FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REG):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


# 每支：line1（強調色）、line2（白）、tag（底部條）、accent 顏色、角落大符號
THUMBS = [
    {"slug": "網格機器人能不能賺錢_原理風險與誰適合",
     "l1": "網格機器人", "l2": "真的能賺嗎？", "tag": "原理 × 風險 × 誰適合",
     "accent": (255, 210, 63), "mark": "?"},
    {"slug": "自動交易機器人實測企劃_規則先講死_EP0",
     "l1": "10萬 回測", "l2": "自動交易機器人", "tag": "規則先講死 ｜ EP.0",
     "accent": (88, 224, 140), "mark": "$"},
    {"slug": "玩網格90趴賠錢的關鍵參數_區間設定",
     "l1": "90% 玩網格", "l2": "都在賠錢", "tag": "問題出在這「1 個參數」",
     "accent": (255, 96, 96), "mark": "!"},
    {"slug": "派網Pionex是什麼_新手搞懂自動交易平台",
     "l1": "Pionex 派網", "l2": "到底是什麼？", "tag": "新手 5 分鐘搞懂自動交易",
     "accent": (90, 184, 255), "mark": "?"},
    {"slug": "DCA定投機器人vs網格機器人_哪個適合你",
     "l1": "定投 vs 網格", "l2": "你該選哪個？", "tag": "新手選擇指南",
     "accent": (255, 210, 63), "mark": "VS"},
    {"slug": "什麼是回測_沒回測別拿真錢碰",
     "l1": "沒回測過", "l2": "別拿真錢碰", "tag": "什麼是回測？量化思維核心",
     "accent": (255, 96, 96), "mark": "!"},
    # ★示範：實驗格式 + 派網回測卡（抄競品可信度元素，數字誠實含回撤）
    {"slug": "我給機器人1萬跑30天_結果公開",
     "l1": "丟 1萬", "l2": "跑 30 天", "tag": "自動交易機器人實測 ｜ 結果全公開",
     "accent": (88, 224, 140), "mark": "$",
     "card": {"strat": "網格·看漲區間", "pct": "+82.4%", "mdd": "最大回撤  -15.3%",
              "range": "區間  1774 – 2028", "note": "※示意回測，非真實獲利保證"}},
]

CHANNEL = "量化阿森｜Carson Quant"


def gradient_bg(c_top, c_bot):
    base = Image.new("RGB", (W, H), c_top)
    top = Image.new("RGB", (W, H), c_bot)
    mask = Image.new("L", (W, H))
    md = mask.load()
    for y in range(H):
        v = int(255 * (y / H))
        for x in range(W):
            md[x, y] = v
    return Image.composite(top, base, mask)


BASE_BG = (9, 12, 20)            # 近黑深色終端底
CARD_BOX = (W - 580, 150, W - 54, 568)  # 右側數據面板區（卡與真截圖共用）


def _seed_vals(seed, n, lo, hi):
    """由 seed 生 n 個 [lo,hi) 穩定偽隨機值（同 slug 永遠同走勢，不靠全域 random）。"""
    out = []
    val = int.from_bytes(hashlib.md5((seed or "x").encode("utf-8")).digest()[:8], "big")
    for _ in range(n):
        val = (val * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        out.append(lo + (val >> 11) / float(1 << 53) * (hi - lo))
    return out


def terminal_bg(accent, seed="x"):
    """深色『交易終端』背景：細網格 + 種子穩定的 K 線 + accent 指標線 + 左側暗化(保文字可讀)。"""
    img = Image.new("RGB", (W, H), BASE_BG)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 9), width=1)
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 9), width=1)
    n = 48
    step = W / n
    r = _seed_vals(seed, n, -1.0, 1.0)
    prices, p = [], 0.5
    for v in r:
        p = min(0.92, max(0.08, p + v * 0.09))
        prices.append(p)
    top, bot = H * 0.26, H * 0.95
    span = bot - top
    up, dn, cw = (34, 200, 128), (228, 78, 90), step * 0.5
    pts, prev = [], prices[0]
    for i, p in enumerate(prices):
        cx = step * i + step / 2
        mid = bot - p * span
        col = up if p >= prev else dn
        prev = p
        body = 18 + abs(r[i]) * 26
        wick = body / 2 + 10 + abs(r[i]) * 16
        d.line([(cx, mid - wick), (cx, mid + wick)], fill=(*col, 72), width=2)
        d.rectangle([cx - cw / 2, mid - body / 2, cx + cw / 2, mid + body / 2], fill=(*col, 72))
        pts.append((cx, mid))
    if len(pts) > 1:
        d.line(pts, fill=(*accent, 85), width=3, joint="curve")
    # 左濃右淡暗化（用 1px 寬漸層拉伸，快）
    grad = Image.new("L", (W, 1))
    gp = grad.load()
    for x in range(W):
        gp[x, 0] = int(232 * max(0.0, 1 - x / (W * 0.60)))
    return Image.composite(Image.new("RGB", (W, H), BASE_BG), img, grad.resize((W, H)))


def fit_font(text, max_w, start=156, min_size=66):
    """自動縮字級讓 text 寬度 ≤ max_w（避免長標題溢出/壓到右側面板）。"""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    s = start
    while s > min_size:
        f = font(s, True)
        b = probe.textbbox((0, 0), text, font=f, stroke_width=3)
        if b[2] - b[0] <= max_w:
            return f
        s -= 6
    return font(min_size, True)


def draw_text_stroke(d, xy, text, fnt, fill, stroke=(0, 0, 0), sw=6, anchor=None):
    d.text(xy, text, font=fnt, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def draw_backtest_card(d, card: dict, accent):
    """右側畫一張『深色交易終端·回測面板』(像 TradingView/Bloomberg)：視窗點 + 大數字%(正綠負紅)
    + 細分隔線 + 兩列數據 + 誠實註。守誠實鐵則：明標回測非保證。"""
    PANEL = (16, 21, 33)
    BORDER = (46, 56, 80)
    INK = (233, 239, 249)
    GREY = (138, 150, 174)
    GREEN = (38, 214, 134)
    RED = (240, 86, 96)
    pct = card.get("pct", "+82.4%")
    pc = (card.get("pct_color") or ("red" if str(pct).strip().startswith("-") else "green")).lower()
    PCT_COL = RED if pc == "red" else GREEN
    x0, y0, x1, y1 = CARD_BOX
    d.rounded_rectangle([x0 + 6, y0 + 12, x1 + 6, y1 + 12], radius=20, fill=(0, 0, 0, 110))  # 陰影
    d.rounded_rectangle([x0, y0, x1, y1], radius=20, fill=PANEL, outline=BORDER, width=2)
    px = x0 + 34
    # 終端視窗紅黃綠點
    for i, cc in enumerate([(240, 86, 96), (255, 184, 40), (38, 214, 134)]):
        d.ellipse([px + i * 26, y0 + 26, px + i * 26 + 14, y0 + 26 + 14], fill=cc)
    # 策略名 + 標籤(真回測/示意)
    d.text((px, y0 + 60), card.get("strat", "BTC 1H·SuperTrend"), font=font(30, bold=True), fill=INK)
    lbl = card.get("label", "回測")
    lf = font(22, bold=True)
    lb = d.textbbox((0, 0), lbl, font=lf)
    lw = lb[2] - lb[0]
    d.rounded_rectangle([x1 - lw - 58, y0 + 60, x1 - 30, y0 + 60 + (lb[3] - lb[1]) + 14],
                        radius=8, fill=(*accent, 38), outline=(*accent, 190), width=1)
    d.text((x1 - lw - 58 + 14, y0 + 66), lbl, font=lf, fill=accent)
    # 指標名 + 大字主數字%（正綠負紅，靠色彩不靠紅框）
    d.text((px, y0 + 112), card.get("metric", "回測總報酬（含回撤）"), font=font(24, bold=True), fill=GREY)
    pf = font(104, bold=True)
    d.text((px + 2, y0 + 150), pct, font=pf, fill=(0, 0, 0, 120))  # 數字輕陰影
    d.text((px, y0 + 148), pct, font=pf, fill=PCT_COL)
    # 細分隔線
    d.line([(px, y0 + 290), (x1 - 34, y0 + 290)], fill=BORDER, width=2)
    ry = y0 + 304
    for label in (card.get("mdd", "最大回撤  -15.3%"), card.get("range", "夏普 4.8｜勝率 54%")):
        d.text((px, ry), label, font=font(27, bold=True), fill=INK)
        ry += 40
    d.text((px, y1 - 36), card.get("note", "※歷史回測，非未來獲利保證"), font=font(20, bold=False), fill=GREY)


def _pick_pionex_shot(slug: str):
    """從 assets/pionex_shots/ 挑一張真實截圖（依 slug 輪替）。空資料夾或無圖回 None。"""
    try:
        if not SHOTS.exists():
            return None
        shots = sorted(p for p in SHOTS.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        if not shots:
            return None
        idx = sum(ord(c) for c in (slug or "x")) % len(shots)
        return shots[idx]
    except Exception:  # noqa: BLE001
        return None


def _paste_shot_card(img, d, shot_path, accent) -> bool:
    """把真實 Pionex 截圖貼到右側面板區（cover 裁切）＋accent 框＋誠實標籤。成功回 True。"""
    RED = accent
    x0, y0, x1, y1 = CARD_BOX
    rw, rh = x1 - x0, y1 - y0
    try:
        shot = Image.open(shot_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return False
    iw, ih = shot.size
    scale = max(rw / iw, rh / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
    shot = shot.resize((nw, nh), resample)
    left, top = (nw - rw) // 2, (nh - rh) // 2
    shot = shot.crop((left, top, left + rw, top + rh))
    mask = Image.new("L", (rw, rh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, rw - 1, rh - 1], radius=24, fill=255)
    img.paste(shot, (x0, y0), mask)
    d.rounded_rectangle([x0, y0, x1, y1], radius=24, outline=RED, width=6)
    lf = font(24, bold=True)
    lb = d.textbbox((0, 0), "派網實盤", font=lf)
    d.rounded_rectangle([x0 + 16, y0 + 16, x0 + 16 + (lb[2] - lb[0]) + 28,
                         y0 + 16 + (lb[3] - lb[1]) + 16], radius=10, fill=(230, 60, 60))
    d.text((x0 + 16 + 14, y0 + 16 + 8), "派網實盤", font=lf, fill=(255, 255, 255))
    return True


_COIN_ALIASES = {
    "BTC": ["btc", "比特幣", "bitcoin"], "ETH": ["eth", "以太", "ethereum"],
    "SOL": ["sol", "solana"], "BNB": ["bnb", "幣安幣"],
    "XRP": ["xrp", "瑞波"], "DOGE": ["doge", "狗狗"],
}
_STRAT_KW = ["回測", "策略", "supertrend", "超級趨勢", "趨勢", "夏普", "勝率", "backtest", "停損", "做多", "做空"]

# ── 領域判定（治根因：「回測/策略/停損」這類泛用詞台股、加密都會講，
#    不能單憑它們就套加密貨幣的 SuperTrend 卡——那正是台積電片被誤配 BTC 卡的根因）──
_TW_KW = ["台股", "台積電", "2330", "0050", "0056", "00878", "大盤", "加權指數", "加權",
          "股息", "存股", "定期定額", "定投", "etf", "台灣50", "元大", "國泰", "富邦",
          "個股", "股票", "現股", "台指期", "填息", "除息", "上市櫃", "市值型", "高股息", "微笑曲線"]
_CRYPTO_KW = ["btc", "eth", "sol", "bnb", "xrp", "doge", "比特幣", "以太幣", "以太坊",
              "加密貨幣", "幣圈", "幣安", "派網", "pionex", "網格機器人", "自動交易機器人",
              "合約交易", "usdt", "虛擬貨幣", "數位貨幣", "現貨交易"]
# tw_stock_facts.json 目前只有 0050/0056/00878/大盤等 ETF/指數的真回測，沒有個股(如台積電)自己的數字。
# 標題點名這些個股 → 該股沒有對應真數據，誠信起見絕不拿 ETF/大盤數字冒充該股表現(寧無卡不亂配)。
_TW_UNCOVERED_STOCK_KW = ["台積電", "2330"]

TW_FACTS_JSON = PROJECT_ROOT / "STUDIO" / "tw_stock_facts.json"

_TW_BRANCH_LABEL = {"allin": "一次All in", "dca": "定期定額", "buy_hold": "長抱不動",
                     "timing_200ma": "跌破年線擇時", "hidiv": "高股息", "mktcap": "市值型"}


def _asset_domain(low: str) -> str:
    """粗判標題屬於「台股/ETF」還是「加密貨幣」領域。兩邊關鍵字都對上、或都沒對上 → unknown。
    unknown 一律不套任何領域的數據卡（誠信鐵則：台股題絕不配加密卡，反之亦然；領域不明寧可無卡）。"""
    is_tw = any(k in low for k in _TW_KW)
    is_crypto = any(k in low for k in _CRYPTO_KW) or any(
        any(a in low for a in aliases) for aliases in _COIN_ALIASES.values())
    if is_tw and not is_crypto:
        return "tw"
    if is_crypto and not is_tw:
        return "crypto"
    return "unknown"


def _crypto_card(low: str):
    """加密貨幣領域確認後才會被呼叫：標題點名的幣優先真實呈現；否則只在「策略/回測」題材
    才挑夏普最高的正報酬幣。主題對不上(不在加密領域)不會走到這裡。"""
    try:
        data = _json.loads(CARDS_JSON.read_text(encoding="utf-8"))
        cards = {c["coin"]: c for c in data.get("cards", []) if "coin" in c}
    except Exception:  # noqa: BLE001
        return None
    if not cards:
        return None
    is_strat = any(k in low for k in _STRAT_KW)
    # 1) 標題點名某幣 → 用那個幣的真實結果（即使是負的也誠實呈現）
    chosen = None
    for coin, aliases in _COIN_ALIASES.items():
        if coin in cards and any(a in low for a in aliases):
            chosen = cards[coin]
            break
    # 2) 否則只在「策略/回測」題材才套，挑夏普最高的正報酬幣
    if chosen is None:
        if not is_strat:
            return None
        pos = [c for c in cards.values() if c.get("total_return", 0) > 0]
        if not pos:
            return None
        chosen = max(pos, key=lambda c: c.get("sharpe", -99))
    ret = chosen["total_return"] * 100
    mdd = chosen["max_drawdown"] * 100
    return {
        "label": "真回測",
        "strat": f'{chosen["coin"]} {chosen["interval"]}·SuperTrend',
        "metric": "回測總報酬（含回撤）",
        "pct": f'{"+" if ret >= 0 else ""}{ret:.1f}%',
        "pct_color": "green" if ret >= 0 else "red",
        "mdd": f'最大回撤  -{mdd:.1f}%',
        "range": f'夏普 {chosen["sharpe"]:.1f}｜勝率 {chosen["win_rate"]*100:.0f}%',
        "note": "※歷史回測，非未來獲利保證",
    }


def _build_tw_card(r: dict):
    """把 tw_stock_facts.json 一筆結果轉成縮圖卡欄位，只用裡面已有的真數字，不外插不編造。"""
    d = r.get("data", {})
    scored = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        if "total_return" in v:
            scored.append((k, v, v["total_return"], "total_return"))
        elif "cagr" in v:
            scored.append((k, v, v["cagr"], "cagr"))
    if not scored:
        return None
    scored.sort(key=lambda t: t[2], reverse=True)
    pk, pv, pval, pkind = scored[0]
    pct = f'{"+" if pval >= 0 else ""}{pval * 100:.1f}%'
    mdd = pv.get("max_drawdown")
    mdd_txt = f'最大回撤  {mdd * 100:.1f}%' if mdd is not None else None
    metric = ("總報酬" if pkind == "total_return" else "年化報酬") + f'（{_TW_BRANCH_LABEL.get(pk, pk)}）'
    range_txt = None
    if len(scored) > 1:
        sk, sv, sval, skind = scored[1]
        sfx = "總報酬" if skind == "total_return" else "年化"
        range_txt = f'{_TW_BRANCH_LABEL.get(sk, sk)}對照 {"+" if sval >= 0 else ""}{sval * 100:.1f}%（{sfx}）'
    years = d.get("years")
    yr_txt = f'{years:.0f}年' if years else ""
    strat = f'{_TW_BRANCH_LABEL.get(pk, pk)}·{yr_txt}' if yr_txt else _TW_BRANCH_LABEL.get(pk, pk)
    return {
        "label": "台股實測",
        "strat": strat[:14],
        "metric": metric,
        "pct": pct,
        "pct_color": "green" if pval >= 0 else "red",
        "mdd": mdd_txt or (range_txt or "歷史回測"),
        "range": (range_txt if mdd_txt else None) or (f'期間 {years:.0f} 年' if years else "歷史回測"),
        "note": "※歷史回測，非未來獲利保證",
    }


def _tw_card(low: str):
    """台股/ETF領域確認後才會被呼叫：從 tw_stock_facts.json 找關鍵字明確對上(≥2個)的結果才套卡。
    標題點名個股(如台積電)→ 該股沒有真數據，一律不套(誠信優先於好看)。"""
    if any(k in low for k in _TW_UNCOVERED_STOCK_KW):
        return None
    try:
        data = _json.loads(TW_FACTS_JSON.read_text(encoding="utf-8"))
        results = data.get("results", {})
    except Exception:  # noqa: BLE001
        return None
    if not results:
        return None
    best_key, best_score = None, 0
    for key, r in results.items():
        score = sum(1 for k in r.get("keywords", []) if k.lower() in low)
        if score > best_score:
            best_key, best_score = key, score
    if best_score < 2 or not best_key:  # 至少2個關鍵字對上才算可信匹配，避免單一泛用詞誤配
        return None
    return _build_tw_card(results[best_key])


def _real_card(slug: str, title: str):
    """依影片主題領域(台股/加密)挑一張誠實的真數據卡。領域不明、個股無資料、或關鍵字對不上
    → 回 None(交給示意卡或無卡)。誠信鐵則：台股題絕不配加密卡，反之亦然；數字對不上主題寧可不掛卡。"""
    low = f"{title or ''} {slug or ''}".lower()
    domain = _asset_domain(low)
    if domain == "crypto":
        return _crypto_card(low)
    if domain == "tw":
        return _tw_card(low)
    return None


def make_one(cfg: dict):
    if cfg.get("debunk"):
        return _make_debunk(cfg)
    accent = cfg["accent"]
    img = terminal_bg(accent, seed=cfg.get("slug", "x"))
    d = ImageDraw.Draw(img, "RGBA")

    # 右側：有回測卡就畫深色終端面板（真截圖優先），否則留 K 線背景填白
    has_card = False
    if cfg.get("card"):
        _shot = _pick_pionex_shot(cfg.get("slug", ""))
        if _shot and _paste_shot_card(img, d, _shot, accent):
            has_card = True
        else:
            draw_backtest_card(d, cfg["card"], accent)
            has_card = True

    # 標準片也貼吉祥物（品牌一致）：無回測卡時右下貼戰友，主文讓出右側避開
    show_mascot = not has_card
    if show_mascot:
        _paste_mascot(img, mood=cfg.get("mascot_mood", "neutral"), target_h=260)

    # 左側強調色直條（細）
    d.rectangle([0, 0, 12, H], fill=accent)

    # 頻道標（左上 pill：深色玻璃 + accent 圓點）
    tagf = font(32, bold=True)
    ct = CHANNEL
    tb = d.textbbox((0, 0), ct, font=tagf)
    th = tb[3] - tb[1]
    ph = th + 26
    pw = (tb[2] - tb[0]) + 70
    d.rounded_rectangle([54, 42, 54 + pw, 42 + ph], radius=12, fill=(8, 11, 18, 205),
                        outline=(*accent, 110), width=1)
    cyd = 42 + ph // 2
    d.ellipse([74, cyd - 7, 88, cyd + 7], fill=accent)
    d.text((104, 42 + ph // 2 - th // 2 - tb[1]), ct, font=tagf, fill=(224, 231, 244))

    # 主文兩行（自動縮字級不溢出；陰影 + 細描邊，premium 不刺眼）
    max_w = 640 if has_card else (760 if show_mascot else 1040)

    def big(xy, text, fnt, fill):
        d.text((xy[0] + 4, xy[1] + 6), text, font=fnt, fill=(0, 0, 0, 165))
        d.text(xy, text, font=fnt, fill=fill, stroke_width=3, stroke_fill=(6, 9, 15))

    y = 214
    f1 = fit_font(cfg["l1"], max_w, start=156)
    big((58, y), cfg["l1"], f1, accent)
    b1 = d.textbbox((58, y), cfg["l1"], font=f1, stroke_width=3)
    d.rectangle([62, b1[3] + 10, 62 + min(max_w, b1[2] - 58), b1[3] + 20], fill=accent)
    y2 = b1[3] + 38
    f2 = fit_font(cfg["l2"], max_w, start=156)
    big((58, y2), cfg["l2"], f2, (238, 244, 253))

    # 底部低調暗帶（取代整條螢光）：深色 + accent 左緣 + accent 細上線 + 白字
    bar_h = 84
    d.rectangle([0, H - bar_h, W, H], fill=(8, 11, 18, 215))
    d.rectangle([0, H - bar_h, 10, H], fill=accent)
    d.line([(0, H - bar_h), (W, H - bar_h)], fill=(*accent, 150), width=2)
    d.text((42, H - bar_h // 2), cfg["tag"], font=font(44, bold=True),
           fill=(234, 240, 250), anchor="lm")

    out = OUT / f"{cfg['slug']}.jpg"
    img.save(out, "JPEG", quality=92)
    kb = out.stat().st_size / 1024
    print(f"[ok] {out.name}  ({kb:.0f} KB)")
    return out


import os as _os
import re as _re
import json as _json

ACCENTS = {"yellow": (255, 209, 102), "green": (88, 224, 140), "red": (255, 96, 96), "blue": (90, 184, 255)}
# yellow=#FFD166，與 STUDIO/design_system.json accent_palette[0]（make_video.pick_accent 全片鎖金來源）
# 同一個值——B5：縮圖/banner/logo/intro 全線統一，不再各自一種黃

# ── 《拆穿》debunk 縮圖公式：神話數字(金)被紅刀切開 + ≤6大字 + 吉祥物戰友 ──
MASCOT = PROJECT_ROOT / "assets" / "mascot"
_DEBUNK_KW = ("拆穿", "揭穿", "揭露", "打臉", "打假", "真相", "騙局", "智商稅", "翻車", "崩")
_MYTH_NUM_RE = _re.compile(r"\d[\d,\.]*\s*[%倍]?")
_GOLD = (255, 205, 66)      # 神話數字＝金(對手宣稱的漂亮數字)
_KNIFE = (236, 44, 44)      # 紅刀＝把神話一刀切開


def is_debunk(text: str) -> bool:
    """標題含拆穿/真相/打臉/揭穿…等打假關鍵字 → 走《拆穿》縮圖公式。"""
    return any(k in (text or "") for k in _DEBUNK_KW)


def _myth_number(cfg: dict):
    """抓出被拆穿的『神話數字』(如 812%、88.89%、236倍)。優先 cfg['myth']，否則掃 l1/l2/標題。無則 None。"""
    m = (cfg.get("myth") or "").strip()
    if m:
        return m[:8]
    for src in (cfg.get("l1"), cfg.get("l2"), cfg.get("title"), cfg.get("tag")):
        if not src:
            continue
        found = [f.replace(" ", "") for f in _MYTH_NUM_RE.findall(str(src)) if any(c.isdigit() for c in f)]
        if found:
            pref = [f for f in found if "%" in f or "倍" in f]
            return (pref[0] if pref else max(found, key=len))[:8]
    return None


def _paste_mascot(img, mood="smug", target_h=300):
    """右下角貼吉祥物(戰友)。裁掉透明邊只留角色。成功回左緣 x，失敗回 None。"""
    try:
        cand = [MASCOT / f"{mood}.png", MASCOT / "smug.png", MASCOT / "neutral.png"]
        path = next((p for p in cand if p.exists()), None)
        if not path:
            return None
        m = Image.open(path).convert("RGBA")
        bb = m.getchannel("A").getbbox()   # 裁掉 1024 透明留白，角色才不會縮成一點
        if bb:
            m = m.crop(bb)
        scale = target_h / m.height
        nw = max(1, int(m.width * scale))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        m = m.resize((nw, target_h), resample)
        x = W - nw - 20
        y = H - target_h - 64          # 坐在底條之上
        img.paste(m, (x, y), m)
        return x
    except Exception:  # noqa: BLE001
        return None


def _make_debunk(cfg: dict):
    """《拆穿》系列縮圖：紅色警示終端底 + 金色神話數字被紅刀切開 + ≤6大字 + 吉祥物 + 拆穿印章。"""
    accent = ACCENTS["red"]
    img = terminal_bg(accent, seed=cfg.get("slug", "x"))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, 12, H], fill=accent)

    # 頻道標 pill(左上)
    tagf = font(32, bold=True)
    ct = CHANNEL
    tb = d.textbbox((0, 0), ct, font=tagf)
    th = tb[3] - tb[1]
    ph, pw = th + 26, (tb[2] - tb[0]) + 70
    d.rounded_rectangle([54, 42, 54 + pw, 42 + ph], radius=12, fill=(8, 11, 18, 205),
                        outline=(*accent, 130), width=1)
    cyd = 42 + ph // 2
    d.ellipse([74, cyd - 7, 88, cyd + 7], fill=accent)
    d.text((104, 42 + ph // 2 - th // 2 - tb[1]), ct, font=tagf, fill=(224, 231, 244))

    # 吉祥物(戰友)先貼右下,神話數字避開它
    mascot_left = _paste_mascot(img, mood="smug")
    right_limit = (mascot_left - 30) if mascot_left else (W - 70)

    # 神話數字(金)被紅刀切開
    myth = _myth_number(cfg)
    if myth:
        avail = max(240, right_limit - 600)
        mf = fit_font(myth, avail, start=184, min_size=92)
        mb = d.textbbox((0, 0), myth, font=mf, stroke_width=6)
        mw, mh = mb[2] - mb[0], mb[3] - mb[1]
        mx, my = right_limit - mw, 150
        d.text((mx, my - 42), "他吹的神話", font=font(30, bold=True), fill=(150, 160, 182))
        d.text((mx + 4, my + 8), myth, font=mf, fill=(0, 0, 0, 150))            # 陰影
        d.text((mx, my), myth, font=mf, fill=_GOLD, stroke_width=6, stroke_fill=(70, 48, 0))
        d.line([(mx - 40, my + mh + 62), (mx + mw + 40, my - 22)], fill=_KNIFE, width=24)  # 紅刀
        d.line([(mx - 40, my + mh + 62), (mx + mw + 40, my - 22)], fill=(255, 255, 255, 205), width=4)  # 刀光

    # ≤6 大字headline(左欄)
    l1 = (cfg.get("l1") or "拆穿")[:6]
    l2 = (cfg.get("l2") or "")[:6]
    hy = 250 if myth else 296
    f1 = fit_font(l1, 500, start=150)
    d.text((62, hy + 6), l1, font=f1, fill=(0, 0, 0, 165))
    d.text((58, hy), l1, font=f1, fill=(238, 244, 253), stroke_width=3, stroke_fill=(6, 9, 15))
    b1 = d.textbbox((58, hy), l1, font=f1, stroke_width=3)
    if l2:
        f2 = fit_font(l2, 500, start=138)
        y2 = b1[3] + 26
        d.text((62, y2 + 6), l2, font=f2, fill=(0, 0, 0, 165))
        d.text((58, y2), l2, font=f2, fill=_GOLD, stroke_width=3, stroke_fill=(6, 9, 15))

    # 「拆穿」紅印章(標題上方)
    sf = font(40, bold=True)
    sb = d.textbbox((0, 0), "拆穿", font=sf)
    sw, sh = sb[2] - sb[0], sb[3] - sb[1]
    sx, sy = 58, 152
    d.rounded_rectangle([sx, sy, sx + sw + 46, sy + sh + 30], radius=10,
                        fill=(*accent, 235), outline=(255, 255, 255), width=3)
    d.text((sx + 23, sy + 15 - sb[1]), "拆穿", font=sf, fill=(255, 255, 255))

    # 底部低調暗帶 + 招牌簽名
    bar_h = 84
    d.rectangle([0, H - bar_h, W, H], fill=(8, 11, 18, 220))
    d.rectangle([0, H - bar_h, 10, H], fill=accent)
    d.line([(0, H - bar_h), (W, H - bar_h)], fill=(*accent, 150), width=2)
    d.text((42, H - bar_h // 2), (cfg.get("tag") or "我幫你避雷，不賣你夢"),
           font=font(42, bold=True), fill=(234, 240, 250), anchor="lm")

    out = OUT / f"{cfg['slug']}.jpg"
    img.save(out, "JPEG", quality=92)
    kb = out.stat().st_size / 1024
    print(f"[ok] {out.name}  (拆穿樣式, {kb:.0f} KB)")
    return out


def _heuristic(slug: str, title: str) -> dict:
    """無 LLM 時的保底：把標題切成兩行 + 底條。"""
    t = _re.sub(r"[（(].*?[)）]", "", title or slug).strip()
    cut = 6
    for i, ch in enumerate(t[:10]):
        if ch in "？?！!，,。、 ":
            cut = i or cut
            break
    l1 = t[:cut] or t[:6]
    rest = t[cut:].lstrip("？?！!，,。、 ")
    l2 = rest[:8] or "看完秒懂"
    tag = (rest[8:] or t)[:14]
    return {"slug": slug, "l1": l1[:8], "l2": l2[:10], "tag": tag, "accent": ACCENTS["yellow"], "mark": "?"}


def _decorate_debunk(cfg: dict, title: str) -> dict:
    """若標題屬《拆穿》打假題 → 打上 debunk 旗標、抽神話數字、鎖紅色警示配色，交給 _make_debunk 走招牌公式。"""
    if not is_debunk(title):
        return cfg
    cfg["debunk"] = True
    cfg["accent"] = ACCENTS["red"]
    cfg.setdefault("title", title)
    if not cfg.get("myth"):
        m = _myth_number({"title": title, "l1": cfg.get("l1"), "l2": cfg.get("l2")})
        if m:
            cfg["myth"] = m
    # 保底啟發式會把「《拆穿》｜…」原標題硬切成 l1/l2(醜且和金數字重複)；偵測到切片痕跡就換乾淨的打假標語
    _slice_marks = ("拆穿", "｜", "|", "「", "」", "《", "》")
    if any(ch in (cfg.get("l1") or "") for ch in _slice_marks) or (cfg.get("myth") and cfg.get("myth") in (cfg.get("l2") or "")):
        cfg["l1"] = "他說能賺"
        cfg["l2"] = "我拆給你看"
        cfg["tag"] = "我幫你避雷，不賣你夢"   # 底條也一併換招牌簽名(蓋掉切片痕跡)
    return cfg


def derive_cfg(slug: str, title: str) -> dict:
    """從標題自動生縮圖鉤子。優先用 haiku(便宜)，失敗退保底啟發式。《拆穿》題自動套打假公式。"""
    deb = is_debunk(title)
    fb = _decorate_debunk(_heuristic(slug, title), title)
    key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return fb
    try:
        import requests
        myth_line = ('這是「拆穿神話」打假片：l1/l2 用打假語氣(如「他說812%」「我回測給你看」)，'
                     '另給 "myth" 欄＝對手宣稱、要被一刀切開的神話數字(如「812%」「88.89%」「236倍」，抓標題裡的；沒有就給空字串)，'
                     'accent 固定 red。\n') if deb else ""
        prompt = (f"影片標題：{title}\n"
                  "為這支量化交易教學影片產生吸睛 YouTube 縮圖文字，只輸出 JSON：\n"
                  '{"l1":"第一行鉤子(2-6字,最吸睛的詞/數字)","l2":"第二行(3-8字)",'
                  '"tag":"底部說明條(6-14字)","accent":"yellow|green|red|blue","mark":"?或!或$或VS","myth":"被拆穿的神話數字或空字串"}\n'
                  + myth_line +
                  "繁體中文。誠信鐵則：不用『穩賺/保證/必賺』。配色：紅=警示/虧損，綠=獲利/實測，黃=疑問/教學，藍=工具/平台。")
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=40)
        t = r.json()["content"][0]["text"]
        d = _json.loads(_re.search(r"\{.*\}", t, _re.S).group(0))
        cfg = {"slug": slug, "l1": (d.get("l1") or fb["l1"])[:8], "l2": (d.get("l2") or fb["l2"])[:10],
               "tag": (d.get("tag") or fb["tag"])[:16],
               "accent": ACCENTS.get((d.get("accent") or "yellow").lower(), ACCENTS["yellow"]),
               "mark": (d.get("mark") or "?")[:2]}
        if d.get("myth"):
            cfg["myth"] = str(d["myth"])[:8]
        return _decorate_debunk(cfg, title)
    except Exception as e:
        print(f"[warn] haiku 生鉤子失敗，用保底：{str(e)[:80]}", file=sys.stderr)
        return fb


def make_auto(slug: str, title: str, force: bool = False):
    """自動：標題→鉤子→縮圖。已存在且非 force 則跳過。"""
    out = OUT / f"{slug}.jpg"
    if out.exists() and not force:
        print(f"[skip] 已有縮圖：{slug}")
        return out
    cfg = derive_cfg(slug, title)
    # 策略/幣種題材 → 自動掛真實多幣回測卡（真數字、含回撤、誠實）；主題不符或《拆穿》題則不掛
    if not cfg.get("debunk") and not cfg.get("card"):
        rc = _real_card(slug, title)
        if rc:
            cfg["card"] = rc
    return make_one(cfg)


def main() -> int:
    # --batch <json: [{slug,title}]> 批量；--auto <slug> <title> 單支；無參數＝原 6 支示範
    if len(sys.argv) >= 2 and sys.argv[1] == "--batch":
        data = _json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        n = 0
        for it in data:
            try:
                make_auto(it["slug"], it.get("title", it["slug"]), force=("--force" in sys.argv))
                n += 1
            except Exception as e:
                print(f"[fail] {it.get('slug','')[:30]}: {str(e)[:80]}", file=sys.stderr)
        print(f"完成批量 {n}/{len(data)}。")
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--auto":
        make_auto(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else sys.argv[2], force=("--force" in sys.argv))
        return 0
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for cfg in THUMBS:
        if only and only not in cfg["slug"]:
            continue
        make_one(cfg)
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
