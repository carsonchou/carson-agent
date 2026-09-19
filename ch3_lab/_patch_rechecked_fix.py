#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補上閘門擋下來的三件事,以及一個新的段落。

閘門擋下的:
1. `timeline[...].es_kind` 缺 —— facial_feedback 2019 那列與 moral_licensing
   2001 那列有數字卻沒有單位。時間軸上 d / β / 百分點畫在一起,標錯一個
   整條線就是誤導,所以 make_rechecked 對這個 fail-closed。
2. hungry_judges 的 65 只活在 `claim` 這個自由文字欄位裡,而自由文字不供給
   白名單 —— 升格成結構化欄位。
3. terror_management / marshmallow 的 `0.08`、`0.24` 被切成 `0` 與 `08`
   兩個 token。那是**掃描端的正則**不吃小數點,不是白名單的問題;修在
   make_rechecked 那邊(見該檔),這裡不動。

新增的:引用數。從 OpenAlex 用 DOI 查到的真值,無條件捨去到百位當文案值
—— 引用數在 Google Scholar / Crossref / Scopus 之間差很多,是全片唯一一個
觀眾自己去查會得到不同答案的數字,所以講「超過 N」不講精確值,而捨去
保證那個 N 是下界。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))
E = {e["slug"]: e for e in d["episodes"]}

CITED = {
    "hot_hand": 1700, "hungry_judges": 1426, "facial_feedback": 1810,
    "moral_licensing": 1009, "terror_management": 884,
    "backfire_effect": 3218, "false_memory": 1123, "marshmallow_test": 1222,
}
for slug, n in CITED.items():
    o = E[slug]["original"]
    o["cited_by"] = n
    o["cited_by_source"] = "OpenAlex, retrieved 2026-08-31"
    o["cited_by_approx"] = n // 100 * 100
    o["cited_by_approx_note"] = (
        "文案用的「超過 N 次」。無條件捨去到百位,所以它一定是保守的下界。"
        "明確登記在此,否則稿子審核會擋(它只認事實庫裡有的數字)。")

# 1) timeline 的單位
for t in E["facial_feedback"]["timeline"]:
    t["es_kind"] = {
        1988: "raw_diff_10pt_likert",
        2016: "raw_diff_10pt_likert",
        2019: "d",
        2022: "raw_diff_7pt_scale",
    }[t["year"]]
E["facial_feedback"]["timeline"][3]["es_note"] = (
    "2022 的 0.31 是 7 點量表上的平均差(原文並列 5.17% scale range),"
    "跟 1988/2016 的 10 點量表原始差**不是同一把尺** —— 畫面上兩者各自"
    "帶單位,不共用刻度。")
for t in E["moral_licensing"]["timeline"]:
    t["es_kind"] = {2001: "d", 2014: None, 2016: None,
                    2019: "d", 2024: "d"}[t["year"]]
E["moral_licensing"]["timeline"][0]["es_note"] = (
    "0.44 是 Xiao 2024 從原文重算的,Monin & Miller 2001 原文沒報 d。")

# 2) hungry_judges 的 65 升格
E["hungry_judges"]["original"]["key_numbers"] = {
    "approx_favorable_pct": 65,
    "judges": 8,
    "days": 50,
    "_note_for_humans": "原文三處都帶 ~。畫面寫 65% 可以,不准寫 65.0%。",
}

# 3) 新段落用的欄位:這個宣稱後來去了哪裡
SPREAD = {
    "hot_hand": "It became the standard example of how badly people read "
                "randomness — quoted in behavioural economics, in statistics "
                "courses, in every book about cognitive bias.",
    "hungry_judges": "It became the single most quoted result about how "
                     "little of a decision is the decision.",
    "facial_feedback": "It became the textbook demonstration that the body "
                       "feeds back into the mind.",
    "moral_licensing": "It became the standard explanation for why people who "
                       "have just done something good then do something bad.",
    "terror_management": "It became the foundation of a whole research "
                         "programme about what the fear of death does to "
                         "politics, prejudice and belief.",
    "backfire_effect": "It became the reason people say facts do not work.",
    "false_memory": "It became the study that expert witnesses cite when they "
                    "testify that a memory of abuse might have been "
                    "manufactured.",
    "marshmallow_test": "It became the story that a four year old's self "
                        "control predicts the rest of their life — a book, a "
                        "TED talk, and a great deal of parenting advice.",
}
for slug, s in SPREAD.items():
    E[slug]["say_spread"] = s

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote " + P.name)
