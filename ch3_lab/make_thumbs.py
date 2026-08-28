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
#  🔴 「REAL BUT TINY」曾經印在 bystander_effect 上(g = -0.35,心理學裡
#     算中等偏上)。那不是版面問題,是 famous_tone 把「資料裡沒有信賴
#     區間」直接對應到這一檔,於是缺資料變成一個關於大小的斷言。
#     規則那邊已經改成缺區間就必須手寫定調;用字也從 TINY 放寬到 SMALL,
#     因為這一檔真正的意思是「測得到,但撐不起原本那麼強的說法」。
VERDICT = {"gone": "NOT FOUND", "flipped": "IT REVERSED",
           # 🔴 判決字也要跟著量級走,不能只讓佐證那行去補。
           #    我原本的分工是「判決字只講方向,大小交給下面那行」——
           #    但本檔開頭自己寫著:手機上縮圖約 210~320px 寬,**所有
           #    小於 40pt 的註解句在小圖上都不是資訊,是髒污**。而佐證
           #    那行正是 48pt 起跳、灰色、貼在最底的那個元素。
           #    等於把緩和語放進我自己認定會先消失的地方,縮到 320px
           #    之後觀眾看到的還是滿版紅字「IT REVERSED」,而 ep004 的
           #    95% CI 下界是 0.004。三個尺寸的元素要講同一件事。
           "flipped_tiny": "BARELY REVERSED",
           "shrunk_real": "REAL BUT SMALL", "held": "IT HELD UP",
           "stronger": "EVEN BIGGER"}
COLOR = {"gone": "#FF4A2E", "flipped": "#FF4A2E", "shrunk_real": "#4A9EFF",
         # 借 shrunk_real 那檔的藍:它不是乾淨的失敗,也不是乾淨的反轉。
         "flipped_tiny": "#4A9EFF",
         "held": "#22D67F", "stronger": "#22D67F"}
#: 判決之後那一行佐證。數字用事實庫的真值填,措辭依定調 ——
#: 手寫的只有主張那兩行,這裡不是。
#: 佐證那一行 = 規模 + 結局。**拆成兩半**,因為兩半的正確寫法各自
#: 依賴不同的欄位:
#:  - 規模:有原始研究才能說「retested」。sleep_memory / implicit_bias_test
#:    沒有原始研究(它們是把一堆實驗統合起來,不是重做某一篇),
#:    印「Retested on 14,900 people」是**方法論宣稱**,而且是錯的 ——
#:    這一類守門結構上看不見(memory yt-integrity-methodology-claims-blindspot)。
#:  - 結局:shrunk_real 有兩種來源,有原始值可比才能說「比較小」。
SCALE = {
    True:  "Retested on {n:,} people.",
    False: "Pooled from {k} {k_word}, {n:,} people.",
}
OUTCOME = {
    "gone": "Not found.",
    "flipped": "It went the other way.",
    # 🔴 方向翻了、但量很小的那種要講出來。ep004 是 -0.54 → **+0.13**:
    #    方向確實相反、n=997 也顯著,所以判 flipped 沒錯 —— 但滿版紅字
    #    「IT REVERSED」配上「It went the other way.」讀起來像是發現了一個
    #    反向的**真效應**,而 0.13 連 Cohen 慣例的「小」(d 是 0.2)都不到。
    #    判決字只講方向不講大小,所以大小要由佐證那行補上,否則整張圖
    #    合起來講的比資料多。門檻取自 make_episode.thresholds —— 那是這條線
    #    的唯一來源,不在這裡另寫一組。
    "flipped_tiny": "It went the other way — but barely.",
    "shrunk_real": "Real, but much smaller.",
    "shrunk_real_nocmp": "Real, but small.",
    "held": "It held.",
    "stronger": "Even bigger.",
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
    """本集的效果量與樣本數。**直接讀 publish_meta 落下來的 `facts` 欄。**

    ## 為什麼不再用正規表示式從說明裡撈
    舊版是 `re.findall(r"([\d,]+) participants", description)` 取第一個。
    對 FReD 那批剛好對,對 `romantic_red` 就錯了:說明裡第一個出現的
    人數是 **602**(含 360 位女性的總量),而縮圖上那個數字是掛在
    效果量 0.09 上的 —— 0.09 是 **242 位男性**的值。於是同一支片,
    標題說 242、縮圖說 602。

    那不是正規表示式寫壞,是**拿替身值當真值**:說明是給人讀的散文,
    它的措辭改一個字,這裡撈到的東西就變了,而且不會有任何跡象。
    產生端已經把數字明寫成 `facts`,這裡照讀。

    fail-closed:沒有 `facts` 就不產。
    """
    f = o.get("facts")
    if not f:
        return None
    return f


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
    eo, n_r = f.get("es_o"), f.get("n_r")
    # 名案沒有 `has_original` 以外的線索;FReD 那批一定有原始研究。
    # 規模那句依「重做 vs 統合」選,不是依「有沒有原始研究」。
    # FReD 那 19 支全部是逐篇重做,所以預設 True。
    has_orig = f.get("is_replication", True)
    if n_r is None or (not has_orig and not f.get("k")):
        print(f"  跳過(數字不齊):{o['title'][:40]}")
        return False
    tone = o["tone"]
    # 判決字/顏色/佐證句**全部**用 copy_tone 的結果當 key ——
    # 原本它算得比用得晚,於是只有佐證那行接上了。
    from make_episode import copy_tone
    ctone = copy_tone(tone, f.get("es_r"), f.get("es_kind", "d"))
    col = COLOR[ctone]
    word = VERDICT[ctone]
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
    # 🔴 行距要**跟著字級走**。原本兩行寫死在 0.855 / 0.725(間距 0.13),
    #    字級卻是量出來的:短句(「THIS TEST REVEALS / YOUR HIDDEN BIAS」)
    #    量到的字級大,兩行就黏在一起;長句字級小,中間空一大塊。
    #    寫死間距配上浮動字級,必然有幾支難看,而難看是靜默的。
    #    上限 80 是版面算出來的:整塊置中在 0.795,上緣不能超過 0.97
    #    (出血)、下緣不能低於 0.615(判決塊頂端在 0.595)。
    fs1 = min(fit(plt, lines[0], 88), fit(plt, lines[1], 88), 80)
    gap = fs1 * (100 / 72) * 1.25 / H          # 1pt = 100/72 px,行距 1.25 倍
    for i, ln in enumerate(lines):
        ax.text(0.5, 0.795 + gap / 2 - i * gap, ln, ha="center", va="center",
                fontsize=fs1, color="#C6CCD4", weight="bold")

    # 判決塊:實色滿版,一眼看到成不成立。用字見 VERDICT 的說明 ——
    # punchy 但不 overclaim。
    ax.add_patch(plt.Rectangle((0.03, 0.235), 0.94, 0.36, color=col, zorder=2))
    ax.text(0.5, 0.415, word, ha="center", va="center",
            fontsize=fit(plt, word, 168, 0.86), color="#0E1116",
            weight="bold", zorder=3)

    # 佐證:數字從事實庫來,措辭依**資料裡有什麼**。降到最小 ——
    # 它是支持不是主角。
    key = ("shrunk_real_nocmp" if tone == "shrunk_real" and eo is None
           else ctone)
    sub = (SCALE[has_orig].format(n=int(n_r), k=f.get("k"),
                                  k_word=f.get("k_word") or "studies")
           + " " + OUTCOME[key])
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
