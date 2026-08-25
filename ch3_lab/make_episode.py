#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_episode.py — 吃 FReD 的一列,吐一支完整影片。

## 架構決定的理由
- **數字全部走模板填空,不經 LLM**。稿子裡每個數字都直接來自 FReD 欄位,
  生成後再過一次審核:稿中出現的數字必須在事實庫找得到,否則阻擋。
  (編造統計是主頻道踩過的紅線,這條產線從結構上不給它機會。)
- **畫面只做圖表**。效果量長條、樣本數對比、信賴線 —— 都是資料的直接呈現,
  不是美術。這是我唯一被證明做得好的形態。
- **白話主張用 FReD 的 description 欄**(claim_text_o 是論文結果段原文,不能唸)。

用法:
  python make_episode.py --list             # 看佇列
  python make_episode.py --row 0            # 產第 0 集
  python make_episode.py --row 0 --script-only
"""
import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import wave

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent                      # 絕對路徑:腳本可能從任何 cwd 被呼叫
QUEUE = ROOT / "facts" / "episode_queue.csv"
W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
ACCENT, WARN = "#4EA3F5", "#F5A54E"


# ── 事實 ────────────────────────────────────────────────────────────
_TYPO = {"criminial": "criminal", "positvely": "positively",
          "foregiveness": "forgiveness"}
_LEADIN = re.compile(r"^(we\s+(find|found|show|investigated)\s+(that\s+)?"
                     r"(the\s+hypothesis\s+that\s+)?)", re.I)


def speakable(claim):
    """把來源主張整成唸得出口的句子——只動唸稿,畫面上的引用仍是原文。

    來源是別人維護的資料庫,有拼字錯(criminial)、殘留的引號、以及
    作者第一人稱的開場(We investigated the hypothesis that …)。
    TTS 會照著唸,而唸錯字比看錯字更傷可信度。
    """
    c = claim.strip().strip('"').strip("“”").strip()
    c = _LEADIN.sub("", c)
    for bad, good in _TYPO.items():
        c = re.sub(bad, good, c, flags=re.I)
    return c.strip().rstrip(".")


def build_facts(row):
    """把一列 FReD 轉成本集事實庫。每個值都標明來源欄位。"""
    f = lambda k: (None if pd.isna(row.get(k)) else row.get(k))
    facts = {
        "claim": str(f("description") or "").strip().rstrip("."),
        "es_type": str(f("es_type_o") or "d").lower(),
        "orig": {"n": int(float(f("no"))), "es": round(float(f("eo")), 2),
                 "year": int(float(f("year_o"))) if f("year_o") else None,
                 "title": str(f("title_o") or "")[:120],
                 "author": str(f("author_o") or "")[:80],
                 "doi": str(f("doi_o") or "")},
        "repl": {"n": int(float(f("nr"))), "es": round(float(f("er")), 2),
                 "year": int(float(f("year_r"))) if f("year_r") else None,
                 "title": str(f("title_r") or "")[:120],
                 "doi": str(f("doi_r") or "")},
        "verdict": str(f("reported_success") or ""),
        "source": "FORRT Replication Database (FReD), OSF 2tbvd",
    }
    facts["n_ratio"] = round(facts["repl"]["n"] / max(1, facts["orig"]["n"]), 1)
    return facts


def size_word(es, kind):
    """Cohen(1988)的慣例門檻。說「按慣例算是大的」而不是斷言它就是大的。

    🔴 「小」之下要再分一層(2026-08-25)。舊版把 d=0.12 講成 essentially nothing,
    但那配上 N=6,608 多半是**統計上測得到、實務上很小**——講成「什麼都沒有」是
    過度打臉,而這個頻道的可信度全押在不過度打臉上。佇列裡 14/34 集落在這一帶,
    所以這不是邊角案例。真的可以說「幾乎是零」的門檻是 |d|<0.05。
    """
    a = abs(es)
    hi, mid, lo, floor = (0.5, 0.3, 0.1, 0.03) if kind.startswith("r") \
        else (0.8, 0.5, 0.2, 0.05)
    return ("large" if a >= hi else "medium" if a >= mid else "small" if a >= lo
            else "below what the convention calls small" if a >= floor
            else "essentially nothing")


def say_num(x):
    """讓 TTS 唸對小數:0.04 → 'zero point zero four'。"""
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
    out = words[whole] if whole in words else whole
    return out + " point " + " ".join(words[c] for c in frac)


# ── 稿子(模板填空,數字不經 LLM)──────────────────────────────────
def build_script(F):
    o, r = F["orig"], F["repl"]
    kind = F["es_type"]
    big, small = size_word(o["es"], kind), size_word(r["es"], kind)
    claim = speakable(F["claim"])
    claim = claim[0].upper() + claim[1:] if claim else claim
    verdict = F["verdict"].lower()

    # 🔴 收尾必須由**數字**決定,不能只看 verdict 欄位:
    #    實測第 3 集 verdict='mixed' 但 0.85→0.07,舊模板卻說「This one held up」,
    #    旁白與畫面上的長條圖直接矛盾。凡是宣稱都要能被畫面驗證。
    shrink = abs(r["es"]) / max(abs(o["es"]), 1e-6)
    if shrink <= 0.35:
        tone = "gone"
    elif shrink <= 0.7:
        tone = "shrunk"
    else:
        tone = "held"

    close_txt = {
        "gone": ("A bigger sample is not a guarantee of truth. But there is a reason "
                 "this keeps happening in one direction. A small study only gets "
                 "published if it finds something, so the first number published is "
                 "usually the luckiest one. That is called publication bias, and it is "
                 "not an accusation against anyone. It is a property of the filter. "),
        "shrunk": ("The effect did not vanish — it shrank. That happens often enough "
                   "to be worth noticing: the first, smallest study is usually the one "
                   "that reports the biggest number. "),
        "held": ("This one held up. That matters as much as the ones that don't, "
                 "because a finding that survives a much larger test is one you can "
                 "actually build on. "),
    }[tone]

    # 🔴 開場要分軌(2026-08-25):舊版一律用「It sounded plausible」起手,
    #    那是在預告要打臉。用在 HOLD 集上等於掉包觀眾——而 HOLD 集正是這個頻道
    #    不是一味打臉的證據,不能靠騙點擊進來。
    #
    #    ⚠️ HOLD 開場一度寫成「Most findings from that era did not survive」——
    #    那是斷言一個我沒計算的基準率。就算拿 FReD 去算也不能講:我手上這 348 列
    #    是篩過的子集,拿它當「那個年代的心理學」的比例就是拿替身值當真值。
    #    現在的版本只用本集自己的、已溯源的數字製造懸念。
    hook_txt = (f"In {o['year']}, a study reported this: {claim}. "
                f"It sounded plausible. It was published, and it was repeated."
                if tone != "held" else
                f"In {o['year']}, a study reported this: {claim}. "
                f"It was based on {o['n']:,} people. "
                f"Years later, another team ran it again on {r['n']:,} — "
                f"not to debunk it, just to check.")

    segs = [("hook", hook_txt),
            ("original",
             f"The study was run on {o['n']:,} people. "
             f"The effect it measured was {say_num(o['es'])} — "
             f"by the usual convention, a {big} effect."),
            ("scale",
             "A quick note on what that number means. "
             "Effect size is not the same as being true or false. "
             "It is how far apart two groups are. "
             "Around zero point two is small, zero point five is medium, "
             "zero point eight is large. "
             "And the smaller the study, the more that number can move by chance."),
            ("replication",
             f"So another team ran the same study again. "
             f"This time with {r['n']:,} people — "
             f"{F['n_ratio']} times the original sample. "
             f"Same design. More people."),
            ("result",
             f"The effect they measured was {say_num(r['es'])}. "
             + (f"That is {small}." if small != "essentially nothing"
                else "That is, essentially, nothing.")
             + f" The original number was {say_num(o['es'])}."
             # 🔴 作者自陳與數字打架時要講出來,不能安靜蓋掉(2026-08-25)。
             #    FReD 的 reported_success 記的是**重複研究團隊自己的結論**,
             #    有 verdict='successful' 但效果量掉到 0.02 的列——那通常是
             #    「成功證實了沒有效果」。安靜改口會讓觀眾以為我在挑對我有利的
             #    講法;講出來反而是最強的可信度證明。
             + (" The replication team recorded this as a successful replication. "
                "That is not a contradiction: what they successfully showed is that "
                "the effect is not there."
                if tone == "gone" and verdict == "successful" else "")),
            ("close", close_txt + "Both papers are linked below.")]
    return segs


def audit(segs, F):
    """稿中每個數字都必須能從事實庫反推,否則阻擋。"""
    allowed = set()
    for v in (F["orig"]["n"], F["repl"]["n"], F["orig"]["year"], F["repl"]["year"]):
        if v is not None:
            allowed |= {str(v), f"{v:,}"}
    allowed.add(str(F["n_ratio"]))
    # 主張原文本身帶的數字是**來源欄位逐字帶過來的**,不是我產生的 → 放行。
    # 審核的目的是擋「我編出來的數字」,不是擋引用。
    allowed |= set(re.findall(r"\d[\d,\.]*", F["claim"]))
    for v in (F["orig"]["es"], F["repl"]["es"]):
        allowed |= {f"{abs(v):.2f}", f"{abs(v):g}"}
    bad = []
    for name, text in segs:
        for tok in re.findall(r"\b\d[\d,\.]*\b", text):
            if tok not in allowed:
                bad.append((name, tok))
    return bad


# ── 畫面 ────────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams.update({"text.color": FG, "axes.labelcolor": DIM,
                         "xtick.color": DIM, "ytick.color": DIM})
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


def render_scene(plt, name, t, dur, F):
    o, r = F["orig"], F["repl"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)

    if name == "hook":
        lines = wrap(F["claim"] + ".", 44)[:4]
        for i, ln in enumerate(lines):
            st = 0.3 + i * 0.65
            if t > st:
                q = ease(min(1.0, (t - st) / 1.3))
                ax.text(0.5, 0.66 - i * 0.10, ln, ha="center", va="center",
                        fontsize=52, color=FG, alpha=q, weight="bold")
        if t > dur * 0.62:
            q = ease(min(1.0, (t - dur * 0.62) / 1.3))
            ax.text(0.5, 0.24, f"{o['author'].split(',')[0]}, {o['year']}",
                    ha="center", fontsize=24, color=DIM, alpha=q)

    elif name == "scale":
        marks = [(0.2, "small"), (0.5, "medium"), (0.8, "large")]
        ax2 = fig.add_axes([0.14, 0.34, 0.72, 0.16]); ax2.set_facecolor(BG)
        for sp in ("top", "right", "left"):
            ax2.spines[sp].set_visible(False)
        ax2.spines["bottom"].set_color("#2A2F36")
        ax2.set_yticks([]); ax2.set_xlim(0, 1.05)
        ax2.set_xlabel("effect size", fontsize=19, labelpad=12)
        ax2.tick_params(labelsize=16)
        p = ease(min(1.0, t / (dur * 0.5)))
        for v, lab in marks:
            if p > v / 1.05:
                ax2.axvline(v, color=DIM, lw=1.4, ls=(0, (4, 4)))
                ax2.text(v, 0.55, lab, ha="center", fontsize=20, color=DIM)
        if t > dur * 0.6:
            q = ease(min(1.0, (t - dur * 0.6) / 1.3))
            ax2.scatter([abs(o["es"])], [0], s=300, color=DIM, zorder=5, alpha=q)
            ax2.text(abs(o["es"]), -0.75, "this study", ha="center",
                     fontsize=19, color=FG, alpha=q)
        fig.text(0.14, 0.72, "What the number means", fontsize=42,
                 color=FG, weight="bold")
        fig.text(0.14, 0.65, "Smaller studies swing further by chance.",
                 fontsize=23, color=DIM)

    elif name in ("original", "replication"):
        cur = o if name == "original" else r
        label = "THE ORIGINAL STUDY" if name == "original" else "THE REPLICATION"
        col = DIM if name == "original" else ACCENT
        ax.text(0.5, 0.80, label, ha="center", fontsize=26, color=col,
                weight="bold", alpha=ease(min(1.0, t / 1.0)))
        if t > 1.0:
            q = ease(min(1.0, (t - 1.0) / 1.4))
            shown = int(cur["n"] * q)
            ax.text(0.5, 0.58, f"{shown:,}", ha="center", fontsize=118,
                    color=FG, weight="bold")
            ax.text(0.5, 0.47, "participants", ha="center", fontsize=30, color=DIM)
        if t > dur * 0.55:
            q = ease(min(1.0, (t - dur * 0.55) / 1.3))
            ax.text(0.5, 0.31, f"{F['es_type']} = {abs(cur['es']):.2f}",
                    ha="center", fontsize=52, color=col, weight="bold", alpha=q)
            ax.text(0.5, 0.23, f"{size_word(cur['es'], F['es_type'])} effect",
                    ha="center", fontsize=24, color=DIM, alpha=q)

    elif name == "result":
        ax2 = fig.add_axes([0.16, 0.30, 0.68, 0.36]); ax2.set_facecolor(BG)
        for s in ("top", "right", "left"):
            ax2.spines[s].set_visible(False)
        ax2.spines["bottom"].set_color("#2A2F36")
        mx = max(abs(o["es"]), abs(r["es"])) * 1.25
        p = ease(min(1.0, t / (dur * 0.5)))
        ax2.barh([1], [abs(o["es"]) * p], height=0.42, color=DIM)
        ax2.barh([0], [abs(r["es"]) * p], height=0.42, color=WARN)
        ax2.set_yticks([1, 0])
        ax2.set_yticklabels([f"original\n{o['n']:,} people",
                             f"replication\n{r['n']:,} people"], fontsize=19)
        ax2.set_xlim(0, mx); ax2.set_xlabel(f"effect size ({F['es_type']})",
                                            fontsize=19, labelpad=12)
        ax2.tick_params(labelsize=16)
        ax2.text(abs(o["es"]) * p, 1, f"  {abs(o['es']):.2f}", va="center",
                 fontsize=26, color=FG, weight="bold")
        if t > dur * 0.45:
            ax2.text(abs(r["es"]) * p, 0, f"  {abs(r['es']):.2f}", va="center",
                     fontsize=26, color=WARN, weight="bold")
        fig.text(0.16, 0.80, "Same study. Bigger sample.", fontsize=44,
                 color=FG, weight="bold")

    else:  # close
        msg = ("The effect did not survive." if F["verdict"].lower() == "failed"
               else "This one held up.")
        if t > 0.5:
            q = ease(min(1.0, (t - 0.5) / 1.3))
            ax.text(0.5, 0.66, msg, ha="center", fontsize=48, color=FG,
                    alpha=q, weight="bold")
        if t > 3.0:
            q = ease(min(1.0, (t - 3.0) / 1.4))
            ax.text(0.5, 0.46, "Every number in this video comes from",
                    ha="center", fontsize=22, color=DIM, alpha=q)
            ax.text(0.5, 0.40, "the published replication record.",
                    ha="center", fontsize=22, color=DIM, alpha=q)
            for i, d in enumerate([o["doi"], r["doi"]]):
                if d:
                    ax.text(0.5, 0.30 - i * 0.055,
                            d.replace("https://doi.org/", "doi:")[:60],
                            ha="center", fontsize=18, color=ACCENT, alpha=q * 0.9)
            ax.text(0.5, 0.15, F["source"], ha="center", fontsize=16,
                    color=DIM, alpha=q * 0.7)
    return fig


# ── 主流程 ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    ap.add_argument("--voice", default="am_michael")
    a = ap.parse_args()

    q = pd.read_csv(QUEUE)
    if a.list or a.row is None:
        print(f"佇列 {len(q)} 集:")
        for i, (_, r) in enumerate(q.head(25).iterrows()):
            print(f"  {i:>3}. {abs(float(r['eo'])):.2f}→{abs(float(r['er'])):.2f}  "
                  f"N {int(float(r['no']))}→{int(float(r['nr']))}  "
                  f"{str(r['description'])[:64]}")
        return 0

    row = q.iloc[a.row]
    F = build_facts(row)
    segs = build_script(F)
    bad = audit(segs, F)
    if bad:
        print("⛔ 稿中有事實庫查無來源的數字:", bad)
        return 1
    slug = f"ep{a.row:03d}"
    out = ROOT / "eps" / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(F, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{slug}] {F['claim'][:66]}")
    print(f"  {F['es_type']} {abs(F['orig']['es']):.2f}→{abs(F['repl']['es']):.2f}  "
          f"N {F['orig']['n']:,}→{F['repl']['n']:,}  判定 {F['verdict']}")
    print(f"  稿 {words} 字 ≈ {words / 155 * 60:.0f} 秒   數字溯源 ✓")
    for name, text in segs:
        (out / f"narr_{name}.txt").write_text(text, encoding="utf-8")
    if a.script_only:
        for name, text in segs:
            print(f"\n  [{name}] {text}")
        return 0

    # 旁白(3.11 venv 跑 Kokoro)
    tts = ROOT / "_tts_ep.py"
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        # 🔴 段落名從 segs 推導,不寫死:先前加了 scale 段卻沒同步,
        #    整條產線到混音階段才炸(seg_scale.wav 不存在)。
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        f"    s, sr = k.create(t, voice='{a.voice}', speed=0.98, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<12}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"), str(tts)],
                   check=True, cwd=str(REPO))

    plt = _plt()
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    for p in frames.glob("*.png"):
        p.unlink()
    idx, durs, parts, sr = 0, [], [], 24000
    for name, _ in segs:
        with wave.open(str(out / f"seg_{name}.wav")) as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
            nch = w.getnchannels()
            dur = w.getnframes() / sr + 0.7
        x = np.frombuffer(raw, np.int16)
        if nch > 1:
            x = x.reshape(-1, nch).mean(axis=1).astype(np.int16)
        parts.append(np.concatenate([x, np.zeros(max(0, int(dur * sr) - len(x)),
                                                 np.int16)]))
        durs.append(dur)
        for i in range(int(dur * FPS)):
            fig = render_scene(plt, name, i / FPS, dur, F)
            fig.savefig(frames / f"f{idx:05d}.png", facecolor=BG, dpi=100)
            plt.close(fig)
            idx += 1
        print(f"  畫面 {name:<12}{dur:5.1f}s")
    with wave.open(str(out / "voice.wav"), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.concatenate(parts).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(frames / "f%05d.png"), "-i", str(out / "voice.wav"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart",
                    str(out / f"{slug}.mp4")], check=True)
    for p in frames.glob("*.png"):
        p.unlink()
    frames.rmdir()
    print(f"完成 → {out / (slug + '.mp4')}  ({sum(durs):.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
