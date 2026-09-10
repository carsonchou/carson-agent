# -*- coding: utf-8 -*-
"""harm2:允許期間宣告**跨句繼承**,而且繼承到的年數必須**對得上算術**。

為什麼要有這一版(這段是本檔存在的理由,不要刪):
  harm.py 的 A 格 = 32.0%,督導拿它當「觀眾被誤導」報過。**那是錯的。**
  手開三支原檔(安勤3479 / 台虹8039 / 陽明2609)全部發現:
      「同期/同樣的資金和時間」往前 2~4 句就有「近十年」「約十年」「同樣的十年區間」,
      而且個股自己的數字算出來也是 10 年 ⇒ 蘋果比蘋果,觀眾沒有被誤導。
  ⇒ 只看「同一句有沒有寫」量到的是**規則ⓜ-1 的字面**,不是傷害。

本版判準:
  對每一句「0050 同時給總報酬+年化」的句子,取**前 W 句 + 後 2 句**的視窗,
  抽出視窗裡所有的期間宣告年數 D(近十年→10、二零一六年八月起→算不出就記為 None 但視為有宣告年份錨點)。
  · 若 D 裡有任何一個 ≈ n(算術推出的年數,容忍 1.5)⇒ **無害**(揭露了,而且揭露對)。
  · 若視窗完全沒有任何期間宣告 ⇒ 🔴 **A 無揭露**。
  · 若視窗有宣告但沒有一個對得上 n ⇒ 🔴 **B 揭露錯**(比沒揭露更糟:主動說錯)。
  · n 與片名年數一致 ⇒ C 同期,不進分子。

🔴 已知射程限制(不得外推):
  1. 只看「同句同時給總報酬與年化」的 0050 句;只給一個數字的句子結構上看不見 ⇒ 報的是下界。
  2. 視窗是句數不是語意,W 的選擇會改變結果 ⇒ 本檔同時印 W=3/6/10 三組,不挑一個報。
  3. 讀的是磁碟上今天的 .voice.txt,不保證等於當初發布的那一版。
  4. 「2016年8月22日開始」這種**起日錨點**算「有宣告」但算不出年數 ⇒ 保守起見**視為對得上**,
     以免把誠實的稿子誤判成 B。這個選擇會讓 B 偏低,是刻意往「少報自己人有罪」偏。
"""
import re, io, os, glob, sys, math, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
src = io.open(os.path.join(HERE, "arith.py"), encoding="utf-8").read().split("# ── 對照 ──")[0]
ns = {}; exec(compile(src, "arith_head", "exec"), ns)
OUT, ALIAS, TOT, ANN, SENT, cn2num = ns["OUT"], ns["ALIAS"], ns["TOT"], ns["ANN"], ns["SENT"], ns["cn2num"]
grab, title_years = ns["grab"], ns["title_years"]

YRS   = re.compile(r"(?:近|約|過去|最近)?\s*([0-9]+|[零〇一二三四五六七八九十百兩]+)\s*年")
ANCHOR= re.compile(r"[0-9零〇一二三四五六七八九二]{2,4}\s*年\s*[0-9零一二三四五六七八九十]{1,2}\s*月"
                   r"|上市以來|掛牌以來|成立以來")
TOL = 1.5

def declared(win):
    """視窗裡宣告的年數集合;有起日錨點回 'ANCHOR'"""
    ys = set()
    for m in YRS.finditer(win):
        v = m.group(1)
        v = float(v) if v.isdigit() else cn2num(v)
        if v and 1 <= v <= 40: ys.add(v)
    if ANCHOR.search(win): ys.add("ANCHOR")
    return ys

def scan(path, W):
    base = os.path.basename(path); N = title_years(base)
    if N is None: return None
    t = io.open(path, encoding="utf-8", errors="replace").read()
    sents = [m.group(0).strip() for m in SENT.finditer(t) if m.group(0).strip()]
    worst, hit = "C", None
    rank = {"C":0, "A":3, "B":2}
    for i, s in enumerate(sents):
        al = list(ALIAS.finditer(s))
        if not al: continue
        tail = s[al[-1].end():]
        R = grab(TOT, tail); a = grab(ANN, tail)
        if R is None or a is None or R <= 0 or a <= 0: continue
        n = math.log(1+R/100.0)/math.log(1+a/100.0)
        if abs(n - N) <= TOL: cls = "C"
        else:
            win = "".join(sents[max(0,i-W): i+3])
            ds = declared(win)
            if not ds: cls = "A"
            elif "ANCHOR" in ds or any(isinstance(d,float) and abs(d-n)<=TOL for d in ds): cls = "C"
            else: cls = "B"
        if rank[cls] > rank[worst]:
            worst, hit = cls, dict(n=round(n,2), R=R, a=a, sent=s, idx=i,
                                   win=list(map(str, declared("".join(sents[max(0,i-W):i+3])))))
    import datetime
    return dict(base=base, N=N, cls=worst, hit=hit,
                mtime=datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat())

files = sorted(glob.glob(os.path.join(OUT, "*個股體檢*.voice.txt")))
print("== 對照(三支督導手開過的原檔,全部應判為 C 無害)==")
CTRL = ["安勤3479長抱16年", "台虹8039臺虹8039抱16年", "陽明26092609抱20年"]
ok = True
for kw in CTRL:
    p = [f for f in files if kw in os.path.basename(f)][0]
    r = scan(p, 6)
    m = "OK" if r["cls"]=="C" else "🔴FAIL"
    if r["cls"]!="C": ok=False
    print("  %-28s 判為 %s ⇒ %s" % (kw, r["cls"], m))
if not ok:
    print("\n🔴 手開驗證過的三支沒有全部落 C ⇒ 尺還沒對,不准報數字。"); sys.exit(1)
print("✅ 三支手驗案例全部落 C\n")

from collections import Counter
CUT = "2026-08-20"
for W in (3, 6, 10):
    recs = [x for x in (scan(p, W) for p in files) if x]
    print("== 視窗 W=%d(前%d句+後2句)==" % (W, W))
    for label, sel in (("全部", recs),
                       ("08-20 前", [r for r in recs if r["mtime"] <  CUT]),
                       ("08-20 後", [r for r in recs if r["mtime"] >= CUT])):
        c = Counter(r["cls"] for r in sel); n = len(sel)
        print("   %-9s 可判定=%3d ｜🔴A 完全沒揭露=%2d (%4.1f%%) ｜🔴B 揭露錯=%2d (%4.1f%%) ｜C 無害=%3d"
              % (label, n, c["A"], 100.0*c["A"]/n if n else 0, c["B"], 100.0*c["B"]/n if n else 0, c["C"]))
    if W == 6:
        keep = recs
    print()

print("== W=6 下的 🔴 案例逐支(A/B 全列)==")
for r in sorted([r for r in keep if r["cls"] in ("A","B")], key=lambda x:x["mtime"]):
    h = r["hit"]
    print("  %s [%s] 片名%2d年 數字自招%.1f年 視窗宣告=%s"
          % (r["mtime"], r["cls"], int(r["N"]), h["n"], h["win"] or "無"))
    print("       %s" % r["base"][:60])
    print("       ⚑ %s" % h["sent"][:110])
json.dump(keep, io.open(os.path.join(HERE,"harm2_rows.json"),"w",encoding="utf-8"),
          ensure_ascii=False, indent=1, default=str)
