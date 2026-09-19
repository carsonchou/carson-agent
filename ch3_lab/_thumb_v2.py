#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_thumb_v2.py — 縮圖第二次改版的比稿(暫用)。

## 上一版錯在哪(Carson:「封面標題不夠吸引人」)
上一版把 **`0.04` 放成畫面最大的元素**,而效果量對一般觀眾沒有任何意義 ——
它是**我**這種看得懂統計的人才覺得是重點的東西。而且圖上完全沒說「什麼」
不見了:「GONE + 0.04」要配著標題才讀得懂,但在 feed 裡縮圖是先被看到的。

我為「已經懂的人」設計了一張圖,而那批人不需要這個頻道。

## 這一版的原則
**大字放白話的主張,數字降成佐證。** 一個滑過去的人需要的是
「一個他相信的說法」+「它是錯的」,不是一個小數。

A|主張被劃掉:主張佔滿上半,一條粗線劃過去,下面一行講規模
B|主張 + 判決塊:主張在上,底下一條實色塊寫判決,數字縮到角落
C|問句 + 大反差:主張寫成問句,答案用一個字回答

用法:
  python _thumb_v2.py
"""
import json
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "_thumb_ab"
W, H = 1280, 720
BG, FG = "#0E1116", "#FFFFFF"
HOT = "#FF4A2E"        # 比上一版更飽和 —— 上一版在一排明亮縮圖裡太安靜
GOOD = "#22D67F"

#: 主張的**白話版**。來源的 claim 是論文語言,直接放上去沒人看得懂。
#: 這裡只做「講人話」的改寫,不改變意思,也不加任何新宣稱。
PLAIN = {
    "ego_depletion": ("WILLPOWER", "RUNS OUT", "23 labs looked. They couldn't find it."),
    "bystander_effect": ("A CROWD STOPS", "PEOPLE HELPING", "105 studies. This one is real."),
    "implicit_bias_test": ("THIS TEST REVEALS", "YOUR HIDDEN BIAS", "184 samples. Real, but it barely predicts."),
    "sleep_memory": ("YOU CAN STRENGTHEN", "MEMORY IN YOUR SLEEP", "91 experiments. This one held up."),
    "romantic_red": ("RED MAKES WOMEN", "MORE ATTRACTIVE", "242 men. Nothing there."),
}
#: 🔴 判決字必須從**定調**來,不能用手寫的「成立/不成立」布林值。
#    我用布林值的後果:`implicit_bias_test` 被印成「NOT FOUND」,而那篇
#    統合分析**找到了** r=0.274 —— 它是真的,只是很弱。副標寫對了
#    (「barely predicts anything」),大字卻寫反。
#    而我在兩分鐘前才剛批評別的版本「NO」不誠實,然後自己犯同一個錯。
#    二分法配上五種定調,必然會把中間那三種壓扁到某一端。
VERDICT = {
    "gone":        ("NOT FOUND",    HOT),    # 測不到,不是「不存在」
    "flipped":     ("IT REVERSED",  HOT),    # 方向相反,而且顯著
    "shrunk_real": ("REAL BUT TINY", "#4A9EFF"),  # 兩邊都不是
    "held":        ("IT HELD UP",   GOOD),
    "stronger":    ("EVEN BIGGER",  GOOD),
}
#: 五支名案的定調(從各自的信賴區間/效果量判定,見 make_short.collect)
TONE = {"ego_depletion": "gone", "bystander_effect": "held",
        "implicit_bias_test": "shrunk_real", "sleep_memory": "held",
        "romantic_red": "gone"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    return plt


def fit(plt, text, base, max_frac=0.92, weight="bold"):
    """量文字寬度反推字級 —— A/C 兩版第三欄的字直接溢出畫面,
    而主張的長度本來就會變(「WILLPOWER」vs「THIS TEST REVEALS」)。"""
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=base,
                weight=weight)
    fig.canvas.draw()
    frac = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    return base if frac <= max_frac else max(20, int(base * max_frac / frac))


def design_d(plt, slug, es):
    """D|合併版:主張(白、自動縮放)+ 判決塊(實色、滿版大字)+ 佐證。

    ## 為什麼判決字不是「NO」
    C 版那個大大的 NO 最好讀,但它**不誠實**:效果量 0.04、信賴區間
    [-0.07, 0.15] 的意思是「找不到」,不是「不存在」。這個頻道的簡介
    白紙黑字寫著「不是一味打臉」,而縮圖是最多人看到的地方 ——
    在那裡overclaim,後面講再多都補不回來。
    「NOT FOUND」一樣是滿版大字,而且它是真的。
    """
    l1, l2, sub = PLAIN[slug]
    word, col = VERDICT[TONE[slug]]
    fig, ax = canvas(plt)
    fs1 = min(fit(plt, l1, 88), fit(plt, l2, 88))
    ax.text(0.5, 0.855, l1, ha="center", va="center", fontsize=fs1,
            color="#C6CCD4", weight="bold")
    ax.text(0.5, 0.725, l2, ha="center", va="center", fontsize=fs1,
            color="#C6CCD4", weight="bold")
    ax.add_patch(plt.Rectangle((0.03, 0.235), 0.94, 0.36, color=col, zorder=2))
    ax.text(0.5, 0.415, word, ha="center", va="center",
            fontsize=fit(plt, word, 168, 0.86), color="#0E1116",
            weight="bold", zorder=3)
    ax.text(0.5, 0.115, sub, ha="center", va="center",
            fontsize=fit(plt, sub, 48, 0.90, "normal"), color="#8A929C")
    return fig


def canvas(plt):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    return fig, ax


def design_a(plt, slug, es):
    """A|主張被劃掉。最直接:你相信的那句話,一條線劃過去。"""
    l1, l2, sub = PLAIN[slug]
    holds = HOLDS[slug]
    col = GOOD if holds else HOT
    fig, ax = canvas(plt)
    ax.text(0.5, 0.74, l1, ha="center", va="center", fontsize=104,
            color=FG, weight="bold", zorder=3)
    ax.text(0.5, 0.57, l2, ha="center", va="center", fontsize=104,
            color=FG, weight="bold", zorder=3)
    if not holds:
        # 劃掉 = 「這句話不成立」,不需要任何統計素養就讀得懂
        ax.plot([0.06, 0.94], [0.655, 0.655], color=HOT, lw=16, zorder=4,
                solid_capstyle="butt")
    else:
        ax.text(0.5, 0.655, "✓", ha="center", va="center", fontsize=170,
                color=GOOD, weight="bold", alpha=0.22, zorder=2)
    ax.add_patch(plt.Rectangle((0, 0), 1, 0.30, color=col, zorder=1))
    ax.text(0.5, 0.155, sub, ha="center", va="center", fontsize=52,
            color="#0E1116", weight="bold", zorder=3)
    return fig


def design_b(plt, slug, es):
    """B|判決塊。主張在上,底下一條實色塊直接給答案。"""
    l1, l2, sub = PLAIN[slug]
    holds = HOLDS[slug]
    col = GOOD if holds else HOT
    word = "IT HELD UP" if holds else "IT DIDN'T"
    fig, ax = canvas(plt)
    ax.text(0.5, 0.80, l1, ha="center", va="center", fontsize=92,
            color="#9AA3AF", weight="bold")
    ax.text(0.5, 0.655, l2, ha="center", va="center", fontsize=92,
            color="#9AA3AF", weight="bold")
    ax.add_patch(plt.Rectangle((0.04, 0.20), 0.92, 0.34, color=col, zorder=2))
    ax.text(0.5, 0.37, word, ha="center", va="center", fontsize=150,
            color="#0E1116", weight="bold", zorder=3)
    ax.text(0.5, 0.095, sub, ha="center", va="center", fontsize=44,
            color="#7A828E")
    return fig


def design_c(plt, slug, es):
    """C|問句 + 一個字的答案。最像一般人講話的方式。"""
    l1, l2, sub = PLAIN[slug]
    holds = HOLDS[slug]
    col = GOOD if holds else HOT
    fig, ax = canvas(plt)
    ax.text(0.06, 0.83, l1, ha="left", va="center", fontsize=86,
            color=FG, weight="bold")
    ax.text(0.06, 0.70, l2 + "?", ha="left", va="center", fontsize=86,
            color=FG, weight="bold")
    ax.text(0.06, 0.40, "YES" if holds else "NO", ha="left", va="center",
            fontsize=290, color=col, weight="bold")
    ax.text(0.97, 0.11, sub, ha="right", va="center", fontsize=46,
            color="#7A828E")
    return fig


def main():
    import imageio.v2 as iio
    OUT.mkdir(exist_ok=True)
    plt = _plt()
    picks = ["ego_depletion", "bystander_effect", "implicit_bias_test"]
    for name, fn in (("D", design_d),):
        for slug in picks:
            fig = fn(plt, slug, None)
            fig.canvas.draw()
            buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
            plt.close(fig)
            iio.imwrite(OUT / f"v2{name}_{slug}.jpg", buf, quality=93)
    # 小圖比稿 —— feed 裡就是這個大小,大圖好看不算數
    rows = []
    for name in "D":
        ims = [iio.imread(OUT / f"v2{name}_{s}.jpg")[::4, ::4] for s in picks]
        h = min(i.shape[0] for i in ims)
        rows.append(np.concatenate(
            [np.pad(i[:h], ((0, 0), (0, 8), (0, 0)), constant_values=45)
             for i in ims], axis=1))
    w = min(r.shape[1] for r in rows)
    iio.imwrite(OUT / "_v2_sheet.jpg", np.concatenate(
        [np.pad(r[:, :w], ((0, 10), (0, 0), (0, 0)), constant_values=45)
         for r in rows], axis=0), quality=95)
    print(f"→ {OUT / '_v2_sheet.jpg'}(上到下 A/B/C,每列三支)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
