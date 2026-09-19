# -*- coding: utf-8 -*-
"""同條件陰性對照 —— 自己重做,不照抄驗證者。
627a3f4e 的陽性配對用「延遲 0~8 s 搜尋取最大 r」,而陰性對照只報了一個 r=-0.0025(一支無關 mp3、
沒寫明是否同一套延遲搜尋)。這裡把陰性對照放到同一個條件:
  目標 = 14 支 S_(13 支 + 9YbT)的上架 mp4(以 API duration 對上的那一份)
  冒名 = 其他 13 支同批 mp3 + 同回聲 CTA 模板、同 TTS 聲音的非命中 S_ mp3(決定性抽樣)
  每一對都跑同一套:4 kHz mono → 20 ms RMS 包絡 → lag 0..8 s 取最大 Pearson r;另記 r@3.00s
"""
import io, json, os, re, sys, subprocess, random
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
R = r"D:\carson-agent\youtube_channel"; O = os.path.join(R, "output")
SNAPD = r"D:\carson-agent\docs\ops\2026-09-11_13支設private_準備"
led = json.load(io.open(os.path.join(R, "STUDIO", "uploaded_ledger.json"), encoding="utf-8"))
id2slug = {v: k for k, v in led.items()}
cand = json.load(io.open(os.path.join(SNAPD, "candidates.json"), encoding="utf-8"))
snap = json.load(io.open(os.path.join(SNAPD, "snapshot.json"), encoding="utf-8"))["items"]
T13 = [r["videoId"] for r in cand["videos"]]
TARGETS = T13 + ["9YbTzPfXz6A"]
SR, HOP = 4000, 80

def dur(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True).stdout.strip()
    return float(o) if o else None
def iso(s):
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", s or "")
    return (int(m.group(1) or 0) * 60 + int(m.group(2) or 0)) if m else None
cache = {}
def env(p):
    if p in cache: return cache[p]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    n = len(x) // HOP
    cache[p] = np.sqrt((x[: n * HOP].reshape(n, HOP) ** 2).mean(axis=1))
    return cache[p]
def xc(a, b, maxlag=8.0):
    best, blag, r3 = -9.0, None, None
    for lag in range(0, int(maxlag / 0.02) + 1):
        seg = b[lag: lag + len(a)]; m = min(len(seg), len(a))
        if m < 50: break
        r = float(np.corrcoef(a[:m], seg[:m])[0, 1])
        if lag == 150: r3 = r
        if r > best: best, blag = r, lag * 0.02
    return best, blag, r3

# 上架 mp4:在 .mp4 / _ytcta.mp4 中挑整秒時長與 API duration 相符的
api_dur = {v: iso(snap[v]["contentDetails"]["duration"]) for v in T13 if v in snap}
s9 = json.load(io.open(os.path.join(SNAPD, "snapshot_9YbT.json"), encoding="utf-8"))["items"]
api_dur["9YbTzPfXz6A"] = iso(s9["9YbTzPfXz6A"]["contentDetails"]["duration"])
import math  # API duration = 本機時長無條件進位(21.02→PT22S),不是四捨五入也不是截斷
mp4 = {}
for v in TARGETS:
    s = id2slug[v]
    opts = [p for p in (os.path.join(O, s + ".mp4"), os.path.join(O, s + "_ytcta.mp4")) if os.path.exists(p)]
    ds = {p: dur(p) for p in opts}
    match = [p for p, d in ds.items() if d is not None and math.ceil(d) == api_dur[v]]
    mp4[v] = match[0] if len(match) == 1 else None
    print("mp4 %s API=%ss 本機=%s → %s" % (v, api_dur[v], {os.path.basename(p)[-9:]: round(d, 2) for p, d in ds.items()},
          "唯一相符" if mp4[v] else "❌ 無唯一相符,略過"))

# 冒名 mp3 池:同批 13+1 的其他支 + 同回聲模板的非命中 S_(決定性抽 16 支)
ECHO = re.compile(r"回開頭對一次|回開頭再聽一次|把這句記起來|回頭重聽一次開頭")
sib = []
for s, v in led.items():
    if not s.startswith("S_") or v in TARGETS: continue
    vt, m3 = os.path.join(O, s + ".voice.txt"), os.path.join(O, s + ".mp3")
    if os.path.exists(vt) and os.path.exists(m3) and ECHO.search(io.open(vt, encoding="utf-8").read()):
        sib.append(v)
random.seed(20260911)
npop = len(sib)
sib = sorted(random.sample(sorted(sib), min(16, npop)))
print("\n同模板非命中冒名池:抽 %d 支(母體 %d 支同回聲模板、有 mp3 的非命中 S_)" % (len(sib), npop))
POOL = TARGETS + sib

own, worst = {}, {}
print("\n%-12s %-8s %-7s %-8s | %-8s %-12s %-8s  n" % ("target", "own maxr", "lag", "own r@3", "冒名max", "是誰的mp3", "冒名r@3max"))
for v in TARGETS:
    if not mp4[v]: continue
    b = env(mp4[v])
    r, lag, r3 = xc(env(os.path.join(O, id2slug[v] + ".mp3")), b)
    own[v] = (r, lag, r3)
    imp = []
    for w in POOL:
        if w == v: continue
        ri, li, r3i = xc(env(os.path.join(O, id2slug[w] + ".mp3")), b)
        imp.append((ri, li, r3i, w))
    imp.sort(reverse=True)
    worst[v] = imp[0]
    r3max = max(x[2] for x in imp if x[2] is not None)
    print("%-12s %.4f   %5.2fs  %.4f   | %.4f   %-12s %.4f   %d" % (v, r, lag, r3 if r3 is not None else float("nan"),
          imp[0][0], imp[0][3], r3max, len(imp)))
print("\n陽性配對 own maxr 最小值:%.4f(%s)" % min((x[0], k) for k, x in own.items()))
print("冒名 maxr 全體最大值:%.4f(target %s ← mp3 of %s @ %.2fs)"
      % max((x[0], k, x[3], x[1]) for k, x in worst.items()))
gap = min(x[0] for x in own.values()) - max(x[0] for x in worst.values())
print("⇒ 間距(陽性最小 − 冒名最大)= %.4f" % gap)
