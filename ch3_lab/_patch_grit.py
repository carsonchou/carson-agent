#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第九題:grit(恆毅力)。

## 為什麼這題排進來
它符合新的選題標準:**觀眾本來就有立場**。有書、有 TED 演講、有學校課程,
而「消費主義線索會不會改變你對別人的期待」沒有人有立場。

## 這一集的故事類型
不是「重測失敗」——Credé 等人**沒有**說 grit 不存在。是
**「效果是真的但小很多,而且它不是一個新東西」**:grit 與盡責性的相關
rho = .84,**比兩份不同的盡責性量表彼此的相關(.63)還高**。

而且最狠的一點是:**不是後人才發現重疊,原始論文自己就寫著 r = .77。**

## 版本陷阱(fact agent 踩到並處理了)
Credé 的 PDF 頁首印 2016,Crossref 註冊的是 2017, 113(3), 492-511,
**同一個 DOI**。以 Crossref 為準。

## r_obs 與 rho 的差別(畫面上只印一個數字時要說清楚)
Table 4 那一列:Conscientiousness 22 / 18,826 / r_obs .66 / rho .84。
.66 是未校正的觀察值,.84 是校正測量誤差後的 true-score 相關。
片中印 .84 就要講「校正測量誤差後」。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))

EP = {
    "slug": "grit",
    "popular_name": "Grit",
    "story_type": "效果是真的但小很多,而且不是一個新東西",
    "story_type_short": "a new name for an old thing",
    "story_type_note": "Credé 等人沒有說 grit 不存在,也沒有說效果是零。"
                       "他們的結論是「效果小」+「與既有構念重疊」+"
                       "「perseverance 這個 facet 仍有增量價值」。"
                       "講成『grit 被推翻了』是過度宣稱。",
    "claim": "grit — passion and perseverance for long-term goals — "
             "predicts success better than talent does",
    "hook": "Grit correlates with plain conscientiousness more tightly than "
            "conscientiousness correlates with itself.",
    "original": {
        "year": 2007,
        "title": "Grit: Perseverance and passion for long-term goals",
        "journal": "Journal of Personality and Social Psychology 92(6):1087-1101",
        "doi": "10.1037/0022-3514.92.6.1087",
        "n": 138, "n_word": "Ivy League undergraduates",
        "es": 0.25, "es_kind": "r",
        "cited_by": 6911,
        "cited_by_source": "OpenAlex, retrieved 2026-08-31",
        "cited_by_approx": 6900,
        "quote": "Gritty students outperformed their less gritty peers: Grit "
                 "scores were associated with higher GPAs (r = .25, p < .01), "
                 "a relationship that was even stronger when SAT scores were "
                 "held constant (r = .34, p < .001).",
        "quote_location": "Study 2 內文",
        "variance_quote": "grit accounted for an average of 4% of the variance "
                          "in success outcomes",
        "key_numbers": {
            "variance_pct": 4,
            "own_conscientiousness_r": 0.77,
            "_note_for_humans": "🔴 .77 是**原始論文 Study 1b 自己報的**:"
                                "「As we expected, grit related to "
                                "Conscientiousness (r = .77, p < .001)」——"
                                "不是後人才發現重疊。這是本集最重要的一點。",
        },
        "n_sum_warning": "六個樣本合計 N = 5,074 是 fact agent 自己加的,"
                         "**論文沒有印這個合計數**,不准當原文引用。",
    },
    "test": {
        "year": 2017,
        "kind": "meta-analysis",
        "same_sample": False,
        "title": "Much ado about grit: A meta-analytic synthesis of the grit "
                 "literature",
        "journal": "Journal of Personality and Social Psychology 113(3):492-511",
        "doi": "10.1037/pspp0000102",
        "year_warning": "PDF 頁首印 2016(APA online-first),Crossref 註冊的是"
                        "2017 —— 同一個 DOI。以 Crossref 為準。",
        "n": 66807, "k": 88, "k_word": "independent samples",
        "es": 0.18, "es_kind": "r",
        "n_quote": "Our results based on 584 effect sizes from 88 independent "
                   "samples representing 66,807 individuals indicate that the "
                   "higher order structure of grit is not confirmed, that grit "
                   "is only moderately correlated with performance and "
                   "retention, and that grit is very strongly correlated with "
                   "conscientiousness.",
        "key_numbers": {
            "two_conscientiousness_scales_r": 0.63,
            "observed_conscientiousness_r": 0.66,
            "perseverance_academic_r": 0.26,
            "consistency_academic_r": 0.10,
            "_note_for_humans": ".66 是未校正的觀察值,.84 是校正測量誤差後的"
                                "true-score 相關。畫面印 .84 就要說明是校正後。",
        },
        "outcomes": [
            {"name": "grit and academic performance", "es": 0.18,
             "es_kind": "r", "p": None,
             "stat": "rho = .18, k = 39, N = 13,141, SDrho = .11",
             "is_claim": True,
             "quote": "Overall grit exhibits a relation with overall academic "
                      "performance of rho = .18 (k = 39, N = 13,141, "
                      "SDrho = .11) and rho = .17 with the overall GPA "
                      "criterion (k = 37, N = 12,601, SDrho = .10)."},
            {"name": "grit and conscientiousness", "es": 0.84, "es_kind": "r",
             "p": None,
             "stat": "rho = .84, k = 22, N = 18,826, SDrho = .07",
             "is_claim": True,
             "quote": "Conscientiousness was very strongly correlated with "
                      "overall grit (k = 22, N = 18,826, rho = .84, "
                      "SDrho = .07) and also with perseverance (k = 8, "
                      "N = 4,967, rho = .83, SDrho = .14) and consistency "
                      "(k = 8, N = 4,967, rho = .61, SDrho = .17)."},
            {"name": "grit and cognitive ability", "es": 0.05, "es_kind": "r",
             "p": None,
             "stat": "rho = .05, k = 21, N = 11,513, SDrho = .12",
             "is_claim": False,
             "quote": "Consistent with the claim that grit and cognitive "
                      "ability are largely orthogonal, grit exhibited only a "
                      "very weak relation with cognitive ability (k = 21, "
                      "N = 11,513, rho = .05, SDrho = .12)."},
        ],
        "killer_quote": "Indeed, the correlation between overall grit and "
                        "conscientiousness, and between persistence and "
                        "conscientiousness (rho = .89) is much stronger than "
                        "what is typically found between scores on two "
                        "different global measures of conscientiousness "
                        "(rho = .63; Pace & Brannick, 2010).",
        "verdict_quote": "Grit as a predictor of performance and success and "
                         "as a focus of interventions holds much intuitive "
                         "appeal, but grit as it is currently measured does "
                         "not appear to be particularly predictive of success "
                         "and performance and also does not appear to be all "
                         "that different to conscientiousness.",
    },
    "timeline": [
        {"year": 2007, "what": "grit predicts grades", "es": 0.25,
         "es_kind": "r"},
        {"year": 2007, "what": "and the original paper's own overlap figure",
         "es": 0.77, "es_kind": "r"},
        {"year": 2017, "what": "88 samples, 66,807 people", "es": 0.18,
         "es_kind": "r"},
        {"year": 2017, "what": "grit against plain conscientiousness",
         "es": 0.84, "es_kind": "r"},
    ],
    "twist_rows": [
        {"label": "grit predicts", "what": "academic performance at",
         "es": 0.18, "es_kind": "r"},
        {"label": "grit matches", "what": "plain conscientiousness at",
         "es": 0.84, "es_kind": "r", "hot": True},
        {"label": "for scale", "what": "two conscientiousness scales match at",
         "es": 0.63, "es_kind": "r"},
    ],
    "say_spread": "It became a book, a TED talk, and a school curriculum — "
                  "the answer to why some children get there and others do "
                  "not.",
    "say_twist": "So the effect is real, and it is 0.18. But the number that "
                 "matters is the next one. They checked how much grit "
                 "overlaps with plain old conscientiousness — a trait "
                 "psychologists have been measuring since long before anyone "
                 "said grit. After correcting for measurement error, 0.84. "
                 "For scale: two different questionnaires that both claim to "
                 "measure conscientiousness agree with each other at 0.63. "
                 "Grit matches conscientiousness more closely than "
                 "conscientiousness matches itself.",
    "say_verdict": "So this is not a debunking. Grit predicts things. It is "
                   "just that it may not be a new thing. And the overlap was "
                   "not discovered later by critics — the original 2007 paper "
                   "reports it, at 0.77, in its own results. "
                   "The meta-analysis put it this way: grit as it is "
                   "currently measured does not appear to be particularly "
                   "predictive of success and performance, and also does not "
                   "appear to be all that different to conscientiousness.",
    "verdict_display": "grit as it is currently measured does not appear to "
                       "be particularly predictive of success and performance "
                       "and also does not appear to be all that different to "
                       "conscientiousness.",
    "reel": {
        "belief": "Grit beats talent.",
        "weight": "It became a book, a TED talk and a school curriculum. "
                  "The 2007 paper is cited more than 6,900 times.",
        "turn": "In 2017 someone pooled 88 samples — 66,807 people. Grit's "
                "correlation with academic performance came out at 0.18. Then "
                "they checked how much grit overlaps with plain old "
                "conscientiousness, which psychologists have measured for "
                "decades. 0.84. For scale, two different questionnaires that "
                "both claim to measure conscientiousness agree with each "
                "other at 0.63.",
        "verdict": "Grit matches conscientiousness more closely than "
                   "conscientiousness matches itself.",
        "ask": "Is grit a real thing, or a new name for an old one?",
    },
    "missing": [],
}

d["episodes"].append(EP)
P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"grit 已加入,現在共 {len(d['episodes'])} 集")
