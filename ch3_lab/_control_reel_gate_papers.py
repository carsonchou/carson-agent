#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`publish_shorts.reel_gate()` 的 papers 分支對照 —— 說明欄裡的 DOI。

🔴 **這條線唯一的資產是「查得到」。** 片子講的每一篇論文,DOI 都要在說明欄裡。
   判準本身很簡單,難的是**證明它真的會擋** —— 一道沒有陽性對照的閘門,
   和沒有閘門的差別只能靠相信(memory `verification-that-cannot-fail`)。

⚠️ **陽性對照用真的批次**:從 build_meta() 拿六支真的 entry,
   **故意從說明欄刪掉一個真 DOI**,看它會不會被擋。不是合成 fixture。

⚠️ papers 分支對「方法片」是**更嚴**不是放寬:要求**每一篇**都在說明欄裡
   而且至少三篇(裁決片是原始 + 重測兩篇)。所以三個壞法都要各自證一次:
   少於三篇、有一篇沒有 doi 欄位、有一篇的 DOI 不在說明欄。
"""
import copy
import pathlib
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import publish_shorts as P                               # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
CASES = [
    {"kind": "negative",
     "label": "六支真的 entry,說明欄沒動 ⇒ papers 分支不准擋"},
    {"kind": "positive",
     "label": "從真的說明欄裡**刪掉一個真 DOI**(其它一個字不動)"
              "⇒ 必須擋,而且理由要點名**那一個** DOI"},
    {"kind": "positive",
     "label": "把某一篇的 `doi` 欄位拿掉 ⇒ 必須擋(理由是「沒有 DOI」)"},
    {"kind": "positive",
     "label": "把 papers 砍到 2 篇 ⇒ 必須擋(理由是「少於 3 篇」)"},
]

SIX = ["study_techniques", "how_to_remember_what_you_read", "focus_techniques",
       "if_then_plans", "learning_styles", "pomodoro"]
ROOT = P.ROOT
ok = []


def say(good, msg):
    ok.append(good)
    print(f"  {'✓' if good else '🔴'} {msg}")


def reels_batch():
    batch = P.build_meta()
    return [o for o in batch
            if o["key"].startswith("reel_") and o["key"][5:] in SIX]


def block_reasons(batch):
    return dict(P.reel_gate(batch))


def main():
    batch = reels_batch()
    print(f"母體:{len(batch)} 支真的 reel entry")
    if len(batch) < len(SIX):
        got = sorted(o["key"][5:] for o in batch)
        print(f"🔴 只拿到 {got} —— 六支還沒渲完,這支不能跑")
        return 1

    print("\n【陰性 ①】說明欄沒動:")
    base = block_reasons(batch)
    doi_block = {k: v for k, v in base.items() if "DOI" in v or "papers" in v}
    print(f"    被擋的:{base or '無'}")
    say(not doi_block, f"papers 分支擋下的:{doi_block or '無'}")

    import json
    facts = ROOT / "facts" / "rechecked_episodes.json"

    print("\n【陽性 ②】從說明欄刪掉一個真 DOI:")
    hits = []
    for o in batch:
        slug = o["key"][5:]
        E = json.loads((ROOT / "reels" / slug / "facts.json")
                       .read_text(encoding="utf-8"))
        papers = E.get("papers") or []
        dois = [x.get("doi") for x in papers if isinstance(x, dict) and x.get("doi")]
        if not dois:
            continue
        victim = dois[0]
        bad = copy.deepcopy(o)
        bad["description"] = bad["description"].replace(victim, "")
        why = dict(P.reel_gate([bad])).get(bad["key"], "")
        hits.append((slug, victim, bool(why) and victim in why, why[:70]))
    for slug, victim, good, why in hits:
        print(f"    {'✓' if good else '🔴'} {slug}:刪掉 {victim} → {why or '沒擋'}")
    say(bool(hits) and all(h[2] for h in hits),
        f"{len(hits)} 支全部被擋,而且理由點名了被刪掉的那一個 DOI")

    print("\n【陽性 ③④】papers 欄位本身壞掉(改 facts.json 的複本):")
    slug = SIX[0]
    fp = ROOT / "reels" / slug / "facts.json"
    orig = fp.read_text(encoding="utf-8")
    o = next(x for x in batch if x["key"] == f"reel_{slug}")
    try:
        E = json.loads(orig)
        E2 = copy.deepcopy(E)
        E2["papers"][0].pop("doi", None)
        fp.write_text(json.dumps(E2, ensure_ascii=False), encoding="utf-8")
        why3 = dict(P.reel_gate([copy.deepcopy(o)])).get(o["key"], "")
        print(f"    拿掉第 0 篇的 doi 欄位 → {why3 or '沒擋'}")
        say("沒有 DOI" in why3, "「有一篇沒有 doi 欄位」會被擋")

        E3 = copy.deepcopy(E)
        E3["papers"] = E3["papers"][:2]
        fp.write_text(json.dumps(E3, ensure_ascii=False), encoding="utf-8")
        why4 = dict(P.reel_gate([copy.deepcopy(o)])).get(o["key"], "")
        print(f"    砍到 2 篇 → {why4 or '沒擋'}")
        say("少於 3 篇" in why4, "「少於三篇」會被擋")
    finally:
        fp.write_text(orig, encoding="utf-8")     # 一定要還原
        assert fp.read_text(encoding="utf-8") == orig, "facts.json 沒還原!"
    print(f"    ✓ {slug}/facts.json 已逐字還原")

    print()
    print("結論:", "✓ 現況不誤擋,而三種「查不到」全部擋得住" if all(ok)
          else "🔴 對照失敗 —— 這道閘門不算數")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
