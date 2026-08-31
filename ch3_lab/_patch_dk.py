#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第十題:Dunning–Kruger。

## 為什麼這題值得做
它是這批裡**觀眾立場最強**的一題:大家不只相信它,還天天拿它去解釋別人。
而且它的敘事點是全庫最乾淨的 —— **同一批 929 人、兩種分析、相反的結論。**

## 🔴 誠實界線:不能說「Dunning-Kruger 是假的」
論文標題自己帶著括號的 (mostly),而且 Discussion 逐字寫著:

  "our contention is that the Dunning-Kruger effects reported in the
   literature are **mostly** the result of statistical artefacts, rather
   than **entirely** so."

安全講法是:**「那張著名的圖,用隨機數字也畫得出來;換成有效的統計檢定,
效果就不見了。」** 每一段都有原文撐。講成「完全是假象」就過頭 ——
而這種過頭正是這個頻道不能犯的那種錯。

另外一個必須講的正面發現:同一篇量到自評智力與實測智力相關 r = 0.28
(Nuhfer 2017 逐人相關甚至 r = .60)。**人是judge得出自己的能力的** ——
只講前半就是選擇性呈現。

## 數字漂移陷阱
「第 12 百分位的人自評第 62」出自**摘要**,是四個研究的**平均**。
各研究內文不一樣(Study 1 是 12→58、Study 2 是 12→62、Study 3 是 10→67)。
畫面上印 12 → 62 一定要標明是摘要的跨研究平均。
四個研究樣本數 65/45/84/140,**合計 334 是 agent 自己加的,論文沒印**。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))

EP = {
    "slug": "dunning_kruger",
    "popular_name": "The Dunning-Kruger effect",
    "story_type": "原始分析有偏誤(但作者自己的字是 mostly,不是 entirely)",
    "story_type_short": "the graph draws itself from noise",
    "story_type_note": "🔴 不准講成「完全是假的」。論文標題自己帶括號的 "
                       "(mostly),Discussion 明講 mostly rather than "
                       "entirely。而且同一篇量到人**確實**judge得出自己的"
                       "能力(r = 0.28)—— 只講前半是選擇性呈現。",
    "claim": "the least competent people are the most confident — too "
             "incompetent to know how incompetent they are",
    "hook": "Take the same 929 people. Analyse them one way and the "
            "Dunning-Kruger effect is right there. Analyse them properly and "
            "it is gone.",
    "original": {
        "year": 1999,
        "title": "Unskilled and unaware of it: How difficulties in "
                 "recognizing one's own incompetence lead to inflated "
                 "self-assessments",
        "journal": "Journal of Personality and Social Psychology 77(6):1121-1134",
        "doi": "10.1037/0022-3514.77.6.1121",
        "n": 65, "n_word": "Cornell undergraduates in the first study",
        "cited_by": 7079,
        "cited_by_source": "OpenAlex, retrieved 2026-08-31",
        "cited_by_approx": 7000,
        "quote": "Across 4 studies, the authors found that participants "
                 "scoring in the bottom quartile on tests of humor, grammar, "
                 "and logic grossly overestimated their test performance and "
                 "ability. Although their test scores put them in the 12th "
                 "percentile, they estimated themselves to be in the 62nd.",
        "quote_location": "摘要 —— 這是**四個研究的平均**,不是任何單一實驗",
        "key_numbers": {
            "actual_percentile": 12,
            "estimated_percentile": 62,
            "_note_for_humans": "各研究內文不同:Study 1 是 12→58、Study 2 "
                                "是 12→62、Study 3 是 10→67。畫面印 12→62 "
                                "要標明是摘要的跨研究平均。四個研究 n = "
                                "65/45/84/140,合計 334 是 agent 自己加的,"
                                "論文沒印,不准當原文引用。",
        },
    },
    "test": {
        "year": 2020,
        "kind": "reanalysis of the original data",
        "same_sample": False,
        "kind_note": "🔴 `same_sample` 是相對於 1999 那批人 —— 這是**新的** "
                     "929 人。片子裡的「同一批」指的是這 929 人被**兩種"
                     "分析各跑一次**,那是集內的對照,不是跟 1999 同批。",
        "title": "The Dunning-Kruger effect is (mostly) a statistical "
                 "artefact: Valid approaches to testing the hypothesis with "
                 "individual differences data",
        "journal": "Intelligence 80:101449",
        "doi": "10.1016/j.intell.2020.101449",
        "n": 929, "n_word": "people",
        "es": -0.05, "es_kind": "r",
        "key_numbers": {"eta_squared_old_method": 0.20,
                        "self_vs_measured_r": 0.28},
        "outcomes": [
            {"name": "the original quartile method, on this data", "es": 0.20,
             "es_kind": "pct", "p": 0.001,
             "stat": "F(3, 925) = 79.00, p < .001, eta2 = 0.20",
             "is_claim": False,
             "quote": "A between-subjects oneway ANOVA test of the difference "
                      "between the mean difference scores across the four "
                      "levels of objective IQ was significant statistically, "
                      "F(3, 925) = 79.00, p < .001, eta2 = 0.20. ... the "
                      "trend in the difference score means was downward "
                      "slopping, suggesting ostensible support for the "
                      "Dunning-Kruger hypothesis."},
            {"name": "a test built for this kind of data", "es": -0.05,
             "es_kind": "r", "p": 0.132,
             "stat": "r(927) = -0.05, 95% CI -0.11 to 0.02, p = .132",
             "is_claim": True,
             "quote": "The correlation between the objective IQ scores and "
                      "the absolute residuals (i.e., the Glejser test "
                      "correlation) was not found to be significant "
                      "statistically, r(927) = -0.05, 95%CI: -0.11/0.02, "
                      "p = .132, suggesting the data were homoscedastic, "
                      "which did not support the Dunning-Kruger hypothesis."},
            {"name": "and no curve in the data", "es": 0.01, "es_kind": "pct",
             "p": 0.545,
             "stat": "R2change <= 0.01, F(1, 926) = 0.37, p = .545",
             "is_claim": True,
             "quote": "The hierarchical multiple regression failed to "
                      "identify a statistically significant quadratic effect, "
                      "R2change <= 0.01, F(1, 926) = 0.37, p = .545 ... "
                      "suggesting, again, a failure to support the "
                      "Dunning-Kruger hypothesis."},
            {"name": "people do judge their own ability", "es": 0.28,
             "es_kind": "r", "p": 0.001, "stat": "r = 0.28",
             "is_claim": False,
             "quote": "We also found that self-assessed intelligence and "
                      "objectively measured intelligence correlated "
                      "positively and statistically significantly at "
                      "r = 0.28, which is comparable to the "
                      "meta-analytically estimated correlations reported in "
                      "the literature (r = 0.33; Freund & Kasten, 2012)."},
        ],
        "honesty_quote": "Thus, at this stage, our contention is that the "
                         "Dunning-Kruger effects reported in the literature "
                         "are mostly the result of statistical artefacts, "
                         "rather than entirely so.",
        "verdict_quote": "When such valid statistical analyses are applied to "
                         "individual differences data, we believe that "
                         "evidence ostensibly supportive of the "
                         "Dunning-Kruger hypothesis derived from the mean "
                         "difference approach employed by Kruger and Dunning "
                         "(1999) will be found to be substantially "
                         "overestimated.",
    },
    "noise_paper": {
        "year": 2016,
        "title": "Random Number Simulations Reveal How Random Noise Affects "
                 "the Measurements and Graphical Portrayals of Self-Assessed "
                 "Competency",
        "journal": "Numeracy 9(1), Article 4",
        "doi": "10.5038/1936-4660.9.1.4",
        "cited_by": 66,
        "quote": "We began to suspect that the graphical convention we "
                 "employed in common with Bell and Volckmann might account "
                 "for this convergence, and we confirmed our suspicion by "
                 "graphing nonsense data generated by random numbers. In "
                 "that graphical convention, random numbers generated "
                 "patterns very similar to those produced by our actual "
                 "data.",
        "followup_2017_doi": "10.5038/1936-4660.10.1.4",
        "followup_2017_quote": "Our data show that peoples' self-assessments "
                               "of competence, in general, reflect a genuine "
                               "competence that they can demonstrate. That "
                               "finding contradicts the current consensus "
                               "about the nature of self-assessment.",
    },
    "timeline": [
        {"year": 1999, "what": "the bottom quarter scored", "es": 12,
         "es_kind": "pct"},
        {"year": 1999, "what": "and rated themselves", "es": 62,
         "es_kind": "pct"},
        {"year": 2016, "what": "random numbers draw the same graph",
         "es": None},
        {"year": 2020, "what": "a test built for the data", "es": -0.05,
         "es_kind": "r"},
    ],
    "twist_rows": [
        {"label": "same 929 people", "what": "the original quartile method",
         "es": 0.20, "es_kind": "pct"},
        {"label": "same 929 people", "what": "a test built for this data",
         "es": -0.05, "es_kind": "r", "hot": True},
        {"label": "and", "what": "people do rate themselves about right",
         "es": 0.28, "es_kind": "r"},
    ],
    "say_spread": "It became the thing everyone reaches for to explain "
                  "somebody they disagree with — a name, a graph, and a "
                  "shortcut.",
    "say_twist": "In 2020 a team took 929 people and analysed them twice. "
                 "First the way the original did it: sort everyone into "
                 "quartiles by test score and compare the average gap between "
                 "what they scored and what they thought they scored. That "
                 "produced the effect, clearly. Then they used a test built "
                 "for this kind of data instead of comparing group averages. "
                 "The correlation was minus 0.05. There was no curve either. "
                 "Same people, same answers, opposite conclusion. "
                 "And four years earlier another group had shown you can "
                 "draw that famous graph out of random numbers.",
    "say_verdict": "So be careful with the sentence you take away. The "
                   "authors did not say the effect is fake. Their own title "
                   "says mostly, and in the discussion they write that these "
                   "effects are mostly the result of statistical artefacts, "
                   "rather than entirely so. And in the same data, people's "
                   "estimates of their own intelligence tracked their actual "
                   "intelligence at 0.28. Which is the part nobody quotes.",
    "verdict_display": "the Dunning-Kruger effects reported in the literature "
                       "are mostly the result of statistical artefacts, "
                       "rather than entirely so.",
    "reel": {
        "belief": "The least competent people are the most confident.",
        "weight": "It has a name, a graph everyone has seen, and the 1999 "
                  "paper is cited more than 7,000 times.",
        "turn": "In 2020 a team took 929 people and analysed them twice. "
                "Sorted into quartiles the way the original did it, the "
                "effect was right there. Using a test built for this kind of "
                "data instead, the correlation was minus 0.05, and there was "
                "no curve. Same people, same answers, opposite conclusion. "
                "And you can draw that famous graph out of random numbers.",
        "verdict": "Mostly a statistical artefact. Mostly is the authors' "
                   "own word, not entirely.",
        "ask": "Have you ever used this one to explain somebody you disagree with?",
    },
    "missing": ["Krajč & Ortmann 2008(10.1016/j.joep.2007.12.006)全文在付費牆後,"
                "DOI 已驗證但沒有拿到逐字原句,所以片中不引它的任何數字"],
}

d["episodes"].append(EP)
P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"dunning_kruger 已加入,現在共 {len(d['episodes'])} 集")
