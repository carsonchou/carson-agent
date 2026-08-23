#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""piano.py — 原創鋼琴環境樂(取代 ambient3 的合成音)。

## 為什麼要重做(Carson 實測反饋 + 頻譜診斷)
- 「耳朵不舒服」→ 診斷:**95~99% 能量在 200Hz 以下**(持續 sine 鋪底造成耳壓),
  外加 0.45~0.85Hz 拍頻(微失諧 sine 互打)持續一小時的搏動。
- 「挺刺耳」→ 診斷:舊的 bell 用**拉伸泛音** fk = f·k·√(1+0.0002k²) 做金屬音,
  高泛音與基音不成整數比 → 臨界頻帶內互相摩擦,而且高泛音衰減太慢。

## 這版的三道保險(針對「不刺耳」)
1. **諧和泛音**:真鋼琴的不諧和度 B 很小(中音域 ~2e-4),泛音幾乎是整數倍。
2. **高泛音衰減快很多**:decay_n = decay_0·(1 + 0.55n)。這是鋼琴「一觸即暖」的關鍵——
   起音後 0.3 秒高頻就掉光,只剩溫暖的低階泛音。
3. **敏感頻段壓低**:2-4kHz 是人耳最敏感的區間(等響曲線谷底),整體做一個
   −4dB 的寬帶凹陷,再於 4.5kHz 之後柔和滾降。氈槌(felt)音色,不是演奏會平台鋼琴。

## 另外兩件事
- **沒有持續鋪底**:鋼琴音會衰減,畫面靠殘響與延音踏板的尾巴連續,不靠嗡鳴。
  低頻只在踩下延音時由琴弦共鳴帶出,佔比目標 <35%。
- 起音 12ms(氈槌),不是 2ms 的硬槌。
"""
import math
import sys
import wave

import numpy as np
from scipy.signal import fftconvolve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SR = 44100


def hz(name):
    N = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    return 440.0 * 2 ** ((N[name[:-1]] + (int(name[-1]) - 4) * 12 - 9) / 12)


def note(f0, dur, vel, rng, bright=1.0):
    """一個鋼琴音。加法合成 + 每階泛音各自的衰減率。"""
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, np.float32)
    B = 2.0e-4                                   # 不諧和度(真鋼琴中音域)
    base_decay = 0.55 + 240.0 / f0 * 0.006       # 低音延長,高音短
    nmax = int(min(18, 4200 / f0))               # 泛音上限跟著音高走,不硬塞高頻
    for k in range(1, max(2, nmax) + 1):
        fk = f0 * k * math.sqrt(1 + B * k * k)
        if fk > 5200:                            # 5.2k 以上不產生,從源頭不刺
            break
        # 槌擊點在 1/8 弦長 → 第 8、16 階被抵消(真鋼琴的音色成因)
        hammer = abs(math.sin(math.pi * k / 8.0))
        amp = hammer / (k ** 1.55)
        dec = base_decay * (1.0 + 0.55 * k)      # 高泛音衰減快很多 = 暖
        out += (amp * np.exp(-dec * t)
                * np.sin(2 * math.pi * fk * t + rng.uniform(0, 6.28))).astype(np.float32)
    # 氈槌起音:12ms 平滑上升,不是硬碰硬
    a = int(SR * 0.012)
    out[:a] *= np.linspace(0, 1, a, dtype=np.float32) ** 1.5
    # 極輕的槌擊聲(低通雜訊),沒有它會像電子琴
    hn = int(SR * 0.03)
    thump = (rng.normal(0, 1, hn).astype(np.float32)
             * np.exp(-np.linspace(0, 9, hn, dtype=np.float32)))
    X = np.fft.rfft(thump); ff = np.fft.rfftfreq(hn, 1 / SR)
    thump = np.fft.irfft(X / (1 + (ff / 900) ** 2), hn).astype(np.float32)
    out[:hn] += thump * 0.05 * vel
    return out * vel * bright


def soften(x):
    """敏感頻段(2-4kHz)−4dB 凹陷 + 4.5kHz 之後柔和滾降 = 氈槌音色。"""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    dip = 1.0 - 0.37 * np.exp(-((np.log2(np.maximum(f, 1) / 2800)) ** 2) / 0.30)
    roll = 1.0 / (1.0 + (f / 4500) ** 2.0)
    return np.fft.irfft(X * dip * roll, len(x))


def reverb(x, rt=3.2, wet=0.30, seed=23):
    n = int(SR * rt)
    rng = np.random.default_rng(seed)
    ir = rng.normal(0, 1, n) * np.exp(-np.linspace(0, 6.0, n))
    pre = int(SR * 0.025); ir[:pre] *= np.linspace(0, 1, pre)
    # 殘響本身也要暖:IR 過低通,否則高頻尾巴會嘶
    X = np.fft.rfft(ir); f = np.fft.rfftfreq(n, 1 / SR)
    ir = np.fft.irfft(X / (1 + (f / 3000) ** 1.6), n)
    ir /= np.abs(ir).sum() / 48
    return (1 - wet) * x + wet * fftconvolve(x, ir, "full")[:len(x)]


def add(buf, x, at, pan, L, R):
    i = int(at * SR); m = min(len(x), len(L) - i)
    if m <= 0:
        return
    th = (pan + 1) * math.pi / 4
    L[i:i + m] += x[:m] * math.cos(th)
    R[i:i + m] += x[:m] * math.sin(th)


# ── 三首:音域/密度/調式都不同 ────────────────────────────────────────
PIECES = {
    # 睡眠:最疏、最低、最輕。A 小調五聲,沒有導音就沒有「還沒解決」的懸念
    "nightfall": dict(scale=("A3", "C4", "D4", "E4", "G4", "A4", "C5"),
                      gap=(7.0, 14.0), vel=(0.16, 0.30), dur=9.0,
                      bright=0.85, seed=202, chord_p=0.15,
                      bass=("A2", "E2"), bass_gap=(26.0, 48.0), bass_vel=0.15),
    # 專注:中密度、中音域。D 大調五聲,明亮但不甜
    "current":   dict(scale=("D4", "E4", "F#4", "A4", "B4", "D5", "E5", "F#5"),
                      gap=(3.5, 7.5), vel=(0.20, 0.36), dur=7.0,
                      bright=1.0, seed=101, chord_p=0.25,
                      bass=("D2", "A2"), bass_gap=(20.0, 38.0), bass_vel=0.17),
    # 雨:最疏,只當雨聲的點綴。F 大調五聲
    "rain":      dict(scale=("F3", "A3", "C4", "D4", "F4", "G4", "A4"),
                      gap=(9.0, 18.0), vel=(0.14, 0.26), dur=10.0,
                      bright=0.8, seed=303, chord_p=0.10,
                      bass=("C3", "F2"), bass_gap=(45.0, 80.0), bass_vel=0.07),
}


def build_piano(name, dur, tail=12.0):
    cfg = PIECES[name]
    rng = np.random.default_rng(cfg["seed"])
    n = int(SR * (dur + tail))
    L, R = np.zeros(n, np.float32), np.zeros(n, np.float32)
    scale = [hz(s) for s in cfg["scale"]]
    t = 2.0
    while t < dur + tail - cfg["dur"]:
        k = int(rng.integers(0, len(scale)))
        vel = float(rng.uniform(*cfg["vel"]))
        pan = float(rng.uniform(-0.45, 0.45))
        add(None, note(scale[k], cfg["dur"], vel, rng, cfg["bright"]), t, pan, L, R)
        # 偶爾疊一個和聲音(三度或五度),讓它不只是單音點狀
        if rng.random() < cfg["chord_p"]:
            k2 = min(len(scale) - 1, k + int(rng.choice([2, 3])))
            add(None, note(scale[k2], cfg["dur"] * 0.8, vel * 0.7, rng, cfg["bright"]),
                t + float(rng.uniform(0.06, 0.22)), pan * -0.6, L, R)
        t += float(rng.uniform(*cfg["gap"]))
    # 低音琴弦:稀疏(20-55 秒一顆)、極輕。給身體感但會衰減 ——
    # 舊版的耳壓來自**持續**的低頻鋪底,不是低頻本身。
    tb = float(rng.uniform(4.0, 12.0))
    bass = [hz(b) for b in cfg["bass"]]
    while tb < dur + tail - 14.0:
        f0 = bass[int(rng.integers(0, len(bass)))]
        add(None, note(f0, 13.0, cfg["bass_vel"] * float(rng.uniform(0.8, 1.15)),
                       rng, 0.75), tb, float(rng.uniform(-0.2, 0.2)), L, R)
        tb += float(rng.uniform(*cfg["bass_gap"]))

    L, R = soften(L), soften(R)
    L = reverb(L, seed=23); R = reverb(R, seed=41)
    return L, R


def loopify(L, R, dur, tail=12.0):
    ts = int(SR * tail); nd = int(SR * dur)
    fade = np.linspace(0, 1, ts)
    out = []
    for ch in (L, R):
        out.append(np.concatenate([ch[:ts] * fade + ch[nd:nd + ts] * (1 - fade), ch[ts:nd]]))
    return out


def write(L, R, path, norm=0.62):
    p = max(np.abs(L).max(), np.abs(R).max())
    if p > 0:
        L, R = L / p * norm, R / p * norm
    pcm = np.empty(len(L) * 2, np.int16)
    pcm[0::2] = (L * 32767).astype(np.int16)
    pcm[1::2] = (R * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    x = (L + R) / 2
    X = np.abs(np.fft.rfft(x[:SR * 20] * np.hanning(min(SR * 20, len(x)))))
    f = np.fft.rfftfreq(min(SR * 20, len(x)), 1 / SR)
    b = lambda lo, hi: float((X[(f >= lo) & (f < hi)] ** 2).sum())
    tot = b(20, 20000) + 1e-9
    print(f"  {path}  {len(L)/SR:.0f}s  "
          f"低{b(20,200)/tot*100:4.1f}% 中{b(200,2000)/tot*100:4.1f}% "
          f"高{b(2000,8000)/tot*100:4.1f}% 極高{b(8000,20000)/tot*100:4.1f}%")


def mix_rain(L, R, seed=303):
    """雨版把雨幕混進來 —— 鋼琴只是點綴,雨是主角(沿用 ambient3 的合成雨)。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("a3", "ambient3.py")
    a3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(a3)
    n = len(L)
    rng = np.random.default_rng(seed)
    bedL = a3.rain_bed(n, rng) * 0.17
    bedR = a3.rain_bed(n, np.random.default_rng(seed + 7)) * 0.17
    # 雨幕也要壓掉 2-4k(舊版雨聲 20.9% 落在 2-8k,那是「嘶」的來源)
    return L + soften(bedL), R + soften(bedR)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    secs = 45.0 if mode == "preview" else 600.0
    for name in PIECES:
        L, R = build_piano(name, secs)
        if name == "rain":
            L, R = mix_rain(L, R)
        if mode == "preview":
            write(L[:int(SR * secs)], R[:int(SR * secs)], f"pv_piano_{name}.wav")
        else:
            L, R = loopify(L, R, secs)
            write(np.tile(L, 6), np.tile(R, 6), f"{name}_piano_60min.wav")
