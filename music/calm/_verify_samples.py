#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_verify_samples.py — 對成片做客觀量測(不涉美學判斷)。

量四件審核員上輪標出的事:
  1. 亮度隨時間走勢(必須收斂,不能單調爬升)
  2. 峰值亮度(暗底片不得 clip 成純白)
  3. 幀間差異(必須持續演化,無卡頓/跳變)
  4. 四邊 row/col 掃描(不得有暗環或亮暈)
"""
import subprocess
import sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def frame(path, t, out="_v.png"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                    "-i", path, "-frames:v", "1", out], check=True)
    return np.asarray(Image.open(out).convert("L"), np.float32)


def edge_scan(g, px=40):
    """四邊各取最外 px 行/列的均值曲線,回報最大單步跳變與端點落差。"""
    out = {}
    for name, band in (("top", g[:px].mean(axis=1)),
                       ("bottom", g[-px:][::-1].mean(axis=1)),
                       ("left", g[:, :px].mean(axis=0)),
                       ("right", g[:, -px:][:, ::-1].mean(axis=0))):
        step = float(np.abs(np.diff(band)).max())
        drop = float(band[0] - band[-1])
        out[name] = (step, drop)
    return out


for name, path in (("ink", "sample_rich_ink.mp4"),
                   ("slate", "sample_rich_slate.mp4"),
                   ("tea", "sample_rich_tea.mp4")):
    print(f"\n=== {name} ===")
    ts = [4, 12, 20, 28, 36]
    gs = [frame(path, t) for t in ts]
    for t, g in zip(ts, gs):
        print(f"  t={t:>2}s  mean={g.mean():6.1f}  p95={np.percentile(g,95):5.0f}"
              f"  p99.9={np.percentile(g,99.9):5.0f}  max={g.max():.0f}")
    trend = gs[-1].mean() - gs[0].mean()
    print(f"  亮度趨勢 {trend:+.1f}(32 秒間;正值大=有爬升風險)")
    clip = float((gs[-1] >= 254).mean() * 100)
    print(f"  近純白像素 {clip:.3f}%")

    # 幀差:連續三對相鄰幀(0.2 秒間隔)
    diffs = []
    for t in (10.0, 20.0, 30.0):
        a = frame(path, t)
        b = frame(path, t + 0.2)
        diffs.append(float(np.abs(a - b).mean()))
    print(f"  幀差(0.2s) {['%.2f' % d for d in diffs]}  → "
          f"{'持續演化' if min(diffs) > 0.3 else '⚠️ 可能停滯'}")

    e = edge_scan(gs[-1])
    worst = max(e.items(), key=lambda kv: abs(kv[1][1]))
    print("  四邊掃描(最大單步 / 端點落差):")
    for k, (step, drop) in e.items():
        print(f"    {k:<7} step={step:5.2f}  drop={drop:+6.2f}")
    print(f"  → 最大端點落差 {worst[0]} {worst[1][1]:+.2f}/255 "
          f"{'✓ 不可見' if abs(worst[1][1]) < 4 else '⚠️ 可能可見'}")
