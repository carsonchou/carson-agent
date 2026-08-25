#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_thumbs.py — 每集的縮圖。

## 設計理由
縮圖只有一件工作:讓人在一排小圖裡看懂「兩個數字差很多」。
所以主體是**兩個數字的對比**,不是插圖、不是人臉、不是箭頭亂飛。
落差本身就是戲——它不需要被裝飾,只需要夠大。

- 尺寸 **1280×720(16:9)**。主頻道踩過:縮圖產生器寫死 1080×1920,
  42 支長片的縮圖在 16:9 版位被擠成一條(memory yt-long-thumbnail-aspect-bug)。
- 深色底(Carson 反覆嫌太亮),但要有質感不能死黑。
- 手機上縮圖只有約 210px 寬,所以數字用滿版級字級,說明字一律 ≥42px。
- **不寫任何事實庫以外的數字**——縮圖跟標題一樣是觀眾一定會看到的字。

用法:
  python make_thumbs.py            # 依 publish_meta.json 全產
  python make_thumbs.py --one 0
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
META = ROOT / "publish_meta.json"
W, H = 1280, 720
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
FALLC, HOLDC = "#F5A54E", "#5FC98A"


def _plt():
    """與影片端同一套字型挑選,縮圖和片子才會是同一個頻道。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    return plt


def wrap(s, n):
    out, line = [], ""
    for w in s.split():
        if len(line) + len(w) + 1 > n:
            out.append(line); line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def facts_of(o):
    """從 publish_meta 的說明裡取回本集的兩個效果量與樣本數。

    說明是 publish_meta 從事實庫產生的,所以這裡不會引入新數字——
    只是把已經審核過的值讀回來。
    """
    import re
    d = o["description"]
    es = re.findall(r"effect size (-?\d+\.\d+)", d)
    ns = re.findall(r"([\d,]+) participants", d)
    if len(es) == 2 and len(ns) == 2:
        return float(es[0]), float(es[1]), ns[0], ns[1], None
    # 名案格式
    m = re.search(r"\b([dgr]) = (-?\d+\.\d+)", d)
    n = re.search(r"([\d,]+) people", d)
    cited = re.search(r"cited ([\d,]+) times", d)
    if m and n:
        return None, float(m.group(2)), (cited.group(1) if cited else None), \
               n.group(1), m.group(1)
    return None


def draw(plt, o, out_path):
    f = facts_of(o)
    if not f:
        print(f"  跳過(讀不回數字):{o['title'][:40]}")
        return False
    eo, er, n_left, n_right, kind = f
    # 顏色由 tone 決定,不是 track(track 已停用)。
    held = o.get("tone") in ("held", "stronger", "shrunk_real")
    col = HOLDC if held else FALLC

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)      # 🔴 鎖死,否則文字會被裁掉

    # 極淡的底紋,免得整張死黑
    for i, y in enumerate(np.linspace(0.06, 0.94, 14)):
        ax.plot([0.04, 0.96], [y, y], color="#161B22", lw=1.2, zorder=0)

    # 🔴 主題**不截斷**:字級隨長度縮,縮到 3 行還放不下才整句捨棄。
    #    先前 wrap(...)[:2] 會默默吃掉尾巴(「…correlated with mind」少了
    #    attribution),那是標題犯過的同一個錯——半句話比沒有話更糟。
    # split("?")[0] 會連問號一起吃掉(「…fix a memory」少了問號)。
    # 問句就保留問號——那正是它要製造的懸念。
    t0 = o.get("topic") or o["title"]
    # ⚠️ 對數字型標題切「第一個句號」會切出孤立半句:
    #    「A 2000 study found 0.82」——一個沒有比較對象的數字,而 0.82
    #    正下方又用滿版大字印一次。這種標題本來就沒有主題,不要硬切。
    if t0.startswith(("A 19", "A 20", "Retested on")) or t0[0].isdigit():
        t0 = ""
    else:
        for sep in (" — ", ". "):
            if sep in t0:
                t0 = t0.split(sep)[0]
                break
    if "?" in t0:
        t0 = t0[:t0.index("?") + 1]
    topic = t0.rstrip(".:;, ")
    for size, per_line in ((44, 32), (38, 38), (32, 45)):
        lines = wrap(topic, per_line)
        if len(lines) <= 3:
            break
    else:
        lines = []
    for i, ln in enumerate(lines):
        ax.text(0.5, 0.93 - i * (size / 560), ln, ha="center", va="center",
                fontsize=size, color=FG, weight="bold", zorder=3)

    # 數字往兩側拉開,箭頭留出淨空(先前 0.26/0.755 會和 0.5 的箭頭相撞)
    LX, RX, y = 0.23, 0.76, 0.44   # RX 0.79 時大字會貼到右邊界
    if eo is not None:
        ax.text(LX, y, f"{eo:.2f}", ha="center", va="center",
                fontsize=124, color=DIM, weight="bold", zorder=3)
        ax.text(0.505, y, "→", ha="center", va="center",
                fontsize=76, color=DIM, zorder=3)
        ax.text(RX, y, f"{er:.2f}", ha="center", va="center",
                fontsize=146, color=col, weight="bold", zorder=3)
        ax.text(LX, 0.21, f"{n_left} people", ha="center", fontsize=40,
                color=DIM, zorder=3)
        ax.text(RX, 0.21, f"{n_right} people", ha="center", fontsize=40,
                color=col, zorder=3)
    else:
        # 🔴 引用數和效果量是**兩種不同的量**,用「→」並排等於在說
        #    「4,928 變成了 0.04」——那是無意義的。改成:效果量置中當主體,
        #    引用數退成上方一行小字的背景資訊。
        ax.text(0.5, y + 0.02, f"{er:.2f}", ha="center", va="center",
                fontsize=170, color=col, weight="bold", zorder=3)
        sub = f"across {n_right} people"
        if n_left:
            sub = f"from a study cited {n_left} times · " + sub
        ax.text(0.5, 0.20, sub, ha="center", fontsize=38, color=DIM, zorder=3)

    ax.text(0.5, 0.07, "THEY RAN IT AGAIN", ha="center", fontsize=30,
            color="#3C4450", weight="bold", zorder=3)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    import imageio.v2 as iio
    iio.imwrite(out_path, buf, quality=92)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", type=int)
    a = ap.parse_args()
    meta = json.loads(META.read_text(encoding="utf-8"))
    todo = [meta[a.one]] if a.one is not None else meta
    plt = _plt()
    ok = 0
    for o in todo:
        d = ROOT / o["dir"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / "thumb.jpg"
        if draw(plt, o, p):
            ok += 1
            o["thumb"] = str(pathlib.Path(o["dir"]) / "thumb.jpg").replace("\\", "/")
    if a.one is None:
        META.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"縮圖 {ok}/{len(todo)} 張,{W}×{H}")


if __name__ == "__main__":
    main()
