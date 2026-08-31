#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新 Short 格式(35~45 秒)的逐集文案。

## 為什麼要重寫,而不是把舊的 20 秒版加長
2026-08-31 實測:28 支 Short、289 次觀看、**0 則留言、0 次分享、1 個讚**。
Analytics 顯示 Shorts feed 佔流量 131/141 —— 管道是通的、平均看完
64.6~79.3% —— 留存也不差。**問題是沒有人有理由反應。**
Shorts 的分發靠前一批曝光回收的訊號決定要不要放大;回收到接近零,
所以它不放大。再發 45 支就是再拿 289 次觀看。

三個機制上站得住的改動(Carson 三個都要):
1. **片長 20 → 35~45 秒。** 2026 演算法用觀看時間取代滑走率,甜蜜點
   30~45 秒。65% 留存的 20 秒片交出 13 秒;55% 留存的 40 秒片交出 22 秒,
   而排序看的是後者。舊版 28 支全部是 14~26 秒。
2. **結尾要有一個看得懂的人答得出來的問題。** 289 次觀看 0 則留言,
   因為片子從頭到尾沒有邀請任何人回應。
3. **只做觀眾本來就有立場的說法。** 你不可能對一個你從沒相信過的說法
   感到被騙。

## 人設的紅線
講述者是「**去把兩篇論文讀完的那個人**」——這是真的,產線真的抓了 PDF、
真的逐字抄了句子。所以允許:「我去讀了兩篇原文」「這是我找到的那一句」。
**不允許**:編造的個人史(「我以前也相信」——那是一句關於一個不存在的人
的假話,而這個頻道唯一的資產就是每一句都查得到)。
語氣可以有立場,事實不可以有立場。

## 每一個數字照樣走溯源閘門
`reel_turn` 裡的數字必須是結構化欄位。想講就升格,不放寬閘門。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))
E = {e["slug"]: e for e in d["episodes"]}

# belief:第 0 幀就要全部出現的那句。是觀眾**本來就相信**的說法,不是論文語言。
# turn:轉折,25~40 字。verdict:一行判決。ask:一個外行答得出來的問題。
COPY = {
    "hot_hand": {
        "belief": "Basketball players get hot streaks.",
        "weight": "For thirty years, psychology said that was an illusion. "
                  "The 1985 paper is cited more than 1,700 times.",
        "turn": "In 2018 two economists checked the arithmetic. If you pick "
                "out the shots that follow three hits, a perfectly random "
                "shooter does not score zero on that measure. He scores "
                "minus 8 percentage points. So the plus 4 the original found "
                "was not nothing. It was 12 points above random.",
        "verdict": "Corrected, the hot hand is plus 13 percentage points. "
                   "The illusion was in the arithmetic.",
        "ask": "Did you ever believe the hot hand was fake?",
    },
    "marshmallow_test": {
        "belief": "A four-year-old who waits for the marshmallow does better in life.",
        "weight": "A book, a TED talk, and a great deal of parenting advice "
                  "are built on it. The 1990 paper is cited more than "
                  "1,200 times.",
        "turn": "In 2018 a team ran it on ten times as many children. The "
                "effect was there: a standardised coefficient of 0.24. Then "
                "they controlled for the family the child came from. 0.08. "
                "Then for everything measured on the same day. 0.05, and no "
                "longer distinguishable from nothing.",
        "verdict": "It is real. Two thirds of it was the family the child "
                   "went home to.",
        "ask": "Would you still run this test on your own kid?",
    },
    "backfire_effect": {
        "belief": "Correcting someone makes them believe the wrong thing harder.",
        "weight": "It is the reason people say facts do not work. The 2010 "
                  "paper is cited more than 3,200 times.",
        "turn": "That paper ran 5 experiments. Backfire showed up in 2 of "
                "them. In 2019 another team tested 52 issues on more than "
                "10,100 people and could not produce it once. For about nine "
                "issues in ten, the correction worked.",
        "verdict": "In 2021 the original author published a paper to say he "
                   "had been misread.",
        "ask": "Have you ever used this study to give up on an argument?",
    },
    "facial_feedback": {
        "belief": "Holding a pen in your teeth makes things funnier, because "
                  "your face feeds back into how you feel.",
        "weight": "It is the textbook demonstration that the body drives the "
                  "mind. Cited more than 1,800 times.",
        "turn": "In 2016, 17 laboratories ran it on 1,894 people. The "
                "difference was 0.03 points on a ten point scale, and 0 of "
                "the 17 pointed the right way. Six years later a bigger "
                "group tried three ways of making people smile. Copying a "
                "smiling face worked. Posing it yourself worked. The pen "
                "still did nothing.",
        "verdict": "The pen died. The idea behind it did not — and the "
                   "original author co-signed the paper that showed it.",
        "ask": "Which would you have bet on?",
    },
    "false_memory": {
        "belief": "You can plant a memory of something that never happened.",
        "weight": "Lost in the mall. It is the study expert witnesses cite "
                  "in court. Cited more than 1,100 times.",
        "turn": "In 2023 it was run again and the rate came back higher: "
                "35 percent, against 25 in the original. Then another team "
                "asked what has to be true to count one. Take out those "
                "whose real childhood could fit the story: 17. Those with no "
                "memory of being lost: 11. Those who never said they "
                "remembered it: 4.",
        "verdict": "35 percent or 4 percent, from the same data. It depends "
                   "what you think the study is for.",
        "ask": "Which number would you accept in a courtroom?",
    },
    "terror_management": {
        "belief": "Reminding people of death makes them defend their beliefs harder.",
        "weight": "A whole research programme about fear, politics and "
                  "prejudice is built on it. The 1994 study reported an "
                  "effect size of 1.34.",
        "turn": "The usual defence when a result does not come back is that "
                "the replicators did it wrong. So this time 7 of the labs "
                "ran a protocol the original authors advised on. Those labs "
                "got 0.08. The labs left to themselves differed by 0.01, "
                "which is not a difference.",
        "verdict": "They let the original authors help design it, and it "
                   "still did not come back.",
        "ask": "What would convince you either way?",
    },
    "moral_licensing": {
        "belief": "Doing one good thing gives you permission to do a bad one.",
        "weight": "It is the standard explanation for why good people do "
                  "shabby things. Cited more than 1,000 times.",
        "turn": "Pooled, the effect is 0.31. Split it: published studies "
                "0.43, unpublished 0.11. Correct for that bias and it is "
                "minus 0.05, which is another way of writing zero. In 2024 "
                "a registered replication on 932 people came back at minus "
                "0.38 — the other way round.",
        "verdict": "Every retest was bigger. Every retest was smaller. "
                   "The last one changed sign.",
        "ask": "Do you catch yourself doing this?",
    },
    "hungry_judges": {
        "belief": "Judges go easy on you right after lunch.",
        "weight": "65 percent granted after a break, almost none before one. "
                  "Cited more than 1,400 times, in law and in management.",
        "turn": "Two teams challenged it, and neither ran the study again. "
                "One got a different set of hearings and found that case "
                "order is not random: prisoners without a lawyer go last, "
                "and they win 15 percent of the time against 35. The other "
                "simulated a judge doing nothing wrong, and got the same "
                "falling line.",
        "verdict": "The original authors answered both and withdrew nothing. "
                   "This one is still an argument.",
        "ask": "Do you think the judges were hungry, or just running late?",
    },
}

for slug, c in COPY.items():
    E[slug]["reel"] = c

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote reel copy for {len(COPY)} episodes")
for s, c in COPY.items():
    w = sum(len(v.split()) for v in c.values())
    print(f"  {s:<20}{w:>4} words ≈ {w / 2.6:.0f}s")
