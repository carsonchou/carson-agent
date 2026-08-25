#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_famous.py — 名案集(意志力耗損、紅色效應、旁觀者效應…)。

## 為什麼不共用 make_episode.py
FReD 那條線是「一篇原始研究 對 一篇重複研究」,兩邊都有 N 和效果量。
名案不是那個形狀:它們被檢驗的方式是**綜合分析或多實驗室聯合重測**,
承重的數字是「多少個實驗室 / 多少個效果量」和「信賴區間有沒有跨過零」,
而原始研究的效果量常常根本不在摘要裡。硬塞進 FReD 的模板會扭曲事實。

改用「當年這篇有多大 → 後來多大規模的檢驗 → 得到什麼」的弧線。
「有多大」用**被引用次數**——那是可查證的硬數字,而且比效果量更能讓人
理解這篇當年的份量。

## 誠信
所有數字來自 facts/famous_episodes.json,那份是逐句人工核對過的(每筆附 quote)。
稿子產生後一律再過 audit():稿中每個數字都必須在本集事實裡找得到,否則不出片。
信賴區間跨過零時**一定要講出來**——那是「測不出來」與「證明沒有」的分界,
省略它就是把不確定講成確定。

用法:
  python make_famous.py --list
  python make_famous.py --slug ego_depletion
  python make_famous.py --slug ego_depletion --script-only
  python make_famous.py --all
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import wave

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
FACTS = ROOT / "facts" / "famous_episodes.json"
W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
ACCENT, WARN, GOOD = "#4EA3F5", "#F5A54E", "#5FC98A"


# ── 唸法 ────────────────────────────────────────────────────────────
def say_num(x, dec=None):
    """0.04 → 'zero point zero four'。

    🔴 負號一定要唸出來(2026-08-25)。舊版用 abs(),把信賴區間
    [-0.07, 0.15] 唸成「from zero point zero seven to zero point one five」——
    跨過零的區間被講成整段都在零的右邊,意思完全相反。
    小數位數跟著來源值走,不要補零:0.04 不能唸成「zero point zero four zero」。
    """
    if dec is None:
        s = f"{x!r}" if isinstance(x, float) else str(x)
        dec = len(s.split(".")[1]) if "." in s else 2
    s = f"{abs(x):.{dec}f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    whole, frac = s.split(".")
    w = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
         "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
    out = (w.get(whole, whole)) + " point " + " ".join(w[c] for c in frac)
    return ("minus " + out) if x < 0 else out


def say_int(n):
    return f"{n:,}"


# ── 稿子 ────────────────────────────────────────────────────────────
def build_script(E):
    t = E["test"]
    o = E.get("original")
    ci = t.get("ci")
    crosses = bool(ci and ci[0] <= 0 <= ci[1])
    es, kind = t["es"], t["es_kind"]
    # 兩組人分開測時(男/女)要講合計。合計值必須在事實庫裡**明確宣告**過
    # ——audit 只認事實庫裡有的數字,我當場相加算出來的它會擋,這是對的:
    # 稿子裡不該出現任何沒被登記過的數字。
    n_people = t.get("n_total", t["n"])

    segs = []
    if E["arc"] == "pair":
        # 引用數的份量差兩個數量級,同一句話撐不起來:4,928 次可以說
        # 「一整片心理學蓋在上面」,437 次不行——那會是我在灌水。
        weight = ("That is how much of psychology was built on top of it."
                  if o["cited_by"] >= 2000 else
                  "It became one of those findings that gets repeated in "
                  "magazines and TED talks without anyone rechecking it.")
        segs.append(("hook",
                     f"In {o['year']}, a study reported that {E['claim']}. "
                     f"It has been cited {say_int(o['cited_by'])} times. "
                     + weight))
        # 🔴 「彙整既有研究」和「重新做一次實驗」是兩件不同的事,不能共用一句話。
        #    綜合分析是把跑過的加起來;多實驗室重測是 23 個實驗室各自**重新**跑,
        #    而且方法事先登記。把後者講成前者,是把這條產線最硬的證據講軟了。
        n_str = ("over " if t.get("n_is_floor") else "") + say_int(t["n"])
        if not t.get("k"):
            test_txt = (f"In {t['year']}, it was tested again, "
                        f"on {say_int(n_people)} people, "
                        f"with the method registered in advance.")
        elif "meta" in t["kind"]:
            test_txt = (f"In {t['year']}, everything that had been run since was "
                        f"pooled — {t['k']} {t['k_word']}, "
                        f"covering {n_str} people.")
        else:
            test_txt = (f"In {t['year']}, {t['k']} {t['k_word']} ran it again — "
                        f"{n_str} people, one shared protocol, "
                        f"and every prediction registered before the data "
                        f"came in.")
        segs.append(("test", test_txt))
    else:
        # ⚠️ 這裡一度寫「被測過的次數幾乎多於心理學裡任何東西」——那是我沒有
        #    根據的最高級。改成只講本集查得到的事實:它被測過很多次,而我們把
        #    它們加起來。
        segs.append(("hook",
                     f"Here is a claim you have probably heard: {E['claim']}. "
                     f"It has been tested a lot of times, in a lot of small "
                     f"studies. So let's just add all of them up."))
        segs.append(("test",
                     f"In {t['year']}, researchers pooled "
                     f"{t['k']} {t['k_word']}, "
                     f"covering {say_int(t['n'])} people."))

    # 🔴 r 型和 d 型的慣例門檻不一樣(r 是 .1/.3/.5,d 是 .2/.5/.8)。
    #    拿 d 的尺去講 r 的數字,會把 r=.27 講成「小」,但按 r 的慣例那接近中等。
    segs.append(("scale",
                 "One number to keep in mind while we look at the result. "
                 "Effect size is not whether something is true. "
                 "It is how big the difference is. "
                 + ("For a correlation, around zero point one is small, "
                    "zero point three is medium, zero point five is large."
                    if kind == "r" else
                    "Around zero point two is small, zero point five is medium, "
                    "zero point eight is large.")))

    res = f"The answer was {say_num(es)}. "
    # 負號在這裡不是「比較小」,而是方向。不講出來,觀眾會以為效應不存在。
    if es < 0 and t.get("direction_note"):
        # ⚠️ 這句一度以「that is the size the original study described」收尾——
        #    我手上**沒有**原始研究的效果量,那個比較做不出來。只講方向。
        res += ("The minus sign here is the direction, not a shortfall: "
                "more people watching, less helping. So the effect is there, "
                "and it points the way the original study said it would. ")
    if t.get("es_second") is not None and E["slug"] == "romantic_red":
        res += (f"That was for the {say_int(t['n'])} men. "
                f"Among the {say_int(t['n_second'])} women, the effect ran the "
                f"other way — {say_num(t['es_second'])}. ")
    elif t.get("es_second") is not None:
        res += (f"For comparison, {t['second_label']} — simply asking people "
                f"what they think — predicted behaviour at "
                f"{say_num(t['es_second'])}. Higher. ")
    if ci:
        res += (f"The ninety-five percent confidence interval ran from "
                f"{say_num(ci[0])} to {say_num(ci[1])}. ")
        if crosses:
            res += ("That range includes zero. Which means this study cannot "
                    "tell you the effect is there at all.")
        else:
            res += "That range does not include zero. The effect is there."
    segs.append(("result", res))

    # 收尾要同時吃三件事:區間跨不跨零、效果量按**自己那把尺**算大算小、
    #    以及有沒有一個「原始研究」可以拿來對比(pooled 沒有,講了就是無中生有)。
    strong = abs(es) >= (0.2 if kind == "r" else 0.2)
    if crosses:
        close = ("Notice what that does not say. It does not say the effect is "
                 "fake. It says that after all of this, we still cannot "
                 "distinguish it from nothing — and that is a different, "
                 "more uncomfortable sentence. ")
    elif t.get("es_second") is not None and E["arc"] == "pooled":
        close = ("So the effect is real. But the measure that was supposed to "
                 "see past what people will admit did not beat simply asking "
                 "them. That is the part that rarely makes the headline. ")
    elif strong and E["arc"] == "pair":
        # ⚠️ 不能說「比你聽過的頭條版本小」——本檔沒有原始研究的效果量,
        #    那個比較我做不出來,講了就是憑感覺編。只講站得住的:規模差距。
        close = (f"So this one survives. It rests on far more people than the "
                 f"{o['year']} experiment that made it famous, and it is still "
                 f"there. ")
    elif strong:
        close = ("So this one survives — not on the strength of one striking "
                 "experiment, but on everything that has been run since. ")
    else:
        close = ("So the effect is real, and it is small. Both halves of that "
                 "sentence matter, and popular write-ups usually keep only "
                 "the first. ")
    segs.append(("close", close + "Every paper is linked below."))
    return segs


def audit(segs, E):
    """稿中每個數字都必須在事實庫找得到。找不到就不出片。"""
    t, o = E["test"], E.get("original") or {}
    allowed = set()

    def add(v):
        # 用 update 而不是 |=:後者會讓 allowed 變成這個閉包的區域變數
        if v is None:
            return
        if isinstance(v, int):
            allowed.update({str(v), f"{v:,}"})
        else:
            allowed.update({f"{abs(v):.2f}", f"{abs(v):.3f}", f"{abs(v):g}",
                            f"{abs(v):.2f}".lstrip("0"),
                            f"{abs(v):.3f}".lstrip("0"),
                            f"{abs(v):.3f}".rstrip("0").rstrip(".")})

    for v in (o.get("year"), o.get("cited_by"), t.get("year"), t.get("k"),
              t.get("n"), t.get("n_second"), t.get("n_total")):
        add(v)
    for v in (t.get("es"), t.get("es_second")):
        add(v)
    for c in (t.get("ci"), t.get("ci_second")):
        if c:
            add(c[0]); add(c[1])
    # 稿子裡的慣例門檻(0.2/0.5/0.8)是 Cohen 的公開慣例,不是本集數據
    allowed |= {"0.2", "0.5", "0.8"}
    allowed |= set(re.findall(r"\d[\d,\.]*", E["claim"]))

    bad = []
    for name, text in segs:
        for tok in re.findall(r"\b\d[\d,\.]*\b", text):
            if tok.rstrip(".") not in allowed and tok not in allowed:
                bad.append((name, tok))
    return bad


# ── 畫面 ────────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def ease(x):
    return x * x * (3 - 2 * x)


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


def render_scene(plt, name, t, dur, E):
    T, o = E["test"], E.get("original") or {}
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    # 🔴 一定要鎖死 0~1(2026-08-25)。本檔的圖表直接畫在這個滿版軸上,
    #    ax.plot 會**自動縮放**資料範圍——信賴區間 [-0.07, 0.15] 一畫下去,
    #    整個座標系就被拉成那個區間,所有 ax.text(0.5, …) 的文字全被裁到畫面外。
    #    結果是片子渲染成功、時長正確、只有圖形沒有半個字。
    #    (make_episode.py 沒中招純粹因為它把圖表畫在另一個子軸上。)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ci = T.get("ci")

    if name == "hook":
        lines = wrap(E["claim"][0].upper() + E["claim"][1:] + ".", 40)[:4]
        for i, ln in enumerate(lines):
            st = 0.3 + i * 0.6
            if t > st:
                q = ease(min(1.0, (t - st) / 1.2))
                ax.text(0.5, 0.68 - i * 0.11, ln, ha="center", va="center",
                        fontsize=54, color=FG, alpha=q, weight="bold")
        if o and t > dur * 0.55:
            q = ease(min(1.0, (t - dur * 0.55) / 1.2))
            ax.text(0.5, 0.24, f"cited {o['cited_by']:,} times",
                    ha="center", fontsize=46, color=ACCENT, alpha=q, weight="bold")
            ax.text(0.5, 0.16, f"{o['title'][:70]} ({o['year']})",
                    ha="center", fontsize=20, color=DIM, alpha=q)

    elif name == "test":
        # 規模:一格一個實驗室/樣本,填滿代表檢驗的廣度
        # 🔴 不是每一集都有 k。romantic_red 是**單一次登記重測**,沒有
        #    「多少個實驗室」可言——舊版 `T['k_word']` 直接 KeyError,
        #    而且是在渲染到一半才炸,把整批後面三集一起帶走。
        k = T.get("k")
        if k:
            cols = min(24, max(6, int(np.ceil(np.sqrt(k) * 1.6))))
            rows = int(np.ceil(k / cols))
            prog = ease(min(1.0, max(0.0, (t - 0.6) / max(0.1, dur * 0.5)))) * k
            for i in range(k):
                if i >= prog:
                    break
                cx = 0.5 + (i % cols - (cols - 1) / 2) * 0.032
                cy = 0.60 - (i // cols - (rows - 1) / 2) * 0.055
                ax.add_patch(plt.Rectangle((cx - 0.012, cy - 0.020), 0.024, 0.040,
                                           color=ACCENT, alpha=0.85))
            if t > 0.4:
                q = ease(min(1.0, (t - 0.4) / 1.0))
                ax.text(0.5, 0.86, f"{k} {T['k_word']}", ha="center",
                        fontsize=44, color=FG, alpha=q, weight="bold")
        elif T.get("n_second"):
            # 兩組分開測:畫兩塊面積,面積比就是人數比
            tot = T["n"] + T["n_second"]
            grow = ease(min(1.0, max(0.0, (t - 0.5) / max(0.1, dur * 0.45))))
            for x, n, lab, c in ((0.29, T["n"], "men", ACCENT),
                                 (0.71, T["n_second"], "women", "#B07FE0")):
                h = 0.34 * (n / tot) * 2 * grow
                ax.add_patch(plt.Rectangle((x - 0.11, 0.44), 0.22, h,
                                           color=c, alpha=0.85))
                if t > 0.9:
                    ax.text(x, 0.38, f"{n:,} {lab}", ha="center", fontsize=40,
                            color=c, weight="bold")
            if t > 0.4:
                ax.text(0.5, 0.88, "one registered replication", ha="center",
                        fontsize=42, color=FG, weight="bold")
        if t > dur * 0.55 and (k or not T.get("n_second")):
            q = ease(min(1.0, (t - dur * 0.55) / 1.2))
            pre = "over " if T.get("n_is_floor") else ""
            ax.text(0.5, 0.20, f"{pre}{T['n']:,} people",
                    ha="center", fontsize=52, color=FG, alpha=q, weight="bold")
        elif t > dur * 0.72 and T.get("n_total"):
            q = ease(min(1.0, (t - dur * 0.72) / 1.2))
            ax.text(0.5, 0.16, f"{T['n_total']:,} people in total", ha="center",
                    fontsize=46, color=FG, alpha=q, weight="bold")

    elif name == "scale":
        ax.plot([0.12, 0.88], [0.5, 0.5], color=DIM, lw=2)
        for x, lab in ((0.12, "0"), (0.31, "0.2\nsmall"), (0.50, "0.5\nmedium"),
                       (0.69, "0.8\nlarge"), (0.88, "1.0")):
            ax.plot([x, x], [0.47, 0.53], color=DIM, lw=2)
            ax.text(x, 0.40, lab, ha="center", va="top", fontsize=26, color=DIM)
        ax.text(0.5, 0.78, "effect size = how big the difference is",
                ha="center", fontsize=40, color=FG, weight="bold")

    elif name == "result":
        es = T["es"]
        # 主結果:數字 + 信賴區間橫條(跨零就標出來)
        q = ease(min(1.0, t / 1.2))
        col = WARN if (ci and ci[0] <= 0 <= ci[1]) else GOOD
        # 有兩組時大字要同時給兩個數字:只放一個而下面畫兩排,
        # 觀眾不知道上面那個是誰的(紅色那集男 +0.09 / 女 -0.09 方向相反)
        if T.get("es_second") is not None and T.get("ci_second"):
            big = f"{es:+.2f}  /  {T['es_second']:+.2f}"
            size = 104
        else:
            big = (f"{abs(es):.3f}".rstrip("0").rstrip(".")
                   if abs(es) < 0.1 else f"{es:.2f}")
            size = 150
        ax.text(0.5, 0.72, big, ha="center", fontsize=size, color=col,
                alpha=q, weight="bold")
        ax.text(0.5, 0.60, f"{T['es_kind']} — {T['kind']}, {T['year']}",
                ha="center", fontsize=26, color=DIM, alpha=q)
        if ci and t > 1.6:
            q2 = ease(min(1.0, (t - 1.6) / 1.4))
            # 🔴 有第二組時**兩排都要畫**(2026-08-25)。紅色那集旁白唸
            #    「女性那組是 minus 0.09」,畫面上卻只有男性的 0.09 ——
            #    觀眾聽到負數、看到正數,正是先前修過的「旁白與圖表打架」。
            rows = [(ci, es, T.get("group_a", ""))]
            if T.get("ci_second") and T.get("es_second") is not None:
                rows.append((T["ci_second"], T["es_second"],
                             T.get("group_b", "")))
            span = max(max(abs(v) for v in c) for c, _, _ in rows)
            span = max(span, max(abs(e) for _, e, _ in rows)) * 1.45 or 1
            x = lambda v: 0.5 + (v / span) * 0.34
            ys = [0.40] if len(rows) == 1 else [0.44, 0.29]
            for (c, e, lab), yy in zip(rows, ys):
                rc = col if len(rows) == 1 else (
                    ACCENT if yy == ys[0] else "#B07FE0")
                lo, hi = c
                ax.plot([x(lo), x(hi)], [yy, yy], color=rc, lw=9,
                        alpha=q2, solid_capstyle="round")
                for v in (lo, hi):
                    ax.plot([x(v), x(v)], [yy - .035, yy + .035], color=rc,
                            lw=4, alpha=q2)
                ax.plot([x(e)], [yy], marker="o", ms=18, color=FG, alpha=q2)
                if lab:
                    ax.text(0.10, yy, lab, ha="left", va="center",
                            fontsize=26, color=rc, alpha=q2, weight="bold")
                    ax.text(0.90, yy, f"{e:+.2f}", ha="right", va="center",
                            fontsize=28, color=rc, alpha=q2, weight="bold")
            top, bot = max(ys) + 0.09, min(ys) - 0.09
            ax.plot([x(0), x(0)], [bot, top], color=DIM, lw=2, ls="--", alpha=q2)
            ax.text(x(0), bot - 0.04, "zero", ha="center", fontsize=24,
                    color=DIM, alpha=q2)
            if len(rows) == 1:
                ax.text(0.5, 0.17, f"95% CI  [{ci[0]:.2f}, {ci[1]:.2f}]",
                        ha="center", fontsize=30, color=col, alpha=q2)
            crossing = [c for c, _, _ in rows if c[0] <= 0 <= c[1]]
            if crossing and t > 3.2:
                q3 = ease(min(1.0, (t - 3.2) / 1.2))
                msg = ("the range includes zero" if len(rows) == 1 else
                       "both ranges include zero")
                ax.text(0.5, 0.09, msg, ha="center",
                        fontsize=32, color=WARN, alpha=q3, weight="bold")
        elif T.get("es_second") is not None and t > 1.6:
            q2 = ease(min(1.0, (t - 1.6) / 1.4))
            lab2 = T.get("second_label", "the other group")
            ax.text(0.5, 0.40, f"{abs(T['es_second']):.3f}".rstrip("0"),
                    ha="center", fontsize=96, color=ACCENT, alpha=q2, weight="bold")
            ax.text(0.5, 0.30, lab2, ha="center", fontsize=28,
                    color=DIM, alpha=q2)

    elif name == "close":
        ax.text(0.5, 0.78, "Sources", ha="center", fontsize=40,
                color=FG, weight="bold")
        y = 0.62
        if o:
            for ln in wrap(f"{o['title']} ({o['year']})", 62)[:2]:
                ax.text(0.5, y, ln, ha="center", fontsize=24, color=DIM); y -= 0.055
            ax.text(0.5, y, f"doi:{o['doi']}", ha="center", fontsize=22,
                    color=ACCENT); y -= 0.09
        for ln in wrap(f"{T['title']} ({T['year']})", 62)[:2]:
            ax.text(0.5, y, ln, ha="center", fontsize=24, color=DIM); y -= 0.055
        ax.text(0.5, y, f"doi:{T['doi']}", ha="center", fontsize=22, color=ACCENT)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


# ── TTS ─────────────────────────────────────────────────────────────
def tts(segs, out_dir, voice="af_heart"):
    """走 3.11 的 Kokoro(本 venv 是 3.9,onnxruntime 版本對不上)。

    直譯器路徑與呼叫方式跟 make_episode.py 對齊——那份是實測跑得動的。
    自己另外猜一套(.venv/、kokoro_tts.say)的結果是整批 5 集全滅。
    """
    tts_py = ROOT / "_tts_famous.py"
    tts_py.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out_dir}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        # 段落名從 segs 推導,不寫死(make_episode 踩過:加了段落沒同步,
        # 整條線到混音才炸)
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        f"    s, sr = k.create(t, voice='{voice}', speed=0.98, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<12}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"),
                    str(tts_py)], check=True, cwd=str(REPO))


def wav_dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    eps = json.loads(FACTS.read_text(encoding="utf-8"))["episodes"]
    if a.list:
        for e in eps:
            t = e["test"]
            print(f"  {e['slug']:<22}{e['arc']:<8}"
                  f"{t['es_kind']}={t['es']:<7}N={t['n']:>7,}  {e['title'][:56]}")
        return 0

    todo = eps if a.all else [e for e in eps if e["slug"] == a.slug]
    if not todo:
        print("找不到,用 --list 看有哪些"); return 1

    for E in todo:
        print(f"\n[{E['slug']}] {E['title']}")
        segs = build_script(E)
        bad = audit(segs, E)
        if bad:
            print(f"  ⛔ 溯源失敗,以下數字不在事實庫:{bad}")
            continue
        words = sum(len(t.split()) for _, t in segs)
        print(f"  稿 {words} 字   數字溯源 ✓")
        out = ROOT / "eps_famous" / E["slug"]
        out.mkdir(parents=True, exist_ok=True)
        for n, t in segs:
            (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
        if a.script_only:
            for n, t in segs:
                print(f"  --- {n} ---\n  {t}")
            continue

        tts(segs, out)
        durs = {n: wav_dur(out / f"seg_{n}.wav") for n, _ in segs}

        plt = _plt()
        frames = out / "frames"
        frames.mkdir(exist_ok=True)
        import imageio.v2 as iio
        idx = 0
        for n, _ in segs:
            dur = durs[n] + 0.7
            for i in range(int(dur * FPS)):
                buf = render_scene(plt, n, i / FPS, dur, E)
                iio.imwrite(frames / f"f{idx:06d}.png", buf)
                idx += 1
            print(f"  畫面 {n:<12}{dur:>6.1f}s")

        # 併音軌
        voice = out / "voice.wav"
        with wave.open(str(voice), "wb") as w:
            first = True
            for n, _ in segs:
                with wave.open(str(out / f"seg_{n}.wav")) as s:
                    if first:
                        w.setparams(s.getparams()); first = False
                    w.writeframes(s.readframes(s.getnframes()))
                    w.writeframes(b"\x00" * int(0.7 * s.getframerate() *
                                                s.getsampwidth() * s.getnchannels()))
        mp4 = out / f"{E['slug']}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames / "f%06d.png"),
             "-i", str(voice), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-shortest", str(mp4)],
            check=True, capture_output=True)
        print(f"完成 → {mp4}  ({int(idx / FPS)}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
