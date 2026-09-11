#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同題重複的對照 —— 「這支是不是同一個題目的第二支」。

🔴 **這條之所以存在,是因為防重機制對它是結構性盲的。**
   `publish_shorts.py:1201` 的防重是 `o["key"] not in done` —— **逐字比 key**。
   而這一批的 key 是 `reel_learning_styles`,帳本裡已上線的那支叫
   `learning_styles`(舊格式,無前綴)⇒ **key 不同,防重不會叫**,
   而觀眾看到的是同一個頻道發同一個題目的第二支。

   這不是潔癖:同頻道發同題近似片正好踩在 YouTube inauthentic 政策點名的
   「模板化 / 變化極小 / 可大規模量產」,而那條是 YPP 生存線
   (memory `yt-inauthentic-template-risk-2026-08`)。

⚠️ 這支量的是**帳本上的題目重疊**,不是「兩支片有多像」。
   它答得出「有沒有同題的已上線片」,答不出「像到會不會被判定為 inauthentic」——
   後者沒有機械判準,要人開兩支片看。**不要把這支的綠燈讀成後者。**
"""
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(r"D:\carson-agent\ch3_lab")
NEW = ["study_techniques", "how_to_remember_what_you_read", "focus_techniques",
       "if_then_plans", "learning_styles", "pomodoro"]
NL = chr(10)
ok = []

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative", "label":
     "六支的 slug **去掉 reel_ 前綴之後**逐一比對帳本 ⇒ 這才是防重漏掉的那一層"},
    {"kind": "negative", "label":
     "六支的題目關鍵詞比對已上線片的標題 ⇒ 抓 slug 改名但題目一樣的那種"},
    {"kind": "positive", "label":
     "learning_styles **必須**被抓到(已知案例:帳本裡有 `learning_styles`)"},
    {"kind": "positive", "label":
     "合成一個 key 叫 `reel_power_posing` ⇒ 必須被抓到(帳本裡有 `power_posing`)"},
    {"kind": "negative", "label":
     "反向對照:合成一個帳本裡完全沒有的題目 ⇒ **不該**被抓到"},
]

STOP = {"the", "a", "an", "of", "to", "and", "or", "is", "are", "not", "do",
        "does", "what", "you", "your", "that", "this", "it", "in", "on",
        "for", "with", "how", "why", "when", "real", "think", "only",
        "actually", "work", "works", "without", "system", "when", "will",
        "their", "them", "we", "us", "my", "me", "be", "been", "was", "were",
        "here", "there", "more", "than", "who", "which", "one", "two",
        "three", "methods", "method", "techniques", "technique"}


def say(good, msg):
    ok.append(bool(good))
    print(f"  {'OK' if good else '**FAIL**'}  {msg}")


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower())
            if w not in STOP and len(w) > 2}


def load():
    led = json.loads((ROOT / "uploaded_shorts.json").read_text(encoding="utf-8"))
    pm = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    titles = {}
    for o in pm:
        k = o.get("key") or (f"reel_{o['slug']}" if o.get("kind") == "reel"
                             else o.get("slug"))
        if k:
            titles.setdefault(k, o.get("title", ""))
        if o.get("slug"):
            titles.setdefault(o["slug"], o.get("title", ""))
    return led, titles


def collide(slug, led, titles, new_title=""):
    """回一串命中理由。空 = 沒撞到。"""
    hits = []
    #: ① key 層:去掉 reel_ 前綴,兩個方向都比 —— 防重只比了一個方向。
    for cand in (slug, f"reel_{slug}"):
        if cand in led:
            hits.append(f"帳本已有 key {cand!r} -> {led[cand]}")
    #: ② 題目層:slug 的字 + 標題的字,和已上線片的標題比重疊。
    mine = words(slug.replace("_", " ")) | words(new_title)
    for k, vid in led.items():
        if k in (f"reel_{slug}",):
            continue
        t = titles.get(k, "")
        theirs = words(k.replace("_", " ")) | words(t)
        inter = mine & theirs
        if len(inter) >= 2 or (inter and words(slug.replace("_", " ")) <= theirs):
            hits.append(f"題目重疊 {sorted(inter)} <- 已上線 {k!r}"
                        f"({vid}) {t[:52]!r}")
    return hits


def main():
    led, titles = load()
    print(f"【帳本】uploaded_shorts.json:{len(led)} 支已上線;"
          f"publish_meta.json 對得出標題的 {len(titles)} 個 key")

    new_titles = {}
    for s in NEW:
        E = json.loads((ROOT / "reels" / s / "facts.json")
                       .read_text(encoding="utf-8"))
        new_titles[s] = E.get("prereg_title", "")

    print(NL + "【① + ② 六支普查】")
    flagged = {}
    for s in NEW:
        h = collide(s, led, titles, new_titles[s])
        if h:
            flagged[s] = h
        print(f"    {s:<30} {'撞到 ' + str(len(h)) + ' 筆' if h else '沒撞到'}")
        for x in h:
            print(f"        - {x}")
    say(True, f"六支全部跑過,命中 {len(flagged)} 支:{sorted(flagged)}")

    print(NL + "【陽性 ③】learning_styles 是已知案例,必須被抓到:")
    say("learning_styles" in flagged,
        "learning_styles 被抓到 ⇒ 這把尺看得到 key 前綴那一層")

    print(NL + "【陽性 ④】合成 reel_power_posing(帳本裡有 power_posing):")
    h4 = collide("power_posing", led, titles, "Power Posing Does Not Work")
    for x in h4[:3]:
        print(f"        - {x}")
    say(bool(h4), "合成案例被抓到")

    print(NL + "【陰性 ⑤】反向對照 —— 合成一個帳本裡沒有的題目:")
    h5 = collide("tax_loss_harvesting_myths", led, titles,
                 "Tax Loss Harvesting Myths")
    for x in h5[:3]:
        print(f"        - {x}")
    say(not h5, "沒撞到 ⇒ 它不是對任何輸入都叫")

    print()
    print("結論:" + (f"同題普查完成,要處置的是 {sorted(flagged)}"
                    if all(ok) else "**對照失敗 —— 這格不算數**"))
    print("⚠️ 這支答得出「有沒有同題已上線片」,答不出「像到會不會被判 inauthentic」。")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
