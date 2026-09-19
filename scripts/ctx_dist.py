import json, os, glob, sys
from datetime import datetime, timezone, timedelta

D = "D:/claude/projects/D--carson-agent"
PANE = {
 "cd3867ec":"w1:p1", "efac2502":"w9:p1", "4332a84b":"wA:p1", "cda0ca12":"wB:p1",
 "8ae57f4b":"wE:p1", "21bca2df":"wF:p1", "818543e1":"wF:p2", "5089f42d":"wF:p3",
 "bcabe778":"wF:p4", "ee3f1512":"wF:p5", "c04d599f":"wG:p4(me)",
}
NOW = datetime.now(timezone.utc)
W5 = NOW - timedelta(hours=5)
W24 = NOW - timedelta(hours=24)

def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def scan(path, acc, sid):
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except Exception:
        return
    with f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            m = o.get("message") or {}
            u = m.get("usage") or {}
            if not u:
                continue
            ts = parse_ts(o.get("timestamp") or "")
            if ts is None or ts < W24:
                continue
            ctx = (u.get("input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0)
            out = u.get("output_tokens", 0) or 0
            if ctx <= 0:
                continue
            acc.setdefault(sid, []).append((ts, ctx, out, os.path.basename(path) != sid + ".jsonl"))

acc = {}
for p in glob.glob(D + "/*.jsonl"):
    sid = os.path.basename(p)[:-6]
    if os.path.getmtime(p) < (NOW - timedelta(hours=26)).timestamp():
        continue
    scan(p, acc, sid)
for p in glob.glob(D + "/*/*.jsonl"):
    sid = os.path.basename(os.path.dirname(p))
    if os.path.getmtime(p) < (NOW - timedelta(hours=26)).timestamp():
        continue
    scan(p, acc, sid)

rows = []
for sid, recs in acc.items():
    recs.sort()
    r24 = recs
    r5 = [r for r in recs if r[0] >= W5]
    ctxs = [r[1] for r in r24]
    sub = sum(1 for r in r24 if r[3])
    rows.append(dict(
        sid=sid, pane=PANE.get(sid[:8], "-"),
        n24=len(r24), n5=len(r5), nsub=sub,
        mean=sum(ctxs)//len(ctxs), mx=max(ctxs), last=r24[-1][1],
        burn24=sum(ctxs), burn5=sum(r[1] for r in r5),
        out24=sum(r[2] for r in r24),
    ))
rows.sort(key=lambda r: -r["burn24"])
tot24 = sum(r["burn24"] for r in rows) or 1
tot5 = sum(r["burn5"] for r in rows) or 1

def mb(n): return "%.1fM" % (n/1e6)
def k(n): return "%.0fK" % (n/1e3)

print("=== 近 24h 各 session context 分佈 (%s UTC) ===" % NOW.strftime("%m-%d %H:%M"))
print("%-10s %-9s %5s %5s %8s %8s %8s %9s %6s" % ("pane","sid","calls","sub","ctx均","ctx峰","ctx末","燒量24h","佔比"))
for r in rows:
    print("%-10s %-9s %5d %5d %8s %8s %8s %9s %5.1f%%" % (
        r["pane"], r["sid"][:8], r["n24"], r["nsub"], k(r["mean"]), k(r["mx"]), k(r["last"]),
        mb(r["burn24"]), 100.0*r["burn24"]/tot24))
print("%-10s %-9s %5d %5s %8s %8s %8s %9s" % ("TOTAL","", sum(r["n24"] for r in rows), "", "", "", "", mb(tot24)))
print()
print("=== 近 5h 視窗 ===")
print("%-10s %-9s %5s %9s %6s" % ("pane","sid","calls","燒量5h","佔比"))
for r in sorted(rows, key=lambda r: -r["burn5"]):
    if r["burn5"] == 0: continue
    print("%-10s %-9s %5d %9s %5.1f%%" % (r["pane"], r["sid"][:8], r["n5"], mb(r["burn5"]), 100.0*r["burn5"]/tot5))
print("%-10s %-9s %5s %9s" % ("TOTAL","","", mb(tot5)))
print()
print("=== 反事實:如果每支都壓在 120K context ===")
hyp = sum(r["n24"]*120000 for r in rows)
print("實際 24h 燒量 = %s / 全壓 120K = %s  =>  倍率 %.2fx" % (mb(tot24), mb(hyp), tot24/float(hyp or 1)))
