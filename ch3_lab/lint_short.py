#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_short.py — 量 Shorts 的內容有沒有越界。

## 為什麼要一支工具而不是用看的
Shorts 的 UI 會蓋住畫面的一部分:下緣約 22%(標題列、頻道名、說明)、
右緣約 12%(按讚/留言/分享/轉動)。被蓋住的字不是「小一點的資訊」,
它就是不存在 —— 但在本機播放器裡看起來完全正常。

我已經靠肉眼抓到兩次(判決句壓在下緣、「23 laboratories」伸進按鈕欄),
兩次都要重渲一輪。用看的會漏,因為要看的是**每一支 × 每一段 × 每一個
淡入時點**。所以改成量:掃出所有非背景的像素,看它們的邊界在哪。

## 判準(**四個邊都量**,影像座標由上往下算)
- 右緣 x ≤ 0.88 —— 再過去是按讚/留言/分享那一欄
- 左緣 x ≥ 0.05 —— 貼邊不好看
- 下緣 y ≤ 0.78 —— 再下去是標題列與頻道名
- 上緣 y ≥ 0.07 —— 再上去是「Shorts」標籤與搜尋圖示
- 第一幀不得是空的(Shorts 靠第一幀決定要不要停下來)

⚠️ 這份清單**必須跟下面的常數一致**。第一版只寫了右緣與下緣,碼也只有
那兩個,於是我拿「檢查器通過」當成「版面沒問題」的證據 —— 而頻道標記
在頂端,從來沒被量過(獨立驗證直接量檔案抓到 y≈0.035)。
一支專門用來「不要相信肉眼、要相信量測」的工具,自己的文件跟實作對不上
是最糟的一種不一致。

用法:
  python lint_short.py                 # 掃全部
  python lint_short.py --one ep013
"""
import argparse
import pathlib
import subprocess
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
# 🔴 **四個邊都要量**。第一版只有右緣與下緣 —— 於是我拿「檢查器通過」
#    當成「這支片版面沒問題」的證據,而頻道標記在**頂端** y≈0.955
#    (Shorts 頂端有「Shorts」標籤與搜尋圖示),它從來沒被檢查過。
#    只驗兩個邊卻宣稱驗過版面,是過度宣稱 —— 跟今天其他幾次同一個形狀。
LEFT_LIMIT, RIGHT_LIMIT = 0.05, 0.88
TOP_LIMIT, BOTTOM_LIMIT = 0.07, 0.78
#: 取樣時間點。每段的字是逐步淡入的,只看一幀會漏掉後面才出現的元素。
SAMPLE_HZ = 2.0


def frames_of(mp4, tmp):
    """每 0.5 秒抽一幀。比逐幀快很多,而字停留的時間都遠超過 0.5 秒。"""
    for p in tmp.glob("*.png"):
        p.unlink()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4),
                    "-vf", f"fps={SAMPLE_HZ}", str(tmp / "f%04d.png")],
                   check=True)
    return sorted(tmp.glob("*.png"))


def check(mp4, tmp):
    import imageio.v2 as iio
    out = []
    fs = frames_of(mp4, tmp)
    if not fs:
        return ["抽不到幀"]
    for i, f in enumerate(fs):
        im = iio.imread(f)
        h, w = im.shape[:2]
        # 背景是接近純色的深底;「內容」= 明顯亮於背景的像素。
        bg = np.median(im.reshape(-1, 3), axis=0)
        mask = (np.abs(im.astype(int) - bg).max(axis=2) > 26)
        if not mask.any():
            if i == 0:
                out.append("第一幀是空的(Shorts 靠第一幀決定停不停)")
            continue
        ys, xs = np.nonzero(mask)
        lx, rx = xs.min() / w, xs.max() / w
        ty, by = ys.min() / h, ys.max() / h
        t = i / SAMPLE_HZ
        if rx > RIGHT_LIMIT:
            out.append(f"t={t:.1f}s 內容右緣 {rx:.3f} > {RIGHT_LIMIT}"
                       f"(伸進按讚欄)")
        if lx < LEFT_LIMIT:
            out.append(f"t={t:.1f}s 內容左緣 {lx:.3f} < {LEFT_LIMIT}(貼邊)")
        if by > BOTTOM_LIMIT:
            out.append(f"t={t:.1f}s 內容下緣 {by:.3f} > {BOTTOM_LIMIT}"
                       f"(被標題列蓋住)")
        if ty < TOP_LIMIT:
            out.append(f"t={t:.1f}s 內容上緣 {ty:.3f} < {TOP_LIMIT}"
                       f"(被頂端的 Shorts 標籤/搜尋圖示蓋住)")
    # 同一種越界會在連續幾幀重複,只留最嚴重的那一筆
    seen, uniq = set(), []
    for m in out:
        k = m.split("內容")[-1][:4]
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one")
    a = ap.parse_args()
    tmp = ROOT / "_lint_tmp"
    tmp.mkdir(exist_ok=True)
    dirs = ([ROOT / "shorts" / a.one] if a.one
            else sorted((ROOT / "shorts").iterdir()))
    bad = ok = 0
    for d in dirs:
        mp4 = d / f"{d.name}_short.mp4"
        if not mp4.exists():
            continue
        probs = check(mp4, tmp)
        if probs:
            bad += 1
            print(f"⛔ {d.name}")
            for p in probs:
                print(f"     {p}")
        else:
            ok += 1
    for p in tmp.glob("*.png"):
        p.unlink()
    tmp.rmdir()
    print(f"\n{ok} 支通過,{bad} 支越界")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
