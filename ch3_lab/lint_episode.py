#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_episode.py — 量長片**檔案本身**:有沒有哪一段畫面幾乎是空的。

## 為什麼需要它(長片端目前的缺口)
`preflight.py` 做兩層:mp4 的 mtime 比程式新、`facts.json` 記的 tone 跟
現行碼重算一致。它自己的說明就寫著第三層「開圖看」太貴、交給獨立驗證員。
於是長片端**沒有任何東西在量畫素**,而這條線最近一次的畫面缺陷正是
「scale 那一幕整幕大部分是黑的」—— 座標軸只佔中間一條窄帶,而那一幕
有 20 多秒。那種缺陷:
- `preflight` 看不到(mtime 新、tone 對)
- 溯源守門看不到(數字全部有出處)
- 我自己看不到(我改了常數就宣稱修好,沒有回頭抽幀)

Shorts 那條有 `lint_short`(量四個邊)與 `_bounds.py`(用現行碼重畫),
長片這條一個都沒有。這支補的是「**產物**長什麼樣」那一半。

## 兩個判準,而且它們抓的**不是同一種東西**

**A. 最長連續近空秒數**(`empty_s`)—— 一道**地板**守門。
不是「這一幀有多滿」(過場本來就會短暫變空),而是「墨水低於門檻的最長
連續秒數」。它抓得到的是災難級的空:整幕沒畫出來、渲染死在中途、
淡入時點寫錯導致長時間黑畫面。

🔴 **它抓不到 scale 那一幕原本的缺陷。** 我一開始是為了那個缺陷建這支的,
但實測打臉:舊碼渲的 `ep000` / `ep018`(正是有那個缺陷的那批)在任何
可用門檻下都**乾淨通過**(1.5~2.0s),而把門檻拉到會抓到它們的高度時,
新碼的片子也一起爆——**沒有任何門檻分得開兩者**。
所以不要以為這一項在守 scale 那一幕。它守的是地板,不是品質。

**B. 中位墨水比例**(`med_ink`)—— 這一項**才**分得開新舊碼。
實測(獨立驗證擴大樣本):
    舊碼 n=7   中位 0.0155   全距 0.0146 ~ 0.0159
    新碼 n=11  中位 0.0210   全距 0.0196 ~ 0.0220
    兩組**完全不重疊**,間距 0.0037 大於任一組的全距。
所以 `med_ink < 0.018` 就是「這支看起來是舊碼渲的」,而 0.018 落在
兩組中間、離兩邊各約 0.0025。這是這支唯一對「版面有沒有變滿」有鑑別力
的指標,而它量的是產物不是意圖。

用法:
  python lint_episode.py --profile eps/ep013/ep013.mp4   # 印出墨水比例序列
  python lint_episode.py                                  # 掃 publish_meta 裡全部
  python lint_episode.py --one eps/ep006/ep006.mp4
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
META = ROOT / "publish_meta.json"

#: 取樣頻率。過場約 0.5~1 秒,2 Hz 足以分辨「過場」與「一整幕都是空的」。
SAMPLE_HZ = 2.0
#: 「幾乎是空的」的墨水比例門檻,以及可以容忍的最長連續秒數。
#
#: 🔴 **這兩個值是量出來的,而且我第一次量錯了結論。** 第一版憑感覺寫
#:    0.010(切在合法內容中間),改成 0.005 之後我寫「0.005 是唯一分得開
#:    過場與真空幕的那一檔」—— 那是拿三個樣本下的結論,**是錯的**。
#:    獨立驗證擴到 6 支 × 8 個門檻:
#:
#:      門檻      0.002 0.003 0.004 0.005 0.006 0.007 0.008
#:      ep000 舊   1.0   1.5   1.5   2.0  28.0  28.0  28.0
#:      ep018 舊   1.0   1.5   1.5   1.5   2.0   3.5  27.5
#:      ep006 新   1.0   1.0   1.5   1.5   2.0   2.0  28.0
#:      ep008 新   1.0   1.0   1.0   1.5   1.5   2.0  22.5
#:      ep012 新   1.0   1.5   1.5   1.5   2.0   2.5  20.0
#:      ep013 新   1.0   1.5   1.5   2.0   2.0  24.0  24.5
#:
#:    0.002~0.005 **四個門檻全都分得開**;0.005 不是唯一,它是**最大的
#:    那個還能全過的值** —— 也就是貼著懸崖。而懸崖位置每支不同
#:    (ep000 在 0.006 就跳到 28s),0.005 距最近的懸崖只有 0.001。
#:    取 0.003:距懸崖兩個校準步,而偵測能力一點沒少(六支都是 1.0~1.5s)。
#:
#: ⚠️ 校準只能引用**目前 repo 裡還是舊碼**的那幾支(ep000~ep005 + ep018)。
#:    我原本引用 ep013 當舊碼基準,而它 04:06 已經被重渲成新碼 ——
#:    那組數字從 repo 再也重現不出來。基準要指向還存在的東西。
INK_FLOOR = 0.003
MAX_EMPTY_S = 3.0

#: 中位墨水的地板。低於它 = 這支看起來是舊碼渲的(見檔頭判準 B)。
#: 兩組實測完全不重疊(舊 0.0146~0.0159 / 新 0.0196~0.0220),
#: 0.018 落在中間,離兩邊各約 0.0025。
MED_INK_FLOOR = 0.018


def frames_of(mp4, tmp, hz=SAMPLE_HZ):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(mp4),
         "-vf", f"fps={hz},scale=480:-1", str(tmp / "f%05d.png")],
        check=True, capture_output=True)
    return sorted(tmp.glob("f*.png"))


def ink_series(mp4, tmp):
    """每個取樣點的「墨水比例」= 與背景色差夠大的畫素佔比。

    背景取整張圖的中位數而不是寫死 BG:長片有漸層與 bloom,寫死顏色會
    把整片背景算成墨水。
    """
    import imageio.v2 as iio
    out = []
    for i, f in enumerate(frames_of(mp4, tmp)):
        im = iio.imread(f)[:, :, :3].astype(int)
        bg = np.median(im.reshape(-1, 3), axis=0)
        ink = (np.abs(im - bg).max(axis=2) > 26).mean()
        out.append((i / SAMPLE_HZ, float(ink)))
    return out


def worst_run(series, floor=INK_FLOOR):
    """回傳 (最長連續近空秒數, 起始秒)。"""
    best = (0.0, None)
    run, start = 0, None
    for t, ink in series:
        if ink < floor:
            if start is None:
                start = t
            run += 1.0 / SAMPLE_HZ
            if run > best[0]:
                best = (run, start)
        else:
            run, start = 0, None
    return best


def check(mp4):
    with tempfile.TemporaryDirectory() as td:
        s = ink_series(mp4, pathlib.Path(td))
    dur, at = worst_run(s)
    med = float(np.median([x for _, x in s]))
    return {"n": len(s), "min_ink": min(x for _, x in s),
            "med_ink": med, "empty_s": dur, "empty_at": at,
            "thin": med < MED_INK_FLOOR,
            "ok": dur <= MAX_EMPTY_S and med >= MED_INK_FLOOR}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one")
    ap.add_argument("--profile", help="印出墨水比例序列(校準用)")
    a = ap.parse_args()

    if a.profile:
        with tempfile.TemporaryDirectory() as td:
            for t, ink in ink_series(pathlib.Path(a.profile), pathlib.Path(td)):
                bar = "#" * int(ink * 200)
                print(f"{t:6.1f}s  {ink:.4f}  {bar}")
        return 0

    if a.one:
        targets = [pathlib.Path(a.one)]
    else:
        meta = json.loads(META.read_text(encoding="utf-8"))
        targets = [ROOT / o["video"] for o in meta
                   if (ROOT / o["video"]).exists()]
    bad = 0
    for p in targets:
        r = check(p)
        flag = ""
        if r["empty_s"] > MAX_EMPTY_S:
            flag += "  ⛔ 近空過久"
        if r["thin"]:
            flag += "  ⛔ 版面偏疏(像舊碼渲的)"
        if not r["ok"]:
            bad += 1
        print(f"{p.parent.name:22s} 取樣 {r['n']:3d}  中位墨水 {r['med_ink']:.3f}"
              f"  最低 {r['min_ink']:.3f}  最長近空 {r['empty_s']:.1f}s"
              + (f" @{r['empty_at']:.0f}s" if r["empty_at"] is not None else "")
              + flag)
    print(f"\n{len(targets) - bad}/{len(targets)} 支通過"
          f"(門檻:墨水 < {INK_FLOOR} 連續超過 {MAX_EMPTY_S} 秒算不通過)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
