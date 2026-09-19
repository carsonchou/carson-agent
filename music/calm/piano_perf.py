#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""piano_perf.py — 一小時放鬆鋼琴「演奏」(不是零散音點)。

## Carson 三次反饋逐條對應
1. 「耳朵不舒服」→ 舊版 95-99% 能量在 200Hz 以下(持續 sine 鋪底造成耳壓)。
   本檔**沒有任何持續鋪底**,所有聲音都是會衰減的琴音。
2. 「挺刺耳」→ 舊版用拉伸泛音做金屬鐘聲。本檔泛音幾乎諧和(B=2e-4)、
   高泛音衰減快 10 倍、2-4kHz(人耳最敏感)−4dB、5.2kHz 以上不產生。
3. 「要演奏那種」→ 本檔重點:**和聲進行 + 左手琶音 + 右手旋律 + 樂句起伏
   + rubato**。不是隨機撒音。

## 怎麼讓它像「人在彈」
- **和聲進行**:每首一組 4 小節循環(如 Am7-Fmaj7-C-Gsus2),不是單一調性掛著
- **左手**:分解和弦走八分音符,低音落拍點、其餘散開
- **右手**:旋律取和弦內音+級進經過音;強拍落和弦音、句尾收在和弦內音
- **樂句**:4 小節一句,句內 velocity 拱形(0.86→1.0→0.95→0.80),句尾放慢
- **rubato**:每個音時值抖動 ±18~22ms,不是機器格線
- **織體變化**:每 8 小節換一種(只有左手/加旋律/加八度/回到疏),12 分鐘不膩

## 效能與記憶體
- **音色庫**:每個音高×3 力度層只算一次,之後只是陣列相加(取樣器作法)。
  否則一小時 7000+ 個音逐一做加法合成跑不完。
- **演算法殘響**(梳狀+全通 IIR)取代 FFT 卷積:本機只剩 1.1GB 可用,
  卷積會吃掉 GB 級記憶體。
"""
import math
import sys
import wave

import numpy as np
from scipy.signal import lfilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SR = 44100


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def render_note(m, dur, layer):
    """一個鋼琴音。layer 0/1/2 = 弱/中/強(力度改變音色,不只是音量)。"""
    f0 = midi_hz(m)
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, np.float32)
    B = 2.0e-4                                    # 不諧和度(真鋼琴中音域)
    base_decay = 0.42 + 240.0 / f0 * 0.010        # 低音延長、高音短
    bright = (0.72, 1.0, 1.28)[layer]             # 彈得越用力泛音越多
    nmax = int(min(20, 5000 / f0))
    for k in range(1, max(2, nmax) + 1):
        fk = f0 * k * math.sqrt(1 + B * k * k)
        if fk > 5200:                             # 從源頭不產生刺耳頻段
            break
        hammer = abs(math.sin(math.pi * k / 8.0))  # 槌擊點 1/8 弦長
        amp = hammer / (k ** (1.58 / bright))
        dec = base_decay * (1.0 + 0.40 * k)       # 高泛音衰減快很多 = 暖
        out += (amp * np.exp(-dec * t)
                * np.sin(2 * math.pi * fk * t)).astype(np.float32)
    a = int(SR * 0.011)                            # 氈槌起音
    out[:a] *= np.linspace(0, 1, a, dtype=np.float32) ** 1.4
    hn = int(SR * 0.025)                           # 極輕槌擊聲
    rng = np.random.default_rng(m * 7 + layer)
    th = (rng.normal(0, 1, hn).astype(np.float32)
          * np.exp(-np.linspace(0, 10, hn, dtype=np.float32)))
    X = np.fft.rfft(th)
    ff = np.fft.rfftfreq(hn, 1 / SR)
    out[:hn] += np.fft.irfft(X / (1 + (ff / 800) ** 2), hn).astype(np.float32) * 0.04
    mx = float(np.abs(out).max())
    return out / mx if mx > 0 else out


class Bank:
    """音色庫:每個音高×力度層只算一次。"""

    def __init__(self, lo, hi, dur=7.0):
        self.d = {}
        for m in range(lo, hi + 1):
            for layer in range(3):
                self.d[(m, layer)] = render_note(m, dur, layer)
        self.lo, self.hi = lo, hi

    def get(self, m, layer):
        return self.d[(max(min(m, self.hi), self.lo), layer)]


QUAL = {"maj": (0, 4, 7), "min": (0, 3, 7), "maj7": (0, 4, 7, 11),
        "min7": (0, 3, 7, 10), "sus2": (0, 2, 7), "maj6": (0, 4, 7, 9)}


def chord_tones(root, qual, lo, hi):
    out = []
    for octv in range(-2, 5):
        for iv in QUAL[qual]:
            p = root + iv + 12 * octv
            if lo <= p <= hi:
                out.append(p)
    return sorted(out)


PIECES = {
    "nightfall": dict(
        bpm=52, seed=202,
        prog=[(57, "min7"), (53, "maj7"), (60, "maj"), (55, "sus2")],
        bass=(40, 52), arp=(52, 67), rh=(67, 86),
        vel=(0.30, 0.62), mel_density=0.55),
    "current": dict(
        bpm=66, seed=101,
        prog=[(62, "maj"), (57, "maj"), (59, "min7"), (55, "maj6")],
        bass=(43, 55), arp=(55, 70), rh=(69, 88),
        vel=(0.38, 0.74), mel_density=0.80),
    "rain": dict(
        bpm=58, seed=303,
        prog=[(53, "maj7"), (50, "min7"), (58, "maj"), (60, "sus2")],
        bass=(41, 53), arp=(53, 68), rh=(68, 86),
        vel=(0.26, 0.55), mel_density=0.50),
}

# 每 8 小節換一種織體:(左手模式, 是否有旋律, 旋律加不加八度)
TEXTURES = [("arp", False, False), ("arp", True, False), ("arp", True, True),
            ("wide", True, False), ("arp", False, False), ("wide", True, True),
            ("arp", True, False), ("sparse", True, False)]

RHYTHMS = [[0.0, 1.0, 2.0], [0.0, 1.5, 2.5], [0.0, 2.0],
           [1.0, 2.0, 3.0], [0.0, 0.75, 1.5, 2.5]]
RHY_P = [0.24, 0.22, 0.20, 0.18, 0.16]


def compose(name, minutes):
    cfg = PIECES[name]
    rng = np.random.default_rng(cfg["seed"])
    spb = 60.0 / cfg["bpm"]
    bar = spb * 4
    nbars = int(minutes * 60 / bar) + 6
    bank = Bank(min(cfg["bass"][0], 40), max(cfg["rh"][1], 88) + 12)
    total = int((nbars * bar + 16) * SR)
    L = np.zeros(total, np.float32)
    R = np.zeros(total, np.float32)
    vlo, vhi = cfg["vel"]

    def place(m, at, vel, pan):
        layer = 0 if vel < 0.42 else (1 if vel < 0.62 else 2)
        x = bank.get(m, layer) * vel
        i = int(at * SR)
        k = min(len(x), total - i)
        if k <= 0:
            return
        th = (pan + 1) * math.pi / 4
        L[i:i + k] += x[:k] * math.cos(th)
        R[i:i + k] += x[:k] * math.sin(th)

    t = 1.0
    last_mel = None
    for b in range(nbars):
        root, qual = cfg["prog"][b % len(cfg["prog"])]
        tex, has_mel, octv = TEXTURES[(b // 8) % len(TEXTURES)]
        bass_pool = chord_tones(root, qual, *cfg["bass"])
        arp_pool = chord_tones(root, qual, *cfg["arp"])
        rh_pool = chord_tones(root, qual, *cfg["rh"])
        if not bass_pool or not arp_pool or not rh_pool:
            t += bar
            continue
        ph = b % 4
        arc = (0.86, 1.0, 0.95, 0.80)[ph]        # 樂句拱形
        ritard = 1.05 if ph == 3 else 1.0        # 句尾放慢

        # 🔴 低音只在拍點彈 1-2 個(舊版八分音符全在低音域,把 73-82% 能量
        #    壓在 200Hz 以下 = 耳壓問題換個樂器復發)。琶音移到中音域。
        for s_b in ([0] if tex == "sparse" else [0, 4]):
            vb = float(rng.uniform(vlo, vhi)) * arc * 0.92
            place(bass_pool[0], t + s_b * spb / 2 * ritard
                  + float(rng.normal(0, 0.016)), vb, -0.34)
        steps = {"sparse": [2, 6], "wide": [1, 3, 5, 7]}.get(
            tex, [1, 2, 3, 5, 6, 7])
        for s in steps:
            stride = 3 if tex == "wide" else 2
            idx = min((s * stride) % len(arp_pool), len(arp_pool) - 1)
            v = float(rng.uniform(vlo, vhi)) * arc * 0.72
            place(arp_pool[idx], t + s * spb / 2 * ritard
                  + float(rng.normal(0, 0.018)), v, -0.20)

        if has_mel and rng.random() < cfg["mel_density"] + 0.25:
            rhythm = RHYTHMS[int(rng.choice(len(RHYTHMS), p=RHY_P))]
            for j, beat in enumerate(rhythm):
                strong = beat in (0.0, 2.0)
                if strong or last_mel is None:
                    cand = rh_pool
                else:
                    cand = [p for p in range(rh_pool[0], rh_pool[-1] + 1)
                            if abs(p - last_mel) <= 2] or rh_pool
                if last_mel is None:
                    m = int(rng.choice(rh_pool))
                else:
                    w = np.array([1.0 / (1 + abs(p - last_mel) * 0.55)
                                  for p in cand], np.float64)
                    m = int(rng.choice(cand, p=w / w.sum()))
                if ph == 3 and j == len(rhythm) - 1:
                    m = min(rh_pool, key=lambda p: abs(p - m))
                v = float(rng.uniform(vlo, vhi)) * arc * (1.0 if strong else 0.82)
                jit = float(rng.normal(0, 0.022))
                place(m, t + beat * spb * ritard + jit, v, 0.26)
                if octv and strong and rng.random() < 0.4:
                    place(m + 12, t + beat * spb * ritard + jit + 0.012,
                          v * 0.45, 0.34)
                last_mel = m
        t += bar * ritard
    return L, R


def soften(x):
    """2-4kHz(人耳最敏感)−4dB + 4.5kHz 後滾降 = 氈槌音色,不刺耳。"""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    dip = 1.0 - 0.28 * np.exp(-((np.log2(np.maximum(f, 1) / 2900)) ** 2) / 0.28)
    # 低頻收斂:120Hz 以下柔和衰減。鋼琴需要低音的身體感,但**累積**的低頻
    # 正是耳壓來源(舊版 95-99%),所以壓住而不是砍掉。
    lowcut = 1.0 / (1.0 + (70.0 / np.maximum(f, 1)) ** 2.2)
    return np.fft.irfft(X * dip * lowcut / (1.0 + (f / 7000) ** 2.0),
                        len(x)).astype(np.float32)


def room(x, wet=0.26, seed=0):
    """演算法殘響(梳狀+全通 IIR)。記憶體幾乎為零 —— 本機只剩 1.1GB。"""
    rng = np.random.default_rng(seed)
    acc = np.zeros_like(x)
    for D0, g in ((1557, 0.80), (1617, 0.79), (1491, 0.81),
                  (1422, 0.78), (1277, 0.77), (1356, 0.76)):
        D = int(D0 * rng.uniform(0.97, 1.03))
        a = np.zeros(D + 1, np.float64)
        a[0] = 1.0
        a[D] = -g
        acc += lfilter([1.0], a, x).astype(np.float32)
    acc /= 6.0
    for D, g in ((225, 0.5), (556, 0.5), (441, 0.5)):
        b = np.zeros(D + 1, np.float64)
        b[0] = -g
        b[D] = 1.0
        a = np.zeros(D + 1, np.float64)
        a[0] = 1.0
        a[D] = -g
        acc = lfilter(b, a, acc).astype(np.float32)
    X = np.fft.rfft(acc)
    f = np.fft.rfftfreq(len(acc), 1 / SR)
    acc = np.fft.irfft(X / (1 + (f / 2600) ** 1.6), len(acc)).astype(np.float32)
    return ((1 - wet) * x + wet * acc * 0.55).astype(np.float32)


def loopify(L, R, dur, tail=10.0):
    ts, nd = int(SR * tail), int(SR * dur)
    fade = np.linspace(0, 1, ts, dtype=np.float32)
    return [np.concatenate([c[:ts] * fade + c[nd:nd + ts] * (1 - fade), c[ts:nd]])
            for c in (L, R)]


def write(L, R, path, reps, norm=0.60):
    p = max(float(np.abs(L).max()), float(np.abs(R).max()))
    if p > 0:
        L, R = L / p * norm, R / p * norm
    block = np.empty(len(L) * 2, np.int16)
    block[0::2] = (L * 32767).astype(np.int16)
    block[1::2] = (R * 32767).astype(np.int16)
    raw = block.tobytes()
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        for _ in range(reps):
            w.writeframes(raw)
    seg = ((L + R) / 2)[:SR * 20]
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    bnd = lambda lo, hi: float((X[(f >= lo) & (f < hi)] ** 2).sum())
    tot = bnd(20, 20000) + 1e-9
    print(f"  {path}  {len(L) * reps / SR / 60:.0f}分  "
          f"低{bnd(20, 200) / tot * 100:4.1f}% "
          f"中{bnd(200, 2000) / tot * 100:4.1f}% "
          f"高{bnd(2000, 8000) / tot * 100:4.1f}%")


def rain_bed_tiled(n, seed=303):
    """雨幕。🔴 不一次生成 12 分鐘 —— bandpass 要對 3170 萬點做 FFT,本機只剩
    1.1GB 會炸。雨是統計上穩態的訊號,生成 90 秒再交叉淡接平鋪,聽不出接縫。"""
    seg = int(SR * 90)
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, seg).astype(np.float32)
    X = np.fft.rfft(base)
    f = np.fft.rfftfreq(seg, 1 / SR)
    # 300Hz-3.5kHz 帶通(上緣壓低:舊版雨聲 20.9% 落在 2-8k,那是「嘶」的來源)
    X *= 1.0 / (1 + (300.0 / np.maximum(f, 1)) ** 3) / (1 + (f / 3500) ** 3)
    seg_x = np.fft.irfft(X, seg).astype(np.float32)
    xf = int(SR * 3)                       # 3 秒交叉淡接
    fade = np.linspace(0, 1, xf, dtype=np.float32)
    seg_x[:xf] = seg_x[:xf] * fade + seg_x[-xf:] * (1 - fade)
    seg_x = seg_x[:seg - xf]
    out = np.tile(seg_x, int(n / len(seg_x)) + 1)[:n]
    # 雨勢緩慢起伏(三個不可公度的慢波,永不完全重複)
    t = np.arange(n, dtype=np.float32) / SR
    amp = (1.0 + 0.15 * np.sin(2 * np.pi * 0.011 * t)
           + 0.10 * np.sin(2 * np.pi * 0.0043 * t + 1.7)
           + 0.07 * np.sin(2 * np.pi * 0.023 * t + 4.1))
    out *= amp
    mx = float(np.abs(out).max())
    return out / mx if mx > 0 else out


def add_drops(L, R, seed=311):
    """近處的滴答聲。短訊號,直接散在整條時間軸上,成本很低。"""
    rng = np.random.default_rng(seed)
    n = len(L)
    t = 0.4
    while t < n / SR - 1.0:
        d = int(SR * rng.uniform(0.05, 0.12))
        x = (rng.normal(0, 1, d).astype(np.float32)
             * np.exp(-np.linspace(0, rng.uniform(8, 13), d, dtype=np.float32)))
        X = np.fft.rfft(x)
        ff = np.fft.rfftfreq(d, 1 / SR)
        f0 = rng.uniform(700, 2600)
        x = np.fft.irfft(X / (1 + (f0 * 0.7 / np.maximum(ff, 1)) ** 3)
                         / (1 + (ff / (f0 * 1.5)) ** 3), d).astype(np.float32)
        mx = float(np.abs(x).max())
        if mx > 0:
            x = x / mx * rng.uniform(0.03, 0.09)
        i = int(t * SR)
        k = min(d, n - i)
        pan = float(rng.uniform(-0.85, 0.85))
        th = (pan + 1) * math.pi / 4
        L[i:i + k] += x[:k] * math.cos(th)
        R[i:i + k] += x[:k] * math.sin(th)
        t += float(rng.exponential(0.55))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    mins, reps = (1.3, 1) if mode == "preview" else (12.0, 5)
    for name in PIECES:
        L, R = compose(name, mins)
        n = int(mins * 60 * SR)
        cut = n + SR * 10
        L, R = soften(L[:cut]), soften(R[:cut])
        L, R = room(L, seed=1), room(R, seed=2)
        if name == "rain":                    # 雨版:鋼琴是點綴,雨是主角
            bed = rain_bed_tiled(len(L))
            L = L + bed * 0.30
            R = R + rain_bed_tiled(len(R), seed=310) * 0.30
            add_drops(L, R)
        if mode == "preview":
            write(L[:n], R[:n], f"pv2_{name}.wav", 1)
        else:
            L, R = loopify(L, R, mins * 60)
            write(L, R, f"{name}_piano60.wav", reps)
