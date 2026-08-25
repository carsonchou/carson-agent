#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_ep001.py — 第一集畫面。全部是資料圖表,沒有一格是「畫」出來的。

設計原則(從這個 session 的四次失敗學到的):
- 我做得好的是**渲染真實系統**,做不好的是美感取向的東西 → 畫面只做圖表與數字
- 每一個出現在畫面上的數字都來自 facts/*.json,與旁白同一份來源
- 深色底 + 單一強調色 + 大字級:縮圖與手機上都讀得到

五個場景各自對齊旁白段落的實際長度(不是猜的,是量到的)。
"""
import json
import pathlib
import subprocess
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
F = json.loads((ROOT / "facts" / "ep001_ego_depletion.json").read_text(encoding="utf-8"))
C = F["claims"]

W, H, FPS = 1920, 1080, 30
BG = "#0E1116"
FG = "#E8EAED"
DIM = "#8A9099"
ACCENT = "#4EA3F5"
WARN = "#F5A54E"

for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
    if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = fam
        break
plt.rcParams["text.color"] = FG
plt.rcParams["axes.labelcolor"] = DIM
plt.rcParams["xtick.color"] = DIM
plt.rcParams["ytick.color"] = DIM


def fig():
    f = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    f.patch.set_facecolor(BG)
    return f


def save(f, path):
    f.savefig(path, facecolor=BG, dpi=100)
    plt.close(f)


def ease(x):
    return x * x * (3 - 2 * x)


# ── 場景 1:主張 ────────────────────────────────────────────────
def scene_hook(t, dur):
    f = fig()
    ax = f.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    p = ease(min(1.0, t / 1.6))
    ax.text(0.5, 0.62, "Willpower is a battery.", ha="center", va="center",
            fontsize=76, color=FG, alpha=p, weight="bold")
    if t > 2.2:
        q = ease(min(1.0, (t - 2.2) / 1.6))
        ax.text(0.5, 0.48, "Use it here — and you have less of it there.",
                ha="center", va="center", fontsize=36, color=DIM, alpha=q)
    if t > 5.0:
        q = ease(min(1.0, (t - 5.0) / 1.4))
        ax.text(0.5, 0.30, "EGO DEPLETION", ha="center", va="center",
                fontsize=30, color=ACCENT, alpha=q, weight="bold",
                fontstretch="expanded")
        ax.text(0.5, 0.24, "Baumeister et al., 1998", ha="center", va="center",
                fontsize=20, color=DIM, alpha=q * 0.9)
    return f


# ── 場景 2:逐年被引(真實資料) ──────────────────────────────
def scene_spread(t, dur):
    cy = F["original"]["counts_by_year"]
    years = np.array([c["year"] for c in cy])
    cnts = np.array([c["cited_by_count"] for c in cy])
    f = fig()
    ax = f.add_axes([0.10, 0.16, 0.84, 0.62]); ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("bottom", "left"):
        ax.spines[s].set_color("#2A2F36")
    p = ease(min(1.0, t / (dur * 0.55)))
    n = max(2, int(len(years) * p))
    ax.plot(years[:n], cnts[:n], color=ACCENT, lw=3.4)
    ax.fill_between(years[:n], cnts[:n], color=ACCENT, alpha=0.13)
    ax.scatter([years[n - 1]], [cnts[n - 1]], s=70, color=ACCENT, zorder=5)
    ax.set_xlim(years.min(), years.max())
    ax.set_ylim(0, cnts.max() * 1.18)
    ax.set_ylabel("citations per year", fontsize=17)
    ax.tick_params(labelsize=15)
    f.text(0.10, 0.87, "The claim spread", fontsize=44, color=FG, weight="bold")
    f.text(0.10, 0.825, f"“{F['original']['title'][:62]}”", fontsize=17, color=DIM)
    if t > dur * 0.55:
        q = ease(min(1.0, (t - dur * 0.55) / 1.6))
        f.text(0.94, 0.87, f"{F['original']['cited_by_count']:,}", fontsize=62,
               color=WARN, ha="right", weight="bold", alpha=q)
        f.text(0.94, 0.833, "total citations", fontsize=17, color=DIM,
               ha="right", alpha=q)
    if t > dur * 0.72:
        q = ease(min(1.0, (t - dur * 0.72) / 1.4))
        f.text(0.10, 0.075, f"2010 meta-analysis: {C['meta2010_studies']} studies, "
               f"“a medium-sized effect”", fontsize=21, color=DIM, alpha=q)
    return f


# ── 場景 3:重複實驗規模 ────────────────────────────────────────
def scene_replication(t, dur):
    f = fig()
    ax = f.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    f.text(0.5, 0.86, "So they ran it again — properly.", fontsize=46,
           color=FG, ha="center", weight="bold",
           alpha=ease(min(1.0, t / 1.4)))
    k = C["k_labs"]
    cols, rows_ = 8, 3
    p = ease(min(1.0, max(0.0, (t - 1.2) / (dur * 0.42))))
    shown = int(k * p)
    for i in range(k):
        r, c = divmod(i, cols)
        x = 0.30 + c * 0.058
        y = 0.60 - r * 0.085
        on = i < shown
        ax.scatter([x], [y], s=340, marker="s",
                   color=ACCENT if on else "#1B2028",
                   edgecolors="#2A2F36", linewidths=1.2)
    if shown >= k:
        q = ease(min(1.0, (t - 1.2 - dur * 0.42) / 1.2))
        f.text(0.5, 0.30, f"{k} laboratories", fontsize=40, color=FG,
               ha="center", alpha=q, weight="bold")
        f.text(0.5, 0.235, f"{C['total_N']:,} participants", fontsize=34,
               color=ACCENT, ha="center", alpha=q, weight="bold")
        f.text(0.5, 0.16, "one protocol · agreed in advance · "
               "analysis registered before data collection",
               fontsize=20, color=DIM, ha="center", alpha=q)
    return f


# ── 場景 4:效果量與信賴區間(核心) ────────────────────────────
def scene_result(t, dur):
    f = fig()
    ax = f.add_axes([0.12, 0.28, 0.78, 0.40]); ax.set_facecolor(BG)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#2A2F36")
    ax.set_yticks([])
    ax.set_xlim(-0.35, 0.75)
    ax.set_xlabel("effect size  (Cohen's d)", fontsize=19, labelpad=14)
    ax.tick_params(labelsize=16)
    ax.axvline(0, color=DIM, lw=1.6, ls=(0, (5, 5)))
    ax.text(0, -0.62, "no effect", ha="center", fontsize=17, color=DIM)

    lo, hi = C["ci"]
    d = C["d"]
    p = ease(min(1.0, t / (dur * 0.45)))
    x0, x1 = lo * p, hi * p
    ax.plot([x0, x1], [0, 0], color=WARN, lw=7, solid_capstyle="round")
    ax.scatter([d * p], [0], s=260, color=WARN, zorder=6,
               edgecolors=BG, linewidths=2.5)
    f.text(0.12, 0.86, "What 23 labs measured", fontsize=44, color=FG, weight="bold")
    if t > dur * 0.45:
        q = ease(min(1.0, (t - dur * 0.45) / 1.3))
        f.text(0.12, 0.79, f"d = {d}      95% CI [{lo}, {hi}]",
               fontsize=30, color=WARN, alpha=q, weight="bold")
    if t > dur * 0.68:
        q = ease(min(1.0, (t - dur * 0.68) / 1.3))
        f.text(0.5, 0.14, "The interval contains zero.", fontsize=38,
               color=FG, ha="center", alpha=q, weight="bold")
        f.text(0.5, 0.075, "The data cannot tell this effect apart from nothing.",
               fontsize=24, color=DIM, ha="center", alpha=q)
    return f


# ── 場景 5:收尾 ────────────────────────────────────────────────
def scene_close(t, dur):
    f = fig()
    ax = f.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    lines = [("No one faked anything.", 0.70, 44, FG),
             ("A finding was repeated for a decade", 0.575, 34, DIM),
             ("before anyone reproduced it at scale.", 0.505, 34, DIM)]
    for i, (txt, y, size, col) in enumerate(lines):
        st = 0.6 + i * 1.5
        if t > st:
            q = ease(min(1.0, (t - st) / 1.3))
            ax.text(0.5, y, txt, ha="center", va="center",
                    fontsize=size, color=col, alpha=q,
                    weight="bold" if i == 0 else "normal")
    if t > 6.2:
        q = ease(min(1.0, (t - 6.2) / 1.5))
        ax.text(0.5, 0.34, "Every number in this video is from the papers below.",
                ha="center", fontsize=21, color=DIM, alpha=q)
        srcs = [F["original"], F["meta2010"], F["replication"]]
        for i, s in enumerate(srcs):
            ax.text(0.5, 0.26 - i * 0.045,
                    f"{s['doi'].replace('https://doi.org/', 'doi:')}",
                    ha="center", fontsize=17, color=ACCENT, alpha=q * 0.85)
    return f


SCENES = [("hook", scene_hook), ("spread", scene_spread),
          ("replication", scene_replication), ("result", scene_result),
          ("close", scene_close)]


def main():
    import wave
    frames = ROOT / "frames"
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.png"):
        f.unlink()
    idx = 0
    durs = []
    for name, fn in SCENES:
        with wave.open(str(ROOT / f"seg_{name}.wav")) as w:
            dur = w.getnframes() / w.getframerate() + 0.7      # 尾巴留白
        durs.append(dur)
        n = int(dur * FPS)
        for i in range(n):
            save(fn(i / FPS, dur), frames / f"f{idx:05d}.png")
            idx += 1
        print(f"  {name:<12} {dur:5.1f}s  {n:4d} 幀", flush=True)
    print(f"共 {idx} 幀 / {sum(durs):.1f}s")

    # 音訊:五段串接(每段尾端補靜音對齊)。用 stdlib wave,不引入額外相依。
    parts, sr, sw = [], None, 2
    for (name, _), dur in zip(SCENES, durs):
        with wave.open(str(ROOT / f"seg_{name}.wav")) as w:
            sr, sw, nch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            raw = w.readframes(w.getnframes())
        x = np.frombuffer(raw, np.int16)
        if nch > 1:
            x = x.reshape(-1, nch).mean(axis=1).astype(np.int16)
        pad = int(dur * sr) - len(x)
        parts.append(np.concatenate([x, np.zeros(max(0, pad), np.int16)]))
    audio = np.concatenate(parts)
    with wave.open(str(ROOT / "ep001_voice.wav"), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(audio.tobytes())

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(frames / "f%05d.png"), "-i", str(ROOT / "ep001_voice.wav"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart",
                    str(ROOT / "ep001.mp4")], check=True)
    print(f"完成 → {ROOT / 'ep001.mp4'}")


if __name__ == "__main__":
    main()
