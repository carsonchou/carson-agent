# -*- coding: utf-8 -*-
"""退稿區複驗:被閘門擋下的「期間偷換」到底是不是真的?

🔴🔴 2026-09-11 夜:**本工具的基準是錯的,標紅結果全部作廢,不要引用任何數字。**
   w9:p1 手開全部 16 支標紅,只有聯電 2303 是真的;督導回頭手開六支原檔,
   六支的旁白都在同一段寫明「近十年,從 2016-08-01 起」,個股與 0050 兩邊都是十年。
   下面那段「在這個母體片名基準是對的」是**沒查證就寫下的前提**,查證只要開一支稿讀那一段。
   ⇒ 這支還留著只為了留下錯誤形狀(和 01~03 同一個理由)。要重做,基準必須是
     **同段個股自己的 (總報酬, 年化) 反推**,和 04 一樣;片名年數只能當提示,不能當基準。
   詳見 docs/ops/2026-09-11_期間偷換_督導獨立複驗.md §九。

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
# ---- 移植 05_arith_selfconsist_ruler.py 的解析修正(基建線 09-11)----
# 🔴 **移植本身沒問題,但不要引用「16→13」那個數**(督導 09-11 夜裁決):
#    那個差分是拿**本檔這把基準錯掉的尺**量出來的,前後兩次都量在錯的東西上,
#    差分不會因為兩邊用同一把錯尺就變得有意義(memory `wrong-baseline-measures-the-design`)。
#    作廢範圍見本檔 docstring 開頭那段。
# 修的是本檔 docstring 自己點名的已知失效(「4.6年套牢」)。三個差異:
#  一、年數要含中文數字,否則「十年ALL IN」抓不到,只抓到旁邊那個「4.6年套牢」。
#  二、🔴 NOT_PERIOD 要**雙向**掃。05 那支只掃前文(治「套牢近9年」),
#      而這個母體的長相是「4.6年套牢」—— 非期間詞在**後面**。只掃一邊會漏。
#  三、片名可能有多個候選年數 ⇒ 只有和**全部**候選都差超過 TOL 才標紅。
# 對照(memory `fp-fixes-silently-eat-true-positives`):補完後那 6 支
# (0829_0729/0803/0810/1251/1319/1326)**全部仍標紅**,且**零支新增變紅**。
# 🔴 當時我把這 6 支寫成「督導手開確認的真陽性」,**那句話已被督導自撤**:
#    六支原檔的旁白都在同一段寫明「近十年,從二零一六年八月一日開始」,
#    個股與 0050 兩邊都是十年,**零支偷換** —— 我是拿**片名年數**當個股那一邊
#    的期間才標紅的。⇒ 這一列剩下的意義只有「改動沒讓輸出翻面」,
#    **不是陽性對照**(陽性對照要用真案例,而這個母體裡真陽性只有聯電 2303)。
# ⚠️ 消掉的三支意義不同:嘉澤 3533、臺虹 8039 變 ok(片名真期間就是十年,n=10.0 自洽);
#    尖點 8021 變**片名無年數**=不可判定,那是「儀器不再亂猜」不是「已證明沒問題」。
# ⚠️ 豐泰 9910(0826_1339,6.7%/0.7%)**沒修掉**:那是成對抽錯不是年數抽錯,本補不治。
YRT = re.compile(r"(?:(\d+(?:\.\d+)?)|([零〇一二三四五六七八九十百千萬兩點]+))\s*年")
NOT_PERIOD = re.compile(r"套牢|解套|創高|間隔|長達|腰斬|停滯|又$|個月")
TOL = 1.5

def title_years(ttl):
    out = []
    for m in YRT.finditer(ttl):
        v = float(m.group(1)) if m.group(1) else cn2num(m.group(2))
        if v is None or v <= 0.5 or v >= 100: continue          # ≥100 是西元年不是期間
        if NOT_PERIOD.search(ttl[max(0, m.start()-14):m.start()]): continue
        if NOT_PERIOD.search(ttl[m.end():m.end()+4]): continue  # 「4.6年套牢」
        out.append(v)
    return out

rows = []
for f in sorted(glob.glob(os.path.join(ROOT, "*.txt"))):
    t = io.open(f, encoding="utf-8", errors="replace").read()
    if "期間偷換" not in t[:300]: continue
    m = re.search(r"# 標題:\s*(.*)", t)
    ttl = m.group(1).strip() if m else ""
    tys = title_years(ttl); ty = tys[0] if tys else None
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
    v = ("🔴疑真偷換" if all(abs(n - y) > TOL for y in tys) else "ok") if tys else "片名無年數"
    if tys and len(tys) > 1: ty = min(tys, key=lambda y: abs(n - y))
    rows.append((os.path.basename(f)[:9], ttl[:34], ty, R, g, n, v))

print("退稿區「期間偷換」共 %d 支\n" % len(rows))
print("%-10s %-6s %-9s %-7s %-6s %-8s %s" % ("檔", "片名年", "0050總", "0050年化", "推算n", "判", "標題"))
for k, ttl, ty, R, g, n, v in rows:
    print("%-10s %-6s %-9s %-7s %-6s %-8s %s" % (
        k, ty if ty else "-", ("%.1f" % R) if R else "-", ("%.1f" % g) if g else "-",
        ("%.1f" % n) if n else "-", v, ttl))
print("\n🔴🔴 本工具的**基準是錯的**(見檔頭 docstring),標紅數字全部作廢,不要引用。")
print("   「N年套牢」那類解析失效已在 09-11 修掉,但修前修後的支數差**不要引用** ——")
print("   兩次都量在錯的基準上。真要判,只有一條路:**開原檔讀那一段**。")
print("   但仍有已知殘留:豐泰 9910(0826_1339)是**成對抽錯**(6.7%/0.7%),不是年數抽錯。")
print("   「片名無年數」= 不可判定,**不算通過**。")
