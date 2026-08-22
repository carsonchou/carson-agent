#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_verify_final.py — 60 分鐘成片驗收(上傳前最後一道自檢)。

驗四件這個架構特有的風險:
1. **段界跳動**:成片由 6 段各自編碼再 concat。物理靠 checkpoint 續算是連續的,
   但編碼器重啟可能在 10/20/30/40/50 分處留下可見接縫。取接縫前後各一幀比對,
   與同段內同間隔的幀差當對照組——接縫幀差必須落在對照組的常態範圍內。
2. **整小時亮度走勢**:樣片只有 40 秒,推不出 60 分鐘。直接量成片 12 個時點。
3. **白爆**:任何時點 ≥254 的像素比例必須是 0。
4. **時長與音軌**:必須是 3600 秒且有音訊流(-shortest 會靜默截短)。
"""
import subprocess
import sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def probe(path, key):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", key,
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return r.stdout.strip()


def frame(path, t, out="_vf.png"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", path, "-frames:v", "1", out], check=True)
    return np.asarray(Image.open(out).convert("L"), np.float32)


def check(path):
    print(f"\n=== {path} ===")
    dur = float(probe(path, "format=duration") or 0)
    astream = probe(path, "stream=codec_type").splitlines()
    print(f"  時長 {dur/60:.2f} 分  串流 {astream}  "
          f"{'✓' if abs(dur - 3600) < 5 and 'audio' in astream else '⚠️ 異常'}")

    print("  整小時亮度:")
    rows = []
    for m in (2, 7, 12, 18, 24, 30, 36, 42, 48, 53, 57, 59):
        g = frame(path, m * 60)
        rows.append((m, g.mean(), np.percentile(g, 99.9), (g >= 254).mean() * 100))
    for m, mu, p999, clip in rows:
        print(f"    {m:>2}分  mean={mu:6.1f}  p99.9={p999:5.0f}  白爆={clip:.4f}%")
    mus = np.array([r[1] for r in rows])
    drift = mus[-3:].mean() - mus[3:6].mean()
    print(f"  後段 vs 中段漂移 {drift:+.1f}  "
          f"{'✓ 穩定' if abs(drift) < 8 else '⚠️ 仍在漂'}")
    maxclip = max(r[3] for r in rows)
    print(f"  最大白爆 {maxclip:.4f}%  {'✓' if maxclip < 0.01 else '⚠️'}")

    # 段界:對照組 = 同段內相同間隔的幀差
    print("  段界連續性(接縫幀差 vs 同段內對照):")
    ctrl = []
    for t in (300, 900, 1500, 2100):
        a = frame(path, t); b = frame(path, t + 0.2)
        ctrl.append(float(np.abs(a - b).mean()))
    lo, hi = float(np.mean(ctrl)), float(np.max(ctrl))
    print(f"    對照組(段內 0.2s):平均 {lo:.2f}  最大 {hi:.2f}")
    bad = []
    for k in range(1, 6):
        t = k * 600
        a = frame(path, t - 0.1); b = frame(path, t + 0.1)
        d = float(np.abs(a - b).mean())
        flag = "" if d <= hi * 2.5 else "  ⚠️ 疑似接縫"
        if flag:
            bad.append(k)
        print(f"    {k*10:>2}分接縫  幀差 {d:.2f}{flag}")
    print(f"  段界判定:{'✓ 無可見接縫' if not bad else '⚠️ 第 ' + str(bad) + ' 處異常'}")


if __name__ == "__main__":
    import os
    for p in (sys.argv[1:] or ["final_B.mp4", "final_C.mp4", "final_A.mp4"]):
        if os.path.exists(p):
            check(p)
        else:
            print(f"{p} 尚未產出")
    if os.path.exists("_vf.png"):
        os.remove("_vf.png")
