# -*- coding: utf-8 -*-
import io, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\carson-agent\solo_saas")
from numerus.selfcontra import find_contradictions, foreign_tokens_from_filename
CORPUS = r"D:\carson-agent\youtube_channel\output"
def read(p):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try: return io.open(p, encoding=enc).read()
        except (UnicodeDecodeError, LookupError): continue
    return ""
A, T = {}, {}
for root, _d, fs in os.walk(CORPUS):
    for f in sorted(fs):
        if not f.endswith(".voice.txt"): continue
        p = os.path.join(root, f); txt = read(p)
        fk = foreign_tokens_from_filename(f)
        a = find_contradictions(txt, foreign_tokens=fk)
        t = find_contradictions(txt, metric="total", foreign_tokens=fk, tol=60.0)
        if a: A[f] = a
        if t: T[f] = t
print("annual=%d  total=%d  交集=%d  只有 total 抓到=%d" % (len(A), len(T), len(set(A) & set(T)), len(set(T) - set(A))))
k = [f for f in T if "ALL-IN0050" in f]
print("\nALL-IN0050 在 total 母體裡:", bool(k))
for f in k:
    for c in T[f]:
        print("  [%s/%s] %.1f pp" % (c.metric, c.strategy, c.spread))
        print("   憑↓ %.1f%%  %s" % (c.low.value, c.low.sentence[:100]))
        print("   憑↑ %.1f%%  %s" % (c.high.value, c.high.sentence[:100]))
print("\n只有 total 抓到的前 12 支:")
for f in sorted(set(T) - set(A))[:12]:
    c = T[f][0]
    print("  %.0f pp  %s" % (c.spread, f[:52]))
