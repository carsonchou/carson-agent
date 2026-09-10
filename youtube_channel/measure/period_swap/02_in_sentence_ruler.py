# -*- coding: utf-8 -*-
"""交集尺:期間不符 ∧ 同句沒揭露 ⇒ 觀眾被誤導。

為什麼要交集(這一段是本檔存在的理由):
  · 只用「同句沒寫期間」(w9 的 ①):會叫到「數字其實就是片名那段期間」的無害句。
  · 只用「算術上期間不符」(督導的算術尺):會叫到**設計本身** ——
    three_way 對照固定用十年(共同起點才比得了 0050),片名 16 年配十年 0050 數字,
    只要那句寫了「近十年」就是誠實的。單獨用它會得到 73.3%,而那個數字幾乎全是設計不是缺陷。
  ⇒ 兩者**都成立**才是「數字不是這段期間的,而且觀眾看不出來」。

分三格報,不合併(memory:31.1% 被標記 ≠ 三成的片講錯了):
  A 期間不符 ∧ 沒揭露   = 觀眾被誤導          🔴
  B 期間不符 ∧ 有揭露   = 設計如此,誠實
  C 期間相符             = 本來就同一段期間

對照:
  陽性 安勤3479 —— 片名16年、數字自招10年、該句無期間 ⇒ 必須落 A
  陰性 大立光3008 —— 片名10年、數字自招10年 ⇒ 必須落 C
  陰性2 需要一支落 B 的(有揭露),跑完自動挑一支印出來人工複核
"""
import re, io, os, glob, sys, math, json, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arith.py"),
              encoding="utf-8").read().split("# ── 對照 ──")[0]
ns = {}
exec(compile(src, "arith_head", "exec"), ns)
scan, OUT = ns["scan"], ns["OUT"]

PERIOD = re.compile(r"[0-9零〇一二三四五六七八九十百兩\.]\s*年|上市以來|掛牌以來|成立以來")
TOL = 1.5

def classify(rec):
    """回傳 (格, 句) —— 一支稿只要有一句落 A 就是 A;否則有 B 就是 B;否則 C"""
    best = ("C", None)
    for h in rec["hits"]:
        mismatch = abs(h["n"] - rec["N"]) > TOL
        if not mismatch: continue
        disclosed = bool(PERIOD.search(h["sent"]))
        if not disclosed: return ("A", h)
        best = ("B", h)
    return best

recs = []
for p in sorted(glob.glob(os.path.join(OUT, "*個股體檢*.voice.txt"))):
    r = scan(p)
    if r: r["cls"], r["hit"] = classify(r); recs.append(r)

# ── 對照 ──
print("== 對照 ==")
ok = True
def one(kw):
    for r in recs:
        if kw in r["base"]: return r
for label, kw, want in (("陽性 安勤3479","安勤3479","A"), ("陰性 大立光3008","大立光3008十年","C")):
    r = one(kw)
    if r is None: print("  %s 不在射程內 ⇒ 對照無效"%label); ok=False; continue
    m = "OK" if r["cls"]==want else "🔴FAIL"
    if r["cls"]!=want: ok=False
    print("  %-15s 片名%s年 判為 %s (期望 %s) ⇒ %s" % (label,int(r["N"]),r["cls"],want,m))
if not ok:
    print("\n🔴 對照沒過,數字不准引用。"); sys.exit(1)
print("✅ 對照通過\n")

CUT = "2026-08-20"
from collections import Counter
def table(label, sel):
    c = Counter(r["cls"] for r in sel)
    n = len(sel)
    if not n: return
    print("  %-9s 可判定=%3d ｜ 🔴A 誤導=%3d (%4.1f%%) ｜ B 誠實=%3d ｜ C 同期=%3d"
          % (label, n, c["A"], 100.0*c["A"]/n, c["B"], c["C"]))

print("== 母體 = 片名有年數 且 有『同句同時給 0050 總報酬+年化』的個股體檢稿 ==")
table("全部", recs)
table("08-20 前", [r for r in recs if r["mtime"] <  CUT])
table("08-20 後", [r for r in recs if r["mtime"] >= CUT])
print()
by = {}
for r in recs:
    by.setdefault(r["mtime"][:7], []).append(r)
for m in sorted(by): table(m, by[m])

print("\n== B 格(期間不符但有揭露)抽一支人工複核 ==")
b = [r for r in recs if r["cls"]=="B"]
if b:
    r = b[0]; print("  %s 片名%s年 n=%.2f" % (r["base"][:50], int(r["N"]), r["hit"]["n"]))
    print("   " + r["hit"]["sent"][:150])
else:
    print("  🔴 B 格是空的 —— 那表示『有揭露』這個條件從來沒成立過,要懷疑 PERIOD 正則")

print("\n== 🔴 A 格:08-20 之後的(全部)==")
A = sorted([r for r in recs if r["cls"]=="A" and r["mtime"]>=CUT], key=lambda x:x["mtime"])
for r in A:
    print("  %s 片名%2d年 數字自招%.1f年 R=%.1f%% a=%.1f%%  %s"
          % (r["mtime"], int(r["N"]), r["hit"]["n"], r["hit"]["R"], r["hit"]["a"], r["base"][:46]))
print("  共 %d 支" % len(A))

json.dump([dict(base=r["base"],mtime=r["mtime"],N=r["N"],cls=r["cls"],
                n=r["hit"]["n"] if r["hit"] else None,
                sent=r["hit"]["sent"] if r["hit"] else None) for r in recs],
          io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"harm_rows.json"),
                  "w",encoding="utf-8"), ensure_ascii=False, indent=1)
