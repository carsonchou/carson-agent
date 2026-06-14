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
from typing import Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # 無視窗後端
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

# 深色主題（與 K 線卡一致）
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


def classify(text: str) -> Optional[str]:
    """依關鍵字判斷主題；回傳概念 key 或 None。順序＝優先序（越專一越前面）。"""
    t = (text or "").lower()
    # 順序＝優先序：越專一、越不會被順口提及的主題排越前面，
    # 通用詞（波動/回測/虧損…）排後面，避免把真正主題搶走。
    rules = [
        ("martingale", ("馬丁", "凹單", "加碼攤平", "翻倍下注", "輸了加倍", "馬丁格爾")),
        ("overfit", ("過擬合", "過度最佳化", "過度優化", "曲線擬合", "參數最佳", "最佳化參數", "90%參數")),
        ("compound", ("複利", "72法則", "72 法則", "利滾利", "錢滾錢", "本金翻倍")),
        ("dca", ("定投", "定期定額", "dca", "分批買", "攤平成本", "平均成本", "無腦買", "買在高點", "微笑曲線")),
        ("grid", ("網格", "格子單", "高賣低買", "低買高賣", "等差", "等比", "上下限", "區間來回", "震盪行情")),
        ("winrate", ("勝率", "盈虧比", "期望值", "賺賠比", "賺多賠少", "大賺小賠")),
        ("sharpe", ("夏普", "sharpe", "風險調整後", "報酬波動比")),
        ("backtest", ("樣本外", "樣本內", "回測", "out of sample", "out-of-sample", "驗證期")),
        ("drawdown", ("最大回撤", "回撤", "drawdown", "套牢", "腰斬", "歸零", "回吐")),
        ("trend", ("單邊行情", "單邊", "趨勢盤", "一路噴", "急漲", "急跌", "破底", "噴出")),
    ]
    for key, kws in rules:
        for kw in kws:
            if kw.lower() in t:
                return key
    return None


# --------------------------------------------------------------------------- #
# 各主題畫法（在 ax 上作畫，座標自定，外觀統一在 _new_ax / _finish 處理）
# --------------------------------------------------------------------------- #

def _grid(ax, rng):
    n = 220
    x = np.arange(n)
    # 區間震盪價格：均值回歸（OU 過程），確保在固定箱型內來回、不漂走
    lo_b, hi_b, mid = 94.0, 106.0, 100.0
    price = np.empty(n)
    price[0] = mid
    for i in range(1, n):
        price[i] = price[i - 1] + 0.10 * (mid - price[i - 1]) + rng.randn() * 1.1
    price = np.clip(price, lo_b + 0.3, hi_b - 0.3)
    levels = np.linspace(95, 105, 6)
    for lv in levels:
        ax.axhline(lv, color=(1, 1, 1, 0.13), lw=1, zorder=1)
    # 上下界（網格範圍）較亮
    ax.axhline(hi_b, color=(*RED, 0.5), lw=1.4, ls="--", zorder=2)
    ax.axhline(lo_b, color=(*GREEN, 0.5), lw=1.4, ls="--", zorder=2)
    ax.plot(x, price, color=FG, lw=2.2, zorder=3)
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
        ax.scatter([px_], [lv], s=72, zorder=4,
                   color=RED if up else GREEN, edgecolors="white", linewidths=0.7)
    ax.set_xlim(0, n - 1)
    ax.set_ylim(lo_b - 2, hi_b + 2)
    return "區間來回．低買高賣", ("● 低買", GREEN, "● 高賣", RED)


def _dca(ax, rng):
    n = 160
    x = np.arange(n)
    dip = -22 * np.exp(-((x - 70) ** 2) / (2 * 26 ** 2))
    price = 100 + dip + np.cumsum(rng.randn(n) * 0.35)
    ax.plot(x, price, color=FG, lw=2.2, zorder=3)
    buys_x = np.arange(8, n, 18)
    buys_y = price[buys_x]
    ax.scatter(buys_x, buys_y, s=60, color=GREEN, edgecolors="white",
               linewidths=0.6, zorder=4)
    avg = np.cumsum(buys_y) / np.arange(1, len(buys_y) + 1)
    ax.step(buys_x, avg, where="post", color="#ffd23f", lw=2.0, zorder=3)
    ax.set_xlim(0, n - 1)
    return "逢低分批．拉低平均成本", ("● 每期買進", GREEN, "— 平均成本", (1, 0.82, 0.25))


def _compound(ax, rng):
    n = 120
    x = np.linspace(0, n, n)
    comp = 100 * (1.022) ** (x / 3)
    lin = 100 + (comp[-1] - 100) * (x / n) * 0.42
    ax.plot(x, lin, color=MUTED, lw=2.0, ls="--", zorder=2)
    ax.plot(x, comp, color=GREEN, lw=2.8, zorder=3)
    ax.fill_between(x, lin, comp, color=GREEN, alpha=0.12, zorder=1)
    ax.set_xlim(0, n)
    ax.set_ylim(80, comp[-1] * 1.05)
    return "複利．時間越久越陡", ("— 複利", GREEN, "-- 單利", MUTED)


def _drawdown(ax, rng):
    n = 200
    x = np.arange(n)
    eq = 100 + np.cumsum(rng.randn(n) * 0.9 + 0.18)
    ax.plot(x, eq, color=FG, lw=2.2, zorder=3)
    run_max = np.maximum.accumulate(eq)
    # 找最大回撤區段
    dd = (eq - run_max)
    trough = int(np.argmin(dd))
    peak = int(np.argmax(eq[: trough + 1])) if trough > 0 else 0
    ax.fill_between(x[peak:trough + 1], eq[peak:trough + 1], run_max[peak:trough + 1],
                    color=RED, alpha=0.28, zorder=2)
    ax.scatter([peak, trough], [eq[peak], eq[trough]], s=60, color=RED,
               edgecolors="white", linewidths=0.6, zorder=4)
    ax.annotate("最大回撤", xy=(trough, eq[trough]), xytext=(0, -28),
                textcoords="offset points", ha="center", color=RED, fontsize=15)
    ax.set_xlim(0, n - 1)
    return "賺得快不算贏．扛得住才算", None


def _sharpe(ax, rng):
    n = 160
    x = np.arange(n)
    smooth = 100 + np.cumsum(np.full(n, 0.16) + rng.randn(n) * 0.12)
    jagged = 100 + np.cumsum(np.full(n, 0.16) + rng.randn(n) * 0.85)
    ax.plot(x, smooth, color=GREEN, lw=2.6, zorder=3)
    ax.plot(x, jagged, color=MUTED, lw=1.8, zorder=2)
    ax.set_xlim(0, n - 1)
    return "同樣報酬．波動越小越值錢", ("— 高夏普", GREEN, "— 低夏普", MUTED)


def _winrate(ax, rng):
    cats = ["賺的單", "賠的單"]
    vals = [42, 58]
    colors = [GREEN, RED]
    bars = ax.bar(cats, vals, color=colors, width=0.55, zorder=3,
                  edgecolor="white", linewidth=0.5)
    ax.plot([-0.4, 1.4], [50, 50], color=(1, 1, 1, 0.18), lw=1, zorder=1)
    # 盈虧比箭頭：賺的單金額更大
    ax.annotate("但賺的單\n抓更大", xy=(0, 42), xytext=(0, 70),
                ha="center", color=GREEN, fontsize=15,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.6))
    ax.set_ylim(0, 90)
    ax.set_xlim(-0.6, 1.6)
    return "勝率低也能賺．靠盈虧比", None


def _martingale(ax, rng):
    n = 9
    x = np.arange(n)
    bet = 2.0 ** x
    ax.bar(x, bet, color=RED, width=0.6, zorder=3, edgecolor="white", linewidth=0.5)
    ax.annotate("一次爆倉\n全部歸零", xy=(n - 1, bet[-1]), xytext=(n - 3.2, bet[-1] * 0.9),
                ha="center", color=RED, fontsize=15,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.6))
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_ylim(0, bet[-1] * 1.18)
    return "輸了就加倍．遲早一次清光", None


def _overfit(ax, rng):
    n = 160
    x = np.arange(n)
    split = 100
    ins = 100 + np.cumsum(np.full(n, 0.42) + rng.randn(n) * 0.18)
    out = ins.copy()
    out[split:] = ins[split] + np.cumsum(np.full(n - split, -0.55) + rng.randn(n - split) * 0.5)
    ax.axvline(split, color=(1, 1, 1, 0.18), lw=1.2, ls="--", zorder=1)
    ax.plot(x[: split + 1], ins[: split + 1], color=GREEN, lw=2.6, zorder=3)
    ax.plot(x[split:], out[split:], color=RED, lw=2.6, zorder=3)
    ax.text(split * 0.5, ax.get_ylim()[1], "樣本內", ha="center", va="top", color=GREEN, fontsize=14)
    ax.text(split + (n - split) * 0.5, ins[split], "樣本外", ha="center", color=RED, fontsize=14)
    ax.set_xlim(0, n - 1)
    return "回測完美．實盤打回原形", None


def _backtest(ax, rng):
    n = 180
    x = np.arange(n)
    split = 120
    eq = 100 + np.cumsum(np.full(n, 0.22) + rng.randn(n) * 0.6)
    ax.axvspan(0, split, color=(1, 1, 1, 0.04), zorder=0)
    ax.axvline(split, color=(1, 1, 1, 0.20), lw=1.2, ls="--", zorder=1)
    ax.plot(x[: split + 1], eq[: split + 1], color=FG, lw=2.4, zorder=3)
    ax.plot(x[split:], eq[split:], color="#ffd23f", lw=2.4, zorder=3)
    ax.text(split * 0.5, ax.get_ylim()[1], "回測期", ha="center", va="top", color=MUTED, fontsize=14)
    ax.text(split + (n - split) * 0.5, ax.get_ylim()[1], "驗證期", ha="center", va="top",
            color="#ffd23f", fontsize=14)
    ax.set_xlim(0, n - 1)
    return "真正能信的是樣本外", None


def _trend(ax, rng):
    n = 170
    x = np.arange(n)
    up = rng.rand() > 0.5
    drift = 0.42 if up else -0.42
    price = 100 + np.cumsum(np.full(n, drift) + rng.randn(n) * 0.45)
    col = GREEN if up else RED
    ax.plot(x, price, color=col, lw=2.6, zorder=3)
    ax.fill_between(x, price.min() - 2, price, color=col, alpha=0.10, zorder=1)
    ax.set_xlim(0, n - 1)
    return ("單邊噴出．網格反而踏空" if up else "單邊崩跌．網格越攤越深"), None


def _candles(ax, rng):
    n = 46
    o = 100.0
    xs, data = [], []
    for i in range(n):
        c = o + rng.randn() * 1.4 + 0.05
        hi = max(o, c) + abs(rng.randn()) * 0.8
        lo = min(o, c) - abs(rng.randn()) * 0.8
        data.append((o, hi, lo, c))
        xs.append(i)
        o = c
    for i, (op, hi, lo, cl) in enumerate(data):
        up = cl >= op
        col = GREEN if up else RED
        ax.plot([i, i], [lo, hi], color=col, lw=1.2, zorder=2)
        ax.add_patch(Rectangle((i - 0.32, min(op, cl)), 0.64, max(abs(cl - op), 0.05),
                               color=col, zorder=3))
    ax.set_xlim(-1, n)
    return None, None


_DISPATCH = {
    "grid": _grid, "dca": _dca, "compound": _compound, "drawdown": _drawdown,
    "sharpe": _sharpe, "winrate": _winrate, "martingale": _martingale,
    "overfit": _overfit, "backtest": _backtest, "trend": _trend, "candle": _candles,
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
                         dest=None, force: Optional[str] = None):
    """回傳滿版深色底 + 置中數據圖的 PIL.Image(RGB)；判不到主題回 None。

    圖只佔畫面中段（約 18%~76% 高），上方留給大標題、下方留給字幕。
    accent 目前用於未來擴充；配色已內建紅綠主題。
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

    # 圖軸放在上中段；下方 0~0.30 留給圖說/圖例與字幕（字幕約在 y=0.20 處）
    ax = fig.add_axes([0.06, 0.34, 0.88, 0.46])
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(axis="y", color=(1, 1, 1, 0.06), lw=1)

    caption, legend = drawer(ax, rng)

    # 圖說（圖下方、字幕上方）
    if caption:
        fig.text(0.5, 0.30, caption, ha="center", va="center",
                 color=FG, fontsize=21, weight="bold")
    # 圖例（caption 下方，仍在字幕 y≈0.20 之上）
    if legend and len(legend) == 4:
        l1, c1, l2, c2 = legend
        fig.text(0.36, 0.265, l1, ha="center", color=c1, fontsize=14)
        fig.text(0.64, 0.265, l2, ha="center", color=c2, fontsize=14)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    img = Image.fromarray(buf, "RGBA").convert("RGB")
    plt.close(fig)

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
