"""用可量測的代理指標排序旁白吸引力(我聽不到,不猜)。

指標與依據:
  語速  wpm —— 解說類甜蜜點 150-170。太慢悶、太快聽不懂。
  音高變化 —— 半音標準差。單調(<1.5)= 無聊;過大(>5)= 誇張不可信。
  動態範圍 —— 短時能量的 p90-p10(dB),抑揚頓挫的量。
  清晰度  —— 2-4kHz(子音辨識帶)佔比。太低含糊、太高刺耳。
"""
import glob, sys, numpy as np, soundfile as sf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NWORDS = 63     # 樣稿字數


def f0_track(x, sr, lo=60, hi=350):
    """自相關基頻追蹤:只在有聲段取值。"""
    win = int(sr * 0.045); hop = int(sr * 0.015)
    vals = []
    for i in range(0, len(x) - win, hop):
        seg = x[i:i + win]
        if np.sqrt((seg ** 2).mean()) < 0.015:      # 靜音/氣音跳過
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, "full")[win - 1:]
        lo_i, hi_i = int(sr / hi), int(sr / lo)
        if hi_i >= len(ac):
            continue
        p = int(np.argmax(ac[lo_i:hi_i])) + lo_i
        if ac[p] > 0.3 * ac[0]:
            vals.append(sr / p)
    return np.array(vals)


rows = []
for f in sorted(glob.glob("ch3_lab/sw_*.wav")):
    x, sr = sf.read(f)
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = len(x) / sr
    wpm = NWORDS / dur * 60
    f0 = f0_track(x.astype(np.float64), sr)
    semi = 12 * np.log2(f0 / np.median(f0)) if len(f0) > 20 else np.array([0.0])
    pitch_var = float(np.std(semi))
    # 動態範圍
    win = int(sr * 0.05)
    e = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    e = e[e > 1e-4]
    dyn = float(20 * np.log10(np.percentile(e, 90) / np.percentile(e, 10))) if len(e) else 0
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / sr)
    b = lambda a, c: float((X[(fr >= a) & (fr < c)] ** 2).sum())
    clarity = b(2000, 4000) / (b(80, 8000) + 1e-9) * 100
    rows.append((f.split("sw_")[1][:-4], wpm, float(np.median(f0)) if len(f0) else 0,
                 pitch_var, dyn, clarity))

# 評分:語速離 160 越近越好;音高變化 2.5-4.5 最佳;動態 12-22dB;清晰度 3-9%
def score(r):
    _, wpm, f0m, pv, dyn, cl = r
    s_wpm = max(0, 1 - abs(wpm - 160) / 60)
    s_pv = max(0, 1 - abs(pv - 3.5) / 3.0)
    s_dyn = max(0, 1 - abs(dyn - 17) / 12)
    s_cl = max(0, 1 - abs(cl - 6) / 6)
    return 0.34 * s_wpm + 0.30 * s_pv + 0.21 * s_dyn + 0.15 * s_cl

rows.sort(key=score, reverse=True)
print(f"{'聲線':<13}{'語速':>7}{'基頻':>7}{'音高變化':>9}{'動態dB':>8}{'清晰%':>7}{'總分':>7}")
for r in rows:
    print(f"{r[0]:<13}{r[1]:7.0f}{r[2]:7.0f}{r[3]:9.2f}{r[4]:8.1f}{r[5]:7.1f}{score(r)*100:7.1f}")
