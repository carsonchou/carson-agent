#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_thumbs.py — 每集的縮圖。

## 設計理由(2026-08-28 改版,Carson:「不太吸引人」)
舊版把**標題整句重印在縮圖上**,再把兩個效果量並排。三個問題:

1. **標題是重複資訊**。YouTube 版面上標題本來就顯示在縮圖旁邊,再印一次
   等於把 40% 的版面花在觀眾已經看得到的字上。
2. **`0.63 → 0.00` 對外行不構成訊息**。效果量是圈內記號 —— 觀眾不知道
   0.63 算大還算小,那兩個數字沒有情緒,也沒有直覺。
3. **純文字、沒有形狀**。手機上縮圖約 210~320px 寬,**字會先糊掉,形狀
   不會**。實測把三個設計縮到 320px 並排看,結論很硬:所有小於 40pt 的
   註解句在小圖上都不是資訊,是髒污。

所以現在的版面只有三層,由上而下:
- **判決字**(GONE / SHRANK / HELD / STRONGER / FLIPPED)佔頂端橫幅,
  一個詞,顏色由結局決定
- **兩根長條**,高度就是效果量 —— 形狀在字糊掉之後還讀得懂
- **兩個樣本數**,一行講完

判決字**只能從 tone 直譯**,不能為了聳動換詞:「GONE」對應 tone=gone
(重做後效應不顯著),不是在說原研究造假。

## 其他不可回頭的規格
- 尺寸 **1280×720(16:9)**。主頻道踩過:縮圖產生器寫死 1080×1920,
  42 支長片的縮圖在 16:9 版位被擠成一條(memory yt-long-thumbnail-aspect-bug)。
- `set_xlim/set_ylim` 必鎖,否則 `ax.plot` 會自動縮放把文字整批裁掉。
- 深色底(Carson 反覆嫌太亮),但要有質感不能死黑。
- **不寫任何事實庫以外的數字**。

用法:
  python make_thumbs.py            # 依 publish_meta.json 全產
  python make_thumbs.py --one 0
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
META = ROOT / "publish_meta.json"
W, H = 1280, 720
BG, FG, DIM = "#0E1116", "#F2F4F7", "#79808B"
BAND, GREY = "#151A21", "#49515D"

#: 判決字與顏色。⚠️ shrunk_real **兩邊都不是**:歸紅色等於說它垮了
#  (旁白明講 not a debunking),歸綠色等於說它守住了(它掉了 73%)。
#  所以它有自己的藍。
#
#  🔴 用字要**punchy 且成立**。「GONE」聽起來像「不存在」,但 gone 的
#     真正意思是「這次測不到」——效果量 0.04、信賴區間跨零,那是
#     「找不到」不是「證明沒有」。改成 NOT FOUND:一樣是滿版大字,
#     而且它是真的。縮圖是最多人看到的地方,在那裡 overclaim,
#     後面講再多都補不回來。
VERDICT = {"gone": "NOT FOUND", "flipped": "IT REVERSED",
           "shrunk_real": "REAL BUT TINY", "held": "IT HELD UP",
           "stronger": "EVEN BIGGER"}
COLOR = {"gone": "#FF4A2E", "flipped": "#FF4A2E", "shrunk_real": "#4A9EFF",
         "held": "#22D67F", "stronger": "#22D67F"}
#: 判決之後那一行佐證。數字用事實庫的真值填,措辭依定調 ——
#: 手寫的只有主張那兩行,這裡不是。
EVIDENCE = {
    "gone": "Retested on {n:,} people. Not found.",
    "flipped": "Retested on {n:,} people. It went the other way.",
    "shrunk_real": "Retested on {n:,} people. Real, but much smaller.",
    "held": "Retested on {n:,} people. It held.",
    "stronger": "Retested on {n:,} people. Even bigger.",
}


def plain_claim(o):
    """縮圖上那兩行白話主張。**手寫**,存在 facts/plain_claims.json。

    查表本身在 `plain.py` —— Short 的開場卡念的是同一句,兩邊必須是
    同一份資料。缺就不產(fail-closed),理由見 plain.py。
    """
    import plain
    return plain.lines(o.get("dir"), o.get("slug"))


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


def fit(plt, text, base, max_frac=0.92, weight="bold"):
    """量文字寬度反推字級。主張的長度差很多(「WILLPOWER」vs「ACCOUNTABILITY
    STOPS」),固定字級一定會有幾支溢出畫面 —— 而溢出是靜默的。"""
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=base,
                weight=weight)
    fig.canvas.draw()
    frac = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    return base if frac <= max_frac else max(20, int(base * max_frac / frac))


def draw(plt, o, out_path):
    f = facts_of(o)
    if not f:
        print(f"  跳過(讀不回數字):{o['title'][:40]}")
        return False
    eo, er, n_left, n_right, _kind = f
    tone = o["tone"]
    col = COLOR[tone]
    word = VERDICT[tone]
    lines = plain_claim(o)
    if not lines:
        print(f"  ⛔ 缺白話主張(facts/plain_claims.json):"
              f"{o.get('dir') or o.get('slug')} —— 不產,免得把論文語言放上去")
        return False

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)      # 🔴 鎖死,否則文字會被裁掉

    # 主張:白話、兩行、自動縮放。**這是版面上最大的元素** ——
    # 上一版最大的是效果量,而那對一般觀眾沒有意義。
    fs1 = min(fit(plt, lines[0], 88), fit(plt, lines[1], 88))
    ax.text(0.5, 0.855, lines[0], ha="center", va="center", fontsize=fs1,
            color="#C6CCD4", weight="bold")
    ax.text(0.5, 0.725, lines[1], ha="center", va="center", fontsize=fs1,
            color="#C6CCD4", weight="bold")

    # 判決塊:實色滿版,一眼看到成不成立。用字見 VERDICT 的說明 ——
    # punchy 但不 overclaim。
    ax.add_patch(plt.Rectangle((0.03, 0.235), 0.94, 0.36, color=col, zorder=2))
    ax.text(0.5, 0.415, word, ha="center", va="center",
            fontsize=fit(plt, word, 168, 0.86), color="#0E1116",
            weight="bold", zorder=3)

    # 佐證:數字從事實庫來,措辭依定調。降到最小 —— 它是支持不是主角。
    n_r = int(str(n_right).replace(",", ""))
    sub = EVIDENCE[tone].format(n=n_r)
    ax.text(0.5, 0.115, sub, ha="center", va="center",
            fontsize=fit(plt, sub, 48, 0.90, "normal"), color="#8A929C")
    ax.text(0.985, 0.028, "THEY RAN IT AGAIN", ha="right", va="bottom",
            fontsize=20, color="#39414D", weight="bold")

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
