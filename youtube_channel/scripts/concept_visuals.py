# -*- coding: utf-8 -*-
"""concept_visuals.py — 依段落文字判斷量化主題，用 matplotlib 畫「跟旁白對得上」的數據圖。

設計目標：解決「整支影片一張靜態圖、像在乾聽旁白」的問題。
每個段落依其小標 + 旁白關鍵字，選一張能說明當下重點的圖：
  網格→價格震盪+網格線+買賣點 / 定投→定期買點+成本均線 / 複利→指數成長曲線 /
  回撤→權益曲線+回撤陰影 / 夏普→平滑vs崎嶇兩線 / 勝率→盈虧長條 /
  馬丁→爆量加碼後崩 / 過擬合→樣本內外背離 / 趨勢→單邊走勢 / 回測→樣本內外切分。
判不到主題就回 None，呼叫端退回原本的 K 線卡。

對外只暴露 render_concept_chart(width, height, text, accent, seed, dest_or_none) -> PIL.Image | None
回傳的是「滿版深色底 + 置中數據圖」的 RGB 影像；大標題條與字幕由 make_video 疊上去。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # 無視窗後端
import matplotlib.pyplot as plt
import matplotlib.patheffects as _pe   # 2026-07-28:給關鍵數字加描邊,避免被圖線穿過看不清
import numpy as np
from matplotlib.patches import Rectangle

# 深色主題（與 K 線卡一致）
_LOG_RATIO = 8.0    # 最高/最低價超過這個倍數就改對數座標(見 _maybe_log_y)

BG = (10 / 255, 14 / 255, 26 / 255)
PANEL = (16 / 255, 21 / 255, 38 / 255)
GRID = (1, 1, 1, 0.07)
FG = (0.82, 0.86, 0.95)
MUTED = (0.55, 0.60, 0.72)
RED = (255 / 255, 96 / 255, 96 / 255)
GREEN = (88 / 255, 220 / 255, 140 / 255)


def _seeded_rng(seed: str) -> np.random.RandomState:
    h = int(hashlib.md5((seed or "x").encode("utf-8")).hexdigest(), 16) % (2 ** 31)
    return np.random.RandomState(h)


# --------------------------------------------------------------------------- #
# 真資料層(2026-07-17)
#
# 判準沿用 _backtest 拆除案:**圖只要在描繪「市場真實走勢」,就必須來自真資料;
# 拿不到真資料就不畫那張圖**。絕不畫 rng 亂數線冒充行情。
#
# ⚠️ 「不畫」必須真的沒有圖。render_ffmpeg._make_seg_card 的降級鏈原本是
#    concept → K線卡 → 字卡,而 K線卡(make_video._render_candles_strip)也是
#    `rng.randn().cumsum()` 隨機漫步 —— 所以舊的「fail-safe 不畫」其實是
#    「換一張假圖」。該處已同批改成 concept → 字卡(見那邊註解)。
# --------------------------------------------------------------------------- #

_FACTS_CACHE = Path(__file__).resolve().parent.parent / "STUDIO" / "tw_facts_cache"

# 台股代號:00 開頭 ETF(0050/0056/00878/00631L…)或 4 位數個股(2330/2412…)。
_TICKER_RE = re.compile(r"(00\d{2,3}[A-Z]?|[1-9]\d{3})")

_REAL_CACHE: dict = {}


def resolve_ticker(text: str) -> Optional[str]:
    """從標題+旁白抓出「在 tw_facts_cache 有真實 CSV」的台股代號;抓不到→None。

    只認**我們手上真的有價格檔**的代號 —— 講到 00929 但沒有 00929.csv 就回 None
    (→ 不畫圖),不會拿別檔的資料頂替。
    """
    if not text:
        return None
    for m in _TICKER_RE.findall(text):
        if (_FACTS_CACHE / f"{m}.csv").exists():
            return m
    return None


def load_real(ticker: str):
    """讀真實日收盤。回傳 (dates: np.ndarray[datetime64], close: np.ndarray) 或 None。"""
    if ticker in _REAL_CACHE:
        return _REAL_CACHE[ticker]
    f = _FACTS_CACHE / f"{ticker}.csv"
    if not f.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_csv(f)
        if "Date" not in df.columns or "Close" not in df.columns or len(df) < 30:
            return None
        df = df.dropna(subset=["Close"]).sort_values("Date")
        out = (pd.to_datetime(df["Date"]).to_numpy(), df["Close"].to_numpy(dtype=float))
    except Exception:  # noqa: BLE001 - 讀檔/解析任何問題一律當「沒有真資料」→ 不畫
        return None
    _REAL_CACHE[ticker] = out
    return out


class Ctx:
    """畫圖上下文。real=(ticker, dates, close) 或 None(沒有真資料)。
    reveal=漸進揭露比例 0<r<=1:1.0=畫完整資料(等同舊行為),<1.0=只畫到資料的前 r 比例
    (「講到哪個數字就畫到哪」)。② 子段切分靠這個把一段 130s 的靜態卡拆成多張漸進圖。"""

    __slots__ = ("rng", "direction", "real", "text", "reveal")

    def __init__(self, rng, direction, real, text, reveal=1.0):
        self.rng = rng
        self.direction = direction
        self.real = real
        self.text = text
        self.reveal = reveal


def _reveal_k(n: int, reveal: float, minpts: int) -> int:
    """把「揭露比例 reveal」換算成「畫前 k 個資料點」。
    reveal>=1.0 → k=n(完整,與舊行為 byte-identical);<1.0 → k=前 r 比例,但不少於 minpts、不多於 n。
    minpts 是這張圖「有意義」的最少點數(如 dca 至少要幾個月、drawdown 要夠算峰谷)。"""
    if reveal >= 1.0:
        return n
    return max(min(minpts, n), min(n, int(round(n * reveal))))


def _maybe_log_y(ax, series) -> str:
    """漲幅太大就改對數座標;回傳要接在圖說後面的註記(沒改回空字串)。

    ## 為什麼(2026-08-03 實測)
    旺矽 6223 的體檢片,「最大回撤 -81.7%」發生在 2008 年。但這檔 18 年漲了 116 倍,
    在線性座標上 2008 年的價位貼著 x 軸——**那個 -81.7% 的崩跌在圖上完全看不見**,
    紅色「-81.7%」標註旁邊是一片空白,整張圖就是「一條平線 + 末端爆衝」。
    圖在數學上完全正確,但傳達不出它要講的那件事。

    本頻道長片幾乎都是「存 N 年」這種跨十幾二十年的題目,線性座標會把前面 80% 的歷史
    壓成一條線。倍數超過 _LOG_RATIO 就改對數,早年的波動才看得見。

    誠信:對數座標會讓漲幅在視覺上變溫和,不標示等於誤導 → 一律在圖說標「對數座標」。"""
    try:
        lo, hi = float(np.nanmin(series)), float(np.nanmax(series))
    except Exception:  # noqa: BLE001
        return ""
    if lo <= 0 or hi / lo < _LOG_RATIO:
        return ""
    ax.set_yscale("log")
    # set_yscale 會自己把 y 刻度加回來(外層本來 set_yticks([]) 關掉了),預設是 10¹/10² 這種
    # 科學記號。本頻道受眾是新手(見 memory yt-beginner-repositioning),科學記號等於看不懂,
    # 改成一般數字並調暗,只當背景參考。
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _p: (f"{v:,.0f}" if v >= 1 else f"{v:g}")))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda *_a: ""))
    ax.tick_params(axis="y", colors=MUTED, labelsize=15, length=0)
    return "（縱軸為對數座標）"


def _year_ticks(ax, dates, n_max=6):
    """真實年份刻度 —— 有座標軸才能證明這是真資料(舊的裝飾圖 set_xticks([]) 全空)。
    刻度標籤上色,否則預設黑字在深色底上看不見。"""
    import pandas as pd
    yrs = pd.DatetimeIndex(dates).year.to_numpy()
    uniq = sorted(set(yrs.tolist()))
    step = max(1, len(uniq) // n_max)
    picks = uniq[::step]
    ax.set_xticks([int((yrs == y).argmax()) for y in picks])
    ax.set_xticklabels([str(y) for y in picks])
    ax.tick_params(axis="x", colors=MUTED, labelsize=16, length=0)


def classify(text: str) -> Optional[str]:
    """依關鍵字判斷主題；回傳概念 key 或 None。順序＝優先序（越專一越前面）。"""
    t = (text or "").lower()
    # 順序＝優先序：越專一、越不會被順口提及的主題排越前面，
    # 通用詞（波動/回測/虧損…）排後面，避免把真正主題搶走。
    rules = [
        ("martingale", ("馬丁", "凹單", "加碼攤平", "翻倍下注", "輸了加倍", "馬丁格爾")),
        # ⚠️ 2026-07-17 移除 "overfit"：見下方 _overfit 拆除說明(與 _backtest 同物種,
        #    rng 亂數冒充樣本內外驗證)。「過擬合/過度最佳化」現在不對應任何卡 → 不畫。
        ("compound", ("複利", "72法則", "72 法則", "利滾利", "錢滾錢", "本金翻倍")),
        ("dca", ("定投", "定期定額", "dca", "分批買", "攤平成本", "平均成本", "無腦買", "買在高點", "微笑曲線")),
        ("grid", ("網格", "格子單", "高賣低買", "低買高賣", "等差", "等比", "上下限", "區間來回", "震盪行情")),
        # ⚠️ 2026-07-17 移除 "winrate"(硬寫 42/58 假統計)、"sharpe"(rng 亂數線冒充夏普):
        #    見各自拆除說明。「勝率/盈虧比/夏普」現在不對應任何卡 → 不畫。
        # ⚠️ 2026-07-17 移除 ("backtest", ("樣本外","樣本內","回測","out of sample","驗證期"))：
        #    見下方 _backtest 拆除說明。**不要因為「回測」是本頻道高頻詞就把它接回來**——
        #    那正是它中毒最深的原因(每支長片都講回測 → 每支都被畫上我們沒做過的樣本外驗證)。
        #    「回測」現在不對應任何概念卡 → classify 回 None → 不畫卡(fail-safe:寧可少一個
        #    視覺元素,也不要編一個我們沒做過的實驗)。
        ("drawdown", ("最大回撤", "回撤", "drawdown", "套牢", "腰斬", "歸零", "回吐")),
        ("trend", ("單邊行情", "單邊", "趨勢盤", "一路噴", "急漲", "急跌", "破底", "噴出")),
    ]
    for key, kws in rules:
        for kw in kws:
            if kw.lower() in t:
                return key
    return None


# 正負向關鍵字：用來把「隨機漫步線」的走勢方向跟旁白綁定（A6-a）。
# 分兩層：先看「結果／損益」詞（虧損/獲利…精準對應錢有沒有變多），這層有訊號就直接採用；
# 沒訊號才退而看「價格動作」詞（漲/跌/暴漲…）。這樣「比特幣暴漲後追高，結果虧損23%」
# 這種「market 漲、但你的錢賠」的敘事，才不會被 4 個「漲」蓋過 2 個「虧損」判成上漲圖。
_NEG_OUTCOME_WORDS = (
    "虧損", "虧錢", "賠錢", "賠了", "倒賠", "慘賠", "套牢", "腰斬", "歸零",
    "爆倉", "踩雷", "踏空", "回吐", "虧", "賠",
)
_POS_OUTCOME_WORDS = ("賺錢", "獲利", "大賺", "翻倍", "倍增", "賺翻", "回本", "賺")
_NEG_PRICE_WORDS = ("暴跌", "崩跌", "崩盤", "下殺", "破底", "跌破", "跌深", "重摔", "拉回", "回檔", "跌")
_POS_PRICE_WORDS = ("飆漲", "大漲", "暴漲", "噴出", "新高", "漲")


def _direction(text: str) -> int:
    """粗判整段文字的漲跌方向：-1＝跌/虧、+1＝漲/賺、0＝中性(找不到明顯訊號或打平)。
    優先看損益結果詞，抓不到訊號才退看價格動作詞（見上方註解）。"""
    t = text or ""
    neg1 = sum(t.count(w) for w in _NEG_OUTCOME_WORDS)
    pos1 = sum(t.count(w) for w in _POS_OUTCOME_WORDS)
    if neg1 != pos1:
        return -1 if neg1 > pos1 else 1
    neg2 = sum(t.count(w) for w in _NEG_PRICE_WORDS)
    pos2 = sum(t.count(w) for w in _POS_PRICE_WORDS)
    if neg2 == pos2:
        return 0
    return -1 if neg2 > pos2 else 1


# --------------------------------------------------------------------------- #
# 各主題畫法（在 ax 上作畫，座標自定，外觀統一在 _new_ax / _finish 處理）
# --------------------------------------------------------------------------- #

def _grid(ax, ctx):
    """網格交易【機制示意圖】—— 確定性,零 rng。

    這不是「某檔的真實走勢」,而是「網格策略怎麼運作」的教學圖(像複利/馬丁那兩張數學圖)。
    用確定性阻尼正弦波畫一個箱型震盪 —— 正弦波一看就是示意、不會被誤認成真實行情,
    且完全確定性(不再 `rng.randn()` 假造價格序列)。真實市場走勢一律走 dca/trend/candle
    /drawdown 那四張真資料圖。"""
    n = 220
    x = np.arange(n)
    # 確定性阻尼正弦:三個頻率疊加,在固定箱型內來回,不 rng
    lo_b, hi_b, mid = 94.0, 106.0, 100.0
    t = x / n
    price = mid + 5.2 * np.sin(2 * np.pi * 3.0 * t) + 1.6 * np.sin(2 * np.pi * 7.0 * t + 0.9)
    price = np.clip(price, lo_b + 0.3, hi_b - 0.3)
    levels = np.linspace(95, 105, 6)
    for lv in levels:
        ax.axhline(lv, color=(1, 1, 1, 0.13), lw=1, zorder=1)
    # 上下界（網格範圍）較亮
    ax.axhline(hi_b, color=(*RED, 0.5), lw=1.4, ls="--", zorder=2)
    ax.axhline(lo_b, color=(*GREEN, 0.5), lw=1.4, ls="--", zorder=2)
    # 漸進揭露:價格線由左至右長出來(reveal=1.0→全部,byte-identical);超出已揭露處的買賣點不畫。
    k = _reveal_k(n, ctx.reveal, minpts=12)
    ax.plot(x[:k], price[:k], color=FG, lw=2.2, zorder=3)
    # 觸網買賣點：跌破網格線→買(綠)，漲破→賣(紅)。
    # 蒐集所有觸網點後做稀疏化（去掉太靠近的、總量上限），避免畫面太雜。
    pts = []
    for lv in levels:
        for c in np.where(np.diff(np.sign(price - lv)))[0]:
            pts.append((int(x[c]), float(lv), bool(price[c + 1] > price[c])))
    pts.sort()
    kept = []
    for px_, lv, up in pts:
        if kept and px_ - kept[-1][0] < 9:  # 太靠近就略過
            continue
        kept.append((px_, lv, up))
    if len(kept) > 14:  # 總量上限，等距取樣
        step = len(kept) / 14.0
        kept = [kept[int(i * step)] for i in range(14)]
    for px_, lv, up in kept:
        if px_ >= k:            # 只畫已揭露範圍內的觸網點
            continue
        ax.scatter([px_], [lv], s=72, zorder=4,
                   color=RED if up else GREEN, edgecolors="white", linewidths=0.7)
    ax.set_xlim(0, n - 1)
    ax.set_ylim(lo_b - 2, hi_b + 2)
    return "區間來回．低買高賣", ("● 低買", GREEN, "● 高賣", RED)


def _dca(ax, ctx):
    """真實定期定額:用該檔真實日收盤,每月第一個交易日買進,畫真實平均成本線。
    沒有真資料(抓不到有 CSV 的代號)→ 回 None → 不畫圖。"""
    if not ctx.real:
        return None
    ticker, dates, px = ctx.real
    import pandas as pd
    # 漸進揭露:只畫真實資料的前 k 個交易日(講到哪一年就畫到哪一年)。reveal=1.0→k=全部(等同舊行為)。
    k = _reveal_k(len(px), ctx.reveal, minpts=60)   # 至少 ~3 個月才畫得出定投均線
    px, dates = px[:k], dates[:k]
    di = pd.DatetimeIndex(dates)
    # 每月第一個交易日的索引 = 真實扣款日
    first = pd.Series(np.arange(len(di)), index=di).groupby([di.year, di.month]).first().to_numpy()
    if len(first) < 2:
        return None                              # 揭露太少、湊不出兩個扣款日 → 不畫(退卡)
    units = np.cumsum(1.0 / px[first])          # 每期投入 1 單位金額
    avg_cost = np.cumsum(np.ones(len(first))) / units   # 真實平均成本
    ax.plot(np.arange(len(px)), px, color=FG, lw=2.0, zorder=3)
    ax.scatter(first, px[first], s=18, color=GREEN, edgecolors="none", zorder=4)
    ax.step(first, avg_cost, where="post", color="#ffd23f", lw=2.2, zorder=5)
    ax.set_xlim(0, len(px) - 1)
    # 定投圖同樣要對數(見 _maybe_log_y):線性座標下橘色平均成本線會整條貼在底部,
    # 「成本被拉高/壓低」這件事——也就是這張圖唯一要講的事——完全看不出來。
    _note = _maybe_log_y(ax, px)
    _year_ticks(ax, dates)
    ret = (units[-1] * px[-1]) / len(first) - 1.0
    return (f"{ticker} 每月定投．實際平均成本 {avg_cost[-1]:.1f} 元(總報酬 {ret*100:+.0f}%){_note}",
            ("● 每月買進", GREEN, "— 實際平均成本", (1, 0.82, 0.25)))


def _compound(ax, ctx):
    """複利 vs 單利【機制示意圖】—— 確定性數學,零 rng,不宣稱任何真實標的。"""
    n = 120
    x = np.linspace(0, n, n)
    comp = 100 * (1.022) ** (x / 3)
    lin = 100 + (comp[-1] - 100) * (x / n) * 0.42
    # 漸進揭露:曲線由左至右長出來(reveal=1.0→全部,byte-identical)。軸固定在完整範圍,揭露時不跳。
    k = _reveal_k(n, ctx.reveal, minpts=8)
    ax.plot(x[:k], lin[:k], color=MUTED, lw=2.0, ls="--", zorder=2)
    ax.plot(x[:k], comp[:k], color=GREEN, lw=2.8, zorder=3)
    ax.fill_between(x[:k], lin[:k], comp[:k], color=GREEN, alpha=0.12, zorder=1)
    ax.set_xlim(0, n)
    ax.set_ylim(80, comp[-1] * 1.05)
    return "複利．時間越久越陡", ("— 複利", GREEN, "-- 單利", MUTED)


def _drawdown(ax, ctx):
    """真實最大回撤:直接從該檔真實收盤算 peak→trough,標真實日期與跌幅。
    沒有真資料 → 不畫(舊版是 rng 亂數 equity curve 卻標「最大回撤」,等於編一個沒發生的崩跌)。"""
    if not ctx.real:
        return None
    ticker, dates, eq = ctx.real
    import pandas as pd
    # 漸進揭露:只看真實資料的前 k 天,標「到目前為止」的真實最大回撤(峰谷都在已揭露範圍內)。
    k = _reveal_k(len(eq), ctx.reveal, minpts=40)
    eq, dates = eq[:k], dates[:k]
    x = np.arange(len(eq))
    run_max = np.maximum.accumulate(eq)
    dd = eq / run_max - 1.0
    trough = int(np.argmin(dd))
    peak = int(np.argmax(eq[: trough + 1])) if trough > 0 else 0
    ax.plot(x, eq, color=FG, lw=2.0, zorder=3)
    ax.fill_between(x[peak:trough + 1], eq[peak:trough + 1], run_max[peak:trough + 1],
                    color=RED, alpha=0.28, zorder=2)
    ax.scatter([peak, trough], [eq[peak], eq[trough]], s=52, color=RED,
               edgecolors="white", linewidths=0.6, zorder=4)
    d0 = pd.Timestamp(dates[peak]).date()
    d1 = pd.Timestamp(dates[trough]).date()
    # 🔴 2026-07-28 可讀性:最大回撤這個數字**就是這張圖的主角**,原本 fontsize=16 在 1080p 上
    # 只有 ~21px,手機上根本看不見。放大到 34 並加深色描邊(圖線可能穿過它),讓它一眼可讀。
    # 標註**一律放谷底上方**:谷底依定義是這段的最低點,上方必然有空間(而且正是回撤陰影區,
    # 配深色描邊很好讀);往下放則會壓到年份刻度——第一版依相對高度決定上下,實測仍有兩張中招
    # (視窗不同時谷底相對位置會變),索性拿掉這個判斷,永遠往上,行為可預測。
    ax.annotate(f"{dd[trough]*100:.1f}%", xy=(trough, eq[trough]), xytext=(0, 52),
                textcoords="offset points", ha="center", va="bottom", color=RED,
                fontsize=34, fontweight="bold",
                path_effects=[_pe.withStroke(linewidth=4, foreground=BG)], zorder=6)
    ax.set_xlim(0, len(eq) - 1)
    # 對數座標要在畫完之後設(fill_between 已經吃過線性座標的數值,設 yscale 只影響呈現)。
    note = _maybe_log_y(ax, eq)
    _year_ticks(ax, dates)
    return f"{ticker} 實際最大回撤 {dd[trough]*100:.1f}%({d0} → {d1}){note}", None


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 _sharpe / _winrate 已於 2026-07-17 拆除(誠信)——不要重建。
#
# _sharpe:畫兩條 `rng.randn()` 隨機漫步,標「高夏普 / 低夏普」。夏普是**算出來的數字**,
#   不是畫出來的形狀 —— 這張圖等於宣稱「我們算了這兩個策略的夏普」,而那兩條線是亂數。
#   ⚠️ 若要復活:必須拿兩檔**真實**標的算真實夏普(tw_facts_computed.json 就有真值),
#      不是畫兩條抖動幅度不同的亂數線。
#
# _winrate:硬寫 `vals = [42, 58]` 當「賺的單/賠的單」比例 —— 這是**編造的統計數字**,
#   和昨晚抓到的「毛利率選股勝率31%」同一物種(見 memory yt-integrity-fabricated-stats-fix)。
#   沒有任何回測產出過 42/58,它純粹是為了畫面好看填的。
#
# 兩者拆除後 classify 不再回這兩個 key → 該段不畫概念圖(fail-safe)。
# ─────────────────────────────────────────────────────────────────────────────


def _martingale(ax, ctx):
    """馬丁格爾加倍下注【機制示意圖】—— 確定性數學(2^n),零 rng,不宣稱真實交易紀錄。"""
    n = 9
    x = np.arange(n)
    bet = 2.0 ** x
    # 漸進揭露:加碼長條一根根疊上去(reveal=1.0→全部,byte-identical);「爆倉歸零」註解等最後一根出現才標。
    kb = _reveal_k(n, ctx.reveal, minpts=2)
    ax.bar(x[:kb], bet[:kb], color=RED, width=0.6, zorder=3, edgecolor="white", linewidth=0.5)
    if kb >= n:
        ax.annotate("一次爆倉\n全部歸零", xy=(n - 1, bet[-1]), xytext=(n - 3.2, bet[-1] * 0.9),
                    ha="center", color=RED, fontsize=15,
                    arrowprops=dict(arrowstyle="->", color=RED, lw=1.6))
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_ylim(0, bet[-1] * 1.18)
    return "輸了就加倍．遲早一次清光", None


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 _overfit 已於 2026-07-17 拆除(誠信)——不要重建。
#
# **它和 _backtest 是同一物種,昨晚只拆了 _backtest,漏了這支。**
# 它畫一條 rng 亂數 equity curve,用 axvline 切成「樣本內 | 樣本外」,綠線轉紅,
# 字卡寫「回測完美．實盤打回原形」。三個致命點與 _backtest 完全一致:
#   1. **我們根本沒有樣本外驗證**(tw_facts_engine 全是全期間/近10年/固定崩盤區間,
#      沒有任何一組做樣本內外切分)→ 這張圖在宣稱**一個我們沒有的嚴謹度**。
#   2. 兩段曲線都是 `rng.randn()` 亂數 —— 純虛構。
#   3. classify 的 "overfit" 命中詞含「過擬合/過度最佳化/曲線擬合」,而「拆穿過度擬合」
#      正是本頻道避雷片的高頻主題 → 它會在**講別人造假的那支片裡**替我們造假。
#
# 判準同 _backtest(2026-07-17 定):方向是「自我設限」還是「膨脹」?宣稱一個沒有的
# 嚴謹度 = 膨脹 = 紅線。
# ⚠️ 若將來真的做了樣本內外切分:要畫的是**真實回測結果**(從事實庫讀),不是亂數。
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 _backtest 已於 2026-07-17 拆除(誠信)——不要重建。
#
# 它畫「回測期 | 驗證期」split-chart，字卡寫「真正能信的是樣本外」。三個致命點：
#   1. **我們根本沒有樣本外驗證**。tw_facts_engine 全部是全期間/近10年/固定崩盤區間的
#      回測，沒有任何一組做樣本內外切分。這張圖宣稱的是**一個我們沒有的嚴謹度**。
#   2. 曲線是 `rng.randn()` 亂數、漲跌方向 `rng.rand() > 0.5` 擲骰 —— 純虛構。
#   3. 它還被 render_ffmpeg 強制插進**每一支長片**(見該檔「強制回測對比 beat」拆除說明)，
#      所以這個宣稱是全頻道規模的，不是單片失誤。
#
# 判準(2026-07-17 定):**方向是「自我設限」還是「膨脹」?** 誠實揭露限制(如「我的回測
# 沒算手續費」)最壞只是低報自己 → 安全;宣稱一個沒有的嚴謹度 → 膨脹 → 紅線。
# 與已拆除的「賽跑條」同 species:**不是圖畫得不準,是圖在替我們宣稱沒做過的事**。
#
# ⚠️ 若將來 tw_facts_engine 真的做了樣本內外切分:也**不可**復活這支——那時要畫的是
#    **真實回測結果**(從事實庫 data 讀),不是 rng 亂數。亂數圖沒有任何情況下是對的。
# ─────────────────────────────────────────────────────────────────────────────


def _trend(ax, ctx):
    """真實單邊行情:從該檔真資料中,挑一段**方向與旁白一致**的真實區間放大。

    舊版用 rng 亂數畫,方向靠擲骰 → 抓到過「圖在跌、旁白在講漲 1050%」。
    現在改成:旁白說漲就去真資料裡找真實的漲段;找不到符合方向的真實區間 → **不畫**
    (不會為了配合旁白而捏一段行情出來)。
    """
    if not ctx.real:
        return None
    ticker, dates, px = ctx.real
    import pandas as pd
    # 漸進揭露:只在真實資料的前 k 天裡挑符合旁白方向的真實區間(不會揭露到未來)。
    k = _reveal_k(len(px), ctx.reveal, minpts=140)
    px, dates = px[:k], dates[:k]
    win = max(60, len(px) // 12)          # 取約一年的窗
    if len(px) < win * 2:
        return None
    # 掃所有窗,算報酬;依旁白方向挑「最強的真實漲段/跌段」
    starts = np.arange(0, len(px) - win, max(1, win // 4))
    rets = np.array([px[s + win - 1] / px[s] - 1.0 for s in starts])
    want_up = ctx.direction > 0
    if ctx.direction == 0:
        # 🔴 2026-07-28:旁白沒有明確方向時,舊碼直接不畫 → 實測一支 0050 長片 **9 段有 5 段全空白**。
        # 但「不知道該挑哪一段」不等於「什麼都不能畫」:改成畫**完整的真實走勢**——不挑區間、
        # 不做任何方向宣稱,就是把這檔的真實歷史攤開。誠信上比挑一段更保守(挑區間才是有立場的),
        # 畫面上則從空白變成有內容。原本的「不猜方向」精神保留:只是把它從「不畫」改成「不挑」。
        ax.plot(np.arange(len(px)), px, color=FG, lw=2.2, zorder=3)
        ax.fill_between(np.arange(len(px)), float(np.min(px)) * 0.98, px,
                        color=FG, alpha=0.07, zorder=1)
        ax.set_xlim(0, len(px) - 1)
        _note = _maybe_log_y(ax, px)
        _year_ticks(ax, dates)
        _r = px[-1] / px[0] - 1.0
        _d0 = pd.Timestamp(dates[0]).date()
        _d1 = pd.Timestamp(dates[-1]).date()
        return f"{ticker} 實際走勢 {_d0} → {_d1}({_r*100:+.1f}%){_note}", None
    cand = rets > 0 if want_up else rets < 0
    if not cand.any():
        # 同上:真資料裡找不到符合旁白方向的區間 → 不強行挑,改畫完整真實走勢(不做方向宣稱)
        ax.plot(np.arange(len(px)), px, color=FG, lw=2.2, zorder=3)
        ax.fill_between(np.arange(len(px)), float(np.min(px)) * 0.98, px,
                        color=FG, alpha=0.07, zorder=1)
        ax.set_xlim(0, len(px) - 1)
        _note = _maybe_log_y(ax, px)
        _year_ticks(ax, dates)
        _r = px[-1] / px[0] - 1.0
        return (f"{ticker} 實際走勢 {pd.Timestamp(dates[0]).date()} → "
                f"{pd.Timestamp(dates[-1]).date()}({_r*100:+.1f}%){_note}"), None
    idx = int(starts[np.argmax(rets)] if want_up else starts[np.argmin(rets)])
    seg = px[idx:idx + win]
    col = GREEN if want_up else RED
    ax.plot(np.arange(len(seg)), seg, color=col, lw=2.6, zorder=3)
    ax.fill_between(np.arange(len(seg)), seg.min() * 0.98, seg, color=col, alpha=0.10, zorder=1)
    ax.set_xlim(0, len(seg) - 1)
    _year_ticks(ax, dates[idx:idx + win], n_max=3)
    r = seg[-1] / seg[0] - 1.0
    d0 = pd.Timestamp(dates[idx]).date()
    d1 = pd.Timestamp(dates[idx + win - 1]).date()
    return f"{ticker} 實際走勢 {d0} → {d1}({r*100:+.1f}%)", None


def _candles(ax, ctx):
    """真實 K 線:用該檔真實日收盤合成的週線 OHLC(開=區間首日收、收=末日收、高低=區間極值)。
    沒有真資料 → 不畫(舊版是 rng 隨機漫步蠟燭,純虛構)。"""
    if not ctx.real:
        return None
    ticker, dates, px = ctx.real
    import pandas as pd
    tail = px[-260:] if len(px) >= 260 else px   # 近一年
    dts = dates[-len(tail):]
    grp = max(3, len(tail) // 46)                # 併成 ~46 根
    bars = []
    for i in range(0, len(tail) - grp + 1, grp):
        w = tail[i:i + grp]
        bars.append((w[0], w.max(), w.min(), w[-1]))
    # 漸進揭露:由左至右逐根顯示 K 棒(reveal=1.0→全部,byte-identical)。
    kb = _reveal_k(len(bars), ctx.reveal, minpts=6)
    bars = bars[:kb]
    for i, (op, hi, lo, cl) in enumerate(bars):
        up = cl >= op
        col = GREEN if up else RED
        ax.plot([i, i], [lo, hi], color=col, lw=1.2, zorder=2)
        ax.add_patch(Rectangle((i - 0.32, min(op, cl)), 0.64, max(abs(cl - op), 0.01),
                               color=col, zorder=3))
    ax.set_xlim(-1, len(bars))
    d0 = pd.Timestamp(dts[0]).date()
    _last = len(dts) - 1 if ctx.reveal >= 1.0 else min(len(dts) - 1, kb * grp - 1)
    d1 = pd.Timestamp(dts[_last]).date()
    return f"{ticker} 實際 K 線({d0} → {d1})", None


# ─────────────────────────────────────────────────────────────────────────────
# 個股體檢專用的兩張真財報圖(2026-08-03)
#
# 為什麼加:實測一支 9 分 08 秒的體檢長片,**整片視覺只有 5 張不同畫面,其中一張佔 67%**
# (從 15s 一路播到 540s)。根因是段落標題「公司是誰／基本面資料／價格體檢／估值位置」
# 四段 classify() 全部回 None → 全部退回整片共用的同一張圖。
# 體檢片的段落是固定模板,靠關鍵字猜本來就猜不到;而真正該畫的東西(財報、估值)
# 以前根本沒有對應的圖。
#
# ⚠️ 這兩個 key **故意不加進 classify() 的關鍵字表**——只能由呼叫端明確指定(force)。
# 「營收/毛利/本益比」是本頻道的高頻詞,一旦進了關鍵字表,任何片只要順口提到就會被
# 畫上別檔公司的財報圖(和 _backtest 當年中毒的路徑一模一樣,見上方拆除說明)。
#
# 資料一律取自 STUDIO/stock_checkup_facts.json 的真實事實,零 rng;取不到 → 回 None 不畫。
# ─────────────────────────────────────────────────────────────────────────────
_CHECKUP_FACTS: Optional[dict] = None


def _checkup_facts() -> dict:
    """讀個股體檢事實庫(整支 process 只讀一次)。讀不到回 {},呼叫端據此不畫。"""
    global _CHECKUP_FACTS
    if _CHECKUP_FACTS is None:
        p = Path(__file__).resolve().parent.parent / "STUDIO" / "stock_checkup_facts.json"
        try:
            _CHECKUP_FACTS = (json.loads(p.read_text(encoding="utf-8")) or {}).get("results") or {}
        except Exception:  # noqa: BLE001
            _CHECKUP_FACTS = {}
    return _CHECKUP_FACTS


def _fact_for(ctx, slug: str) -> Optional[dict]:
    """拿這一段所屬標的的某組體檢事實的 data;沒有真價格資料(認不出標的)就回 None。"""
    if not ctx.real:
        return None
    code = ctx.real[0]
    f = _checkup_facts().get(f"checkup_{slug}__{code}")
    return (f or {}).get("data") if isinstance(f, dict) else None


def _history(ax, ctx):
    """完整真實走勢——**不挑區間、不做方向宣稱**,就是把這檔的一生攤開。

    為什麼要跟 _trend 分開:_trend 會去掃「最強的真實漲段」放大(那是為了配合旁白說
    「一路噴」的段落)。但個股體檢的「公司是誰」段講的是產業,拿最漂亮的一段窗口當門面
    ——實測旺矽被挑出 2024-11→2026-06 的 +634%——對一個以誠實避雷定位的頻道是反效果,
    而且和旁白內容無關。這張圖只呈現完整歷史,沒有挑選,也就沒有立場。"""
    if not ctx.real:
        return None
    ticker, dates, px = ctx.real
    import pandas as pd
    k = _reveal_k(len(px), ctx.reveal, minpts=140)
    px, dates = px[:k], dates[:k]
    if len(px) < 60:
        return None
    x = np.arange(len(px))
    ax.plot(x, px, color=FG, lw=2.2, zorder=3)
    ax.fill_between(x, float(np.min(px)) * 0.98, px, color=FG, alpha=0.07, zorder=1)
    ax.set_xlim(0, len(px) - 1)
    note = _maybe_log_y(ax, px)
    _year_ticks(ax, dates)
    r = px[-1] / px[0] - 1.0
    d0, d1 = pd.Timestamp(dates[0]).date(), pd.Timestamp(dates[-1]).date()
    return f"{ticker} 完整真實走勢 {d0} → {d1}（{r*100:+.0f}%）{note}", None


def _fundamentals(ax, ctx):
    """年度營收長條 + 年度EPS折線(雙軸),全部取自真實財報事實,零 rng。"""
    rev = _fact_for(ctx, "revenue_trend") or {}
    eps = _fact_for(ctx, "eps_trend") or {}
    rs = [r for r in (rev.get("series") or []) if r.get("revenue")]
    es = [e for e in (eps.get("series") or []) if e.get("eps") is not None]
    if len(rs) < 2 and len(es) < 2:
        return None
    code = ctx.real[0]
    base = rs if len(rs) >= len(es) else es
    k = _reveal_k(len(base), ctx.reveal, minpts=2)
    rs, es = rs[:k], es[:k]

    cap = []
    if len(rs) >= 2:
        yrs = [r["year"] for r in rs]
        vals = [r["revenue"] / 1e8 for r in rs]          # 元 → 億元
        ax.bar(yrs, vals, color=GREEN, alpha=0.55, width=0.62, zorder=2)
        ax.annotate(f"{vals[-1]:,.0f}億", xy=(yrs[-1], vals[-1]), xytext=(0, 10),
                    textcoords="offset points", ha="center", va="bottom", color=GREEN,
                    fontsize=30, fontweight="bold",
                    path_effects=[_pe.withStroke(linewidth=4, foreground=BG)], zorder=6)
        # 刻度最多 6 個。圖說畫在軸下方僅約 43px 處(那個位置是為了避開字幕框算出來的,
        # 不能動),年份標籤太密就會被圖說壓住——實測 10 根柱每根都標,2019~2021 直接糊成一團。
        step = max(1, -(-len(yrs) // 6))     # 無條件進位:10 年 → step 2 → 5 個標籤(整除會算成 1)
        picks = yrs[::step]
        ax.set_xticks(picks)
        ax.set_xticklabels([str(y) for y in picks])
        ax.tick_params(axis="x", colors=MUTED, labelsize=16, length=0)
        ax.tick_params(axis="y", colors=(1, 1, 1, 0.0))
        cap.append(f"年度營收 {yrs[0]}→{yrs[-1]}")
    if len(es) >= 2:
        ax2 = ax.twinx()
        ax2.set_facecolor(BG)
        for s in ax2.spines.values():
            s.set_visible(False)
        ax2.set_yticks([])
        ey = [e["year"] for e in es]
        ev = [e["eps"] for e in es]
        ax2.plot(ey, ev, color=RED, lw=2.6, marker="o", ms=7,
                 markeredgecolor="white", markeredgewidth=0.6, zorder=5)
        # 2026-08-12 抽幀抓到:EPS 末點在低檔時,固定 -34pt 的下方標籤會壓到 x 軸年份
        # 與圖說(訊芯-KY 那張「EPS 0.40元」直接疊在圖說上)。末點在軸下半 → 標籤改放上方。
        _lo2, _hi2 = ax2.get_ylim()
        _above = (ev[-1] - _lo2) < (_hi2 - _lo2) * 0.45 if _hi2 > _lo2 else False
        ax2.annotate(f"EPS {ev[-1]:.2f}元", xy=(ey[-1], ev[-1]),
                     xytext=(0, 12 if _above else -34),
                     textcoords="offset points", ha="center",
                     va="bottom" if _above else "top", color=RED,
                     fontsize=28, fontweight="bold",
                     path_effects=[_pe.withStroke(linewidth=4, foreground=BG)], zorder=6)
        cap.append(f"年度EPS {ey[0]}→{ey[-1]}")
    # 圖說要短。它和年份刻度只差 ~43px,長句子橫向鋪開就會蓋掉刻度(實測整行壓在 2019~2021 上)。
    span = f"{rs[0]['year']}→{rs[-1]['year']}" if len(rs) >= 2 else f"{es[0]['year']}→{es[-1]['year']}"
    return f"{code} 真實財報 {span}：綠柱=營收／紅線=EPS", None


def _valuation(ax, ctx):
    """本益比在自身歷史區間的位置:畫 P25~P75 區間帶 + 中位數 + 目前值,只陳述位置。"""
    d = _fact_for(ctx, "valuation_position") or {}
    p25, p50, p75 = d.get("p25"), d.get("median"), d.get("p75")
    cur, rank = d.get("latest_per"), d.get("percentile_rank")
    if None in (p25, p50, p75, cur, rank):
        return None
    code = ctx.real[0]
    lo = min(p25, cur) * 0.85
    hi = max(p75, cur) * 1.12
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 1)
    ax.axhspan(0.36, 0.64, xmin=(p25 - lo) / (hi - lo), xmax=(p75 - lo) / (hi - lo),
               color=FG, alpha=0.16, zorder=2)
    ax.plot([p50, p50], [0.30, 0.70], color=FG, lw=2.4, zorder=4)
    for v, lab in ((p25, f"P25 {p25:.0f}"), (p50, f"中位數 {p50:.0f}"), (p75, f"P75 {p75:.0f}")):
        ax.annotate(lab, xy=(v, 0.24), ha="center", va="top", color=FG, fontsize=16, zorder=5)
    # 漸進揭露:區間先出現,目前值最後才落點(reveal=1.0 時與舊行為一致)。
    if ctx.reveal >= 0.55:
        colr = RED if rank >= 50 else GREEN
        ax.scatter([cur], [0.5], s=340, color=colr, edgecolors="white",
                   linewidths=1.2, zorder=6)
        ax.annotate(f"目前 {cur:.0f} 倍", xy=(cur, 0.5), xytext=(0, 46),
                    textcoords="offset points", ha="center", va="bottom", color=colr,
                    fontsize=32, fontweight="bold",
                    path_effects=[_pe.withStroke(linewidth=4, foreground=BG)], zorder=7)
        ax.annotate(f"落在自身歷史第 {rank:.0f} 百分位", xy=(cur, 0.5), xytext=(0, -46),
                    textcoords="offset points", ha="center", va="top", color=FG,
                    fontsize=19, zorder=7)
    ax.set_xticks([])
    ax.grid(False)
    yrs = d.get("years") or "?"
    return f"{code} 本益比 vs 自身近{yrs}年區間（只陳述位置）", None


_DISPATCH = {
    # 真資料圖(拿不到真 CSV → drawer 回 None → 不畫):
    "dca": _dca, "drawdown": _drawdown, "trend": _trend, "candle": _candles,
    # 個股體檢真財報圖(只能 force 指定,沒有 classify 關鍵字——見上方說明):
    "fundamentals": _fundamentals, "valuation": _valuation, "history": _history,
    # 機制示意圖(確定性數學/幾何,不宣稱真實市場史,零 rng):
    "grid": _grid, "compound": _compound, "martingale": _martingale,
    # 已拆除(2026-07-17,誠信):backtest / overfit(rng 假樣本外)、sharpe(rng 假夏普)、
    # winrate(硬寫 42/58 假統計)。見各自拆除說明,不要接回來。
}


def _font_setup():
    # 讓中文 annotation 不變豆腐：先把 Linux Noto CJK 註冊進 matplotlib，再挑「真正可用」的字型
    import os
    import matplotlib.font_manager as fm
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
        try:
            if os.path.exists(p):
                fm.fontManager.addfont(p)
        except Exception:
            pass
    avail = {f.name for f in fm.fontManager.ttflist}
    prefer = ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans CJK SC",
              "Noto Sans CJK JP", "Microsoft YaHei", "SimHei", "PingFang TC"]
    chosen = [c for c in prefer if c in avail] or prefer
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = chosen + ["DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def render_concept_chart(width: int, height: int, text: str, accent, seed: str,
                         dest=None, force: Optional[str] = None,
                         fallback_ticker: Optional[str] = None, reveal: float = 1.0,
                         variant: int = 0, meta: Optional[dict] = None):
    """回傳滿版深色底 + 置中數據圖的 PIL.Image(RGB)；判不到主題回 None。

    圖只佔畫面中段（約 18%~76% 高），上方留給大標題、下方留給字幕。
    accent 目前用於未來擴充；配色已內建紅綠主題。
    fallback_ticker：整片主題代號(如整支片講 0050)。當「這一段」文字沒點名代號、但整片有,
        就用整片代號畫真資料 —— 一支 0050 的片每段都能畫真 0050 圖,而不是半數退文字卡。
        仍要求那代號在 tw_facts_cache 有真 CSV;沒有就退 None(不畫)。
    """
    from PIL import Image

    key = force or classify(text)
    if key is None:
        return None
    drawer = _DISPATCH.get(key)
    if drawer is None:
        return None

    _font_setup()
    rng = _seeded_rng(seed + key)

    dpi = 100
    fig_w, fig_h = width / dpi, height / dpi
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor(BG)

    # 圖軸放在上中段；下方留給圖說與字幕。
    # 完播節奏修復同批順手修(2026-07-15,獨立驗收抓到 concept_visuals.py:149 這條「逢低
    # 分批．拉低平均成本」跟字幕框疊在一起):舊版 caption 固定畫在 fig-fraction y=0.30、
    # 圖例(legend)在 y=0.265,但字幕框錨在畫面 78% 高、往上長出自己的高度——實測 16:9
    # 長片 2 行字幕的字幕框可以吃到 fig-fraction y≈0.38(9:16 短片≈0.35),兩者的安全區間
    # 幾乎沒有交集,legend 幾乎必中、caption 遇到長字幕也會中。改法:圖軸 bottom 從 0.34
    # 拉高到 0.46(騰出更多下方淨空),caption 挪到 0.42(留 ~0.04 安全margin 在最壞情境
    # 2 行長片字幕框頂之上);legend(圖例圓點文字)直接拿掉——顏色語意本來就在圖上用
    # 紅/綠點畫出來,legend 文字是錦上添花,兩害相權不留它,徹底消除這條重疊來源。
    # 2026-07-28 質感:圖表原本只佔畫面高 34%,上方留白過多。**只把上緣從 0.80 抬到 0.86**
    # (下緣 0.46 一動不動——那是為避開 2 行字幕框算出來的安全邊距,見上方註解),面積 +18%。
    ax = fig.add_axes([0.06, 0.46, 0.88, 0.40])
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(axis="y", color=(1, 1, 1, 0.06), lw=1)

    # 統一契約(2026-07-17):所有 drawer 收 (ax, ctx),回 (caption, legend) 或 None。
    # ctx.real = (ticker, dates, close) 有真資料 / None 沒有。真資料圖(dca/trend/candle/
    # drawdown)拿不到真資料就回 None → 這裡直接不出圖(fail-safe),絕不畫亂數頂替。
    real = None
    # 🔴 2026-07-28 標的錯置修復:原本一律 `resolve_ticker(段落文字)` 優先,於是段落旁白只要
    # 順口提到別檔(常見:拿 0050 當對照),整張圖就會變成那一檔——實測技嘉 2376 的體檢片,
    # 有一段旁白主要在講技嘉的回撤,卻因為文中提到 0050 而畫出「0050 實際最大回撤」的圖,
    # 畫面與旁白講的標的對不上(觀眾看到的是別檔的走勢)。
    # 規則:**當整片有明確主題標的(fallback_ticker,取自標題)時,主題標的優先**;
    # 段落文字解析只在整片沒有主題標的時才作主(如「0056 vs 0050」這類比較片,標題解不出
    # 單一主體,維持舊行為讓各段自己決定)。
    _seg_tk = resolve_ticker(text)
    _vid_tk = fallback_ticker if (fallback_ticker and
                                  (_FACTS_CACHE / f"{fallback_ticker}.csv").exists()) else None
    tk = _vid_tk or _seg_tk
    if tk:
        rd = load_real(tk)
        if rd is not None:
            # 🔴 2026-07-28 同圖輪播防治(這是解封 video_ticker 的必要配套):
            # 解封整片主題標的後,同一支片裡兩個都被判成 drawdown 的段落會畫出**一模一樣**的圖
            # (實測技嘉片 seg1/seg2 完全重複)——正是舊註解警告、也是 Carson 抱怨過的「同圖輪播」。
            # 修法給每段一個 variant(呼叫端用「這個概念在本片第幾次出現」帶進來):
            # variant=0 走完整歷史;variant>=1 改看**近期窗**(依序 45% / 25% 的尾段),
            # 於是同一檔的同一種圖會呈現「長期全景 → 近期特寫」的不同視角,既有變化也多給資訊。
            _d, _c = rd[0], rd[1]
            # 🔴 2026-08-12 tail-window 廢除(數字爆現樣張抓包的三方矛盾):variant≥1 的
            # 近期窗圖會算出**跟旁白不同的數字**——旁白引用的 fact_key 全是全歷史
            # (「最大回撤69.3%」),近期窗圖卻標 -57.0%,觀眾聽到 69 看到 57 = 畫面在
            # 打臉自己的旁白,這比「兩段圖一樣」嚴重得多。鐵律:**圖表的資料窗口必須
            # 跟旁白引用的窗口一致**;variant 之後只准拿來變樣式,不准變窗口。
            # (同圖輪播的視覺問題現由「卡片邊界對齊+段內漸進揭露+換卡punch」緩解。)
            real = (tk, _d, _c)
    ctx = Ctx(rng=rng, direction=_direction(text), real=real, text=text,
              reveal=max(0.05, min(1.0, float(reveal))))

    result = drawer(ax, ctx)
    if result is None:            # drawer 判定「沒有真資料可畫」→ 不出概念圖
        plt.close(fig)
        return None
    caption, legend = result

    # 2026-08-12 抽幀實錘:x 軸年份刻度畫在軸下 ~43px,與 y=0.42 的圖說同一水平帶,
    # 圖說一長必壓年份(訊芯基本面圖 2022~2024 全被蓋)。統一把年份刻度**移入圖內**
    # (負 pad)+描邊保可讀——刻度與圖說徹底分層,所有 drawer 一次受益。
    try:
        ax.tick_params(axis="x", pad=-30)
        for _tl in ax.get_xticklabels():
            _tl.set_path_effects([_pe.withStroke(linewidth=4, foreground=BG)])
    except Exception:  # noqa: BLE001
        pass

    # 圖說（圖下方、字幕安全區之上；見上方 ax 位置註解）。legend 已拿掉，不再畫。
    if caption:
        fig.text(0.5, 0.42, caption, ha="center", va="center",
                 color=FG, fontsize=26, weight="bold")

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    img = Image.fromarray(buf, "RGBA").convert("RGB")
    plt.close(fig)

    # 關鍵數字 out-param(2026-08-12 純ffmpeg動畫v2地基):caption 是本模組剛從**真實
    # 資料**算出並印在圖上的字,從它抽數字=誠信安全的單一事實來源(旁白是中文數字,
    # 模糊轉換有印錯數字的風險,絕不走那條)。呼叫端(make_video.render_concept_card)
    # 自己決定要不要落 sidecar;失敗不影響出圖。
    if meta is not None:
        try:
            import re as _re
            nums = _re.findall(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|倍)", caption or "")
            meta["caption"] = caption or ""
            meta["key_numbers"] = [n.replace(" ", "") for n in nums][:3]
        except Exception:  # noqa: BLE001
            pass

    if dest is not None:
        from pathlib import Path
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG")
    return img


if __name__ == "__main__":
    # 快速自測：每個主題各出一張 1080x1920
    import sys
    from pathlib import Path
    out = Path("output/_concept_test")
    out.mkdir(parents=True, exist_ok=True)
    for k in _DISPATCH:
        im = render_concept_chart(1080, 1920, "", (255, 210, 63), seed="t_" + k, force=k)
        if im:
            im.save(out / f"{k}.png")
            print("ok", k)
