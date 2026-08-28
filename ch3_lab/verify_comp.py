#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_comp.py — 合輯的驗收:抽出該看的幀,看過了才發通行證。

## 為什麼要一支工具
`publish_comp` 要求 `verified.json` 才准發(合輯是新格式、超過 10 分鐘、
而排程會在無人看管時送出)。但「看過了」如果靠臨時拼指令,就會變成
今天出過問題的那種檢查:**只看了兩個邊卻宣稱看過版面**。

所以把「該看哪幾幀」定死在這裡:

- **intro**:片頭字卡有沒有把標題寫完整
- **每一張串場卡**:問題有沒有洩漏結果、字有沒有被切掉
- **每一個接縫**:本體被裁掉結語之後,結尾有沒有切在句子中間
  (裁切點是算出來的,算錯就會聽到半句話 —— 這是最可能出錯的地方)
- **outro**:片尾那份清單的數字對不對
- **章節時間戳**:manifest 說第 k 章在 m:ss,那個時間點畫面上該是第 k 段

## 通行證
`--ok` 才會寫 `verified.json`,而且把當時的 `manifest.total` 一起記進去 ——
重剪過那個值會變,通行證自動失效。**這支不會自己判斷內容對不對**:
它負責把該看的東西擺到你面前,判斷仍然是人的事。

用法:
  python verify_comp.py --bucket fail            # 抽幀 + 印章節,不發通行證
  python verify_comp.py --bucket fail --ok       # 看過了,寫通行證
"""
import argparse
import json
import pathlib
import subprocess
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent


def grab(mp4, t, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                    "-i", str(mp4), "-frames:v", "1", str(out)], check=False)
    return out if out.exists() else None


def sheet(paths, out, cols=3):
    import imageio.v2 as iio
    ims = [iio.imread(p)[::4, ::4] for p in paths if p]
    if not ims:
        return None
    h = min(i.shape[0] for i in ims)
    rows = []
    for i in range(0, len(ims), cols):
        r = [np.pad(x[:h], ((0, 0), (0, 8), (0, 0)), constant_values=45)
             for x in ims[i:i + cols]]
        while len(r) < cols:
            r.append(np.full_like(r[0], 25))
        rows.append(np.concatenate(r, axis=1))
    w = min(r.shape[1] for r in rows)
    iio.imwrite(out, np.concatenate(
        [np.pad(r[:, :w], ((0, 10), (0, 0), (0, 0)), constant_values=45)
         for r in rows], axis=0), quality=94)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True,
                    choices=["fail", "mixed", "held"])
    ap.add_argument("--ok", action="store_true",
                    help="看過了,發通行證(只有這個旗標會寫 verified.json)")
    a = ap.parse_args()

    d = ROOT / "compilations" / a.bucket
    mp4 = d / f"{a.bucket}_compilation.mp4"
    man_p = d / "manifest.json"
    if not mp4.exists() or not man_p.exists():
        print(f"⛔ {a.bucket}:缺 mp4 或 manifest.json,先重剪。")
        return 1
    man = json.loads(man_p.read_text(encoding="utf-8"))
    tmp = d / "_verify"
    tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()

    print(f"[{a.bucket}] {man['title']}")
    print(f"  成片 {man.get('mp4_seconds', 0) / 60:.1f} 分、"
          f"manifest 記 {man['total'] / 60:.1f} 分、{man['n']} 個發現\n")

    shots, labels = [], []
    for c in man["clips"]:
        st, du = c["start"], c["dur"]
        stem = c["clip"].rsplit(".", 1)[0]
        if stem == "intro":
            shots.append(grab(mp4, st + du * 0.7, tmp / "a_intro.png"))
            labels.append("intro")
        elif c.get("kind") == "card":
            k = stem[4:]
            shots.append(grab(mp4, st + du * 0.6, tmp / f"b_card{k}.png"))
            labels.append(f"card{k} @ {int(st)//60}:{int(st)%60:02d}")
        elif stem.startswith("body"):
            # 🔴 接縫:本體的**最後一秒**。裁切點是算出來的,算錯就會在
            #    這裡聽到/看到半句話 —— 這是整個新格式最可能出錯的地方。
            shots.append(grab(mp4, st + du - 0.6, tmp / f"c_seam{stem[4:]}.png"))
            labels.append(f"{stem} 結尾(裁切點)")
        elif stem == "outro":
            shots.append(grab(mp4, st + du * 0.75, tmp / "d_outro.png"))
            labels.append("outro 清單")

    out = sheet([s for s in shots if s], d / "_verify_sheet.jpg")
    print("  抽幀:")
    for l in labels:
        print(f"    {l}")
    print(f"\n  → {out}")

    # 🔴 章節**從 publish_comp 拿**,不要自己算一份。這裡一度自己算,而
    #    publish_comp 修好之後這邊沒跟上 —— 於是驗收工具印出來的時間戳
    #    跟實際會寫進說明欄的**不一樣**,而驗收工具的整個用途就是
    #    「確認說明欄會寫對」。同型錯誤第八次。
    sys.path.insert(0, str(ROOT))
    from publish_comp import chapter_times
    print("\n  章節(說明欄會用的,與 publish_comp 同一份):")
    for k, (t, row) in enumerate(chapter_times(man), 1):
        print(f"    {t//60}:{t%60:02d}  第 {k} 段  (row {row})")

    if not a.ok:
        print("\n  (沒有 --ok,未發通行證。看過上面那張圖與章節之後再加 --ok)")
        return 0

    import datetime
    import hashlib
    # 通行證綁 **mp4 的雜湊**,不是片長。「同樣六集重渲之後再剪一次」
    # 長度只差零點幾秒,拿秒數當識別碼在最該擋的情境下分辨不出來。
    ver = {
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "by": "ch3 pipeline operator",
        "mp4_md5": hashlib.md5(mp4.read_bytes()).hexdigest(),
        "mp4_seconds": man.get("mp4_seconds"),
        "manifest_total": man["total"],
        "checked": ["intro", "cards", "seams", "outro", "chapters"],
        "sheet": str(out.relative_to(ROOT)) if out else None,
    }
    (d / "verified.json").write_text(
        json.dumps(ver, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  ✓ 通行證已寫入 {d / 'verified.json'}"
          f"\n    綁定 mp4 md5 {ver['mp4_md5'][:12]}… —— 重剪後自動失效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
