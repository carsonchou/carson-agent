#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把八集的 say_twist / say_verdict / story_type_short 寫進事實庫。

每一段都只用**逐字原句裡有的內容**改寫成口語,不新增任何宣稱。
稿子裡要唸出來的數字若還不是結構化欄位,一併升格 —— 那正是
make_rechecked.audit 逼出來的:想講的數字沒過閘門,就把它變成欄位,
而不是把閘門放寬。
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
d = json.loads(P.read_text(encoding="utf-8"))
E = {e["slug"]: e for e in d["episodes"]}

# ─── hot_hand ───────────────────────────────────────────────────────
e = E["hot_hand"]
e["story_type_short"] = "the arithmetic was wrong, not the players"
# 稿子要唸 +4(GVT 自報)與 +12(高出隨機基準多少)。兩者原本只活在
# quote 裡,而 quote 不供給白名單 —— 升格成欄位。
e["test"]["key_numbers"] = {
    "observed_pp_as_reported": 4,
    "observed_pp_recomputed": 3,
    "gap_above_random_pp": 12,
    "bias_pp": -8,
    "corrected_pp": 13,
    "_note_for_humans": "4 與 3 的差別見 internal_inconsistency:摘要用 GVT "
                        "自報的 .49/.45 相減,Table II 用逐球員資料重算。",
}
e["say_twist"] = (
    "Here is the part it took thirty-three years to notice. "
    "The original team did not miscount anything. They compared what the "
    "players did against zero — against the idea that a random shooter "
    "shows no difference at all. But if you go through a sequence, pick out "
    "only the shots that follow three hits, and measure how often those go "
    "in, a perfectly random shooter does not come out at zero. He comes out "
    "below it. On this design, 8 percentage points below it. "
    "So the plus 4 the original study found was not, as everyone read it, "
    "about the same as random. It was 12 points above random. "
    "Take the bias out, and the average difference goes from plus 3 "
    "to plus 13. For scale, the gap between the median three point shooter "
    "and the best one in the NBA that season was 12 points."
)
e["say_verdict"] = (
    "So this is not a study that failed to replicate. The data were fine. "
    "The analysis had a bias in it that nobody on either side had spotted, "
    "and when you take it out the conclusion turns over. "
    "The people who found it wrote: the results of our reanalysis lead us "
    "to a conclusion that is the opposite of theirs. Belief in the hot hand "
    "is not a cognitive illusion."
)

# ─── facial_feedback ────────────────────────────────────────────────
e = E["facial_feedback"]
e["story_type_short"] = "the method died, the idea did not"
e["say_twist"] = (
    "So the pen is gone. And for six years that was the whole story — "
    "one of the most repeated demonstrations in psychology, and 17 labs "
    "could not find it. "
    "Then look at what happened in 2022. A larger group went back with "
    "three different ways of putting a smile on someone's face. "
    "Getting people to copy a smiling face: 0.49. "
    "Asking them to make the expression themselves: 0.4. "
    "And the pen held in the teeth, the version that made the idea famous: "
    "0.04. Still nothing. "
    "One of the authors on that paper is the man who ran the 1988 study."
)
e["say_verdict"] = (
    "So be careful which sentence you take away. The replication report "
    "said it themselves: the results do not invalidate the more general "
    "facial feedback hypothesis. What fell over was the pen. "
    "The 2022 team put it this way — our results do not provide "
    "unequivocal evidence of a pen in mouth effect. Nonetheless, they do "
    "provide strong evidence that other tasks designed to produce partial "
    "or full recreations of happy expressions can both modulate and "
    "initiate feelings of happiness."
)

# ─── moral_licensing ────────────────────────────────────────────────
e = E["moral_licensing"]
e["story_type_short"] = "every retest was bigger, and smaller"
e["test"]["key_numbers"] = {
    "published_d": 0.43,
    "unpublished_d": 0.11,
    "trimfill_added_studies": 21,
}
e["say_twist"] = (
    "The meta-analysis is where it gets uncomfortable, because it answers "
    "a question nobody asked it. Split the studies by whether they got "
    "published. Published: 0.43. Sitting in a drawer, unpublished: 0.11. "
    "The funnel plot test for that asymmetry came back significant, and "
    "the correction for it wanted to add 21 studies that do not exist. "
    "Then follow the number forward. "
    "In 2016, 3,134 people — the effect is still there, and it is a ninth "
    "of the size. In 2019 somebody re-ran the whole pile correcting for "
    "that publication bias, and the corrected estimate was minus 0.05, "
    "which is another way of writing zero. "
    "In 2024, a registered replication of the original study, 932 people. "
    "Minus 0.38. Not smaller. The other way round."
)
e["say_verdict"] = (
    "So the shape here is not one study falling over. It is a number that "
    "got smaller every single time somebody looked at it with more people, "
    "and then changed sign. And the person who ran the first failed "
    "replication is one of the authors of the meta-analysis that found the "
    "bias. That is what it looks like when a field checks itself. "
    "The 2024 team's own sentence: we could not replicate the original "
    "findings."
)

# ─── terror_management ──────────────────────────────────────────────
e = E["terror_management"]
e["story_type_short"] = "the original authors helped, and it still failed"
e["test"]["key_numbers"] = {
    "author_advised_labs": 7,
    "author_advised_n": 699,
    "in_house_labs": 10,
    "in_house_n": 851,
}
e["say_twist"] = (
    "Here is what makes this one different from every other failed "
    "replication you have heard about. The usual defence, when a result "
    "does not come back, is that the replicators did it wrong. They did "
    "not understand the paradigm. They changed something that mattered. "
    "So this time they removed that defence in advance. "
    "7 of the labs, 699 people, ran a protocol the original authors "
    "themselves advised on. The other 10 labs, 851 people, wrote their own. "
    "The author advised version: 0.08. "
    "And the difference between the two approaches was 0.01, which is not "
    "a difference. The original effect was 1.34."
)
e["say_verdict"] = (
    "So the effect did not come back, and it did not come back under the "
    "conditions its own authors specified. That closes off the "
    "easy explanation. The paper's own summary: neither the author advised "
    "nor the in house protocols successfully replicated the original "
    "finding. And a sentence from the authors that is worth sitting with — "
    "it could be that changes in history have substantially altered the "
    "observability of the effect."
)

# ─── backfire_effect ────────────────────────────────────────────────
e = E["backfire_effect"]
e["story_type_short"] = "the author says you read it wrong"
e["original"]["key_numbers"] = {
    "conservatives_control_pct": 32,
    "conservatives_corrected_pct": 64,
    "experiments_in_paper": 5,
    "experiments_showing_backfire": 2,
}
e["say_twist"] = (
    "You have almost certainly heard the conclusion from this study, even "
    "if you have never heard the study. It is the reason people say facts "
    "do not work, that you cannot argue anybody out of anything. "
    "So here is the thing that gets left out. That paper contains 5 "
    "experiments. Backfire showed up in 2 of them. "
    "And in 2021, the author who ran it wrote a paper in order to say so. "
    "His words: the results have frequently been misinterpreted as showing "
    "that all corrections are counterproductive, or that backfire effects "
    "are the primary cause of the persistence of misperceptions. "
    "Our findings do not support either claim."
)
e["say_verdict"] = (
    "So what actually survives is smaller and more useful than the version "
    "that travelled. Corrections mostly work — in about nine issues out of "
    "ten the average person moves toward the facts. "
    "And notice what the replication did not find. When they used the "
    "original wording, nobody moved, which partly reproduces the original "
    "result. What killed backfire was rewriting the question. "
    "The author's own conclusion in 2021: the primary challenge is not to "
    "prevent backfire effects, but to understand how to target corrective "
    "information better and make it more effective."
)

# ─── false_memory ───────────────────────────────────────────────────
e = E["false_memory"]
e["story_type_short"] = "it replicated, and then the counting changed"
e["test"]["key_numbers"] = {
    "coded_false_memories": 43,
    "with_possibly_true_events": 22,
    "no_recall_of_being_lost": 7,
    "no_self_reported_memory": 9,
    "rate_after_first_deduction": 17,
    "rate_after_second_deduction": 11,
    "rate_after_third_deduction": 4,
    "self_reported_pct": 14,
}
e["say_twist"] = (
    "So it replicated, and it replicated upward. That should have been the "
    "end of it. "
    "Then another team went back to the same data and asked a question the "
    "headline number does not answer: what has to be true for something to "
    "count as an implanted memory? "
    "Three things, and they took them one at a time. "
    "The event has to not have actually happened — 22 of the 43 had "
    "something in their real childhood it could be. That takes 35 percent "
    "down to 17. "
    "There has to be a memory of being lost — 7 more had no recall at all. "
    "That takes it to 11. "
    "And the person has to say they remember it — 9 more did not. "
    "That takes it to 4."
)
e["say_verdict"] = (
    "So which number is the real one depends entirely on what you think "
    "the study is for. If you are asking whether suggestion can push "
    "people into describing something that never happened, 35 percent. "
    "If you are asking whether it produces the kind of memory a court "
    "would act on, 4. "
    "The researchers who wrote the reply — including the author of the "
    "original 1995 study — put it this way: whether the false memory rate "
    "is 4 percent, or 35 percent, or somewhere in between, the findings "
    "are important."
)

# ─── marshmallow_test ───────────────────────────────────────────────
e = E["marshmallow_test"]
e["story_type_short"] = "real, and mostly your parents"
e["test"]["key_numbers"] = {
    "seconds_that_matter": 20,
    "mothers_without_degree_n": 552,
    "bivariate_beta": 0.24,
    "with_background_controls_beta": 0.08,
    "with_concurrent_controls_beta": 0.05,
}
e["say_twist"] = (
    "The retest is ten times the size, and the first thing it finds is "
    "that the effect is there. 0.24, on its own, with nothing controlled "
    "for. Real, and about half what the original reported. "
    "Then they add what they know about the child before the marshmallow "
    "ever appeared — family income, the mother's education, how the home "
    "was run, what the child could already do. "
    "0.24 becomes 0.08. "
    "Add what was measured at the same time as the test itself, and it is "
    "0.05, and it is no longer distinguishable from nothing. "
    "And the piece that does survive is not what the story needs it to be. "
    "Most of the difference came from whether a child could wait 20 "
    "seconds. Not fifteen minutes. 20 seconds."
)
e["say_verdict"] = (
    "So this is not a debunking, and anyone selling it as one is selling "
    "you something. Waiting predicts later achievement. It is just that "
    "two thirds of what looked like willpower was the family the child "
    "went home to. "
    "The authors' own sentence: this bivariate correlation was only half "
    "the size of those reported in the original studies, and was reduced "
    "by two thirds in the presence of controls for family background, "
    "early cognitive ability, and the home environment."
)

# ─── hungry_judges ──────────────────────────────────────────────────
e = E["hungry_judges"]
e["story_type_short"] = "still an open argument"
e["test"]["key_numbers"] = {"hearing_days": 12}
e["say_twist"] = (
    "Now, this is the point where these videos normally tell you the "
    "finding fell over. This one has not, and it matters that I say so. "
    "Neither challenge ran the study again. "
    "The first one is a letter. They got hold of a different set of "
    "hearings and talked to the people in the room, and what they came "
    "back with is that the order of cases is not random. Prisoners without "
    "a lawyer tend to go last, and they tend to lose. In their data, "
    "prisoners with a lawyer succeeded 35 percent of the time and prisoners "
    "without one, 15. "
    "The second is not data at all. It is a simulation of a completely "
    "rational judge who simply avoids starting a case he cannot finish "
    "before the break. That judge produces the same falling line. "
    "And the original authors answered both, in the same journal, and "
    "have not withdrawn anything."
)
e["say_verdict"] = (
    "So where does that leave it. The original result rests on an "
    "assumption stated in the paper — that the order of cases is set by "
    "when each prisoner's lawyer turns up, and that nobody in the room can "
    "see the schedule. Everything turns on whether that is true, and the "
    "people who queried it did not have the case order in their data, "
    "so they could not test it directly. "
    "Even the simulation's author says his account covers a drop of 15 to "
    "45 percent only, and that the analyses do not provide conclusive "
    "evidence. "
    "This one is not settled. That is the honest answer, and it is a less "
    "satisfying video than the alternative."
)

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✓ 寫回 {P.name}")
for s, x in E.items():
    print(f"  {s:20s} twist {len(x.get('say_twist',''))} 字元 "
          f"verdict {len(x.get('say_verdict',''))} 字元")
