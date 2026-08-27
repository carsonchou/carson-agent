#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_compilation.py — 把多集組成一支有結構的長片。

## 為什麼這是最大的槓桿
YPP 要 4,000 小時 = 240,000 分鐘。算式很殘忍:

  1.7 分鐘的片、每次觀看貢獻 1.3 分 → 需要 **184,615 次觀看**
  10 分鐘的片、每次觀看 3.5 分(主頻道實測)→ 需要 **68,571 次觀看**

同一批內容,只因為片長不同,需要的流量差 **2.6 倍**。而片長是這裡唯一
完全由我決定的變數 —— 流量不是。

## 但這不能是灌水
把同一件事講久一點會殺掉留存,那反而更糟(觀看時數 = 觀看數 × 停留時間,
灌水兩邊都輸)。所以合輯是**真的多給東西**:一支片講 5 個發現,每個都有
自己的主張、數字、判決。觀眾多留 5 倍是因為多看了 5 件事。

順帶解決兩個問題:
- **模板化**:一支片內含 5 種不同的結局與敘事,不再是「同一套版型換數字」
- **開場**:合輯的開場可以先拋出最強的那個落差當鉤子,而不是從第一個
  發現慢慢講起

## 誠信
不重算任何數字 —— 每一段都直接沿用該集已通過審核的旁白與畫面邏輯。
合輯自己只加「串場」,而串場**不做任何數字宣稱**。

用法:
  python make_compilation.py --bucket fail --limit 5
  python make_compilation.py --bucket fail --limit 5 --script-only
"""
import argparse
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"

TITLES = {
    "fail": ("{n} psychology findings that did not survive a bigger test",
             "Every one of these was published, cited, and repeated. Then a "
             "much larger team ran the same study again."),
    "mixed": ("{n} findings that are real — and much smaller than you were told",
              "Not debunked. Corrected. This is the outcome that gets covered "
              "worst, because it has no villain."),
    "held": ("{n} psychology findings that actually held up",
             "You have heard a lot about the ones that broke. These did not."),
}


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


def pick(bucket, limit):
    """挑出該 bucket 已產好的集數,依落差大小排序 —— 最戲劇性的放最前面當鉤子。"""
    from make_episode import build_facts, TONE_META
    q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    out = []
    for i, r in q.iterrows():
        d = ROOT / "eps" / f"ep{i:03d}"
        if not (d / f"ep{i:03d}.mp4").exists():
            continue
        F = build_facts(r)
        if TONE_META[F["tone"]]["bucket"] != bucket:
            continue
        gap = abs(abs(F["orig"]["es"]) - abs(F["repl"]["es"]))
        out.append((gap, i, F, d))
    out.sort(key=lambda x: -x[0])
    return out[:limit]


def build_script(bucket, items):
    """串場只負責銜接,**不做任何數字宣稱** —— 數字全在各集自己的段落裡。"""
    from make_episode import say_num
    n = len(items)
    lead = items[0][2]
    segs = [("intro",
             f"In {lead['orig']['year']}, a study reported an effect of "
             f"{say_num(lead['orig']['es'])}. "
             f"When a far larger team ran the same study again, the number "
             f"came back {say_num(lead['repl']['es'])}. "
             f"That is the first of {n} findings in this video. "
             f"Every number comes from the published replication record, and "
             f"every paper is linked below.")]
    for k, (_, i, F, _d) in enumerate(items, 1):
        segs.append((f"card{k}",
                     f"Number {k}." if k > 1 else "Let's start."))
    segs.append(("outro",
                 "Every one of these came from the same public database, one "
                 "row per finding, with the original paper and the replication "
                 "both linked. Nothing here was estimated. If a finding "
                 "survives a larger test, it gets its own video too."))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="fail", choices=["fail", "mixed", "held"])
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    items = pick(a.bucket, a.limit)
    if len(items) < 2:
        print(f"⛔ {a.bucket} 只有 {len(items)} 集產好,不夠組合輯")
        return 1
    n = len(items)
    title = TITLES[a.bucket][0].format(n=n)
    print(f"[{a.bucket}] {title}")
    total = 0.0
    for gap, i, F, d in items:
        mp4 = d / f"ep{i:03d}.mp4"
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(mp4)],
                           capture_output=True, text=True)
        dur = float(r.stdout.strip())
        total += dur
        print(f"  ep{i:03d}  落差 {gap:.2f}  {dur:>5.0f}s  "
              f"{F['orig']['es']:+.2f} → {F['repl']['es']:+.2f}")
    segs = build_script(a.bucket, items)
    print(f"\n主體 {total:.0f} 秒 = {total/60:.1f} 分,加串場約 "
          f"{(total + 45)/60:.1f} 分")
    if a.script_only:
        for k, t in segs:
            print(f"  --- {k} ---\n  {t}")
        return 0

    out = ROOT / "compilations" / a.bucket
    out.mkdir(parents=True, exist_ok=True)
    for k, t in segs:
        (out / f"narr_{k}.txt").write_text(t, encoding="utf-8")

    # 串場語音
    tts = out / "_tts_comp.py"
    names = tuple(k for k, _ in segs)
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        f"for n in {names!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        "    s, sr = k.create(t, voice='af_heart', speed=0.98, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<8}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"),
                    str(tts)], check=True, cwd=str(REPO))

    # 串場畫面
    plt = _plt()
    import imageio.v2 as iio
    clips = []
    for k, (gap, i, F, d) in enumerate(items, 1):
        card = out / f"card{k}"
        card.mkdir(exist_ok=True)
        with wave.open(str(out / f"seg_card{k}.wav")) as w:
            cd = w.getnframes() / w.getframerate() + 0.6
        for fi in range(int(cd * FPS)):
            fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
            fig.patch.set_facecolor(BG)
            ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
            ax.set_xlim(0, 1); ax.set_ylim(0, 1)
            ax.text(0.5, 0.56, f"{k}", ha="center", va="center", fontsize=220,
                    color="#1B222C", weight="bold")
            ax.text(0.5, 0.40, f"of {len(items)}", ha="center", fontsize=44,
                    color=DIM)
            fig.canvas.draw()
            iio.imwrite(card / f"f{fi:05d}.png",
                        np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
            plt.close(fig)
        seg = out / f"card{k}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i",
                        str(card / "f%05d.png"), "-i", str(out / f"seg_card{k}.wav"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(seg)],
                       check=True, capture_output=True)
        for f in card.glob("*.png"):
            f.unlink()
        card.rmdir()
        clips.append(seg)
        clips.append(d / f"ep{i:03d}.mp4")
        print(f"  串場 {k}/{len(items)}")

    # intro / outro
    for name in ("intro", "outro"):
        dd = out / name
        dd.mkdir(exist_ok=True)
        with wave.open(str(out / f"seg_{name}.wav")) as w:
            sd = w.getnframes() / w.getframerate() + 0.6
        lines = ([title] if name == "intro" else
                 ["Every number here is from", "the published record."])
        for fi in range(int(sd * FPS)):
            fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
            fig.patch.set_facecolor(BG)
            ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
            ax.set_xlim(0, 1); ax.set_ylim(0, 1)
            words, cur, rows = lines[0].split() if name == "intro" else [], "", []
            if name == "intro":
                for wd in words:
                    if len(cur) + len(wd) + 1 > 30:
                        rows.append(cur); cur = wd
                    else:
                        cur = (cur + " " + wd).strip()
                rows.append(cur)
            else:
                rows = lines
            for ri, ln in enumerate(rows[:4]):
                ax.text(0.5, 0.62 - ri * 0.10, ln, ha="center", va="center",
                        fontsize=58, color=FG, weight="bold")
            fig.canvas.draw()
            iio.imwrite(dd / f"f{fi:05d}.png",
                        np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
            plt.close(fig)
        seg = out / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i",
                        str(dd / "f%05d.png"), "-i", str(out / f"seg_{name}.wav"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(seg)],
                       check=True, capture_output=True)
        for f in dd.glob("*.png"):
            f.unlink()
        dd.rmdir()
        print(f"  {name} 完成")

    order = [out / "intro.mp4"] + clips + [out / "outro.mp4"]
    lst = out / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in order),
                   encoding="utf-8")
    final = out / f"{a.bucket}_compilation.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", str(final)],
                   check=True, capture_output=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(final)],
                       capture_output=True, text=True)
    print(f"完成 → {final}  ({float(r.stdout.strip())/60:.1f} 分)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
