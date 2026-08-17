#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_scan_jitter.py — 一次性:掃描庫存的畫面抖動命中率分佈,用來定 audit 門檻。

2026-08-17 兩位觀眾回報「畫面會一直抖」後建的。門檻不能憑空定:
實測發現同一批(修復前渲的)片有些抓到有些抓不到——抖動只在 zoompan 的 zoom 值
跨過整數邊界時發生,採樣點落在哪決定看不看得到。所以要先看分佈。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import audit_video as av  # noqa: E402

OUT = ROOT / "output"
led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))

pend = sorted([p for p in OUT.glob("L_*.mp4") if p.stem not in led],
              key=lambda x: -x.stat().st_mtime)[:12]
pub = sorted([p for p in OUT.glob("L_*.mp4") if p.stem in led],
             key=lambda x: -x.stat().st_mtime)[:8]
shorts = sorted([p for p in OUT.glob("S_*.mp4") if p.stem not in led],
                key=lambda x: -x.stat().st_mtime)[:8]

for label, group in (("未發布長片", pend), ("已發布長片", pub), ("未發布短片", shorts)):
    print(f"\n=== {label} ({len(group)}) ===", flush=True)
    rates = []
    for p in group:
        d, hv, _ = av._probe(p)
        if d < 10 or not hv:
            continue
        h, tot = av._frame_jitter(p, d, points=6)
        if tot <= 0:
            continue
        r = h / tot
        rates.append(r)
        flag = "🔴" if r >= 0.12 else ("⚠️" if r > 0 else "✅")
        print(f"  {flag} {r * 100:5.1f}%  ({h}/{tot})  {p.stem[:40]}", flush=True)
    if rates:
        rates.sort()
        print(f"  → 中位 {rates[len(rates) // 2] * 100:.1f}%  "
              f"最高 {rates[-1] * 100:.1f}%  有抖比例 "
              f"{sum(1 for r in rates if r > 0)}/{len(rates)}", flush=True)
print("\n完成", flush=True)
