# -*- coding: utf-8 -*-
"""評估「總報酬 <-> 年化 互推期間」這個訊號,以及「把 total 加成第二個指標」。

不改偵測器。這支只負責量三件事:
  Q1 可用性:觸發讀數裡有幾筆同句拿得到總報酬(沒有就推不出期間)
  Q2 dca 的假設:年化是不是真的 = (1+總報酬)^(1/y)-1(定期定額本該是 IRR)
  Q3 母體:把 metric 換成 total 掃全語料會標記幾支
"""
import io, math, os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\carson-agent\solo_saas")
from numerus.selfcontra import find_contradictions, foreign_tokens_from_filename
from numerus.zhnum import cn_to_num

CORPUS = r"D:\carson-agent\youtube_channel\output"
_CN = "零一二三四五六七八九十百千兩〇點"
# 🔴 修掉舊儀器的 bug:「年化報酬率」不准被當成總報酬。
#    舊版沒有這個 negative lookbehind,於是「年化 23.7」被抽成 total=23.7,
#    再和 annual=23.7 互推出「1.0 年」—— 憑空造出一個期間。
#    失效方向是**製造**矛盾,不是漏掉,所以它比漏抽危險。
_RX_TOTAL = re.compile(
    r"(?<!年化)(?:總報酬率?|累積報酬率?|報酬率?)[^%s\d]{0,6}(?:百分之)?([%s]+|\d+(?:\.\d+)?)"
    % (_CN, _CN))
_RX_PERIOD = re.compile(r"(?:近|過去|最近|這|來|滿)?([%s]{1,4}|\d{1,3}(?:\.\d+)?)\s*(?:個)?年" % _CN)

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

def implied(total, annual):
    if total is None or annual is None: return None
    if annual <= -100 or total <= -100 or annual == 0: return None
    if abs(annual) < 0.05: return None
    try: return math.log(1 + total / 100.0) / math.log(1 + annual / 100.0)
    except ValueError: return None

def totals_in(s):
    return [v for v in (num(m.group(1)) for m in _RX_TOTAL.finditer(s)) if v and v > 0]

def periods_in(s):
    return [v for v in (num(m.group(1)) for m in _RX_PERIOD.finditer(s)) if v and 1 <= v <= 40]

files = []
for root, _d, fs in os.walk(CORPUS):
    for f in sorted(fs):
        if f.endswith(".voice.txt"):
            files.append(os.path.join(root, f))

# ---- Q1 + Q2 -------------------------------------------------------------
have = miss = 0
fit_rows = []
for p in files:
    txt = read(p); fk = foreign_tokens_from_filename(os.path.basename(p))
    for c in find_contradictions(txt, foreign_tokens=fk):
        for rd in (c.low, c.high):
            ts = totals_in(rd.sentence)
            if not ts:
                miss += 1; continue
            have += 1
            for t in ts:
                y = implied(t, rd.value)
                ps = periods_in(rd.sentence)
                if y and ps:
                    fit_rows.append((c.strategy, y, min(ps, key=lambda q: abs(q - y))))
print("Q1 觸發讀數同句有總報酬:%d / %d(%.0f%%);推不出期間的 %d 筆"
      % (have, have + miss, 100.0 * have / (have + miss), miss))

for strat in ("lump", "dca"):
    rs = [r for r in fit_rows if r[0] == strat]
    if not rs: 
        print("Q2 %s:無樣本"); continue
    err = [abs(y - t) for _s, y, t in rs]
    ok = sum(1 for e in err if e <= 0.35)
    print("Q2 %s:n=%d,算術期間 vs 文字期間 |誤差|<=0.35 年的有 %d 筆(%.0f%%),中位誤差 %.2f 年"
          % (strat, len(rs), ok, 100.0 * ok / len(rs), sorted(err)[len(err) // 2]))

# ---- Q3 ------------------------------------------------------------------
for tol, label in ((60.0, "絕對 60pp"), (30.0, "絕對 30pp")):
    flagged = []
    for p in files:
        txt = read(p); fk = foreign_tokens_from_filename(os.path.basename(p))
        cs = find_contradictions(txt, metric="total", foreign_tokens=fk, tol=tol)
        if cs: flagged.append((os.path.basename(p), cs[0]))
    print("Q3 metric=total,tol=%s:標記 %d / %d 支" % (label, len(flagged), len(files)))
