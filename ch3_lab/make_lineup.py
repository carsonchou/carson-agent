#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_lineup.py — 一個**效應家族**的全部重測,做成一支片。

## 為什麼要有這個集型
ch3 原本是「一篇研究 → 一支片」。那個格式的問題在 2026-08-30 量出來了:
它的題材**在 YouTube 上不存在** —— 搜「action identification mind
attribution」,20 筆結果裡標題真的在講那件事的是 **0 筆**。
27 支片、約 160 次觀看、YT_SEARCH 流量 0。

而同一天的結果頁掃描顯示,有名字的效應(social priming、anchoring、
loss aversion…)有真實需求而且**小頻道排得上去**。差別不在做得好不好,
在做的東西有沒有人找。

**但把單篇研究換成有名字的效應還不夠。** 主頻道的單片冠軍(4,590 分鐘、
訂閱 12,全頻道最高)是三檔 ETF 的對決,不是單一標的的查詢 ——
贏的是**綜合**。而綜合正是這條線唯一別人做不出來的東西:
FReD 的 348 列重測躺在本機,可以一次問「這整條研究路線後來怎麼了」。

所以這個集型的單位不是一篇論文,是**一個效應家族**。

## 誠信:這裡最容易出事的地方
把 15 個研究合成一句話,是**製造宣稱**的最短路徑。所以:
- 每個數字都從 CSV 算出來,`facts.json` 落檔,稿子過 `audit`
- **不說「priming 是假的」** —— 說「這 15 次重測量到的效果接近零」。
  測不到 ≠ 證明不存在,這條線的信譽全押在這個區別上
- **講清楚母體**:這是 FReD 裡符合條件的 15 列,不是文獻全部
- 有例外就講出來(15 個裡有 1 個重測後仍 ≥0.2、1 個方向翻轉)

用法:
  python make_lineup.py --list
  python make_lineup.py --family social_priming --script-only
  python make_lineup.py --family social_priming
"""
import argparse
import json
import re
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from make_episode import (BG, FG, DIM, ACCENT, WARN, FPS, H, W,   # noqa: E402
                          _plt, ease, say_num, speakable, thresholds, wrap)
import render_pipeline as rp                                       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "facts" / "fred_usable.csv"

#: 效應家族。`match` 是拿去比對 FReD `description` 的正規式(小寫)。
#: `name` 是**觀眾會搜的那個字**,不是論文語言 —— 這整個集型的前提。
#: `score` 是 2026-08-30 結果頁掃描的實測值,留著當選題依據。
FAMILIES = {
    "social_priming": {
        "name": "Social priming",
        "match": r"priming",
        "hook": "Read a word. Behave differently.",
        "scan": "切題 20/20、中位觀看 14,743、小頻道 11、中位訂閱 5,570",
    },
    "anchoring": {
        "name": "Anchoring",
        "match": r"anchor",
        "hook": "See a number. Guess closer to it.",
        "scan": "切題 20/20、中位觀看 12,708、小頻道 11、中位訂閱 7,580",
    },
}


#: FReD 的 `description` 有兩種東西混在一起:**被測的主張**,和**重測團隊
#: 自己的結論**(「It did not replicate: d = -0.02, p = .43」)。
#: 後者不能唸,兩個理由:
#:  1. 它跟我下一句要講的重複
#:  2. 🔴 **它跟數值欄會對不上**。實測 money priming 那一列:描述寫
#:     `d = -0.02, p = .43`,而欄位是 `er = +0.02, p = 0.44` ——
#:     符號和 p 值都不一樣。全 348 列裡有 3 列在描述裡寫了 d 值,
#:     **1 列符號不一致**。唸描述裡那個數字,就是唸一個沒有經過
#:     溯源守門的值,而且可能是錯的方向。
#: 所以只取主張,數字一律走欄位。
_VERDICT = re.compile(
    r"\s*(it (did not|failed to) replicate|the replication (failed|did not)|"
    r"we (failed|did not))\b.*$", re.I | re.S)
_LEAD = re.compile(r"^the replication tested whether\s+", re.I)


def claim_of(desc):
    """從 FReD 描述裡取出**被測的主張**,丟掉重測團隊的結論。"""
    t = _VERDICT.sub("", str(desc)).strip().rstrip(".")
    t = _LEAD.sub("", t).strip()
    return speakable(t)


def text_vs_column(desc, er):
    """描述裡寫的 d 值跟欄位對不對得上。對不上就回 True(要記錄)。"""
    m = re.search(r"\bd\s*=\s*(-?\d*\.?\d+)", str(desc))
    if not m:
        return False
    return (float(m.group(1)) < 0) != (float(er) < 0)


def collect(family):
    """把一個家族的所有 FReD 列整成事實。**只算,不編。**"""
    f = FAMILIES[family]
    q = pd.read_csv(SRC, low_memory=False).dropna(subset=["eo", "er", "no", "nr"])
    m = q["description"].astype(str).str.lower().str.contains(
        f["match"], na=False, regex=True)
    s = q[m].copy()
    if s.empty:
        raise SystemExit(f"⛔ {family} 在 FReD 裡沒有符合的列")
    p = pd.to_numeric(s["pval_value_r"], errors="coerce")
    # 🔴 缺 p 值的**不能當成不顯著**。缺就是缺,分開數,講的時候講清楚。
    n_sig = int((p < 0.05).sum())
    n_p = int(p.notna().sum())
    lo = thresholds(str(s["es_type_o"].iloc[0] or "d").lower())[2]
    items = []
    for _, r in s.iterrows():
        items.append({
            "claim": claim_of(r["description"]),
            "eo": round(float(r["eo"]), 2), "er": round(float(r["er"]), 2),
            "no": int(r["no"]), "nr": int(r["nr"]),
            "p": None if pd.isna(r.get("pval_value_r")) else float(r["pval_value_r"]),
            "doi_o": str(r.get("doi_o") or ""), "doi_r": str(r.get("doi_r") or ""),
        })
    items.sort(key=lambda x: -(x["nr"] / max(x["no"], 1)))
    conflicts = int(sum(text_vs_column(r["description"], r["er"])
                        for _, r in s.iterrows()))
    return {
        "family": family, "name": f["name"], "hook": f["hook"],
        "k": len(s),
        "es_kind": str(s["es_type_o"].iloc[0] or "d").lower(),
        "eo_med": round(float(s["eo"].median()), 2),
        "er_med": round(float(s["er"].median()), 2),
        "eo_lo": round(float(s["eo"].min()), 2), "eo_hi": round(float(s["eo"].max()), 2),
        "er_lo": round(float(s["er"].min()), 2), "er_hi": round(float(s["er"].max()), 2),
        "no_sum": int(s["no"].sum()), "nr_sum": int(s["nr"].sum()),
        "scale": round(float(s["nr"].sum() / s["no"].sum())),
        "n_sig": n_sig, "n_p": n_p,
        "n_still": int((s["er"].abs() >= lo).sum()),
        "n_flip": int(((s["eo"] > 0) != (s["er"] > 0)).sum()),
        "small_floor": lo,
        "papers_o": int(s["doi_o"].nunique()), "papers_r": int(s["doi_r"].nunique()),
        "items": items,
        # 資料源自我矛盾的列數。>0 時我不在片裡講方向 —— 見 claim_of。
        "text_col_conflicts": conflicts,
        "source": "FORRT Replication Database (FReD), OSF 2tbvd",
    }


def build_script(F):
    """稿。每個數字都在 F 裡,`audit` 會逐一查。"""
    top = F["items"][0]
    return [
        ("hook",
         f"{F['hook']} That is the claim behind {F['name'].lower()}. "
         f"It has been tested again — not once, but {F['k']} times."),
        ("original",
         f"Across {F['papers_o']} original papers, the effect sizes ran from "
         f"{say_num(F['eo_lo'])} to {say_num(F['eo_hi'])}, with a middle value of "
         f"{say_num(F['eo_med'])}. Those studies together used "
         f"{F['no_sum']:,} people."),
        ("retest",
         f"Then {F['papers_r']} replication papers ran the same tests on "
         f"{F['nr_sum']:,} people. That is {F['scale']} times the original sample."),
        ("collapse",
         f"The effects came back with a middle value of {say_num(F['er_med'])}, "
         f"ranging from {say_num(F['er_lo'])} to {say_num(F['er_hi'])}. "
         f"Of the {F['n_p']} replications that reported a p-value, "
         f"{F['n_sig']} reached the conventional cutoff."),
        ("standout",
         f"The widest gap: {top['claim']}. The first study measured "
         f"{say_num(top['eo'])} on {top['no']:,} people. The replication measured "
         f"{say_num(top['er'])} on {top['nr']:,}."),
        # 🔴 這一句**必須跟著資料分支**。原本寫死成「n_still 個仍然
        #    ≥ small,所以不能說效應不存在」—— 而 social_priming 的
        #    n_still 是 **0**,於是產出「它不證明效應不存在 —— 0 個仍然
        #    達到小效果」:每個數字都對,合起來自相矛盾。
        #    零存活時,「不能斷言不存在」的理由不是倖存者,而是
        #    「測不到」與「證明沒有」本來就是兩件事。
        ("caveat",
         "Two things this does not say. It does not say the original researchers "
         "did anything wrong. And it does not prove these effects are absent. "
         + (f"Not one of the {F['k']} came back at or above what the convention "
            f"calls small — but failing to find something is not the same as "
            f"showing it is not there. "
            if F["n_still"] == 0 else
            f"{F['n_still']} of {F['k']} still came back at or above what the "
            f"convention calls small. ")
         + "What it says is that at this sample size, these effects cannot be "
           "told apart from zero."),
        ("close",
         f"Every number here is one row of the {F['source']}. "
         f"{F['papers_o']} original papers, {F['papers_r']} replications, "
         f"all linked below."),
    ]


def audit(segs, F):
    """稿裡的數字都要在事實裡找得到 —— 跟 make_episode 同一條規矩。"""
    import re
    ok = set()
    for k in ("k", "no_sum", "nr_sum", "scale", "n_sig", "n_p", "n_still",
              "n_flip", "papers_o", "papers_r"):
        ok |= {str(F[k]), f"{F[k]:,}"}
    for k in ("eo_med", "er_med", "eo_lo", "eo_hi", "er_lo", "er_hi"):
        ok.add(f"{F[k]:.2f}"); ok.add(f"{F[k]}")
    for it in F["items"]:
        for k in ("eo", "er", "no", "nr"):
            ok |= {str(it[k]), f"{it[k]:,}", f"{it[k]:.2f}"}
        ok |= set(re.findall(r"\d[\d,\.]*", it["claim"]))
    ok |= set(re.findall(r"\d[\d,\.]*", F["source"]))   # OSF 識別碼不是宣稱
    bad = []
    for name, text in segs:
        for tok in re.findall(r"\d[\d,\.]*", text):
            t = tok.strip(".,")
            if t not in ok and t.lstrip("0") not in {x.lstrip("0") for x in ok}:
                bad.append((name, t))
    return bad


def render_scene(name, t, dur, F):
    plt = F["_plt"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)          # 🔴 鎖死,否則文字被裁

    if name == "hook":
        for i, ln in enumerate(wrap(F["hook"], 26)[:2]):
            ax.text(0.5, 0.62 - i * 0.11, ln, ha="center", va="center",
                    fontsize=72, color=FG, weight="bold",
                    alpha=ease(min(1.0, t / 0.8)))
        if t > 1.6:
            ax.text(0.5, 0.36, F["name"], ha="center", fontsize=44,
                    color=ACCENT, weight="bold",
                    alpha=ease(min(1.0, (t - 1.6) / 1.0)))
        if t > 2.8:
            ax.text(0.5, 0.27, f"{F['k']} replications", ha="center",
                    fontsize=34, color=DIM,
                    alpha=ease(min(1.0, (t - 2.8) / 1.0)))

    elif name in ("original", "retest"):
        big = F["no_sum"] if name == "original" else F["nr_sum"]
        lab = ("the original studies" if name == "original"
               else "the replications")
        ax.text(0.5, 0.70, f"{big:,}", ha="center", va="center", fontsize=190,
                color=FG if name == "original" else ACCENT, weight="bold",
                alpha=ease(min(1.0, t / 0.9)))
        ax.text(0.5, 0.55, f"people, {lab}", ha="center", fontsize=40, color=DIM,
                alpha=ease(min(1.0, t / 0.9)))
        if name == "retest" and t > 1.8:
            ax.text(0.5, 0.38, f"{F['scale']}× the original sample", ha="center",
                    fontsize=48, color=WARN, weight="bold",
                    alpha=ease(min(1.0, (t - 1.8) / 1.0)))
        if name == "original" and t > 1.8:
            ax.text(0.5, 0.38, f"{F['papers_o']} papers", ha="center",
                    fontsize=44, color=DIM,
                    alpha=ease(min(1.0, (t - 1.8) / 1.0)))

    elif name == "collapse":
        # 🔴 這一幕是整支片的理由:15 條線同時塌下來。
        #    單篇研究的片畫不出這張圖 —— 它需要一整個家族。
        ax2 = fig.add_axes([0.16, 0.16, 0.68, 0.60]); ax2.set_facecolor(BG)
        for sp in ("top", "right"):
            ax2.spines[sp].set_visible(False)
        for sp in ("bottom", "left"):
            ax2.spines[sp].set_color("#2A2F36")
        hi = max(max(abs(i["eo"]), abs(i["er"])) for i in F["items"])
        ax2.set_xlim(-0.12, 1.12); ax2.set_ylim(0, hi * 1.12)
        ax2.set_xticks([0, 1]); ax2.set_xticklabels(["original", "replication"],
                                                    fontsize=30, color=DIM)
        ax2.tick_params(axis="y", labelsize=22, colors=DIM)
        ax2.set_ylabel(f"effect size ({F['es_kind']})", fontsize=26, color=DIM,
                       labelpad=14)
        prog = ease(min(1.0, t / (dur * 0.55)))
        n_show = int(prog * len(F["items"]) + 0.001)
        for it in F["items"][:max(n_show, 0)]:
            ax2.plot([0, 1], [abs(it["eo"]), abs(it["er"])],
                     color="#5B6472", lw=2.4, alpha=0.85, zorder=2)
            ax2.scatter([0], [abs(it["eo"])], s=70, color=FG, zorder=3)
            ax2.scatter([1], [abs(it["er"])], s=70, color=ACCENT, zorder=3)
        if t > dur * 0.62:
            q = ease(min(1.0, (t - dur * 0.62) / 1.2))
            fig.text(0.5, 0.085,
                     f"{F['n_sig']} of {F['n_p']} reached p < 0.05",
                     ha="center", fontsize=52, color=WARN, weight="bold", alpha=q)
        fig.text(0.5, 0.88, "What happened when they ran it again",
                 ha="center", fontsize=46, color=FG, weight="bold")

    elif name == "standout":
        it = F["items"][0]
        for i, ln in enumerate(wrap(it["claim"], 40)[:3]):
            ax.text(0.5, 0.80 - i * 0.065, ln, ha="center", fontsize=34,
                    color=DIM, alpha=ease(min(1.0, t / 0.8)))
        if t > 1.2:
            q = ease(min(1.0, (t - 1.2) / 1.0))
            ax.text(0.30, 0.50, f"{abs(it['eo']):.2f}", ha="center", va="center",
                    fontsize=150, color=FG, weight="bold", alpha=q)
            ax.text(0.30, 0.37, f"{it['no']:,} people", ha="center",
                    fontsize=32, color=DIM, alpha=q)
            ax.text(0.50, 0.50, "→", ha="center", va="center", fontsize=90,
                    color=DIM, alpha=q)
        if t > 2.6:
            q = ease(min(1.0, (t - 2.6) / 1.0))
            ax.text(0.70, 0.50, f"{abs(it['er']):.2f}", ha="center", va="center",
                    fontsize=150, color=ACCENT, weight="bold", alpha=q)
            ax.text(0.70, 0.37, f"{it['nr']:,} people", ha="center",
                    fontsize=32, color=ACCENT, alpha=q)

    else:                                            # caveat / close
        txt = ("It does not prove the effect is absent."
               if name == "caveat" else F["source"])
        head = ("Two things this does not say" if name == "caveat"
                else "Where every number came from")
        ax.text(0.5, 0.66, head, ha="center", fontsize=54, color=FG,
                weight="bold", alpha=ease(min(1.0, t / 0.8)))
        if t > 1.2:
            q = ease(min(1.0, (t - 1.2) / 1.2))
            for i, ln in enumerate(wrap(txt, 44)[:3]):
                ax.text(0.5, 0.50 - i * 0.07, ln, ha="center", fontsize=34,
                        color=DIM, alpha=q)
        if name == "close" and t > 2.6:
            q = ease(min(1.0, (t - 2.6) / 1.2))
            ax.text(0.5, 0.26,
                    f"{F['papers_o']} original papers · {F['papers_r']} replications",
                    ha="center", fontsize=30, color=DIM, alpha=q)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    ap.add_argument("--voice", default="am_michael")
    a = ap.parse_args()

    if a.list or not a.family:
        print("可做的家族(依 2026-08-30 結果頁掃描):")
        for k, v in FAMILIES.items():
            try:
                F = collect(k)
                print(f"  {k:18s} {F['k']:>2d} 列  {F['eo_med']:.2f}→{F['er_med']:.2f}"
                      f"  {F['no_sum']:,}→{F['nr_sum']:,} 人")
                print(f"  {'':18s} {v['scan']}")
            except SystemExit as e:
                print(f"  {k:18s} {e}")
        return 0

    F = collect(a.family)
    segs = build_script(F)
    bad = audit(segs, F)
    if bad:
        print("⛔ 稿中有事實庫查無來源的數字:", bad)
        return 1
    out = ROOT / "eps_lineup" / a.family
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(F, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{a.family}] {F['name']}:{F['k']} 個重測")
    print(f"  {F['eo_med']:.2f} → {F['er_med']:.2f}   "
          f"{F['no_sum']:,} → {F['nr_sum']:,} 人({F['scale']}×)   "
          f"p<0.05:{F['n_sig']}/{F['n_p']}")
    print(f"  稿 {words} 字 ≈ {words / 155 * 60:.0f} 秒   數字溯源 ✓")
    for n, t in segs:
        (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    if a.script_only:
        for n, t in segs:
            print(f"\n  [{n}] {t}")
        return 0

    rp.tts(out, segs, voice=a.voice)
    F["_plt"] = _plt()
    mp4, secs = rp.render_and_mux(out, segs, render_scene,
                                  f"{a.family}.mp4", W, H, FPS, ctx=F)
    print(f"完成 → {mp4}  ({secs:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
