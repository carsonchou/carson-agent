#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_domains.py — 第四種集型:同一個宣稱,跨多個領域。

## 為什麼需要它
`effect_scan.py` 量過 22 個候選,第一名是 **10,000 小時法則,分數 24,311
—— 第二名的 2.3 倍**。但它套不進現有的任何一種集型:

- FReD 那條(`make_episode`)要「一篇原始 對 一篇重測」的配對,沒有。
- 名案那條(`make_famous`)要一個效果量 d 或 r,而這篇統合分析的頭條
  數字是**變異數百分比**(26% / 21% / 18% / 4% / <1%)。
- 家族那條(`make_lineup`)要同一個效應的多次重測,這是同一個宣稱在
  不同領域的解釋力。

硬把 26% 換算成 r = 0.51 雖然數學上精確,螢幕上卻會出現一個**觀眾去查
論文查不到的數字**(論文寫 26%,我印 0.51)。寧可多一種集型,不要多一個
對不上的數字。

## 畫面的論證方式
不是印「26%」四個字 —— 那看起來很大。是畫一條滿格的橫條,把練習解釋掉
的那一段上色。26% 的條看起來就是四分之一,那才是這個數字真正的意思。
**視覺本身就是論證,而且它跟數字是同一個數字。**

用法:
  python make_domains.py --script-only
  python make_domains.py
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "facts" / "domain_episodes.json"

W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8ECF1", "#8A94A6"
ACCENT, REST = "#FFC23D", "#252C36"


def load(slug):
    d = json.loads(SRC.read_text(encoding="utf-8"))
    for e in d["episodes"]:
        if e["slug"] == slug:
            return e
    raise SystemExit(f"⛔ {slug} 不在 facts/domain_episodes.json 裡")


def say_pct(dm):
    """唸法。**上界要唸成上界。**

    `pct: 1, pct_is_upper_bound: true` 存的是「less than 1%」。
    唸成「one percent」是把一個上界講成一個點估計 —— 那是**往上報**,
    而且方向剛好讓故事沒那麼強;更重要的是它跟論文原文不一樣,
    觀眾去查會查到不同的字。
    """
    if dm.get("pct_is_upper_bound"):
        return f"less than {dm['pct']} percent"
    return f"{dm['pct']} percent"


def fmt_pct(dm):
    """**寫在畫面上**的百分比。跟 say_pct(唸的)是同一條規則的兩種形式。

    🔴 這兩個必須放在一起。第一版只有 say_pct,縮圖端自己寫了
    `f"{x['pct']}%"` —— 於是旁白唸「less than one percent」、縮圖印
    「1%」。同一個上界,兩個表面,兩種說法,而觀眾看到的是後者。
    今晚同型錯誤的第三次(前兩次:Shorts 標籤單數、預告判決塊)。
    """
    return f"{'<' if dm.get('pct_is_upper_bound') else ''}{dm['pct']}%"


def build_script(E):
    o, t = E["original"], E["test"]
    doms = t["domains"]
    by = {d["name"]: d for d in doms}
    return [
        ("hook",
         "How much you practise is what separates the best from everyone "
         "else. You have heard this one."),
        ("origin",
         f"It comes from a paper published in {o['year']}. Its claim was "
         f"that individual differences, even among elite performers, are "
         f"closely related to how much deliberate practice a person has "
         f"done. That paper has been cited more than "
         f"{o['cited_by_approx']:,} times."),
        ("test",
         f"In {t['year']}, researchers pooled every study they could "
         f"find that measured both things: how much people practised, and "
         f"how well they performed."),
        ("domains",
         "Here is how much of the difference in performance deliberate "
         "practice actually accounted for. "
         + " ".join(f"{d['name'].capitalize()}, {say_pct(d)}." for d in doms)),
        ("punch",
         f"Games is the best case, and even there it is about a quarter. "
         f"In professions - the place this idea gets quoted at work - it is "
         f"{say_pct(by['professions'])}."),
        ("verdict",
         "The authors' own conclusion was that deliberate practice is "
         "important, but not as important as has been argued. "
         "Practice is not nothing. It is just not the whole story."),
        ("close",
         "One claim, the numbers behind it, no adjectives."),
    ]


def audit(E, segs):
    """稿子裡每個數字都要在事實庫找得到。fail-closed。

    ⚠️ 用**數字邊界**比對,不是子字串。今晚 ep0 就是因為 `"1" in "12"`
    成立而給了假綠燈 —— 同一個錯不能在下一支再犯一次。
    """
    o, t = E["original"], E["test"]
    ok = {str(o["year"]), str(t["year"]), str(o["cited_by_approx"]),
          f"{o['cited_by_approx']:,}"}
    ok |= {str(d["pct"]) for d in t["domains"]}
    bad = []
    for name, txt in segs:
        for num in re.findall(r"\d(?:[\d,]*\d)?", txt):
            if num not in ok:
                bad.append((name, num))
    if bad:
        raise SystemExit(f"⛔ 稿子裡有溯源不到的數字:{bad}")
    # 缺的欄位不准出現在稿子裡(k 與 n 摘要沒給,我還沒讀原文)
    for miss in t.get("missing", []):
        raise_if = {"k": ("studies", "papers"), "n": ("participants",)}[miss]
        for name, txt in segs:
            for w in raise_if:
                if w in txt.lower():
                    raise SystemExit(
                        f"⛔ {name} 提到「{w}」,但事實庫把 {miss} 標成 "
                        f"missing(摘要沒給,我還沒讀原文)。不准填空。")
    print(f"  數字溯源 ✓（{len(ok)} 個可用值;"
          f"missing 欄位 {t.get('missing')} 沒被提到）")


def render_scene(name, t_now, dur, ctx):
    plt, E = ctx["plt"], ctx["E"]
    T = E["test"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ease = lambda x: 1 - (1 - x) ** 3
    a = ease(min(1.0, t_now / 0.7))

    def txt(y, s, fs, col=FG, w="bold", al=None, x=0.5, ha="center"):
        ax.text(x, y, s, ha=ha, va="center", fontsize=fs, color=col,
                weight=w, alpha=a if al is None else al)

    if name == "hook":
        txt(0.60, "Practice is what", 70)
        txt(0.47, "separates the best.", 70)
        if t_now > 2.0:
            b = ease(min(1.0, (t_now - 2.0) / 0.7))
            txt(0.30, E["popular_name"], 46, ACCENT, "bold", b)
    elif name == "origin":
        txt(0.66, str(E["original"]["year"]), 150, DIM)
        txt(0.48, "the paper everyone is quoting", 46, DIM, "normal")
        if t_now > 2.4:
            b = ease(min(1.0, (t_now - 2.4) / 0.7))
            txt(0.30, f"cited more than "
                      f"{E['original']['cited_by_approx']:,} times",
                58, ACCENT, "bold", b)
    elif name == "test":
        txt(0.60, str(T["year"]), 150, DIM)
        txt(0.42, "somebody added up every study", 52, FG, "normal")
    elif name in ("domains", "punch"):
        # 滿格的條 = 表現的全部差異。上色的那一段 = 練習解釋掉的部分。
        # 26% 印成字看起來很大,畫成條就是四分之一 —— 兩者是同一個數字。
        txt(0.93, "how much of the difference practice explains", 44, DIM,
            "normal")
        doms = T["domains"]
        for i, d in enumerate(doms):
            step = 1.6 if name == "domains" else 0.0
            if t_now < 0.3 + i * step:
                continue
            b = ease(min(1.0, (t_now - 0.3 - i * step) / 0.6))
            y = 0.76 - i * 0.135
            hot = (name == "punch" and d["name"] == "professions")
            ax.text(0.30, y, d["name"], ha="right", va="center", fontsize=46,
                    color=ACCENT if hot else FG, weight="bold", alpha=b)
            ax.add_patch(plt.Rectangle((0.34, y - 0.035), 0.52, 0.07,
                                       color=REST, alpha=b))
            frac = d["pct"] / 100 * 0.52
            ax.add_patch(plt.Rectangle((0.34, y - 0.035), frac, 0.07,
                                       color=ACCENT, alpha=b))
            lab = fmt_pct(d)
            ax.text(0.885, y, lab, ha="left", va="center", fontsize=44,
                    color=ACCENT if hot else DIM, weight="bold", alpha=b)
    elif name == "verdict":
        txt(0.66, "“important, but not as", 60, FG)
        txt(0.55, "important as has been argued”", 60, FG)
        txt(0.38, "— the authors, in the paper", 42, DIM, "normal")
    else:
        txt(0.60, "THEY RAN IT AGAIN", 92)
        txt(0.42, "one claim · the numbers behind it", 42, DIM, "normal")

    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = []
    for ob in list(ax.texts):
        bb = ob.get_window_extent(renderer=r)
        for v, lo, hi, side in ((bb.x0 / W, 0.02, 0.98, "左"),
                                (bb.x1 / W, 0.02, 0.98, "右"),
                                (bb.y0 / H, 0.03, 0.97, "下"),
                                (bb.y1 / H, 0.03, 0.97, "上")):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise SystemExit(f"⛔ {name} 越界:「{ob.get_text()[:22]}」"
                                 f"{side}緣 {v:.3f}")
        if (ob.get_alpha() or 1) >= 0.35:
            boxes.append((ob.get_text()[:22], bb))
    # 兩兩相交 —— 今晚在 Shorts 上抓到 16 支已上線的片有這個問題,
    # 新集型從第一支就帶著這道守門。
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ta, A), (tb, B) = boxes[i], boxes[j]
            ox = min(A.x1, B.x1) - max(A.x0, B.x0)
            oy = min(A.y1, B.y1) - max(A.y0, B.y0)
            if ox > 2 and oy > 2:
                raise SystemExit(f"⛔ {name} 文字重疊:「{ta}」×「{tb}」"
                                 f"{ox:.0f}×{oy:.0f} 畫素")
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
    ap.add_argument("--slug", default="10000_hour_rule")
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    E = load(a.slug)
    segs = build_script(E)
    print(f"[{a.slug}] {E['popular_name']}")
    audit(E, segs)
    words = sum(len(t.split()) for _, t in segs)
    print(f"  稿 {words} 字 ≈ {words / 2.6:.0f} 秒")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    out = ROOT / "eps_domain" / a.slug
    out.mkdir(parents=True, exist_ok=True)
    for n, t in segs:
        (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    from render_pipeline import tts, render_and_mux
    tts(out, segs)
    mp4, dur = render_and_mux(out, segs, render_scene, f"{a.slug}.mp4",
                              W, H, FPS, ctx={"plt": _plt(), "E": E})
    (out / "facts.json").write_text(json.dumps(E, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
    print(f"完成 → {mp4}  ({dur:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
