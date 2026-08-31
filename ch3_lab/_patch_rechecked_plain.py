#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八集的白話句(縮圖 + Short 開場共用)與 popular_name。

`plain._valid` 的硬規則,寫在這裡免得下次又忘:
  · `lines` 剛好兩行(make_thumbs 只畫 [0][1],第三行會被靜默吃掉)
  · `spoken` 必須以問號結尾
  · **任何一處都不准有數字** —— 數字一律由事實庫填,手寫句裡出現數字
    就是有人繞過了溯源守門
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
PC = ROOT / "facts" / "plain_claims.json"
RE = ROOT / "facts" / "rechecked_episodes.json"

PLAIN = {
    "hot_hand": {
        "lines": ["DOES A BASKETBALL PLAYER", "EVER GET A HOT HAND?"],
        "spoken": "Does a basketball player ever really get a hot hand?"},
    "hungry_judges": {
        "lines": ["DOES A JUDGE GO EASIER", "RIGHT AFTER LUNCH?"],
        "spoken": "Does a judge go easier on you right after lunch?"},
    "facial_feedback": {
        "lines": ["DOES HOLDING A PEN", "IN YOUR TEETH CHEER YOU UP?"],
        "spoken": "Does holding a pen in your teeth actually cheer you up?"},
    "moral_licensing": {
        "lines": ["DOES DOING ONE GOOD THING", "LET YOU DO A BAD ONE?"],
        "spoken": "Does doing one good thing give you permission to do a bad one?"},
    "terror_management": {
        "lines": ["DOES THINKING ABOUT DEATH", "HARDEN YOUR BELIEFS?"],
        "spoken": "Does thinking about your own death harden your beliefs?"},
    "backfire_effect": {
        "lines": ["DOES CORRECTING SOMEONE", "MAKE THEM BELIEVE IT MORE?"],
        "spoken": "Does correcting someone make them believe the wrong thing more?"},
    "false_memory": {
        "lines": ["CAN SOMEONE PLANT", "A CHILDHOOD MEMORY IN YOU?"],
        "spoken": "Can someone plant a childhood memory in you that never happened?"},
    "marshmallow_test": {
        "lines": ["DOES WAITING FOR A SWEET", "AT FOUR PREDICT YOUR LIFE?"],
        "spoken": "Does waiting for a sweet at age four predict how your life goes?"},
}

#: 標題的第一個詞 —— **搜尋詞本身**。零訂閱的頻道只有搜尋這一個入口,
#: 而 08-30 實測 14 支 16:9 長片總共 3 次觀看,標題全是沒人會打的學術句子。
POPULAR = {
    "hot_hand": "The hot hand fallacy",
    "hungry_judges": "The hungry judge effect",
    "facial_feedback": "The facial feedback hypothesis",
    "moral_licensing": "Moral licensing",
    "terror_management": "Terror management theory",
    "backfire_effect": "The backfire effect",
    "false_memory": "The lost in the mall study",
    "marshmallow_test": "The marshmallow test",
}

d = json.loads(PC.read_text(encoding="utf-8"))
for slug, v in PLAIN.items():
    d[f"eps_rechecked/{slug}"] = v
    d[slug] = v                       # slug 那種寫法也要查得到
PC.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

r = json.loads(RE.read_text(encoding="utf-8"))
for e in r["episodes"]:
    e["popular_name"] = POPULAR[e["slug"]]
RE.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

# 寫完立刻用**產線真正會走的那條路**驗一次,不是自己再寫一份檢查。
import sys
sys.path.insert(0, str(ROOT))
import plain                                                # noqa: E402
bad = [s for s in PLAIN if not plain.spoken(f"eps_rechecked/{s}")]
print("FAILED " + str(bad) if bad else "all 8 pass plain._valid")
