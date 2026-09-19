#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_thumb_ab.py — 縮圖三個方向的比稿(暫用,選定後併回 make_thumbs.py)。

## 現行版本的問題(Carson:「不太吸引人」)
1. **標題重印一次**。YouTube 版面上標題本來就顯示在縮圖旁邊,再印一次
   等於把 40% 的版面花在觀眾已經看得到的字上。
2. **0.63 → 0.00 對外行不構成訊息**。效果量是圈內記號,觀眾不知道 0.63
   算大還算小,那兩個數字沒有情緒也沒有直覺。
3. **全灰配一個橘**。在一排明亮縮圖裡看起來像沒載入成功的破圖。
4. **純文字、沒有形狀**。手機上縮圖約 210px 寬,字先糊掉,形狀不會。

所以三個方向都遵守:**先給形狀,再給字;字不超過四個**。

用法:
  python _thumb_ab.py            # 產 3 設計 × 3 集,另存 320px 版驗小圖
"""
import json
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "_thumb_ab"
W, H = 1280, 720
BG, FG, DIM = "#0E1116", "#F2F4F7", "#79808B"

#: 判決字。**只能從 tone 直譯**,不能為了聳動而換詞 ——
#  「GONE」對應的是 tone=gone(重做後效應不顯著),不是「造假」。
VERDICT = {"gone": "GONE", "flipped": "FLIPPED", "shrunk_real": "SHRANK",
           "held": "HELD", "stronger": "STRONGER"}
COLOR = {"gone": "#FF6B4A", "flipped": "#FF6B4A", "shrunk_real": "#7FA8FF",
         "held": "#3DD68C", "stronger": "#3DD68C"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI Black", "Segoe UI", "Arial Black", "Arial",
                "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    return plt


def canvas(plt):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)          # 🔴 鎖死否則文字被裁
    return fig, ax


def mark(ax, col="#39414D"):
    ax.text(0.975, 0.045, "THEY RAN IT AGAIN", ha="right", fontsize=24,
            color=col, weight="bold", zorder=9)


def design_a(plt, F):
    """A|柱狀崩塌 —— 高度就是效果量。形狀在字之前被看懂。"""
    tone = F["tone"]
    col = COLOR[tone]
    eo, er = abs(F["orig"]["es"]), abs(F["repl"]["es"])
    top = max(eo, er, 0.1)
    fig, ax = canvas(plt)
    base, cap = 0.16, 0.60
    for x, v, c, n in ((0.30, eo, "#4A525E", F["orig"]["n"]),
                       (0.60, er, col, F["repl"]["n"])):
        h = max(cap * v / top, 0.012)
        ax.add_patch(plt.Rectangle((x - 0.105, base), 0.21, h,
                                   color=c, zorder=3))
        ax.text(x, base + h + 0.035, f"{v:.2f}", ha="center", fontsize=58,
                color=c if v == er else DIM, weight="bold", zorder=4)
        ax.text(x, base - 0.075, f"{n:,}", ha="center", fontsize=46,
                color=FG, weight="bold", zorder=4)
        ax.text(x, base - 0.128, "people", ha="center", fontsize=30,
                color=DIM, zorder=4)
    ax.plot([0.14, 0.76], [base, base], color="#2A313B", lw=3, zorder=2)
    ax.text(0.965, 0.72, VERDICT[tone], ha="right", va="center", fontsize=112,
            color=col, weight="bold", zorder=5)
    ax.text(0.965, 0.60, "when they ran it again", ha="right", va="center",
            fontsize=32, color=DIM, zorder=5)
    mark(ax)
    return fig


def design_b(plt, F):
    """B|數字撞牆 —— 重做後的值佔滿畫面,原值劃掉。對比最猛。"""
    tone = F["tone"]
    col = COLOR[tone]
    fig, ax = canvas(plt)
    ax.add_patch(plt.Rectangle((0, 0), 0.055, 1, color=col, zorder=2))
    ax.text(0.62, 0.46, f"{F['repl']['es']:.2f}", ha="center", va="center",
            fontsize=310, color=col, weight="bold", zorder=4)
    ax.text(0.20, 0.78, f"{F['orig']['es']:.2f}", ha="center", va="center",
            fontsize=104, color="#5A626E", weight="bold", zorder=4)
    ax.plot([0.10, 0.30], [0.775, 0.785], color="#FF6B4A", lw=9, zorder=5)
    ax.text(0.20, 0.655, f"{F['orig']['n']:,} people", ha="center",
            fontsize=32, color=DIM, zorder=4)
    ax.text(0.20, 0.40, VERDICT[tone], ha="center", va="center", fontsize=78,
            color=FG, weight="bold", zorder=4)
    ax.text(0.20, 0.30, f"on {F['repl']['n']:,} people", ha="center",
            fontsize=34, color=DIM, zorder=4)
    mark(ax)
    return fig


def design_c(plt, F):
    """C|判決佔滿 —— 一個字撐滿畫面,數字退成註腳。小圖存活率最高。"""
    tone = F["tone"]
    col = COLOR[tone]
    word = VERDICT[tone]
    fig, ax = canvas(plt)
    ax.add_patch(plt.Rectangle((0, 0.60), 1, 0.40, color="#151A21", zorder=1))
    ax.text(0.5, 0.795, word, ha="center", va="center",
            fontsize=int(230 - 14 * len(word)), color=col, weight="bold",
            zorder=4)
    ax.text(0.5, 0.50, "THE SAME STUDY. MORE PEOPLE.", ha="center",
            va="center", fontsize=38, color=DIM, weight="bold", zorder=4)
    for x, v, n, c in ((0.28, F["orig"]["es"], F["orig"]["n"], "#5A626E"),
                       (0.72, F["repl"]["es"], F["repl"]["n"], col)):
        ax.text(x, 0.32, f"{v:.2f}", ha="center", va="center", fontsize=118,
                color=c, weight="bold", zorder=4)
        ax.text(x, 0.17, f"{n:,} people", ha="center", fontsize=36,
                color=DIM, zorder=4)
    ax.text(0.5, 0.32, "→", ha="center", va="center", fontsize=64,
            color="#39414D", zorder=4)
    mark(ax)
    return fig


def design_d(plt, F):
    """D|A 的形狀 + C 的判決字 —— 小圖實測後的合成版。

    320px 實測學到的三件事,這版全部照做:
    - **判決字放頂端橫幅**,C 那樣最耐縮;A 把它擠在右邊會跟長條打架
    - **刪掉所有註解句**。「when they ran it again」「THE SAME STUDY.
      MORE PEOPLE.」在小圖上一律是糊的 —— 糊掉的字不是資訊,是髒污
    - **長條保留**,因為形狀在字糊掉之後還讀得懂,那是純文字版沒有的
    """
    tone = F["tone"]
    col = COLOR[tone]
    word = VERDICT[tone]
    eo, er = abs(F["orig"]["es"]), abs(F["repl"]["es"])
    top = max(eo, er, 0.1)
    fig, ax = canvas(plt)
    ax.add_patch(plt.Rectangle((0, 0.715), 1, 0.285, color="#151A21", zorder=1))
    ax.add_patch(plt.Rectangle((0, 0.715), 1, 0.008, color=col, zorder=2))
    # 字級要**由字數決定**且封頂 —— 先前寫 190 讓 GONE 撐出橫幅被切頭。
    ax.text(0.5, 0.858, word, ha="center", va="center",
            fontsize=int(min(132, 980 / max(len(word), 4))),
            color=col, weight="bold", zorder=4)
    base, cap = 0.22, 0.365
    for x, v, c, n in ((0.30, eo, "#49515D", F["orig"]["n"]),
                       (0.70, er, col, F["repl"]["n"])):
        h = max(cap * v / top, 0.014)
        ax.add_patch(plt.Rectangle((x - 0.125, base), 0.25, h, color=c,
                                   zorder=3))
        ax.text(x, base + h + 0.042, f"{v:.2f}", ha="center", va="center",
                fontsize=76, color=c if v == er else "#7A828E",
                weight="bold", zorder=4)
        ax.text(x, base - 0.095, f"{n:,} people", ha="center", va="center",
                fontsize=52, color=FG, weight="bold", zorder=4)
    ax.plot([0.10, 0.90], [base, base], color="#2A313B", lw=3, zorder=2)
    # 「PEOPLE」原本另起一行,小圖上糊成髒污 —— 併進上一行,一行搞定。
    # 頻道標記移進頂端橫幅 —— 放右下角會壓到「331 people」。
    ax.text(0.985, 0.752, "THEY RAN IT AGAIN", ha="right", va="bottom",
            fontsize=22, color="#39414D", weight="bold", zorder=9)
    return fig


def main():
    import imageio.v2 as iio
    OUT.mkdir(exist_ok=True)
    plt = _plt()
    picks = []
    for ep in ("ep013", "ep011", "ep008"):
        p = ROOT / "eps" / ep / "facts.json"
        if p.exists():
            picks.append((ep, json.loads(p.read_text(encoding="utf-8"))))
    if not picks:
        print("⛔ 找不到 facts.json")
        return 1
    for name, fn in (("D", design_d),):
        for ep, F in picks:
            fig = fn(plt, F)
            fig.canvas.draw()
            buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
            plt.close(fig)
            iio.imwrite(OUT / f"{name}_{ep}.jpg", buf, quality=93)
            # 小圖:手機上縮圖約 210~320px 寬,糊不糊在這裡看,不是在大圖看
            small = buf[::4, ::4]
            iio.imwrite(OUT / f"{name}_{ep}_small.jpg", small, quality=93)
            print(f"  {name}_{ep}  tone={F['tone']:<12}"
                  f"{F['orig']['es']:+.2f} → {F['repl']['es']:+.2f}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
