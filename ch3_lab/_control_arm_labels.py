#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影像層清單「自變項有沒有被對調」的對照。

🔴 **這條之所以存在,是因為它原本不存在。** 2026-09-11 的影像層驗證裡,
   六支的組別分派**是我用眼睛看畫面確認的** —— 而眼睛不會在下一批自己再看一次。
   「這次碰巧是對的」不算過關:一個被對調的自變項會讓整個實驗量到反過來的東西,
   而畫面、片長、墨水、重疊**每一格都會是綠的**。這一類壞法沒有任何既有閘門覆蓋。

判準鏈(每一環都要能獨立指得出來,不可以自己證自己):
  ① 臂別的**唯一權威**是事前登記檔,而且讀的是它 commit 當時的 blob
     (`git show <commit>:<path>`),不是工作區那一份 ——
     判準引用的東西會被改,而失效方向幾乎一定是放寬。
  ② 登記檔用**逐字標題**指認每一支,不是 slug ⇒ 用 facts.json 的 `prereg_title`
     接回去。接不上就是接不上,不准用 slug 猜。
  ③ 被檢查的東西是**渲染出來的副標**(reel.captions),再到重畫的那一幀的
     ax.texts 裡確認它真的被畫上去。
  ④ 事前登記的 commit 時間必須早於六支 mp4 的產製時間。

⚠️ 「B 臂帶 actually work」這一句錨在**登記檔 §2 的原文**
   (「標題措辭一律帶 that actually work」),不是錨在我現在看到的字串。
"""
import json
import pathlib
import re
import subprocess
import sys
import wave

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib                                        # noqa: E402
matplotlib.use("Agg")
import matplotlib.axes                                   # noqa: E402
import make_reel as M                                    # noqa: E402
from render_pipeline import SEG_GAP                      # noqa: E402
from make_rechecked import twist_rows                    # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative", "label":
     "六支的 prereg_title 都能在**登記 commit 的 blob** 裡找到,分派 4B/2E 與登記一致"},
    {"kind": "negative", "label":
     "facts.json 自己的 arm 欄與①推出來的臂別一致(兩個來源獨立,對不上=有一邊被動過)"},
    {"kind": "negative", "label":
     "同臂六支的副標完全一致、兩臂互斥;B 群的標題與副標都帶登記檔寫死的 actually work,E 群都不帶"},
    {"kind": "negative", "label":
     "副標真的出現在**重畫那一幀的 ax.texts** 裡 ⇒ 它不只是躺在 json 裡"},
    {"kind": "negative", "label":
     "登記 commit 時間早於六支 mp4 的 mtime ⇒ 登記在產製之前"},
    {"kind": "positive", "label":
     "兩臂的副標整批對調 ⇒ 必須被抓到(這正是沒有任何既有閘門覆蓋的那一種)"},
    {"kind": "positive", "label":
     "只把**一支** B 的副標換成 E 的 ⇒ 必須被抓到(整批對調和單支漂移是兩種壞法)"},
    {"kind": "positive", "label":
     "只把**一支**的 facts.json arm 欄翻面 ⇒ 必須被抓到(這一格在測①②兩個來源真的獨立)"},
    {"kind": "negative", "label":
     "反向對照:把 B 臂的副標整批換成**另一組措辭**(仍帶 actually work、"
     "仍與 E 互斥)⇒ **不該**被抓到。它管的是「姿態」,不是「這六個字串」;"
     "少了這一格,「它抓得到對調」和「它對任何改動都叫」分不開"},
]

PREREG_COMMIT = "dacddd8e"
PREREG_PATH = "docs/ch3_recurrence_test_prereg_2026-09-09.md"
ROOT = pathlib.Path(r"D:\carson-agent\ch3_lab")
REPO = pathlib.Path(r"D:\carson-agent")
SIX = ["study_techniques", "how_to_remember_what_you_read", "focus_techniques",
       "if_then_plans", "learning_styles", "pomodoro"]
#: 登記檔 §2 逐字寫死、且是「唯一被操縱的變數」的那個措辭。
PHRASE = "actually work"
ROW_RE = re.compile(r"^\|\s*([BE]\d)\s*\|\s*([BE])\s*\|[^|]*\|\s*`([^`]+)`\s*\|", re.M)
ok = []


def say(good, msg):
    ok.append(bool(good))
    print(f"  {'OK' if good else '**FAIL**'}  {msg}")


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=REPO, check=True,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def prereg_arms():
    """{逐字標題: 臂} —— 讀的是登記 commit 當時的 blob,不是工作區。"""
    blob = git("show", f"{PREREG_COMMIT}:{PREREG_PATH}")
    rows = ROW_RE.findall(blob)
    if not rows:
        raise SystemExit("[X] 登記檔裡找不到臂別表 —— 表格式改過了,"
                         "這支要跟著改,不要改成模糊比對放它過。")
    return {t.strip(): arm for _, arm, t in rows}, blob


def load_E(slug):
    return json.loads((ROOT / "reels" / slug / "facts.json")
                      .read_text(encoding="utf-8"))


def check(arms, facts):
    """回 (通過?, 第一個理由)。facts = {slug: (prereg_title, arm欄, captions)}"""
    got = {}
    for slug, (title, arm_field, caps) in facts.items():
        if title not in arms:
            return False, f"{slug} 的 prereg_title 在登記檔裡找不到:{title!r}"
        got[slug] = arms[title]
    if sorted(got.values()) != ["B"] * 4 + ["E"] * 2:
        return False, f"臂別分佈不是 4B/2E:{sorted(got.values())}"
    for slug, (title, arm_field, caps) in facts.items():
        if arm_field != got[slug]:
            return False, (f"{slug} 的 facts.json arm={arm_field!r} "
                           f"與登記檔的 {got[slug]!r} 不一致")
    groups = {}
    for slug, (title, arm_field, caps) in facts.items():
        groups.setdefault(got[slug], set()).add(tuple(sorted(caps.items())))
    for arm in ("B", "E"):
        if len(groups.get(arm, ())) != 1:
            return False, f"{arm} 臂內部的副標不一致({len(groups.get(arm, ()))} 種)"
    bset, eset = set(list(groups["B"])[0]), set(list(groups["E"])[0])
    if bset & eset:
        return False, "兩臂的副標有交集 ⇒ 自變項沒有被操縱"
    btxt = " ".join(v for _, v in bset).lower()
    etxt = " ".join(v for _, v in eset).lower()
    if PHRASE not in btxt:
        return False, f"B 臂副標不含登記檔寫死的 {PHRASE!r}:{btxt!r}"
    if PHRASE in etxt:
        return False, f"E 臂副標**含** {PHRASE!r} ⇒ 兩臂糊在一起:{etxt!r}"
    for slug, (title, arm_field, caps) in facts.items():
        has = PHRASE in title.lower()
        if (got[slug] == "B") != has:
            return False, (f"{slug} 是 {got[slug]} 臂,而登記標題"
                           f"{'含' if has else '不含'} {PHRASE!r}:{title!r}")
    return True, "標題、arm 欄、副標三者一致"


def drawn_texts(slug, seg):
    """重畫那一段的一幀,把真的被畫上去的字串收回來。"""
    with wave.open(str(ROOT / "reels" / slug / f"seg_{seg}.wav")) as w:
        dur = w.getnframes() / w.getframerate() + SEG_GAP
    E = load_E(slug)
    ctx = {"plt": M._plt(), "E": E, "rows": twist_rows(E)}
    seen, orig = [], matplotlib.axes.Axes.text

    def rec(self, x, y, s_, *a, **k):
        seen.append(str(s_))
        return orig(self, x, y, s_, *a, **k)

    try:
        matplotlib.axes.Axes.text = rec
        M.render_scene(seg, dur * 0.9, dur, ctx)
    finally:
        matplotlib.axes.Axes.text = orig
    return seen


def main():
    arms, blob = prereg_arms()
    print(f"【事前登記】{PREREG_COMMIT}:{PREREG_PATH}"
          f"({len(blob)} bytes,{len(arms)} 支)")
    for t, a in arms.items():
        print(f"    {a}  {t}")

    facts = {}
    for slug in SIX:
        E = load_E(slug)
        facts[slug] = (E.get("prereg_title", ""), E.get("arm"),
                       dict(((E.get("reel") or {}).get("captions") or {})))

    print(chr(10) + "【現況】六支渲染時真正用的那一份 facts.json:")
    for slug in SIX:
        t, a, caps = facts[slug]
        print(f"    {slug:<30} arm={a}  belief 副標={caps.get('belief')!r}")

    print(chr(10) + "【陰性 ①②③】")
    good, why = check(arms, facts)
    say(good, f"登記 <-> facts <-> 副標:{why}")

    print(chr(10) + "【陰性 ④】副標真的被畫上去了嗎 —— 重畫 belief 段的一幀:")
    drawn_ok = True
    for slug in SIX:
        want = facts[slug][2].get("belief")
        seen = drawn_texts(slug, "belief")
        hit = want in seen
        drawn_ok = drawn_ok and hit
        print(f"    {slug:<30} {'OK' if hit else 'FAIL'} {want!r} "
              f"(那一幀共 {len(seen)} 個字串)")
    say(drawn_ok, "六支的 belief 副標都真的出現在重畫的那一幀裡")

    print(chr(10) + "【陰性 ⑤】登記在產製之前:")
    reg_t = int(git("show", "-s", "--format=%ct", PREREG_COMMIT).strip())
    mp4s = {s: (ROOT / "reels" / s / f"{s}_reel.mp4").stat().st_mtime
            for s in SIX}
    first = min(mp4s.values())
    say(reg_t < first,
        f"登記 commit {reg_t} 早於最早的 mp4 {int(first)}"
        f"(差 {(first - reg_t) / 3600:.1f} 小時)")

    print(chr(10) + "【陽性 ⑥】兩臂的副標整批對調:")
    bcap = next(c for _, a, c in facts.values() if a == "B")
    ecap = next(c for _, a, c in facts.values() if a == "E")
    swapped = {s: (t, a, dict(ecap if a == "B" else bcap))
               for s, (t, a, c) in facts.items()}
    g6, w6 = check(arms, swapped)
    print(f"    理由:{w6}")
    say(not g6, "整批對調被抓到")

    print(chr(10) + "【陽性 ⑦】只把一支 B 的副標換成 E 的:")
    one = {s: (t, a, dict(c)) for s, (t, a, c) in facts.items()}
    victim = next(s for s, (_, a, _) in facts.items() if a == "B")
    one[victim] = (one[victim][0], one[victim][1], dict(ecap))
    g7, w7 = check(arms, one)
    print(f"    理由({victim}):{w7}")
    say(not g7, f"單支漂移({victim})被抓到")

    print(chr(10) + "【陽性 ⑧】只把一支的 facts.json arm 欄翻面:")
    flip = {s: (t, a, dict(c)) for s, (t, a, c) in facts.items()}
    flip[victim] = (flip[victim][0], "E", flip[victim][2])
    g8, w8 = check(arms, flip)
    print(f"    理由({victim}):{w8}")
    say(not g8, f"arm 欄翻面({victim})被抓到 ⇒ 登記檔與 facts.json 是兩個獨立來源")

    print(chr(10) + "【陰性 ⑨】反向對照 —— B 臂換一組措辭,姿態不變:")
    # 🔴 **這一格原本寫的是「把六支的順序打亂」,而 check() 本來就是順序無關的
    #    實作 ⇒ 那一格不可能失敗,是恆真句不是對照。**(總督導 2026-09-11 抓到;
    #    memory `verification-that-cannot-fail` 記的正是這一類:一個沒有任何輸入
    #    能讓它翻面的檢查,和一個恆綠的檢查在報告上長得一模一樣。)
    #    換成一個**真的會經過判準**的無關改動:B 臂整批改寫措辭,姿態不動。
    #    它要回答的問題是:這把尺量的是「姿態」,還是「我現在看到的這六個字串」?
    #    —— 後者會讓任何一次合法的文案潤飾變成假警報,而那種尺會被人關掉。
    reworded = {}
    for slug, (t, a, c) in facts.items():
        if a == "B":
            c = {"belief": "here is what actually works, with receipts",
                 "weight": "and here is who ran the numbers",
                 "turn": "how far it actually moves"}
        reworded[slug] = (t, a, dict(c))
    g9, w9 = check(arms, reworded)
    print(f"    新措辭:{reworded[victim][2]}")
    print(f"    理由:{w9}")
    say(g9, "換了措辭但姿態沒變 ⇒ **沒有**被抓到;它量的是姿態不是字串快照")

    print()
    print("結論:" + ("自變項的分派可機械查核,而且對調會被抓到" if all(ok)
                    else "**對照失敗 —— 這格不算數**"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
