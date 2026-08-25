#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py — 上傳前的陳舊檢查:這支 mp4 真的是「現在這份碼 + 現在這份資料」產的嗎?

## 為什麼需要它
這條線反覆出現同一種災情:**碼修好了、檔案也在,但 mp4 是舊碼的產物**。
它不會報錯、不會缺檔,清單看起來一切正常。實測發生過兩次:
- 9 集的重產沒啟動,mp4 全部早於 `make_episode.py` 的修正時間
- 渲染死在 `render_scene` 裡(k_word、CARD_TEXT 兩次 KeyError)

第二種特別惡毒,因為 `facts.json` 是在**渲染之前**寫的、mp4 是**渲染之後**
才 mux 的。死在中間時 facts.json 是新的、mp4 是舊的 —— 只比對 facts.json
裡的 tone 會回報「相符 = 最新」,**假的全綠比沒有檢查更糟**。

## 三層,由便宜到貴
1. **mtime 斷言**(stat 就好):mp4 要比 facts.json 新、也要比產生它的程式新
2. **tone 一致**:facts.json 記的 tone vs 現行碼重算 —— 抓邏輯漂移
3. 四路查表與開圖(貴,交給獨立驗證員)

前兩層是快篩,第三層才是真憑據。這支只做 1 和 2,但它們擋得掉最常發生的那種。

用法:
  python preflight.py            # 檢查 publish_meta.json 裡的每一集
  python preflight.py --strict   # 有任何一集陳舊就回傳非零(給 CI / 上傳前用)
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd                                    # noqa: E402
from make_episode import build_facts, tone_of          # noqa: E402

META = ROOT / "publish_meta.json"
QUEUE = ROOT / "facts" / "episode_queue.csv"
# 產出會受哪些檔案影響——任何一個比 mp4 新,那支 mp4 就是舊的
SOURCES = ["make_episode.py", "make_famous.py",
           "facts/episode_queue.csv", "facts/famous_episodes.json"]


def mt(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def check(o, q):
    d = ROOT / o["dir"]
    mp4 = ROOT / o["video"]
    thumb = ROOT / o["thumb"] if o.get("thumb") else None
    problems = []

    t_mp4 = mt(mp4)
    if t_mp4 is None:
        return ["mp4 不存在"]
    if thumb and mt(thumb) is None:
        problems.append("縮圖不存在")

    # ① mp4 要比它自己的 facts.json 新
    fj = d / "facts.json"
    t_facts = mt(fj)
    if t_facts is not None and t_mp4 < t_facts:
        problems.append(
            f"mp4 比 facts.json 舊 {t_facts - t_mp4:.0f} 秒"
            f"(渲染很可能死在寫 facts 之後、mux 之前)")

    # ② mp4 要比所有會影響它的原始碼與資料新
    for name in SOURCES:
        ts = mt(ROOT / name)
        if ts is not None and t_mp4 < ts:
            problems.append(f"mp4 比 {name} 舊 {(ts - t_mp4) / 60:.0f} 分鐘")

    # ③ facts.json 記的 tone vs 現行碼重算
    if t_facts is not None and o["kind"] == "fred":
        try:
            recorded = json.loads(fj.read_text(encoding="utf-8")).get("tone")
        except Exception as e:                          # noqa: BLE001
            problems.append(f"facts.json 讀不了({str(e)[:30]})")
            recorded = None
        now = tone_of(build_facts(q.iloc[o["row"]]))
        if recorded != now:
            problems.append(f"tone 漂移:檔案記 {recorded!r},現行碼算出 {now!r}")
    return problems


def main_for(episodes):
    """給 upload.py 用:只檢查這次真的要上傳的那幾集。回傳陳舊的集數。"""
    q = pd.read_csv(QUEUE, low_memory=False)
    stale = []
    for o in episodes:
        probs = check(o, q)
        key = o.get("slug") or pathlib.Path(o["dir"]).name
        if probs:
            stale.append(key)
            for x in probs:
                print(f"  ⛔ {key:<22}{x}")
    if not stale:
        print(f"  {len(episodes)} 集全部是最新產物 ✓")
    return stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    meta = json.loads(META.read_text(encoding="utf-8"))
    q = pd.read_csv(QUEUE, low_memory=False)
    stale = []
    for o in meta:
        probs = check(o, q)
        key = o.get("slug") or pathlib.Path(o["dir"]).name
        if probs:
            stale.append(key)
            print(f"  ⛔ {key:<22}{probs[0]}")
            for extra in probs[1:]:
                print(f"     {'':<20}{extra}")
    ok = len(meta) - len(stale)
    print(f"\n{ok}/{len(meta)} 集是「現在這份碼 + 現在這份資料」的產物")
    if stale:
        print(f"陳舊 {len(stale)} 集:{' '.join(stale)}")
        print("⚠️ 這一層只擋得掉「舊檔」。碼對、檔新、但畫面錯,只有開圖才看得到。")
        return 1 if a.strict else 0
    print("⚠️ 通過這一層不代表內容正確——它只證明檔案不是舊的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
