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

## 🔴 它對「只有畫面改了」是全盲的
第 2 層的真正判準是**旁白逐字比對** —— 那是刻意的(輸出中性的改動不該
誤擋)。但代價是:**改了版面或時序、旁白一個字沒動的時候,它會說「這是
現行碼的產物」而其實不是。** 今天就改了兩處純畫面的東西(scale 幕的版面、
scale/close 兩幕的時序),兩次旁白都完全沒變。

那一半由 `lint_episode.py` 的 `marker_onset` 補:它從 mp4 抽幀量「本集
標記在 scale 幕的第幾成出現」,舊節奏 0.595~0.609、新節奏 0.106~0.130,
分得開。Shorts 那條對應的是 `visual.json` + `frame_digest`。
**跑 preflight 通過不等於畫面是新的**,兩支都要跑。

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


def narration_matches(o):
    """磁碟上的旁白 == 現行碼現在會產出的旁白?

    🔴 mtime 只知道「檔案比程式舊」,不知道「那次改動有沒有影響輸出」。
    實測已經三次是**輸出中性**的改動(TTS 暫存檔改路徑、只影響別集的分支),
    每次都要我手動比對稿子才敢放行 —— 而「我看過 diff 覺得沒影響」正是
    最不該由人來判的那種判斷。所以改成讓程式自己比。

    回傳 True 表示逐字元相同 = 那支 mp4 的內容跟現行碼一致,mtime 警報
    可以忽略。回傳 None 表示比不了(比不了就不放行)。
    """
    d = ROOT / o["dir"]
    try:
        if o["kind"] == "fred":
            import make_episode as M
            q = pd.read_csv(QUEUE, low_memory=False)
            segs = M.build_script(M.build_facts(q.iloc[o["row"]]))
        else:
            import make_famous as MF
            eps = json.loads((ROOT / "facts" / "famous_episodes.json")
                             .read_text(encoding="utf-8"))["episodes"]
            E = next(e for e in eps if e["slug"] == o["slug"])
            segs = MF.build_script(E)
    except Exception:                                        # noqa: BLE001
        return None
    for name, text in segs:
        f = d / f"narr_{name}.txt"
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            return False
    return True


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

    # ② mp4 要比所有會影響它的原始碼與資料新 —— 但 mtime 只是**觸發條件**,
    #    真正的判準是「內容有沒有變」。舊的話就實際比對旁白逐字元。
    older = [n for n in SOURCES
             if mt(ROOT / n) is not None and t_mp4 < mt(ROOT / n)]
    if older:
        same = narration_matches(o)
        if same is None:
            problems.append(f"mp4 比 {', '.join(older)} 舊,而且比不了旁白")
        elif not same:
            problems.append(
                f"mp4 比 {', '.join(older)} 舊,**而且旁白已經不一樣了**")
        # same is True → 改動是輸出中性的,不算陳舊

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
