#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""說明欄的對照 —— 「頁尾那句話對觀眾是不是真的」。

🔴 **這條之所以存在,是因為 2026-09-11 的獨立驗證抓到它為假。**
   說明欄結尾寫「The papers are linked above.」,而上面印的是裸 `doi:10.xxxx`;
   YouTube 只 linkify `http(s)://` ⇒ 觀眾看到一串點不動的字。
   這不是排版問題:**這條線唯一的資產就是「你查得到」,而那句話正好在那個資產
   上撒謊**,和主頻道 84 支描述欄那句假聲明是同一類東西。

🔴 判準釘在「當時」的問題:那次驗證的 (a)(b) 兩節驗的是**舊字串**,而我改的是
   字串產生器 ⇒ **它的結論在我按下修改的那一刻就過期了**。所以這支不是「再確認
   一次」,是把那兩節重新跑在新產物上,而且洩漏樣式的新命中要重新開原文判讀,
   不准沿用上一次的「9 處全是誤報」。

⚠️ 這支**不打網路**:它走 `cites_for()` / `miss_block()` / `desc_for()` 三個
   真的產生器,不走 `build_meta()`(那裡面的 `public_only()` 會打 videos.list)。
   換句話說它證的是「字串長什麼樣」,證不了上傳時送的是這一份 ——
   那一段由 `build_meta()` 只呼叫這三個函式來保證,而這句話是**讀碼**得到的。
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import publish_shorts as P                                # noqa: E402

ROOT = pathlib.Path(r"D:\carson-agent\ch3_lab")
OUT = ROOT / "docs_out"
SIX = ["study_techniques", "how_to_remember_what_you_read", "focus_techniques",
       "if_then_plans", "learning_styles", "pomodoro"]
NL = chr(10)
ok = []

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative", "label":
     "六支說明欄裡每一列引用都帶 https:// ⇒ 頁尾那句「linked above」為真"},
    {"kind": "negative", "label":
     "印出的 DOI 集合 == facts.json 裡遞迴找到的 DOI 集合(一個不漏、一個不多)"},
    {"kind": "negative", "label":
     "沒有 `https://doi.org/https://` 這種雙前綴(三種寫法混在資料裡)"},
    {"kind": "negative", "label":
     "七條洩漏樣式的新命中,逐一開原文判讀過(不沿用上一次的判讀)"},
    {"kind": "positive", "label":
     "把一列引用換成不帶連結的來源 ⇒ 頁尾那句話**必須**跟著改口,不准照樣說 linked"},
    {"kind": "positive", "label":
     "餵一個裸 doi / doi: / 完整網址三種寫法 ⇒ `_doi_url()` 都要吐出同一個規範網址"},
    {"kind": "negative", "label":
     "反向對照:cites 全帶連結時,頁尾**就是**要說 linked ⇒ 它不是恆定改口"},
]

# 獨立驗證第 4 題用的那七條(逐字沿用,好讓兩次的命中可以並排比)
PATTERNS = [
    ("CJK", re.compile(r"[\u4e00-\u9fff]")),
    ("【】", re.compile(r"[【】]")),
    ("指令口吻", re.compile(r"(?i)\b(you are a|your task|as an ai|respond with|"
                            r"output only|do not include)\b")),
    ("未填模板洞", re.compile(r"(\{\w*\}|<[a-z_]+>|\[\[.*?\]\])")),
    ("空值字面", re.compile(r"(?i)\b(none|nan|undefined|todo|n/a|null)\b")),
    ("markdown", re.compile(r"(\*\*|^#{1,6}\s|\[.+?\]\(.+?\))", re.M)),
    ("異常空白", re.compile(r"( {2,}|\t|" + NL + r"{3,})")),
]


def say(good, msg):
    ok.append(bool(good))
    print(f"  {'OK' if good else '**FAIL**'}  {msg}")


def load_E(slug):
    return json.loads((ROOT / "reels" / slug / "facts.json")
                      .read_text(encoding="utf-8"))


def all_dois(o, acc=None):
    """遞迴撈出 facts.json 裡每一個 doi 欄位 —— **不是只走頂層**。
    (`cites_for()` 早期只走頂層 dict,漏掉 timeline[2] 裡那篇。)"""
    acc = set() if acc is None else acc
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "doi" and isinstance(v, str) and v.strip():
                acc.add(P._doi_url(v))
            else:
                all_dois(v, acc)
    elif isinstance(o, list):
        for x in o:
            all_dois(x, acc)
    return acc


def build(slug):
    """走真的那三個產生器 —— 不抄一份來測。"""
    E = load_E(slug)
    r = E.get("reel") or {}
    cites = P.cites_for(E, NL)
    return E, cites, P.desc_for(r, cites, P.miss_block(E, slug, NL), NL)


def main():
    OUT.mkdir(exist_ok=True)
    built = {s: build(s) for s in SIX}

    # ── 落檔:六支說明欄逐字 ───────────────────────────────────
    dump = OUT / "2026-09-11_ch3六支說明欄_修DOI連結後.txt"
    parts = []
    for s in SIX:
        E, cites, desc = built[s]
        parts.append("=" * 72 + NL + f"{s}   ({len(desc)} chars)" + NL
                     + f"title: {P.reel_title(E, s)}" + NL + "=" * 72 + NL
                     + desc + NL)
    dump.write_text(NL.join(parts), encoding="utf-8")
    print(f"【落檔】{dump}({dump.stat().st_size} bytes)")

    print(NL + "【① 每一列引用都點得動嗎】")
    all_linked = True
    for s in SIX:
        E, cites, desc = built[s]
        bad = [c for c in cites if "https://" not in c]
        all_linked = all_linked and not bad
        claims = "linked above" in desc
        print(f"    {s:<30} {len(cites)} 列,無連結 {len(bad)} 列,"
              f"頁尾說 linked={claims}")
        if bad:
            for b in bad:
                print(f"        缺連結:{b!r}")
    say(all_linked, "六支的每一列引用都帶 https:// ⇒ 頁尾那句為真")

    print(NL + "【② DOI 一個不漏、一個不多】")
    dset_ok = True
    for s in SIX:
        E, cites, desc = built[s]
        want = all_dois(E)
        got = set(re.findall(r"https://doi\.org/\S+", desc))
        miss, extra = want - got, got - want
        dset_ok = dset_ok and not miss and not extra
        print(f"    {s:<30} facts {len(want)} / 說明欄 {len(got)} / "
              f"漏 {len(miss)} / 多 {len(extra)}")
        for m in miss:
            print(f"        漏:{m}")
        for e in extra:
            print(f"        多:{e}")
    say(dset_ok, "六支的 DOI 集合完全相等")

    print(NL + "【③ 沒有雙前綴】")
    dbl = [(s, c) for s in SIX for c in built[s][1]
           if "doi.org/https" in c or c.count("doi.org") > 1]
    for s, c in dbl:
        print(f"    {s}: {c!r}")
    say(not dbl, "沒有 https://doi.org/https://... 這種疊出來的網址")

    print(NL + "【④ 七條洩漏樣式 —— 在新產物上重跑】")
    hits = []
    for s in SIX:
        desc = built[s][2]
        for name, rx in PATTERNS:
            for m in rx.finditer(desc):
                a, b = max(0, m.start() - 45), min(len(desc), m.end() + 45)
                hits.append((s, name, m.group(0),
                             desc[a:b].replace(NL, "\n")))
    print(f"    命中 {len(hits)} 處 —— 逐一開原文判讀(不沿用上一次):")
    for s, name, g, ctx in hits:
        print(f"    - [{name}] {s}: {g!r}")
        print(f"        …{ctx}…")
    say(True, f"{len(hits)} 處命中已全部印出上下文,判讀寫在報告裡"
              f"(⚠️ 這是**樣式清單**:沒命中 = 「我列的這 7 種不在」,不等於乾淨)")

    print(NL + "【陽性 ⑤】把一列引用換成不帶連結的來源:")
    E5, c5, _ = built["study_techniques"]
    r5 = E5.get("reel") or {}
    d5 = P.desc_for(r5, c5[:-1] + ["Also: an EEF evaluation report"], "", NL)
    tail5 = d5.rsplit(NL, 2)[-2]
    print(f"    頁尾:{tail5!r}")
    # 🔴 判準不是「有沒有出現 linked above 這四個字」—— 改口後的句子
    #    「The papers **with a DOI** are linked above; the rest are named in
    #    full」正好含著它。要比的是**那句無條件的宣稱**有沒有被說出口。
    UNCOND = ("The papers are linked above.", "Both papers are linked above.")
    say(not any(u in d5 for u in UNCOND) and "named in full" in d5,
        "頁尾跟著改口:無條件那句沒被說出口,而且點名了哪些點不動")

    print(NL + "【陽性 ⑥】三種 DOI 寫法要正規化成同一個:")
    forms = ["10.3390/bs15070861", "doi:10.3390/bs15070861",
             "https://doi.org/10.3390/bs15070861",
             "http://dx.doi.org/10.3390/bs15070861"]
    outs = {P._doi_url(f) for f in forms}
    for f in forms:
        print(f"    {f:<42} -> {P._doi_url(f)}")
    say(outs == {"https://doi.org/10.3390/bs15070861"},
        f"四種寫法收斂成一個({len(outs)} 種輸出)")

    print(NL + "【陰性 ⑦】反向對照 —— 全帶連結時頁尾就是要說 linked:")
    d7 = P.desc_for(r5, c5, "", NL)
    print(f"    頁尾:{d7.rsplit(NL, 2)[-2]!r}")
    say("linked above" in d7,
        "它不是恆定改口 ⇒ ⑤ 抓到的是真的差別,不是一支永遠說 named in full 的尺")

    print()
    print("結論:" + ("說明欄頁尾那句話現在對觀眾為真,且 DOI 一個不漏一個不多"
                    if all(ok) else "**對照失敗 —— 不要發**"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
