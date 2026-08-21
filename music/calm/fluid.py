#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fluid.py — 真實流體模擬(Stable Fluids):墨水在水裡緩慢暈開。

## 為什麼這次不一樣(第五次嘗試前先想清楚)
前四次失敗的共同點:我在**描繪**(畫動物、畫漸層、畫星點),描繪需要美感,我沒有。
主頻道畫面做得出來,是因為那是**渲染一個真實系統**(回測/K線)。
星空雖是真資料,但它是靜態的點——沒有結構在演化,所以無聊。

流體不同:它是**真實物理在你眼前演化**。渦流、暈開、拉絲全是
Navier-Stokes 方程的解,不是我編的。我的工作只是把方程解對——
跟把回測算對是同一種工作。而且「墨水擴散」本來就是療癒影片的成熟類型。

## 算法:Stable Fluids(Jos Stam, SIGGRAPH 1999)
半拉格朗日平流(無條件穩定,可用大時步)+ Chorin 投影(壓力解強制不可壓縮)。
  每步:平流速度場 → 加外力 → 解壓力(Jacobi)→ 減壓力梯度 → 平流染料
染料三通道(RGB 各自平流),所以不同顏色的墨會真的互相纏繞。

## 視覺設計(每個決定都有理由)
- 模擬解析度 GW×GH,渲染時 lanczos 放大;流體是連續場,放大不會像素化
- 墨源:緩慢移動的注入點,顏色從主題調色盤輪換;注入速度極慢(療癒不是熔岩燈)
- 背景是紙色(亮),墨是深色 → **暗墨亮底**,解決前兩版「全黑」的坑
- 溫和的浮力 + 極低黏性 → 墨會自己捲出渦來,不需要我設計動作

用法:
  python fluid.py --secs 30 --theme ink --out fluid.mp4 --audio drift.wav
"""
import argparse
import math
import pathlib
import subprocess
import sys

import numpy as np

try:
    import cv2                      # opencv-python-headless;advect 的 80 倍加速
except ImportError:                 # noqa: SIM105
    cv2 = None

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent

W, H, FPS = 1920, 1080, 24
GW, GH = 640, 360           # 模擬網格(實測 Jacobi 每幀 3ms@192,480 也遠低於實時)
DT = 1.0 / FPS

# 主題:(紙色底, [墨色們])。暗墨亮底——亮度坑踩過兩次,這次底就是亮的。
THEMES = {
    "ink": ((0.93, 0.91, 0.87),
            [(0.13, 0.16, 0.22), (0.32, 0.20, 0.16), (0.16, 0.25, 0.22),
             (0.24, 0.18, 0.30), (0.10, 0.22, 0.28)]),
    "indigo": ((0.90, 0.91, 0.93),
               [(0.15, 0.20, 0.38), (0.12, 0.28, 0.38), (0.30, 0.22, 0.38)]),
    "tea": ((0.94, 0.91, 0.85),
            [(0.35, 0.24, 0.14), (0.20, 0.26, 0.16), (0.42, 0.30, 0.14)]),
    "slate": ((0.13, 0.14, 0.17),          # 這個主題反過來:亮墨暗底
              [(0.75, 0.80, 0.88), (0.55, 0.70, 0.80), (0.80, 0.70, 0.55)]),
}


def bilinear(field, x, y):
    """在 field 上以 (x,y) 浮點座標做雙線性取樣(半拉格朗日平流用)。"""
    h, w = field.shape[:2]
    x = np.clip(x, 0.0, w - 1.001)
    y = np.clip(y, 0.0, h - 1.001)
    x0 = x.astype(np.int32); y0 = y.astype(np.int32)
    fx = x - x0; fy = y - y0
    if field.ndim == 2:
        return (field[y0, x0] * (1 - fx) * (1 - fy) + field[y0, x0 + 1] * fx * (1 - fy)
                + field[y0 + 1, x0] * (1 - fx) * fy + field[y0 + 1, x0 + 1] * fx * fy)
    out = np.empty_like(field[y0, x0])
    for c in range(field.shape[2]):
        f = field[..., c]
        out[..., c] = (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x0 + 1] * fx * (1 - fy)
                       + f[y0 + 1, x0] * (1 - fx) * fy + f[y0 + 1, x0 + 1] * fx * fy)
    return out


class Fluid:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.u = np.zeros((h, w), np.float32)      # 水平速度
        self.v = np.zeros((h, w), np.float32)      # 垂直速度
        self.dye = np.zeros((h, w, 3), np.float32) # 三通道染料
        yy, xx = np.mgrid[0:h, 0:w]
        self.xx = xx.astype(np.float32)
        self.yy = yy.astype(np.float32)

    def advect(self, field, dt, scale):
        # 半拉格朗日:回溯粒子來源位置取樣。無條件穩定。
        # cv2.remap 是 SIMD 實作(實測 ~1ms vs numpy fancy-indexing ~80ms,
        # bilinear() 佔全程 62% 的瓶頸就是它);BORDER_REPLICATE = 原本的 clip 語義
        bx = self.xx - self.u * dt * scale
        by = self.yy - self.v * dt * scale
        if cv2 is not None:
            return cv2.remap(field, bx, by, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        return bilinear(field, bx, by)

    def _fft_kernel(self):
        # 離散五點 Laplacian 在 Fourier 空間的特徵值(週期域;np.roll 本來就是環面)
        ky = 2 * np.cos(2 * np.pi * np.fft.fftfreq(self.h)) - 2
        kx = 2 * np.cos(2 * np.pi * np.fft.rfftfreq(self.w)) - 2
        lam = ky[:, None] + kx[None, :]
        lam[0, 0] = 1.0            # 零頻(平均值)無定義,設 1 之後把該係數歸零
        return lam.astype(np.float32)

    def project(self):
        # Chorin 投影:解 ∇²p = ∇·v(FFT 精確解,取代 24 次 Jacobi——
        # Jacobi 24 次遠未收斂且每幀 96 個 roll 配置,是效能瓶頸;
        # 週期域上 FFT 解是 O(N log N) 且無截斷誤差)
        if not hasattr(self, "_lam"):
            self._lam = self._fft_kernel()
        div = 0.5 * (np.roll(self.u, -1, 1) - np.roll(self.u, 1, 1)
                     + np.roll(self.v, -1, 0) - np.roll(self.v, 1, 0))
        ph = np.fft.rfft2(div) / self._lam
        ph[0, 0] = 0.0
        p = np.fft.irfft2(ph, s=div.shape).astype(np.float32)
        self.u -= 0.5 * (np.roll(p, -1, 1) - np.roll(p, 1, 1))
        self.v -= 0.5 * (np.roll(p, -1, 0) - np.roll(p, 1, 0))

    def vorticity_confinement(self, dt, eps=9.0):
        """Stable Fluids 的已知弱點是數值耗散把小渦抹掉 → 畫面糊。
        渦度約束(Fedkiw 2001):算出渦度 ω,朝 |ω| 梯度方向加回力,
        小旋渦被持續補強 → 墨水才有真實的細絲。eps 控強度。"""
        w = (0.5 * (np.roll(self.v, -1, 1) - np.roll(self.v, 1, 1))
             - 0.5 * (np.roll(self.u, -1, 0) - np.roll(self.u, 1, 0)))
        aw = np.abs(w)
        gx = 0.5 * (np.roll(aw, -1, 1) - np.roll(aw, 1, 1))
        gy = 0.5 * (np.roll(aw, -1, 0) - np.roll(aw, 1, 0))
        mag = np.sqrt(gx * gx + gy * gy) + 1e-5
        nx, ny = gx / mag, gy / mag
        self.u += eps * (ny * w) * dt
        self.v += eps * (-nx * w) * dt

    def step(self, dt, sim_scale):
        self.u = self.advect(self.u, dt, sim_scale)
        self.v = self.advect(self.v, dt, sim_scale)
        self.vorticity_confinement(dt)
        # 浮力:墨越濃的地方微微上升 → 自然的捲曲,不用手設計動作
        density = self.dye.sum(axis=2)
        self.v -= density * 0.55 * dt
        self.project()
        self.dye = self.advect(self.dye, dt, sim_scale)
        # 染料極慢消散,讓畫面不會最後全糊成一色
        self.dye *= (1.0 - 0.016 * dt)
        # 速度阻尼:水,不是煙
        self.u *= (1.0 - 0.06 * dt)
        self.v *= (1.0 - 0.06 * dt)
        # 🔴 邊界條件:np.roll 是環面(上緣接下緣)。不處理的話,
        #    浮力把墨推出上緣後會從下緣冒出來,畫面上下緣出現碎屑(實測截圖可見)。
        #    處理:最外 3 圈速度歸零 + 染料快速衰減 = 邊界像吸墨紙。
        for k in range(3):
            fade = 0.5 + 0.5 * k / 3
            self.u[k, :] *= 0; self.u[-1 - k, :] *= 0
            self.v[k, :] *= 0; self.v[-1 - k, :] *= 0
            self.dye[k, :] *= fade; self.dye[-1 - k, :] *= fade
            self.u[:, k] *= 0; self.u[:, -1 - k] *= 0
            self.v[:, k] *= 0; self.v[:, -1 - k] *= 0
            self.dye[:, k] *= fade; self.dye[:, -1 - k] *= fade


def inject(f: Fluid, t, inks, rng, phases=None):
    """緩慢游走的墨源。位置由多個不可公度的正弦驅動 → 永不重複但連續。
    phases:每支片獨有的相位/頻率擾動(由 --seed 生成)——沒有它,同主題的
    兩支片動態會逐幀相同 = 模板量產,踩 inauthentic 紅線。"""
    n_src = len(inks)
    for i, ink in enumerate(inks):
        p0, fm = (phases[i] if phases else (0.0, 1.0))
        ph = t * (0.021 + 0.006 * i) * fm * 2 * math.pi + i * 2.4 + p0
        cx = f.w * (0.5 + 0.27 * math.sin(ph) * math.cos(ph * 0.37 + i))
        cy = f.h * (0.48 + 0.24 * math.sin(ph * 0.61 + 1.3 * i))
        # 高斯注入
        r = 12.0
        x0, x1 = int(max(0, cx - 3 * r)), int(min(f.w, cx + 3 * r))
        y0, y1 = int(max(0, cy - 3 * r)), int(min(f.h, cy + 3 * r))
        if x0 >= x1 or y0 >= y1:
            continue
        gx = f.xx[y0:y1, x0:x1] - cx
        gy = f.yy[y0:y1, x0:x1] - cy
        g = np.exp(-(gx * gx + gy * gy) / (2 * r * r)).astype(np.float32)
        amt = 0.42 * DT
        for c in range(3):
            f.dye[y0:y1, x0:x1, c] += g * ink[c] * amt
        # 注入一點旋轉的動量,墨才會捲
        swirl = 6.0 * math.sin(t * 0.13 + i * 2.0)
        f.u[y0:y1, x0:x1] += g * (-gy / (r + 1e-6)) * swirl * DT
        f.v[y0:y1, x0:x1] += g * (gx / (r + 1e-6)) * swirl * DT
    np.clip(f.dye, 0.0, 2.5, out=f.dye)


def render_frame(f: Fluid, paper, dark_theme):
    if dark_theme:
        # 亮墨暗底:加色
        img = np.array(paper, np.float32)[None, None, :] + f.dye
    else:
        # 暗墨亮底:減色(像墨吸掉紙的反射)
        img = np.array(paper, np.float32)[None, None, :] * np.exp(-f.dye * 1.4)
    return np.clip(img, 0.0, 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=30)
    ap.add_argument("--theme", default="ink", choices=list(THEMES))
    ap.add_argument("--out", default="fluid.mp4")
    ap.add_argument("--audio")
    ap.add_argument("--warmup", type=float, default=12.0,
                    help="開場前先讓墨擴散幾秒,避免從全白開始")
    ap.add_argument("--resume", default="",
                    help="狀態存檔路徑。存在→載入續跑(跳過暖機);結束時寫回。"
                         "🔴 長片必用:環境會砍長任務,但流體狀態連續、不能獨立分塊,"
                         "只能靠 checkpoint 分段續算(物理不中斷)。")
    ap.add_argument("--seed", type=int, default=7,
                    help="墨源軌跡種子。每支片必須不同,否則同主題動態逐幀相同")
    a = ap.parse_args()

    paper, inks = THEMES[a.theme]
    dark = a.theme == "slate"
    f = Fluid(GW, GH)
    rng = np.random.default_rng(a.seed)
    # 每個墨源一組 (相位偏移, 頻率倍率∈[0.75,1.35]) —— 軌跡族整個換掉
    phases = [(float(rng.uniform(0, 2 * math.pi)), float(rng.uniform(0.75, 1.35)))
              for _ in inks]
    sim_scale = GW / 96.0        # 平流步長相對網格的比例

    n = int(a.secs * FPS)
    print(f"主題 {a.theme}  模擬 {GW}x{GH} → {W}x{H}  {a.secs:.0f}s / {n} 幀"
          f"(暖機 {a.warmup:.0f}s)")

    # 暖機:畫面出現前先跑幾秒,開場就有形狀(有 resume 存檔則直接續跑)
    t0 = a.warmup
    ckpt = pathlib.Path(a.resume) if a.resume else None
    if ckpt and ckpt.exists():
        st = np.load(ckpt)
        f.u[:], f.v[:], f.dye[:] = st["u"], st["v"], st["dye"]
        t0 = float(st["t"])
        print(f"  從存檔續跑 t={t0:.1f}s")
    else:
        for i in range(int(a.warmup * FPS)):
            inject(f, i * DT, inks, rng, phases)
            f.step(DT, sim_scale)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{GW}x{GH}", "-r", str(FPS), "-i", "-"]
    if a.audio:
        cmd += ["-i", str(a.audio)]
    cmd += ["-vf", f"scale={W}:{H}:flags=lanczos,noise=alls=3:allf=t+u,format=yuv420p"]
    if a.audio:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", str(a.out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    import time
    wall = time.time()
    for i in range(n):
        t = t0 + i * DT
        inject(f, t, inks, rng, phases)
        f.step(DT, sim_scale)
        img = render_frame(f, paper, dark)
        p.stdin.write((img * 255).astype(np.uint8).tobytes())
        if i % (FPS * 5) == 0:
            print(f"  {i//FPS:>4d}s / {int(a.secs)}s  ({(time.time()-wall):.0f}s 實耗)")
    p.stdin.close()
    p.wait()
    if ckpt:
        np.savez_compressed(ckpt, u=f.u, v=f.v, dye=f.dye, t=t0 + n * DT)
        print(f"  狀態已存 {ckpt}(t={t0 + n * DT:.1f}s)")
    print(f"完成 → {a.out}  實耗 {time.time()-wall:.0f}s")


if __name__ == "__main__":
    main()
