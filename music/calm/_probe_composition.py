#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_probe_composition.py — 用審核員的同一組指標量構圖與動態(純物理,不編碼)。

審核 R2 的三個致命量測:
  下 1/6 畫面可見內容覆蓋率(他量到三支 40 秒有 38 秒是 0.00%)
  染料垂直質心(他量到單調上飄 0.479→0.317)
  相隔 1 秒幀差(slate 只有 2.50,低於被判死的 tea 4.42)
本探針重跑同樣三項,證明修了或沒修 —— 不換指標,不挑對自己有利的數字。
"""
import importlib.util
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
spec = importlib.util.spec_from_file_location("fl", "fluid.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

theme = sys.argv[1] if len(sys.argv) > 1 else "slate"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 522

paper, inks = fl.RICH_THEMES[theme]
dark = theme == "slate"
f = fl.Fluid(fl.GW, fl.GH)
cfg = fl.RICH_PHYS[theme]
f.dissipation, f.amt_mul = cfg["dissipation"], cfg["amt_mul"]
f.vort, f.swirl, f.buoy = cfg["vort"], cfg["swirl"], cfg["buoy"]
rng = np.random.default_rng(seed)
phases = [(float(rng.uniform(0, 2 * np.pi)), float(rng.uniform(0.75, 1.35)))
          for _ in inks]
weights = [(1.0 if i % 2 == 0 else -1.0) * float(rng.uniform(0.75, 1.25))
           for i in range(len(inks))]
rng.shuffle(weights)
drops = fl.Drops(theme, inks, rng)
ss = fl.GW / 96.0

print(f"{theme}  weights={[round(w,2) for w in weights]}  {secs:.0f}s")
print("   t   下1/6覆蓋%  垂直質心  1秒幀差  飽和度  亮度")
prev = None
H = fl.GH
for i in range(int(secs * fl.FPS)):
    t = i * fl.DT
    fl.inject(f, t, inks, rng, phases, weights)
    drops.maybe(f, t)
    f.step(fl.DT, ss)
    if i % (fl.FPS * 10) == 0:
        img = fl.render_frame_rich(f, paper, dark)
        rgb = img * 255
        g = rgb.mean(axis=2)
        base = g[0, 0]
        vis = np.abs(g - base) > 6            # 可見內容(與底色差 >6/255)
        bot = float(vis[int(H * 5 / 6):].mean() * 100)
        d = f.dye.sum(axis=2)
        cy = float((d.sum(axis=1) * np.arange(H)).sum() / (d.sum() + 1e-9) / H)
        sat = float((rgb.max(axis=2) - rgb.min(axis=2)).mean())
        fd = float(np.abs(g - prev).mean()) if prev is not None else float("nan")
        prev = g
        print(f"  {i//fl.FPS:>3}s   {bot:8.2f}   {cy:7.3f}  {fd:7.2f}  "
              f"{sat:6.1f}  {g.mean():5.1f}")
