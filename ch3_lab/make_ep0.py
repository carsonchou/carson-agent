#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_ep0.py — 頻道預告 / 第零集。

## 為什麼要有這一支
ch3 有 25 集,每一集都是**一個孤立的數字**:某個效應被重測,結果是多少。
沒有任何理由訂閱 —— 看完一支,沒有下一支在等。
memory `yt-subscription-conversion-format-mismatch` 量過:EP0 是全頻道
最強的訂閱轉化器,而 ch3 從來沒有。

## 這支要講的東西必須是真的
戰績直接從 `publish_meta.json` 算,不手寫:

    25 集   重測總人數 58,653
    12 消失   6 撐住   4 變小但還在   2 反而更大   1 勉強翻向

**「6 撐住、2 更大」是這個頻道的護城河。** 如果每一集都是打臉,這個頻道
就只是一個抱怨;而且那也不是資料說的話。memory `yt-belief-buster-franchise`
記過同一條:不一律打臉,證實的那幾支才是差異化。

## 為什麼不再抄一份渲染碼
TTS、逐幀、mux 走 `render_pipeline.py` —— 那支就是為了這件事抽出來的。
這裡只負責「稿子寫什麼、畫面畫什麼」。

用法:
  python make_ep0.py --script-only     # 只看稿與戰績,不渲
  python make_ep0.py
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "eps_lineup" / "ep0"

W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8ECF1", "#8A94A6"
#: 判決色跟 Shorts 同一份(make_short.BUCKET_COLOR)。這裡直接匯入,
#: 不再寫一份 —— 顏色對不上就是同一支片自己說兩種話。
from make_short import BUCKET_COLOR                      # noqa: E402

#: 五種定調 → 桶。跟 make_episode.TONE_META 同一份,一樣用匯入的。
from make_episode import TONE_META, copy_tone            # noqa: E402


#: 畫面上的四組。**點的顏色、標籤的數字、旁白唸的數字全部從這裡來** ——
#: 三個表面一份分類。第一版點用三桶、標籤用五類,結果 13 顆橘點配
#: 「12 gone」。
GROUP_LABEL = {
    "gone": "gone",
    "shrunk": "smaller, still there",
    "flipped": "went the other way",
    "held": "held up",
}
GROUP_ORDER = {"gone": 0, "shrunk": 1, "flipped": 2, "held": 3}
GROUP_COLOR = {
    "gone": BUCKET_COLOR["fail"],
    "shrunk": BUCKET_COLOR["mixed"],
    # 翻向要自己一個顏色。歸進 fail 色就是把「方向相反」講成「沒有效應」,
    # 而那兩件事在片裡是分開講的。
    "flipped": "#C88FD4",
    "held": BUCKET_COLOR["held"],
}


def group_of(r):
    """一集屬於哪一組。判準只有這一個。"""
    t = r["tone"]
    if t in ("held", "stronger"):
        return "held"
    if t in ("flipped", "flipped_tiny"):
        return "flipped"
    return "shrunk" if t == "shrunk_real" else "gone"


def tally():
    """從 publish_meta 算戰績。**一個數字都不手寫。**"""
    m = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    rows, n_sum = [], 0
    for o in m:
        f = o.get("facts") or {}
        if not f or f.get("n_r") is None:
            continue
        ct = copy_tone(o["tone"], f.get("es_r"), f.get("es_kind", "d"))
        rows.append({"slug": o.get("slug") or o["dir"].split("/")[-1],
                     "tone": ct, "bucket": TONE_META[o["tone"]]["bucket"],
                     "es_r": f.get("es_r"), "n_r": int(f["n_r"])})
        n_sum += int(f["n_r"])
    c = {}
    for r in rows:
        c[r["tone"]] = c.get(r["tone"], 0) + 1
    # 四組的數字**從 group_of 數出來**,跟畫面上點的顏色同一個來源。
    g = {k: sum(1 for r in rows if group_of(r) == k) for k in GROUP_LABEL}
    if sum(g.values()) != len(rows):
        raise SystemExit(f"⛔ 分組加總 {sum(g.values())} ≠ {len(rows)}")
    return {"rows": rows, "k": len(rows), "n_sum": n_sum, "counts": c,
            "gone": g["gone"], "shrunk": g["shrunk"],
            "flipped": g["flipped"], "survived": g["held"],
            "held": c.get("held", 0), "stronger": c.get("stronger", 0)}


def say(n):
    """數字唸法。TTS 對「58,653」會唸成「五萬八千六百五十三」,
    但對逗號的處理各家不一 —— 這裡把逗號拿掉交給它自己斷。"""
    return f"{n:,}".replace(",", ",")


def build_script(T):
    """六段,約 95 秒。

    🔴 **第四段不能只講失敗。** 只講 12 個消失,這支片就是在宣稱
    「重測都會失敗」,而我自己的資料說 8 個活下來。那是拿一半的事實
    當全部,而且方向剛好讓故事更聳動 —— 這條線今天已經在三個地方
    修過同型的東西。
    """
    return [
        ("hook",
         "You have probably heard that a lot of famous psychology "
         "experiments do not hold up. That is true. But which ones?"),
        ("method",
         "This channel does one thing. We take a claim you have heard, "
         "find the study it came from, then find out what happened when "
         "somebody ran it again with more people. Every number comes from "
         "the published record, and every paper is named on screen."),
        ("scale",
         f"So far that is {T['k']} claims, and "
         f"{say(T['n_sum'])} people in the replications."),
        ("verdict",
         f"{T['gone']} of them are gone. The retest could not tell them "
         f"apart from nothing. {T['shrunk']} came back smaller but still "
         f"there. {T['flipped']} went the other way. And {T['survived']} "
         f"held up, {T['stronger']} of them larger than the original."),
        ("why",
         "That last part is the reason this channel exists. If everything "
         "failed, this would just be a complaint. It is not. Some findings "
         "survive being tested properly, and those are the ones actually "
         "worth knowing."),
        ("close",
         "One claim, two numbers, no adjectives. Start with the ones "
         "that held."),
    ]


def audit(T, segs):
    """稿子裡的每個數字都要在戰績裡找得到。

    🔴 這是 fail-closed:對不上就不產。標題和旁白是觀眾唯一一定會接觸到
    的東西,在那裡放一個算錯的數字比片子裡錯還嚴重。
    """
    import re
    ok = {str(T[k]) for k in ("k", "gone", "held", "stronger", "shrunk",
                              "flipped", "survived")}
    ok |= {f"{T['n_sum']:,}", str(T["n_sum"])}
    bad = []
    for name, txt in segs:
        for num in re.findall(r"\d[\d,]*", txt):
            if num not in ok:
                bad.append((name, num))
    if bad:
        raise SystemExit(f"⛔ 稿子裡有溯源不到的數字:{bad}")
    # 🔴 這裡的第一版寫的是「T['gone']+T['shrunk']+... == T['k']」——
    #    那**永遠成立**,因為它是拿 tally 自己的分類去驗 tally 自己的總數,
    #    跟旁白講了幾類完全無關。實測:旁白漏講「勉強翻向」那一類(講了
    #    24 個、畫面畫 25 個點),而這個檢查照樣印綠燈。
    #    「寫完檢查先故意讓它失敗一次」——這一個我沒做,於是它第一次跑
    #    就給了假綠燈。改成驗**旁白文字裡真的出現了每一類的數字**。
    # ⚠️ **不能用 `str(v) in said`。** T["flipped"] 是 1,而旁白開頭就是
    #    「12 of them are gone」—— `"1" in "12..."` 成立,於是把那一類整段
    #    刪掉之後檢查照樣通過。第二個假綠燈,同一個檢查、同一輪。
    #    要的是「這個數字自己」,所以前後都不能再接數字。
    said = " ".join(t for n, t in segs if n == "verdict")
    missing = [lab for lab, v in (("消失", T["gone"]), ("變小", T["shrunk"]),
                                  ("翻向", T["flipped"]),
                                  ("撐住", T["survived"]))
               if not re.search(rf"(?<!\d){v}(?!\d)", said)]
    if missing:
        raise SystemExit(
            f"⛔ 旁白沒交代這幾類:{missing} —— 畫面上會畫 {T['k']} 個點,"
            f"觀眾數得出來,對不上就是自己拆自己的台。")
    print(f"  數字溯源 ✓（{len(ok)} 個可用值;四類判決旁白都有交代）")


def render_scene(name, t, dur, ctx):
    """一幀。ctx 帶 tally 結果與 plt。"""
    plt, T = ctx["plt"], ctx["T"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ease = lambda x: 1 - (1 - x) ** 3
    a = ease(min(1.0, t / 0.7))

    def txt(y, s, fs, col=FG, w="bold", al=None):
        ax.text(0.5, y, s, ha="center", va="center", fontsize=fs,
                color=col, weight=w, alpha=a if al is None else al)

    if name == "hook":
        txt(0.60, "Famous experiments.", 74)
        if t > 1.6:
            b = ease(min(1.0, (t - 1.6) / 0.7))
            ax.text(0.5, 0.44, "Run again.", ha="center", va="center",
                    fontsize=88, color="#FFC23D", weight="bold", alpha=b)
    elif name == "method":
        steps = ["a claim you have heard",
                 "the study it came from",
                 "what happened when they ran it again"]
        for i, s in enumerate(steps):
            if t > 0.4 + i * 1.6:
                b = ease(min(1.0, (t - 0.4 - i * 1.6) / 0.7))
                ax.text(0.13, 0.72 - i * 0.19, f"{i + 1}", ha="center",
                        va="center", fontsize=64, color="#FFC23D",
                        weight="bold", alpha=b)
                ax.text(0.22, 0.72 - i * 0.19, s, ha="left", va="center",
                        fontsize=52, color=FG, alpha=b)
    elif name == "scale":
        txt(0.63, str(T["k"]), 220)
        txt(0.45, "claims retested", 46, DIM, "normal")
        if t > 1.8:
            b = ease(min(1.0, (t - 1.8) / 0.7))
            ax.text(0.5, 0.30, f"{T['n_sum']:,} people", ha="center",
                    va="center", fontsize=76, color="#FFC23D",
                    weight="bold", alpha=b)
    elif name == "verdict":
        # 每一集一個點,依判決上色。**點的總數就是集數** —— 觀眾數得出來,
        # 所以它不能跟旁白講的數字對不上。
        # 🔴 點的顏色和下面的標籤**必須出自同一個分類**。
        #    第一版點用 `bucket`(三桶)、標籤用 `copy_tone`(五類):
        #    flipped_tiny 被歸進 fail 桶,於是畫面上 13 顆橘點、標籤寫
        #    「12 gone」。觀眾數得出來,而我的稿子檢查只驗旁白、驗不到
        #    畫面。今天第四個「同一件事兩份分類」。
        rows = sorted(T["rows"], key=lambda r: GROUP_ORDER[group_of(r)])
        cols, size = 10, 0.055
        x0, y0 = 0.5 - (cols - 1) * size / 2, 0.66
        for i, r in enumerate(rows):
            if t < 0.3 + i * 0.09:
                continue
            b = ease(min(1.0, (t - 0.3 - i * 0.09) / 0.5))
            # 🔴 `plt.Circle` 在 axes 分數座標下畫的是**橢圓** ——
            #    x 軸一格 = 1920px、y 軸一格 = 1080px,同一個半徑在兩軸
            #    對應的畫素數差 1.78 倍。抽幀看到的是一排被壓扁的藥丸。
            #    用 Ellipse 把高度乘回長寬比才是圓。
            from matplotlib.patches import Ellipse
            ax.add_patch(Ellipse(
                (x0 + (i % cols) * size, y0 - (i // cols) * size * (W / H)),
                width=0.038, height=0.038 * (W / H),
                color=GROUP_COLOR[group_of(r)], alpha=b))
        if t > 2.8:
            b = ease(min(1.0, (t - 2.8) / 0.7))
            for i, (g, lab) in enumerate(GROUP_LABEL.items()):
                n = sum(1 for r in T["rows"] if group_of(r) == g)
                ax.text(0.5, 0.295 - i * 0.072, f"{n}  {lab}", ha="center",
                        va="center", fontsize=42,
                        color=GROUP_COLOR[g], weight="bold", alpha=b)
    elif name == "why":
        txt(0.62, f"{T['survived']} of {T['k']} held up.", 78)
        if t > 1.8:
            b = ease(min(1.0, (t - 1.8) / 0.7))
            ax.text(0.5, 0.42, "That is the point.", ha="center",
                    va="center", fontsize=56, color=DIM,
                    weight="normal", alpha=b)
    else:
        txt(0.60, "THEY RAN IT AGAIN", 92)
        txt(0.42, "one claim · two numbers · no adjectives", 42, DIM,
            "normal")

    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    for o in list(ax.texts):
        bb = o.get_window_extent(renderer=r)
        for v, lo, hi, side in ((bb.x0 / W, 0.03, 0.97, "左"),
                                (bb.x1 / W, 0.03, 0.97, "右"),
                                (bb.y0 / H, 0.04, 0.96, "下"),
                                (bb.y1 / H, 0.04, 0.96, "上")):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise SystemExit(
                    f"⛔ {name} 版面越界:「{o.get_text()[:24]}」"
                    f"{side}緣 {v:.3f} 不在 [{lo}, {hi}]")
    import numpy as np
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    T = tally()
    segs = build_script(T)
    print(f"[ep0] {T['k']} 集 · {T['n_sum']:,} 人 · "
          f"消失 {T['gone']} / 變小 {T['shrunk']} / 撐住 {T['survived']}")
    audit(T, segs)
    words = sum(len(t.split()) for _, t in segs)
    print(f"  稿 {words} 字 ≈ {words / 2.6:.0f} 秒")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for n, t in segs:
        (OUT / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    # 🔴 **先寫 facts.json,再渲。** preflight 的判準是「mp4 比 facts.json
    #    舊 = 渲染死在寫 facts 之後、mux 之前」——那是對的,而我把順序寫反了
    #    (渲完才寫),於是每一支新集型都會被判成陳舊而**擋在發布前**。
    #    修產線對齊慣例,不要去改那道守門。
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facts.json").write_text(json.dumps(T, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
    from render_pipeline import tts, render_and_mux
    tts(OUT, segs)
    mp4, dur = render_and_mux(OUT, segs, render_scene, "ep0.mp4", W, H, FPS,
                              ctx={"plt": _plt(), "T": T})
    print(f"完成 → {mp4}  ({dur:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
