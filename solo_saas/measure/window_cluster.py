# -*- coding: utf-8 -*-
"""原型:先用算術把讀數分到「回測窗」,再在同一窗內找矛盾。

方向和「推不出來的期間 = 矛盾的證據」相反。語料說的是:
期間不同才是**誤報**的主要機制(25 支裡 12 支),所以算術該拿來當**分群鍵**,
不是當警報。
"""
import io, math, os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\carson-agent\solo_saas")
from numerus.selfcontra import find_contradictions, readings_for, foreign_tokens_from_filename
from numerus.zhnum import cn_to_num
CORPUS = r"D:\carson-agent\youtube_channel\output"
_CN = "零一二三四五六七八九十百千兩〇點"
_RX_TOTAL = re.compile(r"(?<!年化)(?:總報酬率?|累積報酬率?|報酬率?)[^%s\d]{0,6}(?:百分之)?([%s]+|\d+(?:\.\d+)?)" % (_CN, _CN))
def num(t):
    if re.match(r"^\d", t):
        try: return float(t)
        except ValueError: return None
    return cn_to_num(t)
def read(p):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try: return io.open(p, encoding=enc).read()
        except (UnicodeDecodeError, LookupError): continue
    return ""
def implied(t, a):
    if t is None or a is None or a <= -100 or t <= -100 or abs(a) < 0.05: return None
    try: return math.log(1 + t / 100.0) / math.log(1 + a / 100.0)
    except ValueError: return None

def analyse(path, tol=1.0, ytol=0.6):
    txt = read(path); fk = foreign_tokens_from_filename(os.path.basename(path))
    pts = []
    for r in readings_for(txt, "annual", foreign_tokens=fk):
        if r.vague: continue
        ts = [v for v in (num(m.group(1)) for m in _RX_TOTAL.finditer(r.sentence)) if v and v > 0]
        y = implied(ts[0], r.value) if ts else None
        pts.append((r.strategy, r.value, ts[0] if ts else None, y, r.sentence))
    out = []
    for strat in sorted(set(p[0] for p in pts)):
        grp = [p for p in pts if p[0] == strat and p[3]]
        grp.sort(key=lambda p: p[3])
        cur = []
        for p in grp:
            if cur and p[3] - cur[0][3] > ytol:
                out.append((strat, cur)); cur = []
            cur.append(p)
        if cur: out.append((strat, cur))
    return out

for name in ("ALL-IN0050十年", "00631L", "個股體檢復盛應用", "臺股跌破萬點"):
    for root, _d, fs in os.walk(CORPUS):
        for f in fs:
            if f.endswith(".voice.txt") and name in f:
                print("=" * 88); print(f[:70])
                for strat, cl in analyse(os.path.join(root, f)):
                    ys = [p[3] for p in cl]
                    ann = [p[1] for p in cl]; tot = [p[2] for p in cl]
                    verdict = ""
                    if len(cl) > 1 and max(ann) - min(ann) > 1.0:
                        verdict = "  ⇒ 同窗內年化矛盾 %.1f pp" % (max(ann) - min(ann))
                    if len(cl) > 1 and min(tot) and (max(tot) - min(tot)) / min(tot) > 0.02:
                        verdict += "  ⇒ 同窗內總報酬矛盾 %.1f vs %.1f" % (min(tot), max(tot))
                    print("  [%s] 窗≈%.1f~%.1f 年,n=%d  年化 %s  總報酬 %s%s"
                          % (strat, min(ys), max(ys), len(cl),
                             "/".join("%.1f" % a for a in ann),
                             "/".join("%.0f" % t for t in tot), verdict))
