# -*- coding: utf-8 -*-
"""harm7 = harm5 + 結構化欄位斷句(見下)。harm5 = harm4 + 「最相符的鄰近個股數字」配對(最終版)。

harm4 為什麼還不夠:
  它拿「離 0050 句最近的個股句」配對。08-30 那批稿的版型是
  「XX 三種買法對決:All-in / 定期定額 / 0050:近10年(2016-08-01起,可信資料共同起點):
    XX單筆All-in總報酬…」—— 個股與 0050 在**同一句**且該句自己標明十年,
  而同片另有一個「上市以來約18.6年含息還原體檢」區塊。harm4 把這兩個**各自標好期間的區塊**
  硬配在一起,7 支全是這個誤報。

本版判準:
  對每一組 0050 的 (總報酬,年化) ⇒ n_0050,
  在前後 4 句(含本句)內抽出**所有**個股的 (總報酬,年化) ⇒ {n_i},
  取 min |n_0050 - n_i|。有任何一組對得上(≤1.5 年)⇒ 觀眾看到的並排是同期,無害。
  一組都對不上 ⇒ 🔴 真期間偷換。
  (同一句裡個股與 0050 並排時,句內那組必然入選。)

harm5 為什麼還不夠:08-30 起的稿不是散文而是**結構化欄位**
  「久元 三種買法對決:All-in / 定期定額 / 0050:近10.0年(2016-08-19起…):久元單筆All-in總報酬…;…」
  不切「;」就把整塊當一句,而『最後一個別名之後』抓到的其實是**個股自己的**數字
  ⇒ 5 支誤報。本版把「;」也當斷句符,W 隨之放寬到 6。

🔴 射程限制:
  1. 只看同句同時給總報酬+年化者;只給單一數字的比較看不見 ⇒ **報的是下界**。
  2. 「對得上」只證明期間長度相同,不證明起點相同(起點錯位本工具看不見)。
  3. 讀的是磁碟上今天的 .voice.txt,不等於當初發布的那一版。
  4. 解析器先過 13 項單元測試才准掃(harm3 曾因漏「千」把 3967.4 讀成 3,
     而七支對照**全部矇對** —— 對照要挑會踩到已知弱點的樣本)。
"""
import re, io, os, glob, sys, math, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CN = {"零":0,"〇":0,"一":1,"二":2,"兩":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
UNIT = {"十":10, "百":100, "千":1000}

def cn2num(s):
    s = s.strip()
    if not s: return None
    if "點" in s:
        a,_,b = s.partition("點")
        ai = cn2num(a)
        if ai is None: return None
        frac = "".join(str(CN[c]) for c in b if c in CN)
        return float("%d.%s" % (int(ai), frac or "0"))
    if all(c in CN for c in s) and len(s) > 1:      # 位值寫法 二零一六
        return float(int("".join(str(CN[c]) for c in s)))
    tot = sec = cur = 0; seen_unit = None
    for c in s:
        if c in CN: cur = CN[c]
        elif c in UNIT:
            u = UNIT[c]
            if seen_unit is not None and u >= seen_unit: return None  # 十六百 這種畸形串,拒收
            seen_unit = u
            sec += (cur or 1) * u; cur = 0
        elif c == "萬":
            tot += (sec + cur) * 10000; sec = cur = 0; seen_unit = None
        else: return None
    return float(tot + sec + cur)

# ── 先驗尺:解析器單元測試,不過就 exit ──────────────────────────
T = [("三千九百六十七點四",3967.4), ("一千零四十九點三",1049.3), ("兩百三十七點六",237.6),
     ("七百二十一點一",721.1), ("六千九百八十九",6989.0), ("九千五百一十七",9517.0),
     ("五千三百六十一點九",5361.9), ("一百五十八",158.0), ("九點九",9.9), ("二十三點五",23.5),
     ("一萬兩千三百",12300.0), ("二零一六",2016.0), ("十六百七十四",None)]
bad = [(a,b,cn2num(a)) for a,b in T if cn2num(a) != b]
if bad:
    print("🔴 解析器測試不過,不准掃描:"); [print("   %s 期望%s 得到%s"%x) for x in bad]; sys.exit(1)
print("✅ 解析器 13 項測試全過(含千/萬/位值/畸形串拒收)\n")

ALIAS = re.compile(r"0050|零零五零|元大[臺台]灣\s*50|元大[臺台]灣五十")
NUM   = r"(?:百分之([零〇一二三四五六七八九十百千萬兩點]+)|([\d,]+(?:\.\d+)?)\s*%)"
TOT   = re.compile(r"總報酬(?:率)?[^，。]{0,8}?" + NUM)
ANN   = re.compile(r"年化(?:報酬率?)?[^，。]{0,10}?" + NUM)
SENT  = re.compile(r"[^。！？；;\n]{2,}[。！？；;]?")
OUT   = r"D:\carson-agent\youtube_channel\output"
TOL   = 1.5

def grab(rx, s):
    m = rx.search(s)
    if not m: return None
    return cn2num(m.group(1)) if m.group(1) else float(m.group(2).replace(",",""))

def yrs(R, a):
    if R is None or a is None or R <= 0 or a <= 0: return None
    return math.log(1+R/100.0)/math.log(1+a/100.0)

def title_years(b):
    m = re.search(r"(?:存|抱|套牢|長抱|持有)\s*(\d+)\s*年", b)
    return float(m.group(1)) if m else None

def scan(path):
    ss = [m.group(0).strip() for m in SENT.finditer(
          io.open(path,encoding="utf-8",errors="replace").read()) if m.group(0).strip()]
    stock, etf = [], []          # stock 收「句內所有」個股組;0050 只認別名之後
    for i, s in enumerate(ss):
        al = list(ALIAS.finditer(s))
        if al:
            tail = s[al[-1].end():]
            n = yrs(grab(TOT, tail), grab(ANN, tail))
            if n: etf.append((i, n, s))
            head = s[:al[0].start()]
            for seg in (head, tail):          # 同句裡的個股數字也要收
                for m in TOT.finditer(seg):
                    a2 = ANN.search(seg[m.end():m.end()+60])
                    if not a2: continue
                    R = cn2num(m.group(1)) if m.group(1) else float(m.group(2).replace(",",""))
                    A = cn2num(a2.group(1)) if a2.group(1) else float(a2.group(2).replace(",",""))
                    n2 = yrs(R, A)
                    if n2 and abs(n2 - (n or -1)) > 1e-9: stock.append((i, n2, s))
        else:
            for m in TOT.finditer(s):
                a2 = ANN.search(s[m.end():m.end()+60])
                if not a2: continue
                R = cn2num(m.group(1)) if m.group(1) else float(m.group(2).replace(",",""))
                A = cn2num(a2.group(1)) if a2.group(1) else float(a2.group(2).replace(",",""))
                n2 = yrs(R, A)
                if n2: stock.append((i, n2, s))
    if not etf or not stock: return None
    W = 6
    worst = None
    for i, ne, se in etf:
        near = [(j, n2, sk) for j, n2, sk in stock if abs(j - i) <= W]
        if not near: continue
        j, nsk, sk = min(near, key=lambda x: abs(x[1] - ne))
        d = abs(ne - nsk)
        if worst is None or d > worst["d"]:
            worst = dict(d=round(d,2), n0050=round(ne,2), nstock=round(nsk,2),
                         sent=se, stock_sent=sk, gap=abs(i-j))
    if worst is None: return None
    return dict(base=os.path.basename(path), N=title_years(os.path.basename(path)),
                bad=worst["d"] > TOL,
                mtime=datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat(), **worst)

files = sorted(glob.glob(os.path.join(OUT,"*個股體檢*.voice.txt")))
recs = [x for x in (scan(p) for p in files) if x]

print("== 對照(七支手開過原檔;含三支專挑「個股數字帶千」的)==")
EXPECT = {"安勤3479":False,"台虹8039":False,"陽明2609":False,"力成6239":False,
          "合晶6182":False,"昇達科3491":False,      # 合晶個股 1049.3%(帶千)
          "台光電2383":False,"奇鋐3017":False,"旺矽6223":False,  # harm3 因千 bug 誤報的三支
          "眾達-KY4977":True}
ok = True
for kw, want in EXPECT.items():
    r = [x for x in recs if kw.replace("-","").replace("台","臺") in x["base"].replace("-","").replace("台","臺")]
    if not r: print("  %-12s 找不到 ⇒ 對照失效"%kw); ok=False; continue
    r = r[0]; good = (r["bad"]==want); ok &= good
    print("  %-12s 個股%6.1f年 vs 0050%6.1f年 差%5.1f ⇒ %s(期望%s)%s"
          % (kw, r["nstock"], r["n0050"], r["d"], "🔴偷換" if r["bad"] else "無害",
             "🔴偷換" if want else "無害", "  OK" if good else "  🔴FAIL"))
if not ok: print("\n🔴 對照沒全過,不准報數字。"); sys.exit(1)
print("✅ 九支陰性 + 一支陽性(另一條線獨立判定)全過\n")

CUT = "2026-08-20"
for label, sel in (("全部",recs),("08-20 前",[r for r in recs if r["mtime"]<CUT]),
                   ("08-20 後",[r for r in recs if r["mtime"]>=CUT])):
    n=len(sel); b=sum(1 for r in sel if r["bad"])
    print("  %-9s 可判定=%3d  🔴真期間偷換=%2d (%4.1f%%)" % (label,n,b,100.0*b/n if n else 0))
print("\n== 🔴 逐支 ==")
for r in sorted([x for x in recs if x["bad"]], key=lambda x:x["mtime"]):
    print("  %s 個股%5.1f vs 0050%5.1f 差%4.1f 片名%s年  %s"
          % (r["mtime"],r["nstock"],r["n0050"],r["d"],r["N"],r["base"][:52]))
    print("      個股｜%s" % r["stock_sent"][:96])
    print("      0050｜%s" % r["sent"][:96])
json.dump(recs, io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"harm7_rows.json"),
          "w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
