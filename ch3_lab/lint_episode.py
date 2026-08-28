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

## 判準:一段連續的近空畫面
不是「這一幀有多滿」——過場本來就會短暫變空。真正的缺陷是**持續**的空:
連續數秒的畫面上幾乎沒有東西,而觀眾在那幾秒裡沒有得到任何資訊。
所以判準是「墨水比例低於門檻的**最長連續秒數**」。

門檻不是我挑的,是量出來的:見 `--profile` 與模組尾端的校準紀錄。

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
#: 🔴 **這兩個值是量出來的,不是挑的。** 我第一版憑感覺寫 0.010,而實測
#:    這條線的正常內容就落在 0.006~0.09(中位 0.015~0.021)—— 0.010 直接
#:    切在合法內容的中間,會把好畫面判成空的。這正是本檔要抓的那種
#:    「拿一個沒有依據的數字當判準」。
#
#: 校準資料(2026-08-29,ep013 舊碼 / ep006 ep008 新碼,各約 250 個取樣點):
#:   floor 0.002 → 三支的最長連續近空都是 1.0s(純過場)
#:   floor 0.005 → 1.5 ~ 2.0s
#:   floor 0.008 → 22.5 ~ 28.0s(打到 record/close 那種本來就疏的幕)
#: 所以 0.005 是唯一分得開「過場」與「真的空掉一整幕」的那一檔;
#: 3 秒的容忍上限比實測最差值(2.0s)高 50%,不是貼著資料設的。
INK_FLOOR = 0.005
MAX_EMPTY_S = 3.0

#: 附帶的回歸訊號:**中位墨水比例**。scale 那一幕的版面修正前後,
#: 同一條產線的中位墨水從 0.0146(ep013,舊碼)升到 0.0206 / 0.0201
#: (ep006 / ep008,新碼)—— +41%。這比「我改了常數所以應該修好了」
#: 有力得多:它量的是產物,不是意圖。


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
    return {"n": len(s), "min_ink": min(x for _, x in s),
            "med_ink": float(np.median([x for _, x in s])),
            "empty_s": dur, "empty_at": at,
            "ok": dur <= MAX_EMPTY_S}


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
        flag = "" if r["ok"] else "  ⛔"
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
