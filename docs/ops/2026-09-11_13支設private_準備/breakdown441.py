# -*- coding: utf-8 -*-
"""自己重算 627a3f4e 的「441 支判不動」拆解 —— 不照抄驗證者。
① 10 個目錄找得到 voice.txt 的 / 找不到的
② 找不到的裡:_ch_<videoId> 佔位 slug(reconcile_ledger.py 從頻道回填、本機從來沒有 slug)幾支
③ 找不到的裡:git 歷史(--all)任何路徑出現過同名 .voice.txt 的幾支 → 取 git 最後一版,兩把尺判
"""
import io, json, os, re, sys, subprocess, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REPO = r"D:\carson-agent"; R = os.path.join(REPO, "youtube_channel")
SP = os.path.dirname(os.path.abspath(__file__))
led = json.load(io.open(os.path.join(R, "STUDIO", "uploaded_ledger.json"), encoding="utf-8"))
slugs = list(led)
DIRS10 = ["output", "output/_redo", "output/_rejected", "output/_husk_bak", "output/_bad_leak", "output/_retired_ep0",
          "output/_quarantine", "output/_quarantine_bad_script", "output_recover_bak", "scripts/out_sample"]

CTA = re.compile(r"訂閱|追蹤我|追蹤一下|回開頭|回頭重聽|重聽一次開頭|留言告訴我|私訊|Telegram|@Carson"
                 r"|按讚|分享給|不構成投資建議|把這句記起來|這就是「")
ECHO_CUE = re.compile(r"回開頭|回頭重聽|重聽一次開頭|從頭再聽一次|回到開頭")
QUOTED = re.compile(r"[「『\"]([^」』\"]{1,80})[」』\"]")
LEAD2 = re.compile(
    r"(?:(?:不確定的話|如果這個結果讓你意外|再看一次也可以)?[，,]?\s*"
    r"(?:回開頭再聽一次|回開頭對一次|回頭重聽一次開頭|回到開頭再聽一次)"
    r"|這就是|把這句記起來[：:]?)\s*$")
def split_s(t):
    return [s for s in re.split(r"(?<=[。!?！？\n])", t) if re.sub(r"\s", "", s)]
def effective_body(t):
    return "".join(re.sub(r"\s", "", s) for s in split_s(t) if not CTA.search(s))
def echo_leftover(t):
    best = None
    for s in split_s(t):
        if not ECHO_CUE.search(s): continue
        at = t.find(s)
        for m in QUOTED.finditer(s):
            pre = LEAD2.sub("", s[:m.start()])
            head = re.sub(r"\s", "", t[:at] + pre)
            q = re.sub(r"\s", "", m.group(1))
            if q and q == head[:len(q)]:
                v = len(head) - len(q)
                best = v if best is None else min(best, v)
        if best is None: best = 999
    return best
FLOOR = {"S_": 28, "L_": 600}

def find10(sl):
    for d in DIRS10:
        if os.path.exists(os.path.join(R, d, sl + ".voice.txt")): return d
    return None
have = [s for s in slugs if find10(s)]
miss = [s for s in slugs if not find10(s)]
print("ledger %d | 10 目錄找得到 %d | 找不到 %d" % (len(slugs), len(have), len(miss)))
print("  找不到的前綴:", dict(collections.Counter(s[:3] if s.startswith("_ch") else s[:2] for s in miss)))
ch = [s for s in miss if s.startswith("_ch_")]
print("② _ch_ 佔位:%d 支(其中 key == '_ch_'+videoId:%d)" % (len(ch), sum(1 for s in ch if s == "_ch_" + led[s])))
print("   _ch_ 在找得到那側:%d" % sum(1 for s in have if s.startswith("_ch_")))

# git 歷史所有出現過的 .voice.txt 路徑(含已刪除)
paths = [l.strip() for l in io.open(os.path.join(SP, "my_git_voice_paths_all.txt"), encoding="utf-8") if l.strip()]
by_base = collections.defaultdict(list)
for p in paths:
    b = os.path.basename(p)
    if b.endswith(".voice.txt"): by_base[b[:-len(".voice.txt")]].append(p)
rec = [s for s in miss if s in by_base]
print("③ 找不到的裡,git 歷史出現過同名 .voice.txt:%d 支" % len(rec))
print("   前綴:", dict(collections.Counter(s[:2] for s in rec)))
rows = []
for s in rec:
    ps = by_base[s]
    best = None
    for p in ps:  # 每條路徑最後一次碰它的 commit;取時間最晚、且該版本存在的
        o = subprocess.run(["git", "-C", REPO, "log", "--all", "-1", "--format=%H %ct", "--", p],
                           capture_output=True, text=True, encoding="utf-8").stdout.split()
        if not o: continue
        h, ct = o[0], int(o[1])
        blob = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (h, p)], capture_output=True)
        if blob.returncode != 0:  # 該 commit 是刪除 → 取父 commit 的版本
            blob = subprocess.run(["git", "-C", REPO, "show", "%s^:%s" % (h, p)], capture_output=True)
            if blob.returncode != 0: continue
            h = h + "^"
        if best is None or ct > best[1]:
            best = (h, ct, p, blob.stdout.decode("utf-8", "replace"))
    if best is None:
        rows.append(dict(slug=s, vid=led[s], err="git 讀不回")); continue
    h, ct, p, t = best
    eb, el = len(effective_body(t)), echo_leftover(t)
    pre = s[:2]
    A = pre in FLOOR and eb <= FLOOR[pre]; B = el is not None and el <= 2
    on_disk_now = os.path.exists(os.path.join(REPO, p))
    rows.append(dict(slug=s, vid=led[s], commit=h[:10], path=p, eb=eb, el=el, A=A, B=B,
                     chars=len(re.sub(r"\s", "", t)), on_disk_now=on_disk_now))
for r in rows:
    print("   %-11s eb=%-5s el=%-4s A=%-5s B=%-5s %s  %s  %s" % (r["vid"], r.get("eb"), r.get("el"), r.get("A"), r.get("B"),
          r.get("commit"), r.get("path", r.get("err")), r["slug"][:30]))
nA = sum(1 for r in rows if r.get("A")); nB = sum(1 for r in rows if r.get("B"))
print("   兩把尺命中:尺A %d / 尺B %d / 讀不回 %d" % (nA, nB, sum(1 for r in rows if "err" in r)))
print("   git 路徑的目錄分佈:", collections.Counter(os.path.dirname(r["path"]) for r in rows if "path" in r).most_common(5))
print("   現在磁碟上有那條路徑的:", sum(1 for r in rows if r.get("on_disk_now")))
both = set(ch) & set(rec)
truly = len(miss) - len(ch) - len(rec) + len(both)
print("\n⇒ 441 = _ch_ %d + git 可補 %d + 真正判不動 %d(_ch_ 與 git 重疊 %d)" % (len(ch), len(rec), truly, len(both)))
# 真正判不動那一格在帳本裡的位置
order = {s: i for i, s in enumerate(slugs)}
tr = [s for s in miss if s not in set(ch) and s not in set(rec)]
print("   真正判不動 %d 支:帳本前 441 筆內 %d / 後段 %d" % (len(tr), sum(1 for s in tr if order[s] < 441), sum(1 for s in tr if order[s] >= 441)))
print("   _ch_ 在帳本位置:前 441 內 %d / 後段 %d" % (sum(1 for s in ch if order[s] < 441), sum(1 for s in ch if order[s] >= 441)))
json.dump(rows, io.open(os.path.join(SP, "breakdown441_rows.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
