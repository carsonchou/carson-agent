#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""twist_rows:`twist` 那一段畫面上要出現的列。

為什麼需要它 —— 抽幀看出來的:hot hand 那集 twist 有 50 秒,而畫面停在
只有兩列的年份表。**旁白在講「隨機球員應該是 -8」,畫面卻停在別的東西。**
每一列的數字都必須已經是結構化欄位(key_numbers / outcomes),這裡只是
指定它們的顯示順序與說法。

順便補 hot_hand 的顯式 timeline:它原本從 original + test 推,而
original 沒有 es 欄位(+4 與 +3 的口徑差異登記在 internal_inconsistency),
於是時間軸第一列是空的 —— 一張說「what happened to the number」卻沒有
數字的畫面。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))
E = {e["slug"]: e for e in d["episodes"]}

E["hot_hand"]["timeline"] = [
    {"year": 1985, "what": "what the players actually did",
     "es": 4, "es_kind": "percentage_points",
     "es_note": "GVT 自報的 .49/.45 相減。Table II 用逐球員資料重算是 +3;"
                "兩個都是原句,見 internal_inconsistency。"},
    {"year": 1985, "what": "read as: no better than random", "es": None},
    {"year": 2018, "what": "what random actually looks like here",
     "es": -8, "es_kind": "percentage_points"},
    {"year": 2018, "what": "the same data, bias removed",
     "es": 13, "es_kind": "percentage_points"},
]
E["hot_hand"]["twist_rows"] = [
    {"label": "a random shooter", "what": "scores on this measure",
     "es": -8, "es_kind": "percentage_points"},
    {"label": "the players", "what": "scored", "es": 4,
     "es_kind": "percentage_points"},
    {"label": "so the gap", "what": "above random was",
     "es": 12, "es_kind": "percentage_points"},
    {"label": "corrected", "what": "average difference", "es": 13,
     "es_kind": "percentage_points", "hot": True},
]

E["facial_feedback"]["twist_rows"] = [
    {"label": "2016", "what": "pen in the teeth, 17 labs", "es": 0.03,
     "es_kind": "raw_diff_10pt_likert"},
    {"label": "2022", "what": "copying a smiling face", "es": 0.49,
     "es_kind": "raw_diff_7pt_scale"},
    {"label": "2022", "what": "making the expression yourself", "es": 0.4,
     "es_kind": "raw_diff_7pt_scale"},
    {"label": "2022", "what": "pen in the teeth, again", "es": 0.04,
     "es_kind": "raw_diff_7pt_scale", "hot": True},
]

E["moral_licensing"]["twist_rows"] = [
    {"label": "published", "what": "studies", "es": 0.43, "es_kind": "d"},
    {"label": "unpublished", "what": "studies, same effect", "es": 0.11,
     "es_kind": "d"},
    {"label": "2016", "what": "3,134 people", "es": None},
    {"label": "2019", "what": "corrected for that bias", "es": -0.05,
     "es_kind": "d"},
    {"label": "2024", "what": "registered replication, 932 people",
     "es": -0.38, "es_kind": "d", "hot": True},
]

E["terror_management"]["twist_rows"] = [
    {"label": "1994", "what": "the original effect", "es": 1.34,
     "es_kind": "d"},
    {"label": "in house", "what": "10 labs, 851 people", "es": None},
    {"label": "author advised", "what": "7 labs, 699 people", "es": 0.08,
     "es_kind": "g", "hot": True},
    {"label": "difference", "what": "between the two", "es": 0.01,
     "es_kind": "meta-regression b"},
]

E["false_memory"]["twist_rows"] = [
    {"label": "as coded", "what": "43 of 123 participants", "es": 35,
     "es_kind": "pct"},
    {"label": "minus 22", "what": "whose childhood could fit the story",
     "es": 17, "es_kind": "pct"},
    {"label": "minus 7", "what": "with no recall of being lost", "es": 11,
     "es_kind": "pct"},
    {"label": "minus 9", "what": "who did not say they remembered it",
     "es": 4, "es_kind": "pct", "hot": True},
]

E["marshmallow_test"]["twist_rows"] = [
    {"label": "on its own", "what": "waiting predicts achievement at 15",
     "es": 0.24, "es_kind": "beta"},
    {"label": "minus", "what": "family background and early ability",
     "es": 0.08, "es_kind": "beta"},
    {"label": "minus", "what": "everything measured at the same time",
     "es": 0.05, "es_kind": "beta", "hot": True},
]

E["hungry_judges"]["twist_rows"] = [
    {"label": "with a lawyer", "what": "prisoners succeeded", "es": 35,
     "es_kind": "pct"},
    {"label": "without one", "what": "prisoners succeeded", "es": 15,
     "es_kind": "pct"},
    {"label": "and they go", "what": "last in the session", "es": None,
     "hot": True},
]

E["backfire_effect"]["twist_rows"] = [
    {"label": "in the paper", "what": "experiments", "es": 5,
     "es_kind": "count"},
    {"label": "showing", "what": "backfire", "es": 2, "es_kind": "count",
     "hot": True},
    {"label": "2019", "what": "issues retested on 10,100 people", "es": 52,
     "es_kind": "count"},
    {"label": "showing", "what": "backfire", "es": 0, "es_kind": "count"},
]

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote " + P.name)
