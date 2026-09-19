#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ambient3.py — 三支測試片的三首原創環境樂(立體聲,無縫循環,零成本)。

繼承 drift.py 的核心原則:療癒音樂**不能有終點**(五聲音階、低音不移動、
事件疏而不成句、頭尾交叉淡接無縫循環)。三首在「結構」上刻意不同——
這不只是美學,也是差異化紅線:三支片不能是同一個模板換皮。

  A) current (Deep Work・ink 視覺):D 大調五聲。鋪底較厚、呼吸較快,
     點狀音走中高音域、密度中等 —— 給清醒的專注,不是給睡著。
  B) nightfall (Sleep・indigo 視覺):C 低音域,事件極疏(8~16 秒一顆),
     衰減拉到 10~14 秒,低通壓到 3.5kHz,整體 -3dB —— 越聽越暗。
  C) rain (Rain focus・tea 視覺):合成雨 —— 寬頻噪聲雨幕(振幅微擾)
     + 隨機水滴 transient(帶通短衰減)+ 極疏的暖音。雨是主角,音是點綴。

立體聲做法:點狀音等功率隨機聲像;鋪底左右聲道各自獨立 LFO 相位;
殘響左右用不同 IR 種子 → 去相關,耳機聽有空間感。

用法:
  python ambient3.py preview            # 三首各 60 秒樣品
  python ambient3.py full               # 三首 10 分鐘無縫循環 → 平鋪 60 分鐘 WAV
"""
import math
import sys
import wave

import numpy as np
from scipy.signal import fftconvolve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SR = 44100


def pink(n, rng):
    w = rng.normal(0, 1, n)
    X = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / SR); f[0] = f[1]
    X /= np.sqrt(f)
    return np.fft.irfft(X, n)


def hz(name):
    N = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    return 440.0 * 2 ** ((N[name[:-1]] + (int(name[-1]) - 4) * 12 - 9) / 12)


def lowpass(x, cut):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cut) ** 2.2)
    return np.fft.irfft(X, len(x))


def bandpass(x, lo, hi):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (lo / (f + 1e-9)) ** 3) * 1 / (1 + (f / hi) ** 3)
    return np.fft.irfft(X, len(x))


def pad_stereo(dur, root, rng, breathe=(0.03, 0.08), layers=None):
    """會呼吸的鋪底,左右聲道 LFO 相位獨立(頻率相同→不會漂移分家)。"""
    n = int(SR * dur); t = np.arange(n) / SR
    L = np.zeros(n); R = np.zeros(n)
    layers = layers or ((1.0, 0.42), (1.5, 0.20), (2.0, 0.17), (3.0, 0.07), (4.0, 0.045))
    for mult, base in layers:
        for det in (-1, 1):
            f = root * mult * (1 + det * 0.004 * rng.uniform(0.6, 1.4))
            lfo_r = rng.uniform(*breathe)
            phL, phR = rng.uniform(0, 2 * np.pi, 2)
            ph0 = rng.uniform(0, 6.3)
            carrier = np.sin(2 * np.pi * f * t + ph0)
            L += base * (0.72 + 0.28 * np.sin(2 * np.pi * lfo_r * t + phL)) * carrier
            R += base * (0.72 + 0.28 * np.sin(2 * np.pi * lfo_r * t + phR)) * carrier
    return L * 0.12, R * 0.12


def bell(f, dur, amp, rng, decay=(0.45, 0.42)):
    n = int(SR * dur); t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, 9):
        fk = f * k * math.sqrt(1 + 0.0002 * k * k)
        if fk > SR * 0.45:
            break
        out += (1 / k ** 1.8) * np.exp(-(decay[0] + decay[1] * k) * t) \
            * np.sin(2 * np.pi * fk * t)
    fi = int(SR * 0.012); out[:fi] *= np.linspace(0, 1, fi)
    return out * amp


def add_panned(L, R, x, at, pan):
    """等功率聲像疊加。pan∈[-1,1]。"""
    i = int(at * SR); m = min(len(x), len(L) - i)
    if m <= 0:
        return
    th = (pan + 1) * math.pi / 4
    L[i:i + m] += x[:m] * math.cos(th)
    R[i:i + m] += x[:m] * math.sin(th)


def reverb_stereo(L, R, rt, wet):
    out = []
    for ch, seed in ((L, 23), (R, 41)):     # 左右不同 IR → 去相關空間感
        n = int(SR * rt); rng = np.random.default_rng(seed)
        ir = rng.normal(0, 1, n) * np.exp(-np.linspace(0, 6.5, n))
        pre = int(SR * 0.02); ir[:pre] *= np.linspace(0, 1, pre)
        ir /= np.abs(ir).sum() / 55
        # 🔴 np.convolve 是 O(n²) 十分鐘跑不完;fftconvolve 秒級(drift.py 實測)
        out.append((1 - wet) * ch + wet * fftconvolve(ch, ir, "full")[:len(ch)])
    return out


def loopify(L, R, dur, tail):
    ts = int(SR * tail); nd = int(SR * dur)
    fade = np.linspace(0, 1, ts)
    outs = []
    for ch in (L, R):
        head, body, tailseg = ch[:ts], ch[ts:nd], ch[nd:nd + ts]
        outs.append(np.concatenate([head * fade + tailseg * (1 - fade), body]))
    return outs


# ── A) current:專注 ──────────────────────────────────────────────
def build_current(dur, seed=101):
    rng = np.random.default_rng(seed)
    tail = 12.0
    L, R = pad_stereo(dur + tail, hz("D2"), rng, breathe=(0.05, 0.11))
    scale = [hz(x) for x in ("D4", "E4", "F#4", "A4", "B4", "D5", "E5", "F#5", "A5")]
    t = 2.5
    while t < dur + tail - 8:
        f = scale[rng.integers(0, len(scale))]
        w = 0.05 if f < 500 else 0.032
        b = bell(f, rng.uniform(5.0, 8.0), w * rng.uniform(0.75, 1.15), rng)
        add_panned(L, R, b, t, rng.uniform(-0.7, 0.7))
        t += rng.uniform(2.8, 6.5)
    n = len(L)
    air = lowpass(pink(n, rng), 1600); air /= np.abs(air).max() + 1e-9
    L += air * 0.010; R += air * 0.009
    L, R = reverb_stereo(L, R, 4.0, 0.38)
    L, R = lowpass(L, 6500), lowpass(R, 6500)
    return loopify(L, R, dur, tail)


# ── B) nightfall:睡眠 ────────────────────────────────────────────
def build_nightfall(dur, seed=202):
    rng = np.random.default_rng(seed)
    tail = 14.0
    L, R = pad_stereo(dur + tail, hz("C2"), rng, breathe=(0.02, 0.05),
                      layers=((1.0, 0.50), (1.5, 0.18), (2.0, 0.14), (3.0, 0.05)))
    scale = [hz(x) for x in ("C4", "D4", "E4", "G4", "A4", "C5")]
    t = 6.0
    while t < dur + tail - 16:
        f = scale[rng.integers(0, len(scale))]
        b = bell(f, rng.uniform(10.0, 14.0), 0.040 * rng.uniform(0.7, 1.1), rng,
                 decay=(0.22, 0.26))
        add_panned(L, R, b, t, rng.uniform(-0.5, 0.5))
        t += rng.uniform(8.0, 16.0)
    n = len(L)
    air = lowpass(pink(n, rng), 900); air /= np.abs(air).max() + 1e-9
    L += air * 0.012; R += air * 0.011
    L, R = reverb_stereo(L, R, 6.0, 0.45)
    L, R = lowpass(L, 3500), lowpass(R, 3500)
    return loopify(L, R, dur, tail)


# ── C) rain:雨幕 ─────────────────────────────────────────────────
def rain_bed(n, rng):
    """雨幕 = 寬頻噪聲 → 帶通 → 慢速振幅微擾(陣雨感)。"""
    base = rng.normal(0, 1, n)
    bed = bandpass(base, 300, 5200)
    t = np.arange(n) / SR
    # 三個不可公度的慢波 → 雨勢起伏永不重複
    amp = (1.0 + 0.16 * np.sin(2 * np.pi * 0.011 * t)
           + 0.10 * np.sin(2 * np.pi * 0.0043 * t + 1.7)
           + 0.07 * np.sin(2 * np.pi * 0.023 * t + 4.1))
    bed *= amp
    return bed / (np.abs(bed).max() + 1e-9)


def droplet(rng):
    """單顆水滴:短噪聲脈衝過窄帶通,60~140ms。"""
    dur = rng.uniform(0.06, 0.14); n = int(SR * dur)
    x = rng.normal(0, 1, n) * np.exp(-np.linspace(0, rng.uniform(7, 12), n))
    f0 = rng.uniform(900, 3800)
    return bandpass(x, f0 * 0.7, f0 * 1.4)


def build_rain(dur, seed=303):
    rng = np.random.default_rng(seed)
    tail = 10.0
    n = int(SR * (dur + tail))
    bedL = rain_bed(n, rng) * 0.16
    bedR = rain_bed(n, np.random.default_rng(seed + 7)) * 0.16   # 左右各自的雨
    L, R = bedL.copy(), bedR.copy()
    # 水滴:平均每秒 ~2 顆,近處的滴答
    t = 0.3
    while t < dur + tail - 1:
        d = droplet(rng) * rng.uniform(0.02, 0.07)
        add_panned(L, R, d, t, rng.uniform(-0.9, 0.9))
        t += rng.exponential(0.5)
    # 極疏的暖音(F 大調五聲),雨是主角
    padL, padR = pad_stereo(dur + tail, hz("F2"), rng, breathe=(0.02, 0.05),
                            layers=((1.0, 0.30), (2.0, 0.10), (3.0, 0.04)))
    L += padL * 0.5; R += padR * 0.5
    scale = [hz(x) for x in ("F4", "G4", "A4", "C5", "D5")]
    t = 10.0
    while t < dur + tail - 12:
        f = scale[rng.integers(0, len(scale))]
        b = bell(f, rng.uniform(8.0, 12.0), 0.030 * rng.uniform(0.7, 1.1), rng,
                 decay=(0.30, 0.30))
        add_panned(L, R, b, t, rng.uniform(-0.4, 0.4))
        t += rng.uniform(14.0, 26.0)
    L, R = reverb_stereo(L, R, 2.8, 0.22)      # 雨本身自帶擴散,殘響小
    L, R = lowpass(L, 6000), lowpass(R, 6000)
    return loopify(L, R, dur, tail)


def write_stereo(L, R, path, norm=0.72):
    p = max(np.abs(L).max(), np.abs(R).max())
    if p > 0:
        L, R = L / p * norm, R / p * norm
    pcm = np.empty(len(L) * 2, np.int16)
    pcm[0::2] = (L * 32767).astype(np.int16)
    pcm[1::2] = (R * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    rms = float(np.sqrt(((L ** 2 + R ** 2) / 2).mean()))
    print(f"  {path}  {len(L)/SR:.0f}s  RMS {20*math.log10(rms+1e-12):.1f} dBFS")


def tile_60min(L, R, path, norm):
    """10 分鐘無縫循環平鋪 6 次 = 60 分鐘。循環是交叉淡接過的,接縫聽不見。"""
    reps = 6
    write_stereo(np.tile(L, reps), np.tile(R, reps), path, norm)


PIECES = {
    "current":  (build_current,  0.72),
    "nightfall": (build_nightfall, 0.60),   # 睡眠曲刻意更小聲
    "rain":     (build_rain,     0.70),
}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if mode == "preview":
        for name, (fn, norm) in PIECES.items():
            L, R = fn(60)
            write_stereo(L, R, f"preview_{name}.wav", norm)
    else:
        for name, (fn, norm) in PIECES.items():
            print(f"[{name}] 生成 10 分鐘循環…")
            L, R = fn(600)
            tile_60min(L, R, f"{name}_60min.wav", norm)
