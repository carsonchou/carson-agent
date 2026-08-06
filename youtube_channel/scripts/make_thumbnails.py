#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_thumbnails.py — 為 6 支影片產生品牌化 YouTube 縮圖 (1280x720 JPG)。

設計：深藍漸層底 + 高對比大字鉤子 + 強調色 + 頻道標。輸出到 assets/thumbnails/。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re as _re
import sys
import time as _time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "assets" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio_common import save_json_atomic, load_json_safe  # 併發安全 JSON 讀寫，同其他部門


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→llm.complete 拿不到
    OPENROUTER key→縮圖鉤子靜默失敗、全退保底硬切標題)。同 quality_score.py/growth_agent.py 的作法。"""
    envf = PROJECT_ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
# 真實 Pionex 截圖素材夾：Carson 丟後台/回測截圖進來，縮圖卡就自動改用真截圖+紅框（信任貨幣）；空則退回示意設計卡
SHOTS = PROJECT_ROOT / "assets" / "pionex_shots"
# 多幣真實回測卡（backtest_cards.py 產，trading_bot 直連 Pionex 真K棒跑出來的真數字）
CARDS_JSON = PROJECT_ROOT / "STUDIO" / "backtest_cards.json"
# 數據卡數字去重狀態檔：記錄每支影片縮圖用掉的數字組，避免不同影片一直挑到同一組(如 +813.7%)反覆出現
USED_NUMBERS_JSON = PROJECT_ROOT / "STUDIO" / "used_datacard_numbers.json"
_DEDUP_WINDOW = 15  # 只看近 15 支的用過數字做去重比對，太舊的允許再出現

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
# 標題點名個股(如台積電) → 一律不掛數據卡。
# ⚠️ 2026-07-17 註記：這條原本的理由是「事實庫只有 0050/0056/00878/大盤等 ETF/指數，沒有個股數字，
#    不可拿 ETF/大盤數字冒充該股表現」。改讀 tw_facts_computed.json 後這個前提已經不成立——computed
#    確實有 2330 的真回測(dca_vs_allin__2330__full/__10y、stop_profit_vs_hold__2330__*)。
#    仍維持不掛卡：把個股數字放上封面屬於「點名個股」的內容決策(非本次修的資料同源問題)，
#    要開放應另行決策，不由縮圖引擎順手放行。保守側＝寧無卡，不會說謊。
_TW_UNCOVERED_STOCK_KW = ["台積電", "2330"]

# 主來源：tw_facts_computed.json(50 組，每筆帶 period/start/end/method/source，固定起點可重現)。
# legacy tw_stock_facts.json(5 組)已於 2026-07-17 退役，只在 computed 缺該組時 fail-open 保留使用
# ——它每天 04:00 用滾動窗重算 → 數字每天漂移，且無 period 欄。詳見 tw_facts_engine.py:58 的退役說明。
TW_FACTS_JSON = PROJECT_ROOT / "STUDIO" / "tw_stock_facts.json"
TW_FACTS_COMPUTED_JSON = PROJECT_ROOT / "STUDIO" / "tw_facts_computed.json"

# 分支 key → 中文標籤。legacy 與 computed 同一件事的分支命名不同(legacy: timing_200ma／
# computed: timing_ma)，兩個都留著才不會有一邊標成英文 key。computed 另有 leveraged/base 兩種分支。
_TW_BRANCH_LABEL = {"allin": "一次All in", "dca": "定期定額", "buy_hold": "長抱不動",
                     "timing_200ma": "跌破年線擇時",   # legacy(tw_stock_data.py)分支名
                     "timing_ma": "跌破年線擇時",       # computed(tw_facts_engine.calc_buyhold_vs_timing)分支名
                     "hidiv": "高股息", "mktcap": "市值型",
                     "leveraged": "槓桿ETF", "base": "原型ETF"}


def _load_tw_facts_merged():
    """讀台股真回測事實庫，回 {fact_key: fact_entry}；讀不到/全壞 → {}(呼叫端退回無卡，不崩)。

    與寫稿端(produce_batch._load_tw_facts)**同一套合併規則**，這正是「封面數字與腳本同源」的關鍵：
    legacy 當底 → computed 用 setdefault 補進來 → 再用 tw_facts_engine.drop_superseded_legacy()
    把「已被 computed 取代」的 legacy key 剔掉。那份 key 對 key 映射(LEGACY_SUPERSEDED_BY)是唯一
    真相，這裡只呼叫、不複製第二份——重複實作正是這批同型 bug 的成因。

    為什麼還要讀 legacy：drop_superseded_legacy 是 fail-open 設計，computed 缺該組時 legacy 原樣
    保留(有真數據總比沒有好)。5 個重疊主題的 computed 版都在，那 5 組 legacy 會被剔掉。

    不讀 stock_checkup_facts.json(寫稿端有讀)：那 112 組的 data 是單股體檢的扁平欄位／年度極值，
    結構上生不出回測對比卡(_build_tw_card 需要「帶 total_return/cagr 的 dict 分支」)，卻會參與
    關鍵字競爭 → 贏了關鍵字卻生不出卡 = 平白吃掉本來掛得到卡的片。對縮圖只有壞處。
    """
    merged, computed_keys = {}, set()
    for p in (TW_FACTS_JSON, TW_FACTS_COMPUTED_JSON):
        try:
            if not p.exists():
                continue
            d = _json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                continue
            res = d.get("results") or {}
            if not isinstance(res, dict):
                continue
            if p is TW_FACTS_COMPUTED_JSON:
                computed_keys = set(res)
            for k, v in res.items():
                merged.setdefault(k, v)
        except Exception:  # noqa: BLE001 — 單一檔壞掉不該讓整台縮圖引擎倒，換下一份
            continue
    if not merged:
        return {}
    try:
        import tw_facts_engine  # sys.path 已在模組頂插入 scripts/
        return tw_facts_engine.drop_superseded_legacy(merged)
    except Exception as e:  # noqa: BLE001
        # 退役映射載不到：寧可只用 computed(頂多少幾張卡)，也不可讓 legacy 的過期數字混進來跟腳本打臉。
        # 只有在 computed 也讀不到時才整碗用 legacy——那是「有卡但可能對不上」與「完全沒卡」之間的取捨，
        # 此時腳本端(produce_batch)同樣拿不到 computed，兩邊仍是同一份 legacy，不會互相矛盾。
        print(f"[warn] tw_facts_engine 退役映射載入失敗，改用 computed-only：{str(e)[:80]}", file=sys.stderr)
        return {k: v for k, v in merged.items() if k in computed_keys} or merged


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


_PCT_TOKEN_RE = _re.compile(r"[-+]?\d+\.\d+%")


def _load_used_numbers() -> list:
    """讀去重歷史檔；壞檔/沒檔 → 空清單(不擋產圖，只是這次無法去重)。"""
    return load_json_safe(USED_NUMBERS_JSON, default=[]) or []


def _recent_number_signatures(kind: str, window: int = _DEDUP_WINDOW):
    """近 window 支同領域(tw/crypto)縮圖已用過的「主數字」集合 + 「整組數字」集合，供去重比對。"""
    records = [r for r in _load_used_numbers() if r.get("kind") == kind]
    recent = records[-window:]
    mains = {r.get("pct") for r in recent if r.get("pct")}
    fulls = {tuple(r.get("numbers") or []) for r in recent}
    return mains, fulls


def _extract_card_numbers(card: dict) -> list:
    """從已組好的數據卡欄位(pct/mdd/range)掃出所有百分比數字字串，當作這張卡的「整組數字」簽名。"""
    text = " ".join(str(card.get(k, "") or "") for k in ("pct", "mdd", "range"))
    return _PCT_TOKEN_RE.findall(text)


def _record_used_numbers(slug: str, kind: str, target: str, card: dict) -> None:
    """把這次縮圖數據卡用掉的數字組寫回歷史檔，供下次去重比對；統一走 save_json_atomic 防併發洗檔。"""
    records = _load_used_numbers()
    records.append({
        "slug": slug or "",
        "kind": kind,
        "target": target,
        "pct": card.get("pct"),
        "numbers": _extract_card_numbers(card),
        "date": _time.strftime("%Y-%m-%d"),
    })
    if len(records) > 200:  # 去重視窗只看近 _DEDUP_WINDOW 支，不必無限增長
        records = records[-200:]
    try:
        save_json_atomic(USED_NUMBERS_JSON, records)
    except Exception as e:  # noqa: BLE001 — 寫歷史失敗不該擋產圖，只是下次少一筆去重依據
        print(f"[warn] 數據卡去重歷史寫入失敗（不影響本次縮圖）：{str(e)[:80]}", file=sys.stderr)


def _crypto_card(low: str, slug: str = None):
    """加密貨幣領域確認後才會被呼叫：標題點名的幣優先真實呈現；否則只在「策略/回測」題材
    才挑夏普最高的正報酬幣——但跳過近期已用過的數字組合，避免不同影片反覆冒出同一組數字。
    主題對不上(不在加密領域)不會走到這裡。"""
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
    # 2) 否則只在「策略/回測」題材才套，挑夏普最高的正報酬幣——但跳過近期用過的數字組合
    if chosen is None:
        if not is_strat:
            return None
        pos = [c for c in cards.values() if c.get("total_return", 0) > 0]
        if not pos:
            return None
        pos_sorted = sorted(pos, key=lambda c: c.get("sharpe", -99), reverse=True)
        mains, fulls = _recent_number_signatures("crypto")
        for c in pos_sorted:
            pct_s = f'{"+" if c["total_return"] >= 0 else ""}{c["total_return"] * 100:.1f}%'
            mdd_s = f'-{c["max_drawdown"] * 100:.1f}%'
            if pct_s not in mains and (pct_s, mdd_s) not in fulls:
                chosen = c
                break
        if chosen is None:
            # 2026-07-13 硬化：全部候選近期都出現過 → 不再「沿用重複數字」(那正是 Carson 抓到的
            # 「兩支不同影片數字一字不差」真實bug的根因)。誠信鐵則二選一都不能編數字，所以改成
            # 「擋下這張真實數據卡」(回 None)。
            # 2026-07-17 更正本註解：舊版寫「呼叫端會優雅退回誠實標『示意回測』的卡」——那正是
            # 繞過閘門的元兇(擋下真卡→立刻補一張編的數字)。示意卡已拆除，回 None ＝ 這支片不掛卡。
            print(f"[warn] 加密數據卡：近{_DEDUP_WINDOW}支已用完所有未重複的真實候選幣，"
                  f"硬擋不產卡(本片不掛數據卡)，拒絕輸出重複數字", file=sys.stderr)
            return None
    ret = chosen["total_return"] * 100
    mdd = chosen["max_drawdown"] * 100
    card = {
        "label": "真回測",
        "strat": f'{chosen["coin"]} {chosen["interval"]}·SuperTrend',
        "metric": "回測總報酬（含回撤）",
        "pct": f'{"+" if ret >= 0 else ""}{ret:.1f}%',
        "pct_color": "green" if ret >= 0 else "red",
        "mdd": f'最大回撤  -{mdd:.1f}%',
        "range": f'夏普 {chosen["sharpe"]:.1f}｜勝率 {chosen["win_rate"]*100:.0f}%',
        "note": "※歷史回測，非未來獲利保證",
    }
    _record_used_numbers(slug, "crypto", chosen["coin"], card)
    return card


# ── 標的閘門：卡上的數字必須跟標題講的是同一個標的 ──────────────────────────────
# 2026-07-17 改讀 computed 時實測抓到的坑（比「數字過期」更嚴重，是張冠李戴）：
# legacy 的 keywords 帶了「大盤」「加權」，所以標題寫「大盤…20年回測」時 TWII 那筆分數最高、自然勝出；
# computed 的 keywords 改成代碼「TWII」+ 官方全名「加權指數（大盤）」——兩者都**不會**是標題的子字串，
# 於是 TWII 與 0050 只能靠「定期定額」「All in」這種通用詞得分 → 平手 → 由排序決定 →
# **把 0050 的 +762.7% 掛到大盤的片上**。純字串比對治不了，得先確認標的。
# 作法＝_crypto_card「標題點名某幣就用那個幣的真實結果」的台股版。
_TW_EXTRA_ALIASES = {   # 只補 tw_facts_engine.SYMBOLS 的 code/name 沒涵蓋、但標題實際會用的口語寫法
    "TWII":   ["大盤", "加權", "加權指數", "台股大盤", "臺股大盤"],
    "0050":   ["台灣50", "臺灣50"],
    "006208": ["富邦台50", "富邦臺50"],
    "00631L": ["正2", "正二"],
    "2330":   ["台積電", "臺積電"],
}
_TW_ALIAS_CACHE = None


def _tw_symbol_aliases() -> dict:
    """{標的代碼: [比對用別名(小寫)...]}。代碼與官方名稱一律取自 tw_facts_engine.SYMBOLS
    （唯一真相，日後那邊加新 ETF 這裡自動跟上，不複製第二份清單），只疊上 _TW_EXTRA_ALIASES 的口語別名。
    SYMBOLS 載不到 → 退回只認 _TW_EXTRA_ALIASES 的幾檔（其餘標題就沒卡，安全側）。"""
    global _TW_ALIAS_CACHE
    if _TW_ALIAS_CACHE is not None:
        return _TW_ALIAS_CACHE
    base = {}
    try:
        import tw_facts_engine
        for code, info in tw_facts_engine.SYMBOLS.items():
            base[code] = [code, str(info.get("name") or "")]
    except Exception:  # noqa: BLE001
        pass
    for code, extra in _TW_EXTRA_ALIASES.items():
        base.setdefault(code, [code]).extend(extra)
    _TW_ALIAS_CACHE = {c: sorted({a.lower() for a in al if a}) for c, al in base.items()}
    return _TW_ALIAS_CACHE


def _tw_fact_symbols(entry: dict, aliases: dict) -> set:
    """這筆事實講的是哪些標的。computed 由 tw_facts_engine.add() 統一把 code+name 塞進 keywords，
    legacy 則是「大盤」這類口語詞——兩邊都用 keywords 逐項**完全比對**別名（不用子字串，
    免得「0050」誤中「00500」之類）。認不出標的 → 回空集合 → 呼叫端不給上卡。"""
    kws = {str(k).lower() for k in (entry.get("keywords") or [])}
    return {c for c, al in aliases.items() if any(a in kws for a in al)}


def _years_value(entry: dict):
    """這筆事實的回測年數(float)；取不到回 None。
    優先從 computed 的 period(start~end)**真值**反推，確保封面標的年數跟事實庫的期間對得起來；
    legacy 沒有 period 欄 → 退回 data.years。"""
    period = str(entry.get("period") or "")
    if "~" in period:
        try:
            a, b = period.split("~", 1)
            days = (_dt.date.fromisoformat(b.strip()) - _dt.date.fromisoformat(a.strip())).days
            if days > 0:
                return days / 365.25
        except Exception:  # noqa: BLE001 — period 是 '?~?' 或格式怪 → 退回 data.years
            pass
    try:
        v = (entry.get("data") or {}).get("years")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _years_text(entry: dict) -> str:
    """回傳可信的年數字串(如 '29年'/'20.1年'/'12.5年')；取不到 → ''(呼叫端就不標年數)。

    2026-07-17 誠信修正：封面標的年數一律**不可約整**。原本寫死 f'{years:.0f}年'，把 12.5 年印成
    「12年」、20.1 年印成「20年」——同一晚抓到 4 支已發布片把 20.1 年講成「10 年」，同型錯誤。
    保留 1 位小數(29.0 → 「29年」，20.1 → 「20.1年」，12.5 → 「12.5年」)。"""
    yrs = _years_value(entry)
    if not yrs or yrs <= 0:
        return ""
    return f'{f"{yrs:.1f}".rstrip("0").rstrip(".")}年'


_TITLE_YEARS_RE = _re.compile(r"(\d+(?:\.\d+)?)\s*年")
_CN_YEARS = {"三十年": 30, "二十年": 20, "十五年": 15, "十年": 10, "五年": 5, "三年": 3}


def _title_horizon_years(low: str):
    """標題點名的回測年數(「10年」「二十年」)；沒點名回 None。
    用途：同一標的常有多個窗(如 dca_vs_allin__TWII__10y 與 __full=29年)，關鍵字分數會平手，
    此時要挑**期間跟標題對得上**的那筆——否則標題喊 20 年、封面卻掛 10 年窗的數字，
    仍是「封面與內容各說各話」的同型問題。"""
    m = _TITLE_YEARS_RE.search(low)   # 只認數字緊接「年」，不會誤中「年線」「年化」
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    for w, v in _CN_YEARS.items():    # 由長到短比，免得「二十年」被「十年」先吃掉
        if w in low:
            return float(v)
    return None


def _build_tw_card(r: dict, slug: str = None, stock_key: str = None):
    """把事實庫(tw_facts_computed.json 為主)一筆結果轉成縮圖卡欄位，只用裡面已有的真數字，不外插不編造。
    挑主數字時跳過近期已用過的組合（往 scored 清單下找第一個沒用過的分支），
    避免同一支股票/ETF反覆掛出同一組百分比——絕不為了避重而竄改數字本身。

    2026-07-13 硬化：候選池從『每分支只挑一個指標(total_return 優先, elif cagr)』改成
    『total_return 與 cagr 都存在時各自算一個候選』(即「換指標」而非只「換分支」)——
    這是 Carson 抓到的真實bug根因：0050 all-in vs dca 這類題只有 2 個分支，若每分支只認
    1 個指標，全池只有 2 種可能的『pct』數字，題材一熱門(短時間內多支同題)必然撞號。
    把 total_return/cagr 都算進候選池能把可用組合翻倍，同一支股票也能「換指標」呈現
    (例如這支用總報酬、下一支用年化報酬)，不必動用到虛構數字。"""
    d = r.get("data", {})
    scored = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        if "total_return" in v:
            scored.append((k, v, v["total_return"], "total_return"))
        if "cagr" in v:
            scored.append((k, v, v["cagr"], "cagr"))
    if not scored:
        return None
    scored.sort(key=lambda t: t[2], reverse=True)
    mains, fulls = _recent_number_signatures("tw")
    chosen_idx = None
    for idx, (k, v, val, kind) in enumerate(scored):
        pct_s = f'{"+" if val >= 0 else ""}{val * 100:.1f}%'
        mdd_v = v.get("max_drawdown")
        mdd_s = f'{mdd_v * 100:.1f}%' if mdd_v is not None else None
        if pct_s not in mains and (pct_s, mdd_s) not in fulls:
            chosen_idx = idx
            break
    if chosen_idx is None:
        # 2026-07-13 硬化：全部分支×指標組合近期都出現過 → 不再「沿用重複數字」(那正是
        # 「兩支不同影片縮圖數據卡三個數字一字不差」的真實bug根因)。誠信鐵則不能編數字，
        # 所以改成「擋下這張真實數據卡」(回 None)——「換指標仍重複就擋下不產」。
        # 2026-07-17 更正本註解：舊版寫「呼叫端優雅退回誠實標『示意回測』的卡」——那是繞過閘門的
        # 元兇(擋下真卡→立刻補一張編的數字)。示意卡已拆除，回 None ＝ 這支片不掛卡。
        print(f"[warn] 台股數據卡（{stock_key or '?'}）：近{_DEDUP_WINDOW}支已用完所有未重複的真實候選"
              f"分支×指標組合，硬擋不產卡(本片不掛數據卡)，拒絕輸出重複數字", file=sys.stderr)
        return None
    pk, pv, pval, pkind = scored[chosen_idx]
    pct = f'{"+" if pval >= 0 else ""}{pval * 100:.1f}%'
    mdd = pv.get("max_drawdown")
    mdd_txt = f'最大回撤  {mdd * 100:.1f}%' if mdd is not None else None
    metric = ("總報酬" if pkind == "total_return" else "年化報酬") + f'（{_TW_BRANCH_LABEL.get(pk, pk)}）'
    # 對照分支：優先挑排序上緊接著主數字後面那筆，主數字不是原本最高分那筆時退回原本最高分那筆對照
    sec_idx = chosen_idx + 1 if chosen_idx + 1 < len(scored) else (0 if chosen_idx != 0 else None)
    range_txt = None
    if sec_idx is not None:
        sk, sv, sval, skind = scored[sec_idx]
        sfx = "總報酬" if skind == "total_return" else "年化"
        range_txt = f'{_TW_BRANCH_LABEL.get(sk, sk)}對照 {"+" if sval >= 0 else ""}{sval * 100:.1f}%（{sfx}）'
    yr_txt = _years_text(r)   # 用 period 真值反推、不約整（見 _years_text）
    strat = f'{_TW_BRANCH_LABEL.get(pk, pk)}·{yr_txt}' if yr_txt else _TW_BRANCH_LABEL.get(pk, pk)
    card = {
        "label": "台股實測",
        "strat": strat[:14],
        "metric": metric,
        "pct": pct,
        "pct_color": "green" if pval >= 0 else "red",
        "mdd": mdd_txt or (range_txt or "歷史回測"),
        "range": (range_txt if mdd_txt else None) or (f'期間 {yr_txt}' if yr_txt else "歷史回測"),
        "note": "※歷史回測，非未來獲利保證",
    }
    _record_used_numbers(slug, "tw", stock_key or pk, card)
    return card


def _tw_card(low: str, slug: str = None):
    """台股/ETF領域確認後才會被呼叫：從事實庫找關鍵字明確對上(≥2個)的結果才套卡。
    標題點名個股(如台積電)→ 一律不套(見 _TW_UNCOVERED_STOCK_KW)。

    2026-07-17：改讀 _load_tw_facts_merged()(computed 為主)，與寫稿端同源——原本只讀 legacy，
    封面吐 legacy 的舊窗數字、腳本講 computed 的新窗數字，同一支片自己打臉(實測 EP3 大盤長抱：
    封面 +10.2%/20年 vs 腳本 5.7%/29年)。

    另：改成「照關鍵字分數由高到低試，取第一個真的生得出卡的」而非「只認最高分那一筆」。
    事實庫從 5 組長到 50 組後，扣款日效應/停利/錯過最佳N天/崩盤這些主題**結構上生不出對比卡**
    (data 沒有帶 total_return/cagr 的 dict 分支)，若它們搶到最高分就會讓整支片平白無卡。
    """
    if any(k in low for k in _TW_UNCOVERED_STOCK_KW):
        return None
    results = _load_tw_facts_merged()
    if not results:
        return None
    aliases = _tw_symbol_aliases()
    title_syms = {c for c, al in aliases.items() if any(a in low for a in al)}
    if not title_syms:
        # 標題沒點名任何標的 → 無從確認卡上的數字跟片講的是不是同一件事 → 不掛卡。
        # (誠信鐵則同本檔既有規則：數字對不上主題寧可不掛卡；沒卡不等於沒縮圖，圖照出、改貼吉祥物)
        return None
    cands = []
    for key, r in results.items():
        if not isinstance(r, dict):
            continue
        fact_syms = _tw_fact_symbols(r, aliases)
        # 認不出標的、或這筆講到標題沒提的標的 → 不夠格(例如標題只講 0050，就不拿
        # 「0056 vs 0050」那筆來充數；標題講大盤，就絕不拿 0050 的數字頂替)
        if not fact_syms or not fact_syms <= title_syms:
            continue
        score = sum(1 for k in (r.get("keywords") or []) if str(k).lower() in low)
        cands.append((score, key))
    # 排序：關鍵字分數高者優先 → 同分則期間最貼近標題喊的年數者優先(標題沒喊年數就不比這項)
    # → 再同分用 key 名排序，確保同一支片每次都挑到同一筆(可重現)。
    # 至少2個關鍵字對上才算可信匹配，避免單一泛用詞誤配。
    horizon = _title_horizon_years(low)

    def _rank(t):
        score, key = t
        if horizon is None:
            return (-score, 0.0, key)
        fy = _years_value(results[key])
        return (-score, abs(fy - horizon) if fy else 99.0, key)

    for score, key in sorted(cands, key=_rank):
        if score < 2:
            break
        card = _build_tw_card(results[key], slug=slug, stock_key=key)
        if card:
            return card
    return None


def _real_card(slug: str, title: str):
    """依影片主題領域(台股/加密)挑一張誠實的真數據卡。領域不明、個股無資料、或關鍵字對不上
    → 回 None(交給示意卡或無卡)。誠信鐵則：台股題絕不配加密卡，反之亦然；數字對不上主題寧可不掛卡。"""
    low = f"{title or ''} {slug or ''}".lower()
    domain = _asset_domain(low)
    if domain == "crypto":
        return _crypto_card(low, slug=slug)
    if domain == "tw":
        return _tw_card(low, slug=slug)
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


# ⚠️ 2026-07-17 誠信修:**品牌/系列名不是打假宣稱**。
#    「台股真相實驗室」內含「真相」→ 舊版 is_debunk() 把**每一支** tw_lab 影片都判成打假片,
#    於是縮圖去憑空捏一個敵人(「他吹的神話」),還把**我們自己的存量數字**當成對手的神話
#    一刀切開:實測 EP.0 封面印「他吹的神話 29組」打紅叉 + 「他說29組神/我拆給你看」——
#    但 29 組是**我自己還沒拍的真回測存量**,不是誰吹的、更不是我要拆穿的東西。語意整個反過來。
#    修法:比對打假關鍵字前先把品牌/系列名拿掉——它是招牌,不是主張。
_BRAND_PHRASES = ("台股真相實驗室", "臺股真相實驗室", "真相實驗室", "個股體檢系列", "個股體檢", "量化阿森")


def _strip_brand(text: str) -> str:
    t = text or ""
    for b in _BRAND_PHRASES:
        t = t.replace(b, "")
    return t


_NEUTRAL_SERIES = ("個股體檢",)


def is_debunk(text: str) -> bool:
    """標題含拆穿/真相/打臉/揭穿…等打假關鍵字 → 走《拆穿》縮圖公式。
    ⚠️ 先去品牌/系列名再比對(見 _BRAND_PHRASES):招牌裡的「真相」不代表這支在打假。

    🔴 2026-07-28 誠信修復(紅線動作驗證時擋下的事故):**中性系列結構性豁免打假樣式。**
    個股體檢的標題慣用「背後的真相」「崩」這類字,去掉品牌名後仍會命中 _DEBUNK_KW →
    誤判成打假片 → `_decorate_debunk` 會在縮圖上印「336倍**騙局**」「**他吹的神話** 336倍」
    並用紅刀劃掉那個數字。實測 16 支已發布體檢片有 **6 支**中招。
    這不只是難看,是**誠信問題**:被劃掉、被叫「騙局/他吹的神話」的 336倍、1075% 是
    **本頻道自己真回測算出來的真結果**,而個股體檢是中性體檢、**根本沒有「他」**——
    等於憑空捏造一個對手,再把自己的真數據打成假的;而且點進去內容與縮圖不符。
    個股體檢的生死線就是「介紹≠推薦」的中性,故不是調關鍵字,是**整個系列永不套打假樣式**。
    """
    if any(s in (text or "") for s in _NEUTRAL_SERIES):
        return False
    return any(k in _strip_brand(text) for k in _DEBUNK_KW)


def _valid_myth(s) -> str | None:
    """神話數字必須是**帶結果單位**的數字(% 或 倍)才算數;否則回 None(不掛神話卡)。

    ⚠️ 2026-07-17:本檔原本就有「不要 fallback 亂抓裸數字」的防線(見下方掃描分支的註解),
       但**LLM 給的 cfg['myth'] 舊版直接採用、繞過那道防線** → 「29組」就這樣被印成
       「他吹的神話」。裸數字沒有單位就沒有意義,更不可能是對手的績效宣稱。
       (與 fact_pool 無單位池、hook_card 撈裸數字同一個病:**數字沒有單位就不是事實**。)
       這裡是 myth 的**唯一驗證點**——LLM 路徑與掃描路徑共用同一把尺(不重複實作)。
    """
    s = (str(s) if s is not None else "").strip()
    if not s or not any(c.isdigit() for c in s):
        return None
    if "%" not in s and "倍" not in s:
        return None
    return s[:8]


_LEAD_SYM_RE = _re.compile(
    r"^\s*(?:【\s*)?"                      # 可能有【】包住
    r"([一-鿿]{0,4}?\s*\d{4,6}[A-Z]?"   # 台股/ETF 代號:0050、00878、00631L、2330
    r"(?:\s*(?:vs|VS|對比|比)\s*\d{4,6}[A-Z]?)?)")   # 也吃「0050 vs 00631L」對比題


def _lead_symbol(title: str) -> str:
    """從標題開頭抽出標的代號(0050 / 00878 / 00631L / 2330,含「A vs B」)。抽不到回 ""。

    用途:debunk 保底文案要換掉碎片化的 l1 時,**不要連標的一起丟掉**。
    這批 ETF/個股長片靠代號的長尾搜尋持續拿曝光,縮圖上留著代號才對得上搜尋意圖。
    純字串規則、零 LLM 依賴(LLM 掛掉時正是最需要它的時候)。
    """
    m = _LEAD_SYM_RE.match(title or "")
    if not m:
        return ""
    s = " ".join(m.group(1).split())
    if not any(c.isdigit() for c in s):
        return ""
    # ⚠️ 不可用 s[:10] 硬切——「0050 vs 00631L」會被切成「0050 vs 00」,
    # 那正是本次要修的「斷在半個代號」。太長就整段丟掉 vs 部分,只留第一個代號。
    if len(s) > 12:
        first = _re.match(r"^\s*[一-鿿]{0,4}?\s*\d{4,6}[A-Z]?", s)
        s = " ".join(first.group(0).split()) if first else ""
    return s


def _myth_number(cfg: dict):
    """抓出被拆穿的『神話數字』。**只認明確給進來的 cfg['myth']**,無則 None(不掛神話卡)。

    🔴 2026-07-30 拿掉「掃 l1/l2/title/tag 找 %／倍 數字」的 fallback。實測照片存證:
       - 《0050定投10年賺824%?回測拆穿「微笑曲線」陷阱》→ 縮圖印「他吹的神話 **824%**」+紅刀
       - 《0050定期定額vs美股ETF:10年回測**少賺**58%?拆穿躺賺迷思》→ 印「**他說能賺** 58%」+紅刀
       兩個數字都是**我們自己的真回測結果**,卻被指派給一個不存在的「他」再劃掉。
       第二張還把「少賺58%」反轉成「他說能賺58%」——結論被講成相反的意思。

    為什麼不能用更聰明的規則救:「他吹的神話」是在斷言**某個外部的人講過這個數字**。
    這件事**不可能從我們自己的標題推導出來**——標題裡的數字是我們算的。
    所以正解是拿掉推論能力,不是再加判斷字詞。被拆穿的是「微笑曲線」「躺賺迷思」這類
    *說法*,不是某個人;沒有可指認的外部宣稱時,整張圖不掛神話卡即可(這是既有的優雅降級)。

    歷史:先前兩次修補都是窄補——①要求帶 %／倍 單位(_valid_myth) ②豁免「個股體檢」系列
    (_NEUTRAL_SERIES)。結構洞一直在:任何自家標題帶「拆穿/崩/打臉」又含數字的片都會再踩。
    """
    return _valid_myth(cfg.get("myth"))


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
        # 🔴 2026-07-30 移除這裡原本的小標「他吹的神話」。
        # 它在這條產線裡**結構上永遠是假的**,而且可以嚴格證明:
        #   ①本檔 `_numbers_traceable` 這道閘門**強制** LLM 生的數字必須在標題裡找得到,
        #     否則整包退保底 → 所以 cfg['myth'] 保證是**我們自己標題裡的數字**。
        #   ②_myth_number 已不再從自家欄位推論(同日修),剩下的唯一來源就是①。
        # 兩條合起來:被標成「他吹的神話」的數字,百分之百是我們自己算出來的。
        # 實測照片存證:824%(自家回測報酬)、「少賺58%」被印成「他說能賺58%」——結論反轉。
        # 金數字+紅刀的視覺保留:那表達「這說法被推翻」,是創作手法;
        # 但「他吹的」是在指認一個**具體的人講過這句話**,產線沒有任何欄位能證明那個人存在。
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


# 🔴 2026-07-30 空白不再一律當子句邊界。
# 實測:《0050定期定額vs一次All in十年回測:哪個賺更多…》→ 「All in」被中間那個空格
# 切開,l1 拿到「0050定期定額」、l2 變成孤零零的「**in**十年回測」(照片存證)。
# 中文標題裡的空白多半只是排版,而英文詞組(All in / Dollar Cost / vs 兩側)靠空白連著。
# 改法:①先用標點斷句 ②空白只有在**兩側不是英數字**時才算邊界
#   (?<![A-Za-z0-9])\s+(?![A-Za-z0-9]) → 「All in」不斷,「額 vs」也不會被空白拆碎。
#   ⚠️ 2026-07-30 二修:第一版寫成「(?<![A-Za-z0-9])\s+|\s+(?![A-Za-z0-9])」=**任一側**
#   不是英數字就斷,方向寫反了。後果:中文包夾的「額 vs 臺」兩個空白都命中 → 「vs」被切成
#   獨立子句,實測產出第二行只有「vs」兩個字(照片存證)。正解是**兩側都不是英數字**才斷,
#   這樣「All in」和「額 vs 臺」都連著,而純中文之間的排版空白照常斷。
_CLAUSE_SPLIT_RE = _re.compile(
    r"[？?！!，,。、：:；;\-—－]+|(?<![A-Za-z0-9])\s+(?![A-Za-z0-9])")


_SOFT_BREAK = ("的", "了", "與", "和", "或", "跟", "在", "把", "vs", "VS", "、",
               "，", ",", "·", " ", "：", ":")
_DANGLING = "『「《（(【〈“‘"    # 只開沒關的引號/括號,留在結尾就是切壞的痕跡


def _clean_cut(s: str, limit: int) -> str:
    """把 s 切到 limit 字以內,但**不切在詞中間**,也不留懸空的開引號。

    🔴 2026-07-30 為什麼要有這支:_heuristic 的 docstring 寫著「不從單一子句『中間』硬切」,
    但它的實作是 clauses[0][:8] / clauses[1][:10]——子句一旦超過字數就是從中間硬切。
    照片存證:《0056填息天數暴增3倍!存股族最該怕的『高股息陷阱』十年回測》
    → 縮圖第二行印成「存股族最該怕的『高股」,「高股息」被切一半、引號只開沒關。
    (註解宣稱了程式沒做的事——和 make_video 那個「保住浮水印」的假註解同型。)

    策略:先在 limit 內找最後一個自然斷點(的/與/、/空白…)且不要切太短(至少留 limit 的 6 成);
    找不到就退回硬切,但一律清掉結尾的懸空開引號。**寧可短一點,也不要斷在半個詞。**
    """
    s = (s or "").strip()
    if len(s) <= limit:
        return s.rstrip(_DANGLING).strip()
    head = s[:limit]
    best = -1
    for b in _SOFT_BREAK:
        i = head.rfind(b)
        if i > best:
            best = i + (len(b) if b not in ("的", "了", "在", "把") else 1)
    # 斷點太靠前會切到剩沒幾個字,反而看不出主題 → 那就寧可硬切後清尾
    if best >= max(2, int(limit * 0.6)):
        head = head[:best]
    head = head.rstrip(_DANGLING).rstrip("".join(_SOFT_BREAK)).strip()

    # ⚠️ 2026-07-30 二修:上面找不到自然斷點時仍會硬切,而硬切最糟的一種是**切進數字**。
    # 實測產出:「00878存股6」(原文「存股6年」)、「欣興3037存2」「群創3481存2」
    # (原文「存20年」)——數字被腰斬後意思整個變了(6年→6、20年→2)。
    # 規則:若切點正好落在「數字」與其後的單位之間,退到數字之前,寧可短也不要留半個數字。
    _NUMISH = "0123456789０１２３４５６７８９.一二三四五六七八九十百千兩"
    _UNIT = "年倍％%支檔萬億元月日次點成人塊"
    m = _re.search(r"[0-9０-９.一二三四五六七八九十百千兩]+$", head)
    if m and len(s) > len(head) and (s[len(head)] in _NUMISH or s[len(head)] in _UNIT):
        # 切點落在一串數字中間(20→「2」|「0年」)或數字與單位之間(十|年):整串丟掉。
        # 含中文數字——實測「台積電定期定額十年」被切成「…十」,只認阿拉伯數字會漏。
        head = head[:m.start()].rstrip(_DANGLING + "".join(_SOFT_BREAK)).strip()
        # 數字拿掉後常留一個孤立動詞(「欣興3037存」),那個字本來是要接數字的,一起去掉。
        head = head.rstrip("存賺翻漲跌差少多虧賠賺破約近超逾滿").strip()

    # 退化結果不要:純連接詞或剩不到 2 字,寧可回空字串讓呼叫端走保底文案,
    # 也不要在縮圖上印一個「vs」。
    if head in ("vs", "VS", "和", "與", "或", "跟", "的", "了") or len(head) < 2:
        return ""
    return head


def _heuristic(slug: str, title: str) -> dict:
    """無 LLM 時的保底：按標點斷句(不從單一子句『中間』硬切)，避免像「網格上/限」「輕/鬆」
    這種把一個完整詞硬生生切成兩半、跨行斷字的破碎縮圖。
    l1＝第一個完整短句(取其前 8 字內，不夠 8 字就整句)；
    l2＝第二個完整短句(前 10 字內)；沒有第二句就用通用收尾語，絕不從 l1 的子句裡挖字硬湊。"""
    t = _re.sub(r"[（(].*?[)）]", "", title or slug).strip()
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(t) if c]
    if not clauses:
        clauses = [t] if t else [slug or "看完秒懂"]
    # 一律走 _clean_cut:不切在詞中間、不留懸空開引號(舊版 [:8]/[:10] 硬切,
    # 實測把「高股息陷阱」切成「高股」、引號只開沒關)。
    l1 = _clean_cut(clauses[0], 8) or _clean_cut(t, 8) or "看完秒懂"
    l2 = (_clean_cut(clauses[1], 10) if len(clauses) > 1 and clauses[1] else "") or "看完秒懂"
    tag_src = "".join(clauses[2:]) if len(clauses) > 2 else t
    # 底條也清掉開頭/結尾的分隔符——實測產出過「|0056填息天數十年回測」這種孤立豎線。
    tag = _clean_cut((tag_src or t).strip("｜|/·-—　 "), 14) or "量化阿森"
    return {"slug": slug, "l1": l1, "l2": l2, "tag": tag,
            "accent": ACCENTS["yellow"], "mark": "?"}


def _decorate_debunk(cfg: dict, title: str) -> dict:
    """若標題屬《拆穿》打假題 → 打上 debunk 旗標、抽神話數字、鎖紅色警示配色，交給 _make_debunk 走招牌公式。"""
    if not is_debunk(title):
        return cfg
    cfg["debunk"] = True
    cfg["accent"] = ACCENTS["red"]
    cfg.setdefault("title", title)
    # 🔴 2026-07-30 這裡原本會呼叫 _myth_number({"title": title, ...}) 從**自己的標題**
    # 推一個「神話數字」塞進 cfg["myth"]。已移除——理由見 _myth_number 的說明(照片存證:
    # 自家真回測結果 824%／少賺58% 被標成「他吹的神話」「他說能賺」再劃紅刀)。
    # 現在 cfg["myth"] 只可能來自明確供給的外部宣稱;沒有就不掛神話卡。
    # 保底啟發式會把「《拆穿》｜…」原標題硬切成 l1/l2(醜且和金數字重複)；偵測到切片痕跡就換乾淨的打假標語
    # 注意:**不要**把「?／？」放進來當切片訊號——正常鉤子很常帶問號
    # (「真的能賺?」),那會把 LLM 寫的好文案誤判成碎片換掉。
    # 「整行照抄標題」那條判準已經足夠可靠,不需要靠問號。
    _slice_marks = ("拆穿", "｜", "|", "「", "」", "《", "》", "『", "』")
    _tclean = _strip_brand(title).replace(" ", "")

    def _is_sliced(s) -> str:
        """判斷這一行是不是『把原標題硬切出來的碎片』(而非寫好的鉤子)。

        兩個訊號:①含切片痕跡符號 ②整行是原標題的字面子串。
        LLM 寫的鉤子是改寫、不會整行照抄標題,所以②很可靠;而 LLM 掛掉時走的保底
        路徑就是照抄+截斷,會被②抓到。
        """
        s = (s or "").strip()
        if not s:
            return ""
        if any(ch in s for ch in _slice_marks):
            return "有切片符號"
        if s.replace(" ", "") in _tclean and len(s) >= 4:
            return "整行照抄標題"
        return ""

    # 🔴 2026-07-30 改成**逐行**判斷。舊版只看 l1,而且實際上是靠「myth 出現在 l2」
    # 這條副作用才誤觸發替換;我把 myth 推論拿掉後,壞掉的 l2 就沒人接手了,
    # 實測產出「回測拆穿『微」「10年回測少」——斷在半句(照片存證)。
    # 逐行修的好處:l1 常常是乾淨且帶標的的(「0050定投」),整組換掉會犧牲搜尋辨識度。
    _r1, _r2 = _is_sliced(cfg.get("l1")), _is_sliced(cfg.get("l2"))
    if _r1 or _r2 or (cfg.get("myth") and cfg.get("myth") in (cfg.get("l2") or "")):
        if cfg.get("myth"):
            # 有可指認的外部宣稱數字,才能用「他說」這種指人的說法。
            if _r1:
                cfg["l1"] = "他說能賺"
            cfg["l2"] = "我拆給你看"
        else:
            # 沒有外部宣稱 → **不可發明一個說話的人**。指向「說法」本身,不指人、不掛數字。
            # (被拆穿的是「微笑曲線」「躺賺迷思」這類信仰,講「這說法」才是真的。)
            if _r1:
                # 但別把標的一起丟掉:這批是靠個股/ETF 代號長尾搜尋吃曝光的常青片,
                # 縮圖上沒有代號等於少一個辨識點。開頭有代號就留著(確定性抽取,不靠 LLM)。
                cfg["l1"] = _lead_symbol(title) or "這說法"
            cfg["l2"] = "回測拆給你看"
        cfg["tag"] = "我幫你避雷，不賣你夢"   # 底條也一併換招牌簽名(蓋掉切片痕跡)
    return cfg


_DIGITS_RE = _re.compile(r"\d+")


_TRACEABLE_FIELDS = ("l1", "l2", "tag", "myth")   # 本檔 derive_cfg 的文案欄位(預設)


def _numbers_traceable(d: dict, title: str, fields=_TRACEABLE_FIELDS) -> bool:
    """LLM 生的縮圖文字裡,每一串數字都必須在標題裡找得到;否則視為**憑空發明**,整包不採用。

    為什麼是「整包退回」而不是「把那個數字挖掉」:挖字會產生破碎殘句(本檔上面 hook 那條
    已經踩過一次),而且會**留下一個我們沒驗證過的句子**。退保底最乾淨——保底是切標題來的。
    ⚠️ 只比對數字,不比對文案:LLM 仍可自由發揮文字,它只是不准生數字。

    2026-07-17：加 `fields` 參數讓 make_cover.derive() 能拿自己的欄位名(kicker/headline/hook_*)
    共用**同一支**閘門。理由＝make_cover 原本完全沒有這道檢查(它的 LLM prompt 甚至明示要
    「比特幣崩盤·18萬人爆倉」這種帶數字的 kicker),而 daily_publish 優先走 make_cover ——
    等於這道閘門在產線上是被繞過的。複製第二份實作必然 drift(今晚已數不清第幾個實例),
    故改成參數化共用。預設值＝本檔原欄位,既有呼叫端行為不變。
    """
    tnums = set(_DIGITS_RE.findall(title or ""))
    for k in fields:
        for n in _DIGITS_RE.findall(str(d.get(k) or "")):
            if n not in tnums:
                print(f"[warn] 縮圖 LLM 發明了標題沒有的數字 {n!r}(欄位 {k})→ 退保底,不採用",
                      file=sys.stderr)
                return False
    return True


def _force_stock_identity(cfg: dict, slug: str, title: str) -> dict:
    """個股體檢的縮圖:**主標一定要出現股票名或代號**。

    ## 為什麼(2026-08-06 實測)
    抓兩支實際線上縮圖來看:
      聯鈞那支 → 主標「4322%報酬 / 真相大拆解」,**整張圖沒有「聯鈞」也沒有「3450」**
                 (870 觀看 / 6 訂閱 = 0.7%)
      00878 那支 → 主標「00878存股 / 但套牢1.4年」
                 (737 觀看 / 10 訂閱 = **1.4%**)
    這是一個**靠搜尋起家**的頻道:搜尋詞前 25 名幾乎全是個股名與代號,
    體檢片有 49% 流量來自搜尋。**搜「聯鈞」的人,看到一張不寫聯鈞的圖。**
    對他來說那張圖跟他要找的東西對不起來,自然不點。

    做成確定性注入而不是寫進提示:LLM 每次都在「哪個數字最吸睛」上打轉,
    而「這是哪一檔」對搜尋流量來說是必要資訊,不能靠它想起來。
    ⚠️ 只在**兩行主標都沒有**識別資訊時才動,已經有的不改(不破壞好鉤子)。
    """
    if "個股體檢" not in (slug or "") and "個股體檢" not in (title or ""):
        return cfg
    m = _re.search(r"個股體檢([一-鿿]{2,6}?)(\d{4})", slug or "")
    if not m:
        m = _re.search(r"個股體檢([一-鿿]{2,6}?)(\d{4})", title or "")
    if not m:
        return cfg
    name, code = m.group(1), m.group(2)
    l1 = str(cfg.get("l1") or ""); l2 = str(cfg.get("l2") or "")
    # 🔴 「已經有識別資訊」不等於「排版是對的」。實測保底路徑會直接截標題前 8 字,
    #    產出第一行 =「個股體檢【頎邦」——**括號斷在一半**,而且「個股體檢」四個字
    #    白白佔掉最大字級的一半空間(那是系列名,不是這支片的識別)。
    #    所以除了「有沒有」,還要檢查「乾不乾淨」:帶系列前綴或殘缺括號的一律重寫。
    _dirty = ("個股體檢" in l1 or "【" in l1 or "】" in l1
              or l1.endswith(("(", "（", "[", "「")))
    if (name in l1 or name in l2 or code in l1 or code in l2) and not _dirty:
        return cfg          # 已經看得出是哪一檔、而且排版乾淨 → 不動
    # 把識別資訊放進第一行(最大字),原本的 l1 往下擠掉 l2 的位置太亂 →
    # 改成前綴接在 l1 前面,長度仍受 make_one 的排版限制保護。
    # l1 換成識別資訊,但**原本那行通常是全圖最有力的數字**(如「4322%報酬」),
    # 不能丟掉 → 把它擠到第二行。第二行原本的內容(多半是「真相大拆解」這種
    # 沒有資訊量的裝飾句)才是可以捨棄的那個。
    cfg["l1"] = ("%s%s" % (name, code))[:8]
    # 原本的 l1 通常是全圖最有力的數字(如「4322%報酬」)→ 擠到第二行保留。
    # 但如果它本身就是髒的(系列前綴/殘缺括號),**丟掉**而不是搬到第二行去繼續髒;
    # 這時第二行維持原本的 l2(那多半是「但79.9%暴跌風險」這種有內容的鉤子)。
    cfg["l2"] = ((l2 or l1) if _dirty else (l1 or l2))[:10]
    return cfg


def derive_cfg(slug: str, title: str) -> dict:
    """從標題自動生縮圖鉤子。優先用共用 llm.complete(OpenRouter 路由,同其他 dept 腳本)，失敗退保底啟發式。
    《拆穿》題自動套打假公式。
    2026-07 根因修復：舊版直打 api.anthropic.com + 讀 ANTHROPIC_API_KEY——工作室早改 OpenRouter，
    Anthropic key 已失效，每張新縮圖的 LLM 鉤子因此靜默失敗、全退保底硬切標題，是縮圖斷字的根因。"""
    deb = is_debunk(title)
    fb = _decorate_debunk(_heuristic(slug, title), title)
    has_any_key = any(_os.environ.get(k, "").strip() for k in
                      ("OPENROUTER_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
                       "GEMINI_API_KEY", "ANTHROPIC_API_KEY"))
    if not has_any_key:
        return fb
    try:
        import llm  # 共用路由：主供應商(OpenRouter)→失敗退回 fallback，換模型只改 env，同 make_cover.py
        # 🔴 2026-07-30 重寫這段指示。舊版是「l1/l2 用打假語氣(如『他說812%』…)」+
        # 「myth 欄＝**對手宣稱**…**抓標題裡的**」——這兩句自相矛盾且是事故源頭:
        # 一邊叫它從我們自己的標題抓數字,一邊叫它改稱那是對手的宣稱。
        # 加上本檔 `_numbers_traceable` 強制 LLM 的數字必須在標題裡找得到,
        # 結論是:被說成「他吹的」那個數字,**保證是我們自己算的**。禁掉指人的句式。
        myth_line = ('這是「拆穿」類影片:l1/l2 用「戳破一個說法」的語氣。\n'
                     '⛔ 但**不可以指名或暗示某個人講過這個數字**——禁止「他說」「他吹的」'
                     '「網紅說」「某大師說」這類句式。理由:本產線沒有任何欄位能證明那個人存在,'
                     '而下面的誠信閘又強制你的數字必須取自標題,等於那個數字本來就是我們自己算的;'
                     '把它說成別人吹的,是憑空發明一個對手。\n'
                     '✅ 改用指向「說法本身」的講法:「這說法」「真的嗎」「回測拆給你看」「數據不同意」。\n'
                     '另給 "myth" 欄＝標題裡那個**被檢驗的數字**(如「812%」「236倍」);'
                     '它會被畫成金色大字加一道紅刀,表達「這個說法被回測推翻」,不代表有人吹過它。'
                     '抓不到就給空字串。\n'
                     'accent 固定 red。\n') if deb else ""
        prompt = (f"影片標題：{title}\n"
                  "為這支量化交易教學影片產生吸睛 YouTube 縮圖文字，只輸出 JSON：\n"
                  '{"l1":"第一行鉤子(2-6字,最吸睛的詞/數字)","l2":"第二行(3-8字)",'
                  '"tag":"底部說明條(6-14字)","accent":"yellow|green|red|blue","mark":"?或!或$或VS","myth":"被拆穿的神話數字或空字串"}\n'
                  + myth_line +
                  "繁體中文。誠信鐵則：不用『穩賺/保證/必賺』。配色：紅=警示/虧損，綠=獲利/實測，黃=疑問/教學，藍=工具/平台。")
        t = llm.complete(prompt, max_tokens=300, json_mode=True, temperature=0.6)
        d = _json.loads(_re.search(r"\{.*\}", t, _re.S).group(0))
        # 🔴 誠信閘(2026-07-17):**LLM 不准自己發明數字**。
        #    實測:標題「已經拆完 14 集，還有 29 組真回測排隊中」→ LLM 生出「43組實測」
        #    (= 14 + 29 自己加起來的)。我們從來沒有「43 組實測」這個數字,它憑空長在**封面**上
        #    ——而封面是觀眾看最多眼的一個面。這與 hook_card 撈裸數字、fact_pool 無單位池
        #    同一個病:**數字沒有來源就不是事實**。
        #    規則:LLM 文字裡出現的每一串數字,都必須在標題裡找得到;找不到 → 整包退保底
        #    (保底是切標題產生的,數字結構上不可能超出標題)。
        if not _numbers_traceable(d, title):
            return fb
        cfg = {"slug": slug, "l1": (d.get("l1") or fb["l1"])[:8], "l2": (d.get("l2") or fb["l2"])[:10],
               "tag": (d.get("tag") or fb["tag"])[:16],
               "accent": ACCENTS.get((d.get("accent") or "yellow").lower(), ACCENTS["yellow"]),
               "mark": (d.get("mark") or "?")[:2]}
        if d.get("myth"):
            cfg["myth"] = str(d["myth"])[:8]
        return _force_stock_identity(_decorate_debunk(cfg, title), slug, title)
    except Exception as e:
        print(f"[warn] llm 生鉤子失敗，用保底：{str(e)[:80]}", file=sys.stderr)
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
