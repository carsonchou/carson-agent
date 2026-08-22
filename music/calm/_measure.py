#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_measure.py — 成片量測(依審核 R4 修正四處讀法錯誤)。

## 動態:光流,但**必須取原生相鄰幀**
審核 R4 把我量到的 slate 0.63 追到確切原因:我取樣間隔用了 dt=1.0 秒。
Farneback 假設「亮度守恆 + 局部剛性平移」,隔 1 秒的擴散染料場不是平移而是
變形+暈開,找不到一致對應時正則項把估計值往 0 拉 —— 越柔、對比越低的主題
被拉得越狠。他用同一份程式碼只改 dt 重現了我的數字:

    dt(s)    slate    ink     tea
    1.000     0.63    1.95    2.57   ← 我的錯誤口徑
    0.125     3.24    5.49    4.96
    0.042     5.70    6.54    5.50   ← 原生幀距,三支差距 18% 以內

對比只是次因(配對實驗:壓到同對比只掉 9-17%),dt 才是主因(9 倍)。

## 第二指標:NCC 半衰期(對比無關)
NCC 用兩幀 std 正規化,對比在數學上完全抵消。量的是**全域結構重組**速度,
與局部速度正交:slate 31 秒 / tea 17 秒 / ink 12 秒 —— slate 局部速度不慢,
但重組慢 2.6 倍(對助眠主題反而是對的)。

## 另兩處讀法錯誤(同樣由 R4 抓出)
- base 用 ga[0,0] 單一角落像素太脆弱 → 改 np.median
- 出框比合併四邊會被稀釋,且邊緣無染料時分子分母皆趨 0(那是**最好**的情況,
  我卻讀成撞牆)→ 拆四邊 + 加「內側確實有染料」守門
"""
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FPS = 24.0


def frame(path, t, out="_m.png"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.4f}",
                    "-i", path, "-frames:v", "1", out], check=True)
    return np.asarray(Image.open(out).convert("RGB"), np.float32)


def edge_report(d, thresh=0.05):
    """四邊分開看。只有「內側確實有染料」時,邊緣比才有意義。"""
    out = {}
    ref = d.mean()
    for name, band, inner in (
            ("top", d[:15], d[15:45]),
            ("bottom", d[-15:], d[-45:-15]),
            ("left", d[:, :15], d[:, 15:45]),
            ("right", d[:, -15:], d[:, -45:-15])):
        im = inner.mean()
        if im < ref * thresh:            # 內側沒東西 → 這條邊本來就空,不算撞牆
            out[name] = None
            continue
        out[name] = float(band.mean() / (im + 1e-9))
    return out


def stats(path, ts=(14, 22, 30, 37)):
    rows = []
    for t in ts:
        a = frame(path, t)
        b = frame(path, t + 1.0 / FPS)          # 🔴 原生相鄰幀
        ga, gb = a.mean(axis=2), b.mean(axis=2)
        base = float(np.median(ga))
        vis = np.abs(ga - base) > 6
        fl = cv2.calcOpticalFlowFarneback(ga.astype(np.uint8), gb.astype(np.uint8),
                                          None, 0.5, 3, 25, 3, 5, 1.2, 0)
        mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)
        flow = float(mag[vis].mean() * FPS) if vis.any() else 0.0
        H = ga.shape[0]
        d = np.abs(ga - base)
        rows.append(dict(
            flow=flow, std=float(ga.std()),
            top=float(vis[:H // 6].mean() * 100), bot=float(vis[H * 5 // 6:].mean() * 100),
            cy=float((d.sum(axis=1) * np.arange(H)).sum() / (d.sum() + 1e-9) / H),
            mean=float(ga.mean()),
            sat=float((a.max(axis=2) - a.min(axis=2)).mean()),
            clip=float((ga >= 254).mean() * 100),
            strong=float((d > 80).mean() * 100),      # 偏離底色 >80 = 縮圖上看得見的內容
            edges=edge_report(d)))
    return rows


def ncc_halflife(path, t0=16.0, span=40.0):
    """結構重組半衰期:NCC 掉到 0.5 需要幾秒(對比無關)。"""
    a = frame(path, t0).mean(axis=2)
    a = (a - a.mean()) / (a.std() + 1e-9)
    prev_dt, prev_n = 0.0, 1.0
    for dt in (2, 4, 8, 12, 17, 24, 31, 40):
        if t0 + dt > span:
            break
        b = frame(path, t0 + dt).mean(axis=2)
        b = (b - b.mean()) / (b.std() + 1e-9)
        n = float((a * b).mean())
        if n < 0.5:
            f = (prev_n - 0.5) / max(prev_n - n, 1e-9)
            return prev_dt + f * (dt - prev_dt)
        prev_dt, prev_n = dt, n
    return float("inf")


if __name__ == "__main__":
    vids = sys.argv[1:] or ["sample_rich_slate.mp4", "sample_rich_ink.mp4",
                            "sample_rich_tea.mp4"]
    print("        光流px/s  NCC半衰  對比  上1/6 下1/6  質心   亮度  飽和 可見% 白爆%")
    for p in vids:
        rows = stats(p)
        m = lambda k: float(np.mean([r[k] for r in rows]))
        hl = ncc_halflife(p)
        name = p.replace("sample_rich_", "").replace("final_", "").replace(".mp4", "")
        print(f"  {name:<6} {m('flow'):7.2f} {hl:7.1f}s {m('std'):6.1f} "
              f"{m('top'):5.1f} {m('bot'):5.1f} {m('cy'):6.3f} {m('mean'):6.1f} "
              f"{m('sat'):5.1f} {m('strong'):5.2f} {m('clip'):5.3f}")
        hits = []
        for r in rows:
            for k, v in r["edges"].items():
                if v is not None and v < 0.35:
                    hits.append(f"{k}{v:.2f}")
        print(f"         撞牆: {', '.join(hits) if hits else '無'}")
