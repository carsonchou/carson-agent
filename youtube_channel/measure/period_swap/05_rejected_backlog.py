# -*- coding: utf-8 -*-
"""退稿區複驗:被閘門擋下的「期間偷換」到底是不是真的?

為什麼要有這支:04 只掃 output/ 的 .voice.txt,母體是**上得了線的稿**。
「真偷換只有 1 支」講的是那個母體,不能讀成「這個缺陷罕見」。
被擋下來的那 45 支在 output/_rejected/,格式是 *.txt 且第一行有「# 報廢原因:」。

判準和 04 不同,因為 08-30 之前的稿是散文格式,個股的期間只寫在**片名**裡,
稿內不一定有個股自己的 (總報酬, 年化) 成對數字可以反推。
所以這裡拿 0050 的反推 n 去比**片名年數** —— 在這個母體它是對的基準
(散文格式沒有「固定十年共同起點」這個規格),但它是 04 明確報廢過的基準,
**換母體才成立,不要把它搬回 04 用。**

已知失效:片名年數的正則會抓到「4.6年套牢」這種非期間的年數(嘉澤 3533 就是)。
⇒ 標紅的每一支都必須手開原檔確認,本工具只負責縮小範圍。
"""
import io, glob, sys, re, math, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\carson-agent\youtube_channel\output\_rejected"

CN = {"零":0,"〇":0,"一":1,"二":2,"兩":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
U  = {"十":10,"百":100,"千":1000}

def cn2num(s):
    if "點" in s:
        a, b = s.split("點", 1)
        i = cn2num(a)
        if i is None or not b or any(c not in CN for c in b): return None
        return i + float("0." + "".join(str(CN[c]) for c in b))
    tot = sec = cur = 0; su = None
    for c in s:
        if c in CN: cur = CN[c]
        elif c in U:
            u = U[c]
            if su is not None and u >= su: return None   # 「十六百」這種畸形串
            su = u; sec += (cur or 1) * u; cur = 0
        elif c == "萬": tot += (sec + cur) * 10000; sec = cur = 0; su = None
        else: return None
    return float(tot + sec + cur)

# 先驗尺再用尺:錯就 exit,不准往下掃
T = [("六百三十九點八",639.8), ("二十二點二",22.2), ("七百一十二",712.0),
     ("三十三點八",33.8), ("三千九百六十七點四",3967.4), ("十六百七十四",None)]
bad = [(a, b, cn2num(a)) for a, b in T if cn2num(a) != b]
if bad:
    print("🔴 解析器測試不過,不准掃描:"); [print("   ", x) for x in bad]; sys.exit(1)

def num(s):
    m = re.match(r"百分之([零〇一二三四五六七八九十百千萬兩點]+)", s)
    return cn2num(m.group(1)) if m else float(s.replace(",", "").rstrip("%").strip())

NUM = r"(?:百分之[零〇一二三四五六七八九十百千萬兩點]+|[\d,]+(?:\.\d+)?\s*%)"
AL  = re.compile(r"0050|零零五零|元大[臺台]灣\s*50|元大[臺台]灣五[十零]")
TOT = re.compile(r"總報酬(?:率)?[^，。]{0,10}?(" + NUM + ")")
ANN = re.compile(r"年化(?:報酬率?)?[^，。]{0,10}?(" + NUM + ")")
YRT = re.compile(r"(\d+(?:\.\d+)?)\s*年")
TOL = 1.5

rows = []
for f in sorted(glob.glob(os.path.join(ROOT, "*.txt"))):
    t = io.open(f, encoding="utf-8", errors="replace").read()
    if "期間偷換" not in t[:300]: continue
    m = re.search(r"# 標題:\s*(.*)", t)
    ttl = m.group(1).strip() if m else ""
    ym = YRT.search(ttl); ty = float(ym.group(1)) if ym else None
    pair = None
    for s in re.split(r"[。！？；;\n]", t):
        a0 = AL.search(s)
        if not a0 or "嚴禁" in s or "【" in s or "禁止" in s: continue
        seg = s[a0.start():]                     # 主體邊界:只收 0050 之後的數字
        a, b = TOT.search(seg), ANN.search(seg)
        if a and b:
            R, g = num(a.group(1)), num(b.group(1))
            if R and g and R > 0 and g > 0: pair = (R, g); break
    if not pair:
        rows.append((os.path.basename(f)[:9], ttl[:34], ty, None, None, None, "配不成對")); continue
    R, g = pair
    n = math.log(1 + R / 100) / math.log(1 + g / 100)
    v = "🔴疑真偷換" if (ty and abs(n - ty) > TOL) else ("ok" if ty else "片名無年數")
    rows.append((os.path.basename(f)[:9], ttl[:34], ty, R, g, n, v))

print("退稿區「期間偷換」共 %d 支\n" % len(rows))
print("%-10s %-6s %-9s %-7s %-6s %-8s %s" % ("檔", "片名年", "0050總", "0050年化", "推算n", "判", "標題"))
for k, ttl, ty, R, g, n, v in rows:
    print("%-10s %-6s %-9s %-7s %-6s %-8s %s" % (
        k, ty if ty else "-", ("%.1f" % R) if R else "-", ("%.1f" % g) if g else "-",
        ("%.1f" % n) if n else "-", v, ttl))
print("\n🔴 的每一支都要手開原檔確認 —— 片名年數會抓到「N年套牢」這種非期間數字。")
