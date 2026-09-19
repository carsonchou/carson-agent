#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_bright_probe.py — 只跑物理、不編碼,量亮度是否收斂。

審核員的第一必修項:slate 35 秒 mean 52→72(+38%),外推 60 分鐘會全白。
要驗的是**平衡點**(注入 vs 消散),那是物理問題,不必渲染 1080p 影片。
本探針跑 N 分鐘模擬時間,每 30 秒印一次亮度統計 —— 比渲染快 ~10 倍。
"""
import importlib.util
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
spec = importlib.util.spec_from_file_location("fl", "fluid.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

theme = sys.argv[1] if len(sys.argv) > 1 else "slate"
mins = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 522

paper, inks = fl.RICH_THEMES[theme]
dark = theme == "slate"
f = fl.Fluid(fl.GW, fl.GH)
cfg = fl.RICH_PHYS[theme]
f.dissipation, f.amt_mul = cfg["dissipation"], cfg["amt_mul"]
rng = np.random.default_rng(seed)
phases = [(float(rng.uniform(0, 2 * np.pi)), float(rng.uniform(0.75, 1.35)))
          for _ in inks]
drops = fl.Drops(theme, inks, rng)
sim_scale = fl.GW / 96.0

print(f"{theme}  dissipation={f.dissipation}  amt_mul={f.amt_mul}  {mins:.0f} 分鐘模擬")
n = int(mins * 60 * fl.FPS)
for i in range(n):
    t = i * fl.DT
    fl.inject(f, t, inks, rng, phases)
    drops.maybe(f, t)
    f.step(fl.DT, sim_scale)
    if i % (fl.FPS * 30) == 0:
        img = fl.render_frame_rich(f, paper, dark)
        g = (img * 255).mean(axis=2)
        print(f"  t={i//fl.FPS:>5d}s  mean={g.mean():6.1f}  p95={np.percentile(g,95):5.0f}"
              f"  p99.9={np.percentile(g,99.9):5.0f}  dye_max={f.dye.max():.2f}")
