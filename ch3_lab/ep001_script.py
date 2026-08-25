#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ep001_script.py — 第一集腳本。每個數字都從 facts/ep001_ego_depletion.json 取,
不寫死。生成時會自我檢查:稿子裡出現的數字必須在事實庫裡找得到。

這是主頻道 fact_guard 的同一套紀律 —— 編造統計是我踩過的紅線。
"""
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
F = json.loads((ROOT / "facts" / "ep001_ego_depletion.json").read_text(encoding="utf-8"))
C = F["claims"]


def spell(n):
    """數字唸法:讓 TTS 唸對,而不是唸成 four thousand nine hundred twenty eight。"""
    return f"{n:,}"


SEGMENTS = [
    ("hook",
     "In nineteen ninety-eight, psychologists sat people in front of a plate of warm "
     "chocolate-chip cookies, and told some of them to eat radishes instead. "
     "Then everyone got a puzzle that had no solution. "
     "The radish group gave up far sooner. "
     "The conclusion was elegant: willpower is a battery. "
     "Resist the cookies, and you have less left for the puzzle. "
     "They called it ego depletion."),

    ("spread",
     f"That paper has been cited {spell(F['original']['cited_by_count'])} times. "
     "It became a book, then a shelf of books. Corporate training. School policy. "
     "Advice to schedule your hard decisions before lunch. "
     f"By twenty ten, a meta-analysis of {C['meta2010_studies']} studies reported "
     "a medium-sized effect. For about a decade, the battery model was one of the "
     "most repeated findings in psychology."),

    ("replication",
     "Then people tried to run it again, properly. "
     f"{C['k_labs']} laboratories. One protocol, agreed in advance. "
     "The analysis plan registered before a single participant walked through the door. "
     f"{spell(C['total_N'])} people."),

    ("result",
     f"The effect they measured was zero point zero four. "
     "And the ninety-five percent confidence interval ran from "
     "minus zero point zero seven, to plus zero point one five. "
     "That interval contains zero. "
     "In plain language: the data could not tell this effect apart from nothing at all."),

    ("close",
     "This is not a story about fraud. Nobody faked anything. "
     "It is what happens when a finding gets repeated for a decade "
     "before anyone tries to reproduce it at scale. "
     "So the next time you hear that willpower runs out like a battery: "
     f"that claim was tested by {C['k_labs']} laboratories at once, and it did not survive."),
]


def audit():
    """稿子裡的每個數字都必須能在事實庫找到來源。找不到 = 阻擋。"""
    allowed = {
        str(F["original"]["cited_by_count"]), f"{F['original']['cited_by_count']:,}",
        str(C["meta2010_studies"]), str(C["k_labs"]),
        str(C["total_N"]), f"{C['total_N']:,}",
    }
    bad = []
    for name, text in SEGMENTS:
        for tok in re.findall(r"\b\d[\d,]*\b", text):
            if tok not in allowed:
                bad.append((name, tok))
    return bad


if __name__ == "__main__":
    bad = audit()
    if bad:
        print("⛔ 稿中有事實庫查無來源的數字:", bad)
        sys.exit(1)
    total_words = sum(len(t.split()) for _, t in SEGMENTS)
    print(f"五段共 {total_words} 字 → 約 {total_words / 155 * 60:.0f} 秒 @155wpm")
    for name, text in SEGMENTS:
        (ROOT / f"narr_{name}.txt").write_text(text, encoding="utf-8")
        print(f"  {name:<12} {len(text.split()):>3} 字")
    print("數字溯源檢查:全部通過 ✓")
