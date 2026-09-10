# -*- coding: utf-8 -*-
"""真陽性按月的區間估計 —— n 只有 3/4/5,不加區間就會把雜訊講成趨勢。"""
import datetime as dt
import io
import math
import os
import re
import sys

sys.path.insert(0, r"D:\carson-agent\solo_saas")
from numerus.selfcontra import (find_contradictions,  # noqa: E402
                                foreign_tokens_from_filename, readings_for)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CORPUS = r"D:\carson-agent\youtube_channel\output"
SCRATCH = os.path.dirname(os.path.abspath(__file__))
RANK_A = {5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 25}
RANK_B = {24}


def read(p):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(p, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h) * 100, min(1.0, c + h) * 100)


lab = {}
for line in io.open(os.path.join(SCRATCH, "reaudit_out.txt"),
                    encoding="utf-8", errors="replace"):
    m = re.match(r"^\[(\d+)\]\s+[\d.]+ pp\s+(.+\.voice\.txt)\s*$", line.rstrip())
    if m:
        n = int(m.group(1))
        lab[m.group(2)] = "a" if n in RANK_A else "b" if n in RANK_B else "c"

rows = []
for root, _d, files in os.walk(CORPUS):
    for f in sorted(files):
        if not f.endswith(".voice.txt"):
            continue
        p = os.path.join(root, f)
        rel = os.path.relpath(p, CORPUS)
        t = read(p)
        ft = foreign_tokens_from_filename(f)
        rows.append({"rel": rel, "f": f,
                     "d": dt.date.fromtimestamp(os.path.getmtime(p)),
                     "fam": "個股體檢" if "個股體檢" in f else "其他",
                     "dom": bool(readings_for(t, foreign_tokens=ft)),
                     "flag": bool(find_contradictions(t, foreign_tokens=ft)),
                     "k": lab.get(rel)})

print("== 個股體檢家族:真陽性率 + Wilson 95% 區間 ==")
print("| 月份 | 定義域 | (a) | 比率 | 95% 區間 |")
print("|------|-------:|----:|-----:|----------|")
for m in ("2026-07", "2026-08", "2026-09"):
    sub = [r for r in rows if r["d"].strftime("%Y-%m") == m and r["fam"] == "個股體檢"]
    dom = sum(r["dom"] for r in sub)
    tp = sum(1 for r in sub if r["k"] == "a")
    lo, hi = wilson(tp, dom)
    print("| %s | %d | %d | %.1f%% | %.1f%% ~ %.1f%% |" % (m, dom, tp, 100.0 * tp / dom, lo, hi))

print("\n== 12 支真陽性的產出日與所在目錄 ==")
for r in sorted([r for r in rows if r["k"] == "a"], key=lambda r: r["d"]):
    print("  %s  %-10s %s" % (r["d"], os.path.dirname(r["rel"]) or "正本", r["f"][:46]))
b = [r for r in rows if r["k"] == "b"]
for r in b:
    print("  %s  %-10s %s  ← (b) 叫對理由錯" % (r["d"], os.path.dirname(r["rel"]) or "正本", r["f"][:46]))
