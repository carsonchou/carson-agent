#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_measure.py — 成片量測。動態改用**光流位移**,不再用幀差。

審核 R3 證明幀差 ≈ 真實位移 × 訊號振幅 × 覆蓋率 —— 對暗底主題嚴重低估
(光流顯示三支真實運動只差 11%,幀差卻差 3.2 倍)。我曾據此誤把 slate 的
浮力拉到兩倍,製造出新缺陷。故:
  動態  = 光流位移 px/秒(只取有內容的像素)
  對比  = 該幀 std(獨立指標,不與動態混用)
  構圖  = 上/下 1/6 覆蓋率、垂直質心
  出框  = 最外 15px 帶的染料量 vs 緊鄰內側(15-45px)之比,>0.7 才算沒撞牆
"""
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def frame(path, t, out="_m.png"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                    "-i", path, "-frames:v", "1", out], check=True)
    return np.asarray(Image.open(out).convert("RGB"), np.float32)


def stats(path, ts=(14, 22, 30, 37)):
    flows, stds, tops, bots, cys, edges, means, sats, clips = [], [], [], [], [], [], [], [], []
    for t in ts:
        a = frame(path, t)
        b = frame(path, t + 1.0)
        ga = a.mean(axis=2); gb = b.mean(axis=2)
        base = ga[0, 0]
        vis = np.abs(ga - base) > 6
        fl = cv2.calcOpticalFlowFarneback(ga.astype(np.uint8), gb.astype(np.uint8),
                                          None, 0.5, 3, 25, 3, 5, 1.2, 0)
        mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)
        flows.append(float(mag[vis].mean()) if vis.any() else 0.0)
        stds.append(float(ga.std()))
        H = ga.shape[0]
        tops.append(float(vis[:H // 6].mean() * 100))
        bots.append(float(vis[H * 5 // 6:].mean() * 100))
        d = np.abs(ga - base)
        cys.append(float((d.sum(axis=1) * np.arange(H)).sum() / (d.sum() + 1e-9) / H))
        band = np.concatenate([d[:15].ravel(), d[-15:].ravel(),
                               d[:, :15].ravel(), d[:, -15:].ravel()])
        inner = np.concatenate([d[15:45].ravel(), d[-45:-15].ravel(),
                                d[:, 15:45].ravel(), d[:, -45:-15].ravel()])
        edges.append(float(band.mean() / (inner.mean() + 1e-9)))
        means.append(float(ga.mean()))
        sats.append(float((a.max(axis=2) - a.min(axis=2)).mean()))
        clips.append(float((ga >= 254).mean() * 100))
    m = lambda x: float(np.mean(x))
    return dict(flow=m(flows), std=m(stds), top=m(tops), bot=m(bots), cy=m(cys),
                edge=m(edges), mean=m(means), sat=m(sats), clip=m(clips))


if __name__ == "__main__":
    print("          光流px/s   對比std  上1/6%  下1/6%  質心   出框比  亮度   飽和  白爆%")
    for name, p in (("slate", "sample_rich_slate.mp4"),
                    ("ink", "sample_rich_ink.mp4"),
                    ("tea", "sample_rich_tea.mp4")):
        s = stats(p)
        print(f"  {name:<6} {s['flow']:8.2f}  {s['std']:8.1f} {s['top']:6.1f} "
              f"{s['bot']:6.1f}  {s['cy']:5.3f}  {s['edge']:5.2f} "
              f"{s['mean']:6.1f} {s['sat']:6.1f} {s['clip']:6.3f}")
