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

**B. 中位墨水比例**(`med_ink`)—— 也是一道**地板**,不是陳舊偵測器。
兩代確實分得開(舊 0.0146~0.0159 / 新 0.0196~0.0220,零重疊),我一度
想把門檻設在中間當「這支看起來是舊碼渲的」—— 但那需要**每一代重新
校準**,而兩次校準之間它守的是上一代的差異,不是我以為的那件事。
理由詳見 `MED_INK_FLOOR`。設在 0.012 凍結,只抓災難。

**C. 標記出現時點**(`marker_onset`)—— **這一項才是針對性的**。
量的是「本集的效果量標記在 scale 幕的第幾成出現」,也就是我實際改的
那件事。基線是程式裡寫死的比例(不隨產線漂移),而且**反向驗證過**:
拿排在 60% 的 12 支對照組去量,12/12 落在 0.618~0.642。

## 掃描範圍
預設**只掃還能重渲的**。已發布的是舊版面舊節奏、一定會被 C 擋下,而它們
永遠不會重渲 —— 留在清單裡就是一個恆真的警告,而恆真的警告會訓練人
忽略輸出(同 `_stale.py`)。要看全部用 `--all`。

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

#: 中位墨水的**地板**。它的工作只有一個:抓「這支渲壞了 / 大部分是黑的」
#: 這種災難。**它不是陳舊偵測器。**
#
#: 🔴 我一度想把它設在新舊兩代中間(0.018)當「這支看起來是舊碼渲的」
#:    的判準,並且打算**每一代重新校準**。那是錯的,理由:
#:    - 中位墨水對「是不是新碼渲的」只是**代理量**,它只在「這一代剛好
#:      跟上一代的墨水不同」時有效。每改一次產線就要重校,而兩次校準
#:      之間它守的是**上一代的差異**,不是我以為的那件事。
#:    - 逐代往上移的話,爬升的理由是「上一代長什麼樣」而不是「觀眾能
#:      忍受什麼」,遲早開始擋掉本來沒問題的東西。
#:    - 而且它**永遠測不出同一代之內的退步**(總是拿當代校準的)——
#:      「有一支渲出來比同批的疏」剛好落在盲區。
#:    「產物是不是現行碼渲的」交給 `marker_onset`:它量的是我實際改的
#:    那件事,基線是程式裡寫死的比例(不會漂移),而且反向驗證過。
#
#: 所以設成 **0.012 並凍結**:兩代都遠遠高過(舊碼最低 0.0146、
#: 新碼最低 0.0196),各有餘裕。除非「什麼叫疏到不能出貨」這個判斷本身
#: 變了,否則不要再動它 —— 它參照的是人的判斷,不是上一代的產物。
MED_INK_FLOOR = 0.012


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


#: scale 幕裡「本集標記」所在的橫帶(圖形座標,由下往上)。
#: `ax2 = fig.add_axes([0.12, 0.28, 0.76, 0.30])`、`ylim=(-1, 1)`,所以:
#:   資料 y=0(白點)      → 圖形 y = 0.28 + 0.30*0.50 = 0.43
#:   資料 y=-0.62(標籤)  → 圖形 y = 0.28 + 0.30*0.19 = 0.337
#:   資料 y=+0.62(門檻字)→ 圖形 y = 0.523   ← 刻意排除在外
#: 取 [0.32, 0.47] 就只框住標記那兩個元素。
MARK_ROI = (0.32, 0.47)
SEGS = ["hook", "original", "scale", "replication", "result", "record", "close"]


def scene_bounds(ep_dir, name="scale"):
    """從各段 wav 的長度推這一幕在片子裡的起訖秒數。

    ⚠️ 段落順序要用 `make_episode.build_script` 的**真實順序**,不是
    `seg_*.wav` 的檔名排序 —— 那個排序是錯的(alphabetical),我第一次
    抽幀就是這樣抽到別的幕去。
    """
    import wave
    t = 0.0
    for n in SEGS:
        f = ep_dir / f"seg_{n}.wav"
        if not f.exists():
            continue
        with wave.open(str(f)) as w:
            dur = w.getnframes() / w.getframerate()
        if n == name:
            return t, t + dur
        t += dur + 0.5
    return None


#: 標記在不在的判準(ROI 墨水絕對值)。**跨 12 支校準過**:
#:   標記出現前(幕的前 50%)最大 0.00464   ← 只有門檻虛線穿過這條帶
#:   標記出現後(幕的後 30%)最小 0.01823   ← 白點 + 粗體 this study
#: 兩者差 4 倍,0.010 落在中間(離下界 2.2 倍、離上界 1.8 倍)。
#: ⚠️ 不要用「第一幀當基線」——第一幀是**上一幕的殘影**(轉場),
#:    ep006 量到 0.016,比標記出現後還高,於是判準永遠不觸發。
#:    我第一版就是這樣寫的:基線挑了個方便的東西,而不是它代表的東西。
MARK_INK = 0.010
#: 跳過幕開頭 1 秒:轉場殘影會污染。
MARK_SKIP_S = 1.0
#: 標記最晚該在幕的第幾成出現。旁白第一句就把該集的數字當主詞,所以
#: 畫面不該讓它拖到後半。**這個判準經過反向驗證**:拿排在 60% 的那 12 支
#: 對照組去量,12/12 都落在 0.618~0.642 —— 量測還原了已知的真值,
#: 所以它量的確實是「標記何時出現」而不是別的東西。
MARK_LATE = 0.30


def marker_onset(mp4, ep_dir):
    """本集標記在 scale 幕裡**第幾成**才出現。量的是 mp4,不是現行碼。

    🔴 最直覺的寫法是呼叫 `render(plt, "scale", t, dur, D)` 看標記在不在
    —— 但那測的是「現行碼會畫什麼」,跟 `_bounds.py` 是同一個問題。
    這支存在的理由是回答**另一個**:「已經渲好的那個檔案裡有沒有」。
    兩個問題不一樣,兩個都要問(同 `_stale.py` 檔頭)。

    做法是沿用同一套墨水量測,只把窗口縮到標記那條橫帶 —— ROI 一縮小,
    訊噪比就遠好過全片中位墨水(這裡是 4 倍分離,全片中位是 1.35 倍)。
    不需要模板比對,也不需要找圓點。

    回傳 0~1 的比例,或 None(整幕都沒出現)。
    """
    import imageio.v2 as iio
    b = scene_bounds(ep_dir)
    if not b:
        return None
    t0, t1 = b
    span = t1 - t0 - MARK_SKIP_S
    if span <= 0:
        return None
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t0 + MARK_SKIP_S:.2f}",
             "-to", f"{t1:.2f}", "-i", str(mp4),
             "-vf", f"fps={SAMPLE_HZ},scale=480:-1", str(tmp / "f%05d.png")],
            check=True, capture_output=True)
        for i, f in enumerate(sorted(tmp.glob("f*.png"))):
            im = iio.imread(f)[:, :, :3].astype(int)
            h = im.shape[0]
            bg = np.median(im.reshape(-1, 3), axis=0)
            roi = im[int((1 - MARK_ROI[1]) * h):int((1 - MARK_ROI[0]) * h)]
            if float((np.abs(roi - bg).max(axis=2) > 26).mean()) > MARK_INK:
                return round((i / SAMPLE_HZ) / span, 3)
    return None


def check(mp4):
    with tempfile.TemporaryDirectory() as td:
        s = ink_series(mp4, pathlib.Path(td))
    dur, at = worst_run(s)
    med = float(np.median([x for _, x in s]))
    onset = marker_onset(mp4, mp4.parent)
    late = onset is None or onset > MARK_LATE
    return {"n": len(s), "min_ink": min(x for _, x in s),
            "med_ink": med, "empty_s": dur, "empty_at": at,
            "mark_at": onset, "mark_late": late,
            "thin": med < MED_INK_FLOOR,
            "ok": (dur <= MAX_EMPTY_S and med >= MED_INK_FLOOR
                   and not late)}


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

    skipped = []
    if a.one:
        targets = [pathlib.Path(a.one)]
    else:
        # 🔴 預設**只掃還能重渲的**。已發布的長片是舊版面舊節奏,一定會被
        #    標記時點那道擋下 —— 而它們**永遠不會重渲**,所以那會變成一個
        #    恆真的警告:每次跑都有 11 支紅字。恆真的警告會訓練我忽略這支
        #    的輸出,跟今天 `_stale.py` 因為同一個理由改成 pending-only
        #    是同一件事。門檻設多少都比不上這件事重要。
        meta = json.loads(META.read_text(encoding="utf-8"))
        led = ROOT / "uploaded.json"
        pub = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {}
        targets = []
        for o in meta:
            v = ROOT / o["video"]
            if not v.exists():
                continue
            if not a.all and (o.get("dir") in pub or o.get("slug") in pub):
                skipped.append(o.get("dir") or o.get("slug"))
                continue
            targets.append(v)
    bad = 0
    for p in targets:
        r = check(p)
        flag = ""
        if r["empty_s"] > MAX_EMPTY_S:
            flag += "  ⛔ 近空過久"
        if r["thin"]:
            flag += "  ⛔ 版面疏到不能出貨"
        if r["mark_late"]:
            flag += ("  ⛔ 標記整幕沒出現" if r["mark_at"] is None
                     else f"  ⛔ 標記到 {r['mark_at']:.0%} 才出現")
        if not r["ok"]:
            bad += 1
        mk = "—" if r["mark_at"] is None else f"{r['mark_at']:.0%}"
        print(f"{p.parent.name:22s} 取樣 {r['n']:3d}  中位墨水 {r['med_ink']:.3f}"
              f"  標記 {mk:>4s}"
              f"  最低 {r['min_ink']:.3f}  最長近空 {r['empty_s']:.1f}s"
              + (f" @{r['empty_at']:.0f}s" if r["empty_at"] is not None else "")
              + flag)
    if not a.all and skipped:
        # 印到 stderr:stdout 要能直接被別的工具吃
        print(f"\n({len(skipped)} 支已發布、不會重渲,已略過:"
              f"{', '.join(skipped)})", file=sys.stderr)
    print(f"\n{len(targets) - bad}/{len(targets)} 支通過"
          f"(近空:墨水 < {INK_FLOOR} 連續超過 {MAX_EMPTY_S} 秒;"
          f"偏疏:中位墨水 < {MED_INK_FLOOR};"
          f"標記:晚於幕的 {MARK_LATE:.0%})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
