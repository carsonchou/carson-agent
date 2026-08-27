#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_short.py — 從已完成的集數剪一支直式 Short 當引流。

## 為什麼做 Shorts(以及它的代價)
記憶裡有一條硬事實:**Shorts 的觀看不計入 YPP 的 4,000 小時**,而且主頻道
實測 Shorts 的訂閱轉化只有長片的十分之一(0.05% vs 0.46%)。所以在一個
已經有觀眾的頻道上,Shorts 是錯的選擇。

但這個頻道現在是 **10 支片、2 次觀看、0 訂閱** —— 沒有任何分發管道。
YPP 是「有觀眾之後」的問題,現在的問題是**一個觀眾都沒有**。而 Shorts 是
零訂閱頻道唯一會被演算法主動推的格式。

所以定位很明確:**Short 負責被發現,長片負責累積時數**。Short 的說明第一行
就導到完整版,不是取代它。

## 誠信
數字與定調一律沿用該集的事實庫,不重算、不加強。Short 只是把同一個結論
講得更短 —— 它沒有版面放信賴區間,所以**也不做存在性斷言**,只呈現
「當年 X → 重測 Y」這個可驗證的對比,結論留給完整版。

用法:
  python make_short.py --slug ego_depletion
  python make_short.py --row 3
"""
import argparse
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
W, H, FPS = 1080, 1920, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
BUCKET_COLOR = {"fail": "#F5A54E", "mixed": "#8FA3C8", "held": "#5FC98A"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
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


def build_script(D):
    """三段,約 32 秒。刻意不下存在性結論 —— 那需要信賴區間,而這裡沒有版面。"""
    return [
        ("q", f"{D['question']}"),
        ("nums", f"The original study measured {D['say_o']} on "
                 f"{D['n_o']:,} people. "
                 f"The replication measured {D['say_r']} on {D['n_r']:,}."),
        ("end", "The full breakdown, with both papers and the record it comes "
                "from, is on the channel."),
    ]


def render(plt, name, t, dur, D):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    col = D["color"]

    if name == "q":
        for i, ln in enumerate(wrap(D["question"], 20)[:6]):
            st = 0.15 + i * 0.35
            if t > st:
                q = ease(min(1.0, (t - st) / 0.8))
                ax.text(0.5, 0.72 - i * 0.062, ln, ha="center", va="center",
                        fontsize=66, color=FG, alpha=q, weight="bold")
    elif name == "nums":
        # 直式:上下對比而不是左右,手機上讀起來才順
        if t > 0.3:
            q = ease(min(1.0, (t - 0.3) / 0.9))
            ax.text(0.5, 0.72, f"{D['es_o']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=210, color=DIM,
                    alpha=q, weight="bold")
            ax.text(0.5, 0.635, f"the original — {D['n_o']:,} people",
                    ha="center", fontsize=40, color=DIM, alpha=q)
        if t > 1.8:
            q = ease(min(1.0, (t - 1.8) / 0.9))
            ax.text(0.5, 0.52, "↓", ha="center", va="center", fontsize=90,
                    color=DIM, alpha=q)
        if t > 2.6:
            q = ease(min(1.0, (t - 2.6) / 0.9))
            ax.text(0.5, 0.37, f"{D['es_r']:+.2f}".replace("+", ""),
                    ha="center", va="center", fontsize=230, color=col,
                    alpha=q, weight="bold")
            ax.text(0.5, 0.28, f"the replication — {D['n_r']:,} people",
                    ha="center", fontsize=40, color=col, alpha=q)
        if t > 4.4:
            q = ease(min(1.0, (t - 4.4) / 0.9))
            ax.text(0.5, 0.17, D["card"], ha="center", fontsize=52,
                    color=FG, alpha=q, weight="bold")
    else:
        ax.text(0.5, 0.60, "Full episode", ha="center", fontsize=64,
                color=FG, weight="bold")
        ax.text(0.5, 0.52, "on the channel", ha="center", fontsize=64,
                color=FG, weight="bold")
        ax.text(0.5, 0.40, D["source"], ha="center", fontsize=30, color=DIM)

    ax.text(0.5, 0.055, "THEY RAN IT AGAIN", ha="center", fontsize=34,
            color="#3C4450", weight="bold")
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def collect(slug=None, row=None):
    """從既有的事實庫組出 Short 需要的欄位 —— 不重算任何數字。"""
    from make_episode import (build_facts, say_num, CARD_TEXT, TONE_META)
    if row is not None:
        import pandas as pd
        q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
        F = build_facts(q.iloc[row])
        meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
        title = next(o["title"] for o in meta
                     if o.get("row") == row)
        return {
            "key": f"ep{row:03d}",
            "question": title.split(" — ")[0].split("? ")[0].rstrip(".") + "?"
            if "?" not in title else title[:title.index("?") + 1],
            "es_o": F["orig"]["es"], "es_r": F["repl"]["es"],
            "n_o": F["orig"]["n"], "n_r": F["repl"]["n"],
            "say_o": say_num(F["orig"]["es"]), "say_r": say_num(F["repl"]["es"]),
            "card": CARD_TEXT[F["tone"]],
            "color": BUCKET_COLOR[TONE_META[F["tone"]]["bucket"]],
            "source": F["source"],
        }
    eps = json.loads((ROOT / "facts" / "famous_episodes.json")
                     .read_text(encoding="utf-8"))["episodes"]
    E = next(e for e in eps if e["slug"] == slug)
    t, o = E["test"], E.get("original")
    from make_famous import say_num as fsay
    ci = t.get("ci")
    bucket = ("fail" if (ci and ci[0] <= 0 <= ci[1])
              else "mixed" if not ci else "held")
    card = {"fail": "It could not be found again.",
            "mixed": "Smaller — but still there.",
            "held": "It held up."}[bucket]
    return {
        "key": slug,
        "question": E.get("hook_short") or E.get("hook"),
        "es_o": None, "es_r": t["es"],
        "n_o": o["cited_by_approx"] if o else None, "n_r": t["n"],
        "say_o": None, "say_r": fsay(t["es"]),
        "card": card, "color": BUCKET_COLOR[bucket],
        "source": "FORRT Replication Database (FReD)",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--row", type=int)
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()
    if a.slug is None and a.row is None:
        print("要指定 --slug 或 --row"); return 1

    D = collect(a.slug, a.row)
    if D["es_o"] is None:
        print(f"⛔ {D['key']}:名案沒有原始效果量,Short 的「X → Y」對比做不出來。"
              f"這條線先只做 FReD 那批。")
        return 1
    segs = build_script(D)
    out = ROOT / "shorts" / D["key"]
    out.mkdir(parents=True, exist_ok=True)
    for n, txt in segs:
        (out / f"narr_{n}.txt").write_text(txt, encoding="utf-8")
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{D['key']}] {D['question'][:60]}")
    print(f"  稿 {words} 字   {D['es_o']:+.2f} → {D['es_r']:+.2f}   {D['card']}")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    # TTS(每集獨立暫存腳本 —— 並行時寫死路徑會互相覆蓋)
    tts = out / "_tts_short.py"
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        "    s, sr = k.create(t, voice='af_heart', speed=1.0, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<8}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"),
                    str(tts)], check=True, cwd=str(REPO))

    durs = {}
    for n, _ in segs:
        with wave.open(str(out / f"seg_{n}.wav")) as w:
            durs[n] = w.getnframes() / w.getframerate()
    total = sum(durs.values()) + 0.5 * len(segs)
    if total > 58:
        print(f"  ⚠️ {total:.0f} 秒 —— Shorts 上限 60 秒,會被當一般影片")

    plt = _plt()
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    import imageio.v2 as iio
    idx = 0
    for n, _ in segs:
        dur = durs[n] + 0.5
        for i in range(int(dur * FPS)):
            iio.imwrite(frames / f"f{idx:06d}.png", render(plt, n, i / FPS, dur, D))
            idx += 1
        print(f"  畫面 {n:<8}{dur:>6.1f}s")

    voice = out / "voice.wav"
    with wave.open(str(voice), "wb") as w:
        first = True
        for n, _ in segs:
            with wave.open(str(out / f"seg_{n}.wav")) as s:
                if first:
                    w.setparams(s.getparams()); first = False
                w.writeframes(s.readframes(s.getnframes()))
                w.writeframes(b"\x00" * int(0.5 * s.getframerate() *
                                            s.getsampwidth() * s.getnchannels()))
    mp4 = out / f"{D['key']}_short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames / "f%06d.png"),
         "-i", str(voice), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(mp4)],
        check=True, capture_output=True)
    for f in frames.glob("*.png"):
        f.unlink()
    frames.rmdir()
    print(f"完成 → {mp4}  ({int(idx / FPS)}s, {W}x{H})")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
