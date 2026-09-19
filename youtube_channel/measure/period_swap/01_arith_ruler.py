# -*- coding: utf-8 -*-
"""算術尺:0050 的數字自己招認的期間 vs 這支片宣稱的期間。

不問「有沒有寫期間」(那是字面),問**數字對不對得上**(那是傷害)。

原理:總報酬 R 與年化 a 互相決定期間  n = ln(1+R)/ln(1+a)。
      同一句同時給了 R 和 a ⇒ n 是被鎖死的,不需要任何外部資料。
      片名的年數 N 是這支片宣稱的期間。
      n 和 N 差很多 ⇒ 那組 0050 數字不是這支片講的那段期間的。

刻意的邊界:
  · 只看**同一句同時給總報酬和年化**的 0050 句 —— 兩個數字互相驗證,不靠事實庫。
  · 片名年數抓不到就跳過,不猜。
  · n 和 N 差 ≤ 1.5 年 ⇒ 判為一致(容忍起訖日與四捨五入)。
  · 🔴 這把尺**只看得到「同句給了兩個數字」的情形**;句子只給總報酬的,結構上看不見。
    ⇒ 它報的是**下界**,不是計數。

對照:
  陽性 安勤3479 —— 總督導親手算過 8.211^(1/10)=23.4%,片名 16 年 ⇒ 必須叫
  陰性 大立光3008(片名十年)—— 0050 數字自招 10.00 年,與片名一致 ⇒ 必須不叫
  ⚠️ 原本用愛普6531 當陰性,加了主體邊界之後它整支落到射程外 ——
     而它之前「通過」是因為抓到愛普自己的 1691%,|9.99-11|=1.01 剛好在容忍內。
     **矇對的對照比沒有對照更危險**,已換掉。
"""
import re, io, os, glob, sys, math, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = r"D:\carson-agent\youtube_channel\output"

CN = {"零":0,"〇":0,"一":1,"二":2,"兩":2,"三":3,"四":4,"五":5,"六":6,
      "七":7,"八":8,"九":9}

def cn2num(s):
    """中文數字轉 float,支援 百/十/點。純位值(二零一零)也支援。"""
    s = s.strip()
    if not s: return None
    if "點" in s:
        a, _, b = s.partition("點")
        ai = cn2num(a); 
        if ai is None: return None
        frac = "".join(str(CN.get(c,"")) for c in b)
        return float("%d.%s" % (ai, frac or "0"))
    # 位值寫法(全部是 0-9 且不含十/百)
    if all(c in CN for c in s) and len(s) > 1:
        return float(int("".join(str(CN[c]) for c in s)))
    tot, cur = 0, 0
    for c in s:
        if c in CN: cur = CN[c]
        elif c == "十": tot += (cur or 1) * 10; cur = 0
        elif c == "百": tot += (cur or 1) * 100; cur = 0
        else: return None
    return float(tot + cur)

def pct(s):
    """把『百分之七百二十一點一』或『721.1%』轉成 float"""
    m = re.match(r"^[\d.]+$", s)
    if m: return float(s)
    return cn2num(s)

ALIAS = re.compile(r"0050|零零五零|元大[臺台]灣\s*50|元大[臺台]灣五十")
NUM   = r"(?:百分之([零〇一二三四五六七八九十百兩點]+)|([\d.]+)\s*%)"
TOT   = re.compile(r"總報酬(?:率)?[^，。]{0,6}?" + NUM)
ANN   = re.compile(r"年化(?:報酬率)?[^，。]{0,8}?" + NUM)
SENT  = re.compile(r"[^。！？\n]+")
TITLE_YR = re.compile(r"(?:抱|近|上市)?([\d]+|[一二三四五六七八九十]+)\s*年")

def grab(rx, s):
    m = rx.search(s)
    if not m: return None
    return pct(m.group(1) or m.group(2))

def title_years(base):
    """片名裡的年數。取最大的那個(片名常有代號被誤讀成年)"""
    cands = []
    for m in TITLE_YR.finditer(base):
        v = m.group(1)
        v = float(v) if v.isdigit() else cn2num(v)
        if v and 1 <= v <= 40: cands.append(v)
    return max(cands) if cands else None

def scan(path):
    base = os.path.basename(path)
    N = title_years(base)
    if N is None: return None
    t = io.open(path, encoding="utf-8", errors="replace").read()
    hits = []
    for m in SENT.finditer(t):
        s = m.group(0)
        al = list(ALIAS.finditer(s))
        if not al: continue
        # 🔴 主體邊界:只認**最後一個 0050 別名之後**的數字。
        # 沒有這一刀,「愛普 All-in 10年報酬1691%…0050 的712%」會把愛普的數字算成 0050 的。
        tail = s[al[-1].end():]
        R = grab(TOT, tail); a = grab(ANN, tail)
        if R is None or a is None: continue
        if a <= 0 or R <= 0: continue
        n = math.log(1 + R/100.0) / math.log(1 + a/100.0)
        hits.append(dict(sent=s.strip(), R=R, a=a, n=round(n,2)))
    if not hits: return None
    return dict(base=base, N=N, hits=hits,
                mtime=datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat())

TOL = 1.5
def verdict(rec):
    return [h for h in rec["hits"] if abs(h["n"] - rec["N"]) > TOL]

# ── 對照 ──
print("== 對照 ==")
ok = True
for label, kw, want in (("陽性 安勤3479","安勤3479",True), ("陰性 大立光3008","大立光3008十年",False)):
    ps = [p for p in glob.glob(os.path.join(OUT,"*.voice.txt")) if kw in os.path.basename(p)]
    if not ps: print("  %s 找不到檔"%label); ok=False; continue
    r = scan(ps[0])
    if r is None:
        print("  %s 抽不出(片名年數或同句雙數字缺)⇒ 對照無效"%label); ok=False; continue
    bad = verdict(r)
    got = len(bad)>0
    print("  %-14s 片名N=%s 同句雙數字句=%d 不一致=%d 期望%s ⇒ %s"
          % (label, r["N"], len(r["hits"]), len(bad), "叫" if want else "不叫",
             "OK" if got==want else "🔴FAIL"))
    for h in r["hits"]:
        print("      R=%.1f%% a=%.1f%% ⇒ 數字自招 n=%.2f 年  (片名 %s 年)" % (h["R"],h["a"],h["n"],r["N"]))
    if got != want: ok = False
if not ok:
    print("\n🔴 對照沒過,數字不准引用。"); sys.exit(1)
print("✅ 對照通過\n")

# ── 全母體 ──
recs = []
for p in sorted(glob.glob(os.path.join(OUT,"*個股體檢*.voice.txt"))):
    r = scan(p)
    if r: recs.append(r)

bad_recs = [r for r in recs if verdict(r)]
print("== 母體 = 片名有年數 且 有『同句同時給 0050 總報酬+年化』的個股體檢稿 ==")
print("  可判定稿數 = %d   其中數字與片名期間不一致 = %d  (%.1f%%)"
      % (len(recs), len(bad_recs), 100.0*len(bad_recs)/len(recs) if recs else 0))

CUT="2026-08-20"
for label, sel in (("08-20 前",[r for r in recs if r["mtime"]<CUT]),
                   ("08-20 後",[r for r in recs if r["mtime"]>=CUT])):
    b=[r for r in sel if verdict(r)]
    print("  %-9s 可判定=%3d 不一致=%3d  %5.1f%%" % (label,len(sel),len(b),
          100.0*len(b)/len(sel) if sel else 0))

print("\n== 數字自招的 n 分佈(全部不一致案例)==")
from collections import Counter
c = Counter()
for r in bad_recs:
    for h in verdict(r): c[round(h["n"])] += 1
for k in sorted(c): print("   n≈%2d 年 : %d 句" % (k, c[k]))

print("\n== 08-20 後不一致的稿(最多 15 支)==")
for r in sorted([r for r in bad_recs if r["mtime"]>=CUT], key=lambda x:x["mtime"])[:15]:
    h = verdict(r)[0]
    print("  %s 片名%s年 ｜數字自招 %.1f 年 (R=%.1f%%, a=%.1f%%) ｜ %s"
          % (r["mtime"], int(r["N"]), h["n"], h["R"], h["a"], r["base"][:44]))

json.dump([dict(base=r["base"],mtime=r["mtime"],N=r["N"],
                bad=[dict(n=h["n"],R=h["R"],a=h["a"],sent=h["sent"]) for h in verdict(r)])
           for r in bad_recs],
          io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"arith_rows.json"),
                  "w",encoding="utf-8"), ensure_ascii=False, indent=1)
