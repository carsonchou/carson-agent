#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 11~14 題:史丹佛監獄、糖與過動、莫札特效應、成長心態。

四題的誠實界線各不相同,而**那正是這批的價值** —— 如果四題都能用同一句
「又一個倒了」收尾,那就是模板化。

| slug | 界線 |
|---|---|
| stanford_prison | **不准用 retracted / fraud / 造假**。SPE 從未被撤稿,Le Texier 也沒要求撤稿。站得住的講法是原文自己的字對上 Zimbardo 自己的字。 |
| sugar_hyperactivity | 統合分析結論句末的兩個但書(小效果、次群體不能排除)**照唸不准砍**。 |
| mozart_effect | 不是「沒重現」。對照沉默**確實有**一個小效果 —— 只是任何音樂一樣大。真正的分界是**只持續 10~15 分鐘**。 |
| growth_mindset | **不准講成全倒**。Yeager 2019 是預先註冊的全美隨機試驗,而且它**找到了**效果 —— 只是 0.10 個 GPA 點、只在低成就學生、只在同儕規範支持挑戰的學校。 |

## SPE 的樣本數:原始論文自己前後不一致
同一節相隔兩頁寫了 22 與 24,而結論用的是 21(10 囚 + 11 獄卒);
Zimbardo 官網又是第四個版本(70+ / 24)。畫面打 **21**(那才是進了分析的人),
口白補一句原文自己寫了兩個數字 —— **那件事本身就很有畫面**。

## 糖那題沒有「原始研究」
這個信念沒有一篇乾淨的原始實驗。最常被引的 Prinz 1980 是相關研究不是實驗,
而且 agent 一個字都沒拿到(付費牆 + PubMed 無摘要)。
所以 original 除了書目與 DOI 之外全部留空 —— **這比硬填一個好**,
而且開場很好講:「這一集要拆的說法,連一篇像樣的原始研究都找不到。」
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "facts" / "rechecked_episodes.json"
PC = pathlib.Path(__file__).resolve().parent / "facts" / "plain_claims.json"
d = json.loads(P.read_text(encoding="utf-8"))
pc = json.loads(PC.read_text(encoding="utf-8"))

EPS = [
{
 "slug": "stanford_prison",
 "popular_name": "The Stanford prison experiment",
 "story_type": "原始研究不是它宣稱的那樣",
 "story_type_short": "the guards were told what to do",
 "story_type_note": "🔴 **不准用 retracted / fraud / 造假。** SPE 從未被撤稿,"
                    "Le Texier 也沒有要求撤稿,Zimbardo 公開回應過而且他的"
                    "反駁不弱。站得住的講法只有一種:**原始論文自己的字**"
                    "對上 **Zimbardo 自己的字**。",
 "claim": "put ordinary people in a uniform and give them power, and they "
          "will turn cruel on their own",
 "hook": "The original paper says the guards were given no training. "
         "Zimbardo's own reply uses the word training.",
 "original": {
   "year": 1972,
   "title": "Interpersonal Dynamics in a Simulated Prison (ONR Technical "
            "Report Z-09)",
   "journal": "Office of Naval Research; also International Journal of "
              "Criminology and Penology 1:69-97 (1973)",
   "doi": "10.21236/AD0751041",
   "n": 21, "n_word": "students in the analysis",
   "quote": "Neither group received any specific training in these roles.",
   "quote_location": "摘要",
   "second_quote": "To optimize the extent to which their behavior would "
                   "reflect their genuine reactions to the experimental "
                   "prison situation and not simply their ability to follow "
                   "instructions, they were intentionally given only minimal "
                   "guidelines for what it meant to be a guard.",
   "key_numbers": {"applicants": 75, "selected": 24, "arrived": 22,
     "analysed": 21,
     "_note_for_humans": "🔴 原始論文**自己**在相隔兩頁寫了 22 與 24,而"
       "結論用的是 21(10 囚 + 11 獄卒);Zimbardo 官網又是第四個版本"
       "(70+ / 24)。畫面打 21,口白說明原文自己寫了兩個數字。"
       "OCR 掃描件的推論統計會壞(Z-3.88, p^.01 其實是 Z=3.88, p<.01),"
       "所以原始論文的推論統計數字一律不用。"},
 },
 "test": {
   "year": 2019,
   "kind": "archival reinvestigation",
   "same_sample": False,
   "title": "Debunking the Stanford Prison Experiment",
   "journal": "American Psychologist 74(7):823-839",
   "doi": "10.1037/amp0000401",
   "n": None,
   "key_numbers": {"recorded_pct": 15, "interaction_table_pct": 4,
     "video_hours_found": 6, "video_hours_claimed": 12,
     "guessed_hypothesis_pct": 81, "predicted_oppressive_pct": 90},
   "outcomes": [
     {"name": "how much of the experiment was actually recorded", "es": 15,
      "es_kind": "pct", "p": None, "stat": "6 hr video + 15 hr audio of 150 hr",
      "is_claim": True,
      "quote": "Of the 150 hr of the experiment (including the orientation "
               "day), less than 15% have been recorded (6 hr of video and 15 "
               "hr of audio)."},
     {"name": "outsiders who guessed the result from the advert alone",
      "es": 81, "es_kind": "pct", "p": None, "stat": "81%", "is_claim": False,
      "quote": "81% accurately figured out the experimenter's hypothesis"},
   ],
   "briefing_quote": "We can create boredom. We can create a sense of "
     "frustration. We can create fear in them, to some degree. We can create "
     "a notion of the arbitrariness that governs their lives, which are "
     "totally controlled by us, by the system, by you, me, [the warden]. "
     "They'll have no privacy at all... In general, what all this should "
     "create in them is a sense of powerlessness. We have total power in the "
     "situation. They have none.",
   "warden_quote": "[W]e need you to play the part of, you know, tough guard. "
     "[. . .] [T]ry and react as you picture the pigs reacting.",
   "verdict_quote": "Of the 150 hr of the experiment (including the "
     "orientation day), less than 15% have been recorded (6 hr of video and "
     "15 hr of audio).",
 },
 "original_authors_reply": {
   "who": "Philip Zimbardo", "year": 2018,
   "why_must_air": "他的反駁不弱,而且不播就是我們在做我們批評的事。",
   "quotes": [
     "Central in the training of guards was...",
     "it never instructed guards to employ brutality, and it explicitly "
     "banned the use of physical force",
     "In my view, that is the major flaw of the SPE; it had no independent "
     "scientific observer of the unfolding events.",
   ],
 },
 "bbc_study": {
   "year": 2006, "n": 15, "days": 8,
   "doi": "10.1348/014466605X48998",
   "journal": "British Journal of Social Psychology 45(1):1-40",
   "quote": "Unlike the prisoners, the guards failed to identify with their "
            "role. This made the guards reluctant to impose their authority "
            "and they were eventually overcome by the prisoners. "
            "Participants then established an egalitarian social system.",
   "note": "這是唯一**真的重做過一次**的。放時間軸與口述,不當 test —— "
           "本集的故事型是「原始研究不是它宣稱的那樣」,不是「重測失敗」。",
 },
 "timeline": [
   {"year": 1972, "what": "students in the analysis", "es": 21,
    "es_kind": "count"},
   {"year": 1972, "what": "the paper: no training given", "es": None},
   {"year": 2006, "what": "run again, the guards would not play along",
    "es": None},
   {"year": 2019, "what": "of the experiment was ever recorded", "es": 15,
    "es_kind": "pct"},
 ],
 "twist_rows": [
   {"label": "the paper says", "what": "no specific training", "es": None},
   {"label": "the tapes say", "what": "we need you to play tough guard",
    "es": None, "hot": True},
   {"label": "on record", "what": "of the 150 hours", "es": 15,
    "es_kind": "pct"},
 ],
 "say_spread": "It became the standard proof that ordinary people turn cruel "
               "when you give them a uniform — in textbooks, in films, and in "
               "arguments about every atrocity since.",
 "say_twist": "In 2019 a researcher went through the Stanford archive and "
              "listened to the tapes. On the recording of the guard "
              "briefing, the experimenters tell the guards what to produce: "
              "boredom, frustration, fear, a sense of powerlessness. On day "
              "three the warden takes aside a guard who is being too soft and "
              "tells him, we need you to play the part of, you know, tough "
              "guard. And less than 15 percent of the 150 hours was ever "
              "recorded at all.",
 "say_verdict": "So be careful what you take from this. The study has not "
                "been retracted, and nobody is calling it fraud. What is "
                "documented is narrower and harder to argue with: the paper "
                "says the guards received no specific training, and "
                "Zimbardo's own published reply begins a sentence with the "
                "words, central in the training of guards. He also names what "
                "he thinks the real flaw was — that it had no independent "
                "scientific observer of the unfolding events.",
 "verdict_display": "Of the 150 hr of the experiment (including the "
                    "orientation day), less than 15% have been recorded",
 "reel": {
   "belief": "Give ordinary people a uniform and power, and they turn cruel.",
   "weight": "The Stanford prison experiment. It is in every textbook, and "
             "in every argument about how atrocities happen.",
   "turn": "In 2019 somebody went into the Stanford archive and listened to "
           "the tapes. At the guard briefing, the experimenters say what they "
           "want produced: boredom, frustration, fear, a sense of "
           "powerlessness. On day three the warden takes aside a guard who is "
           "being too soft and tells him, we need you to play the part of, "
           "you know, tough guard. And less than 15 percent of the 150 hours "
           "was ever recorded.",
   "verdict": "The paper says the guards got no training. Zimbardo's own "
              "reply says: central in the training of guards.",
   "ask": "Does it still count if they were told to do it?",
 },
 "missing": ["原始論文沒有效果量(本來就沒有,不要硬算)",
             "Le Texier 2019 沒有效果量",
             "1973 期刊版與技術報告是否逐字相同未能複驗(期刊版是無文字層掃描)"],
},
{
 "slug": "sugar_hyperactivity",
 "popular_name": "Sugar and hyperactive children",
 "story_type": "信念本身沒有原始研究,而被騙的是家長",
 "story_type_short": "what changed was the parent",
 "story_type_note": "🔴 統合分析結論句末的兩個但書(小效果、次群體不能"
                    "排除)**照唸不准砍**,砍了就是過度宣稱。",
 "claim": "sugar makes children hyperactive",
 "hook": "Every child got the placebo. The mothers who were told it was "
         "sugar rated their sons as more hyperactive — and changed how they "
         "behaved themselves.",
 "original": {
   "year": 1980,
   "title": "Dietary correlates of hyperactive behavior in children",
   "journal": "Journal of Consulting and Clinical Psychology 48(6):760-769",
   "doi": "10.1037/0022-006X.48.6.760",
   "n": None,
   "no_data_note": "🔴 這一題**沒有乾淨的原始實驗**。最常被引的這篇是"
     "**相關研究不是實驗**,而且付費牆 + PubMed 無摘要,agent 一個字都"
     "沒拿到 → 除了書目與 DOI 之外全部留空。硬填一個數字才是錯的。",
 },
 "test": {
   "year": 1995,
   "kind": "meta-analysis",
   "same_sample": False,
   "title": "The effect of sugar on behavior or cognition in children: "
            "A meta-analysis",
   "journal": "JAMA 274(20):1617-1621",
   "doi": "10.1001/jama.1995.03530200053037",
   "n": None,
   "k": 23, "k_word": "within-subject design studies",
   "key_numbers": {"reports": 16, "constructs": 14,
                   "lowest_mean_es": -0.14, "highest_mean_es": 0.30},
   "n_quote": "Sixteen reports met the inclusion criteria for a total of 23 "
              "within-subject design studies.",
   "outcomes": [
     {"name": "measurement constructs whose interval excluded zero", "es": 0,
      "es_kind": "count", "p": None, "stat": "0 of 14", "is_claim": True,
      "quote": "The weighted mean effect size and related statistics for each "
               "of the 14 measurement constructs revealed that although the "
               "range for these means was from -0.14 for direct observations "
               "and up to +0.30 for academic tests, the 95% confidence "
               "interval for all 14 mean effect sizes included 0."},
   ],
   "verdict_quote": "The meta-analytic synthesis of the studies to date found "
     "that sugar does not affect the behavior or cognitive performance of "
     "children. The strong belief of parents may be due to expectancy and "
     "common association. However, a small effect of sugar or effects on "
     "subsets of children cannot be ruled out.",
 },
 "expectancy_study": {
   "year": 1994,
   "title": "Effects of sugar ingestion expectancies on mother-child "
            "interactions",
   "journal": "Journal of Abnormal Child Psychology 22(4):501-515",
   "doi": "10.1007/BF02168088",
   "n": 35, "n_word": "mother and son pairs",
   "design_quote": "A challenge study design was employed, in which "
     "thirty-five 5- to 7-year-old boys reported by their mothers to be "
     "behaviorally \"sugar sensitive,\" and their mothers, were randomly "
     "assigned to experimental and control groups. In the experimental group, "
     "mothers were told their children had received a large dose of sugar, "
     "whereas in the control condition mothers were told their sons received "
     "a placebo; all children actually received the placebo (aspartame).",
   "result_quote": "Mothers in the sugar expectancy condition rated their "
     "children as significantly more hyperactive. Behavioral observations "
     "revealed these mothers exercised more control by maintaining physical "
     "closeness, as well as showing trends to criticize, look at, and talk to "
     "their sons more than did control mothers.",
   "warning": "🔴 全文付費牆,摘要**沒有** F 值、p 值或效果量 → 片中只能說"
              "「significantly more hyperactive」,不准報任何數字。",
 },
 "timeline": [
   {"year": 1980, "what": "the study people cite is not an experiment",
    "es": None},
   {"year": 1994, "what": "mothers told it was sugar, all placebo", "es": 35,
    "es_kind": "count"},
   {"year": 1995, "what": "of 14 measures, this many cleared zero", "es": 0,
    "es_kind": "count"},
 ],
 "twist_rows": [
   {"label": "1994", "what": "mother and son pairs, all given placebo",
    "es": 35, "es_kind": "count"},
   {"label": "told it was sugar", "what": "mothers rated them more hyperactive",
    "es": None, "hot": True},
   {"label": "1995", "what": "of 14 measures cleared zero", "es": 0,
    "es_kind": "count"},
 ],
 "say_spread": "It is one of the most widely held beliefs about children "
               "anywhere — birthday parties, bedtimes, and a generation of "
               "food rules are built on it.",
 "say_twist": "In 1994 a team took 35 boys whose mothers said they were "
              "sugar sensitive. Every single child was given a placebo. The "
              "only thing that was randomised was what the mother was told. "
              "The mothers who were told their son had just had a large dose "
              "of sugar rated him as significantly more hyperactive. And the "
              "observers watching them saw the mothers themselves change: "
              "staying physically closer, criticising more, watching him "
              "more.",
 "say_verdict": "The meta-analysis that pooled the trials put it this way: "
                "sugar does not affect the behavior or cognitive performance "
                "of children, and the strong belief of parents may be due to "
                "expectancy and common association. But read the last "
                "sentence too, because they wrote it for a reason: a small "
                "effect of sugar, or effects on subsets of children, cannot "
                "be ruled out.",
 "verdict_display": "sugar does not affect the behavior or cognitive "
                    "performance of children. The strong belief of parents "
                    "may be due to expectancy and common association.",
 "reel": {
   "belief": "Sugar makes children hyperactive.",
   "weight": "It is one of the most widely held beliefs about children "
             "anywhere. Birthday parties are organised around it.",
   "turn": "In 1994 a team took 35 boys whose mothers said they were sugar "
           "sensitive. Every child was given a placebo. The only thing "
           "randomised was what the mother was told. The mothers told their "
           "son had just had a large dose of sugar rated him as "
           "significantly more hyperactive — and observers saw those mothers "
           "stay closer to him, criticise him more, and watch him more.",
   "verdict": "What changed was the parent.",
   "ask": "Did you grow up being kept off sugar?",
 },
 "missing": ["Prinz 1980 的 n、效果量、引文(付費牆 + PubMed 無摘要,一個字都沒拿到)",
             "Wolraich 1995 的跨研究總人數(摘要沒給)",
             "Hoover & Milich 1994 的 F 值 / p 值 / 效果量(摘要沒給)"],
},
{
 "slug": "mozart_effect",
 "popular_name": "The Mozart effect",
 "story_type": "效果是真的,但它不屬於莫札特,而且只持續十五分鐘",
 "story_type_short": "any music does it, for fifteen minutes",
 "story_type_note": "🔴 不是「沒重現」。對照沉默**確實有**一個小效果 —— "
                    "只是任何音樂一樣大(0.38 vs 0.37,兩種音樂之間只有 "
                    "0.15)。而原文自己就用 IQ 語言寫,所以**不能說「他們"
                    "根本沒說 IQ」** —— 真正的分界是它只持續 10~15 分鐘。",
 "claim": "listening to Mozart makes you smarter",
 "hook": "The effect is real. It is just not Mozart, and it is over in "
         "fifteen minutes.",
 "original": {
   "year": 1993,
   "title": "Music and spatial task performance",
   "journal": "Nature 365:611",
   "doi": "10.1038/365611a0",
   "n": 36, "n_word": "college students",
   "es": 9, "es_kind": "iq_points",
   "cited_by_approx": None,
   "quote": "Thus, the IQs of subjects participating in the music condition "
            "were 8-9 points above their IQ scores in the other two "
            "conditions.",
   "duration_quote": "The enhancing effect of the music condition is "
     "temporal, and does not extend beyond the 10-15-minute period during "
     "which subjects were engaged in each spatial task.",
   "key_numbers": {"music_iq": 119, "relaxation_iq": 111, "silence_iq": 110,
                   "minutes_min": 10, "minutes_max": 15},
 },
 "test": {
   "year": 2010,
   "kind": "meta-analysis",
   "same_sample": False,
   "title": "Mozart effect-Shmozart effect: A meta-analysis",
   "journal": "Intelligence 38(3):314-323",
   "doi": "10.1016/j.intell.2010.03.001",
   "n": 3000, "n_is_floor": True, "n_word": "people",
   "k": 38, "k_word": "comparisons",
   "es": 0.37, "es_kind": "d",
   "key_numbers": {"any_music_d": 0.38, "between_music_d": 0.15},
   "outcomes": [
     {"name": "Mozart against silence", "es": 0.37, "es_kind": "d", "p": None,
      "stat": "d = 0.37, 95% CI [0.23, 0.52]", "is_claim": True,
      "quote": "We could show that the overall estimated effect is small in "
               "size (d = 0.37, 95% CI [0.23, 0.52]) for samples exposed to "
               "the Mozart sonata KV 448 and samples that had been exposed to "
               "a non-musical stimulus or no stimulus at all preceding "
               "spatial task performance."},
     {"name": "any other music against silence", "es": 0.38, "es_kind": "d",
      "p": None, "stat": "d = 0.38, 95% CI [0.13, 0.63]", "is_claim": True,
      "quote": "Additionally, calculation of effect sizes for samples exposed "
               "to any other musical stimulus and samples exposed to a "
               "non-musical stimulus or no stimulus at all yielded effects "
               "similar in strength (d = 0.38, 95% CI [0.13, 0.63])"},
     {"name": "Mozart against any other music", "es": 0.15, "es_kind": "d",
      "p": None, "stat": "d = 0.15, 95% CI [0.02, 0.28]", "is_claim": True,
      "quote": "whereas there was a negligible effect between the two music "
               "conditions (d = 0.15, 95% CI [0.02, 0.28])."},
   ],
   "lab_quote": "The central finding of the present paper however, is "
     "certainly the noticeably higher overall effect in studies performed by "
     "Rauscher and colleagues than in studies performed by other "
     "researchers, indicating systematically moderating effects of lab "
     "affiliation.",
   "verdict_quote": "On the whole, there is little evidence left for a "
                    "specific, performance-enhancing Mozart effect.",
 },
 "timeline": [
   {"year": 1993, "what": "Mozart, against silence", "es": 9,
    "es_kind": "iq_points"},
   {"year": 1993, "what": "and gone within this many minutes", "es": 15,
    "es_kind": "count"},
   {"year": 2010, "what": "Mozart against silence, pooled", "es": 0.37,
    "es_kind": "d"},
   {"year": 2010, "what": "any other music against silence", "es": 0.38,
    "es_kind": "d"},
   {"year": 2010, "what": "Mozart against any other music", "es": 0.15,
    "es_kind": "d"},
 ],
 "twist_rows": [
   {"label": "Mozart", "what": "against silence", "es": 0.37, "es_kind": "d"},
   {"label": "any other music", "what": "against silence", "es": 0.38,
    "es_kind": "d"},
   {"label": "Mozart", "what": "against any other music", "es": 0.15,
    "es_kind": "d", "hot": True},
 ],
 "say_spread": "It became a state programme handing out classical CDs to "
               "newborns, and a shelf of products aimed at parents.",
 "say_twist": "So somebody pooled everything that had been run since. "
              "Mozart against silence: 0.37. Real, and small. Then the "
              "comparison nobody in the headlines made. Any other music "
              "against silence: 0.38 — the same. And Mozart against any "
              "other music: 0.15. There is also the detail that the effect "
              "is noticeably larger in studies run by the original lab than "
              "by anyone else.",
 "say_verdict": "So the effect is real and it is not Mozart. What it looks "
                "like is that music, any music, wakes you up a little before "
                "a task. And the original paper already told us how long "
                "that lasts. Their own sentence: the enhancing effect of the "
                "music condition is temporal, and does not extend beyond the "
                "10 to 15 minute period during which subjects were engaged "
                "in each spatial task.",
 "verdict_display": "On the whole, there is little evidence left for a "
                    "specific, performance-enhancing Mozart effect.",
 "reel": {
   "belief": "Listening to Mozart makes you smarter.",
   "weight": "It became a state programme handing classical CDs to newborns, "
             "and a shelf of products aimed at parents.",
   "turn": "Pool everything that has been run since. Mozart against silence: "
           "0.37. Real, and small. Then the comparison the headlines never "
           "made. Any other music against silence: 0.38 — the same. Mozart "
           "against any other music: 0.15. And the original paper already "
           "said the effect does not last beyond the 10 to 15 minutes of the "
           "task.",
   "verdict": "The effect is real. It is not Mozart, and it is over in "
              "fifteen minutes.",
   "ask": "What do you put on before you need to concentrate?",
 },
 "missing": ["統合分析的確切總人數(摘要只寫 over 3000 subjects)",
             "各結果的 p 值",
             "出版偏誤用的是哪個檢定與其統計量",
             "1993 那篇沒有報 Cohen's d"],
},
{
 "slug": "growth_mindset",
 "popular_name": "Growth mindset",
 "story_type": "效果是真的但小很多,而且只在特定的人與特定的學校",
 "story_type_short": "real, for half the students",
 "story_type_note": "🔴 **不准講成全倒。** Yeager 2019 是預先註冊、獨立收"
                    "資料的全美隨機試驗,而且它**找到了**效果。只是 0.10 "
                    "個 GPA 點、只在低成就學生(6,320 / 12,490)、而且只在"
                    "同儕規範支持挑戰的學校裡才維持。高成就組是 0.01、"
                    "p = 0.634。**兩個並排放才是誠實的畫面。**",
 "claim": "teaching students that intelligence can grow raises their grades",
 "hook": "The biggest test of growth mindset found it works. For half the "
         "students, by a tenth of a grade point.",
 "original": {
   "year": 2007,
   "title": "Implicit Theories of Intelligence Predict Achievement Across an "
            "Adolescent Transition: A Longitudinal Study and an Intervention",
   "journal": "Child Development 78(1):246-263",
   "doi": "10.1111/j.1467-8624.2007.00995.x",
   "n": 91, "n_word": "students in one school",
   "es": 0.53, "es_kind": "beta",
   "quote": "However, there was a significant effect of experimental "
            "condition on change in grades across the intervention (Time 2 "
            "to Time 3; b = .53, t = 2.93, p<.05).",
   "limits_quote": "First, Study 1 and Study 2 were each conducted in a "
                   "single school.",
   "confound_quote": "This extra antistereotyping training may have "
                     "contributed to our findings.",
 },
 "test": {
   "year": 2019,
   "kind": "randomised controlled trial",
   "same_sample": False,
   "title": "A national experiment reveals where a growth mindset improves "
            "achievement",
   "journal": "Nature 573:364-369",
   "doi": "10.1038/s41586-019-1466-y",
   "n": 12490, "n_word": "ninth-grade students",
   "k": 65, "k_word": "schools",
   "es": 0.11, "es_kind": "d",
   "key_numbers": {"lower_achieving_n": 6320, "higher_achieving_n": 6170,
                   "gpa_points": 0.10, "advanced_maths_pp": 3},
   "outcomes": [
     {"name": "lower-achieving students", "es": 0.11, "es_kind": "d",
      "p": 0.001,
      "stat": "B = 0.10 grade points, 95% CI 0.04 to 0.16, n = 6,320, t = 3.51",
      "is_claim": True,
      "quote": "In line with our first major prediction, lower-achieving "
               "adolescents earned higher GPAs in core classes at the end of "
               "the ninth grade when assigned to the growth mindset "
               "intervention, B = 0.10 grade points (95% confidence interval "
               "= 0.04, 0.16), s.e. = 0.03, n = 6,320, k = 65, t = 3.51, "
               "P = 0.001, standardized mean difference effect size of 0.11, "
               "relative to comparable students in the control condition."},
     {"name": "higher-achieving students", "es": 0.01, "es_kind": "d",
      "p": 0.634, "stat": "n = 6,170, t = 0.480", "is_claim": True,
      "quote": "Confirming the predictions in the pre-analysis plan, "
               "higher-achieving students demonstrated no significant "
               "treatment effects on core course GPAs, B = 0.01 grade points "
               "(95% confidence interval = -0.03-0.06), s.e. = 0.02, "
               "n = 6,170, k = 65, t = 0.480, P = 0.634, standardized mean "
               "difference effect size = 0.01"},
   ],
   "targeting_quote": "Following the pre-registered analysis plan, we report "
     "results for the targeted group of n = 6,320 students who were "
     "lower-achieving relative to peers in the same school.",
   "verdict_quote": "The National Study of Learning Mindsets showed that a "
     "low-cost treatment, delivered in less than an hour, attained a "
     "substantial proportion of the effects on grades of the most effective "
     "rigorously evaluated adolescent interventions of any cost or duration "
     "in the literature within the pre-registered group of lower-achieving "
     "students.",
 },
 "uk_trial": {
   "year": 2019, "n": 5018, "schools": 101,
   "doi": None,
   "no_doi_note": "🔴 EEF 評估報告不是期刊論文,**確認沒有 DOI** —— 照"
                  "fail-closed 閘門它不能當 test,只能進時間軸與口述。",
   "quote": "Pupils in schools that received the intervention did not make "
            "any additional progress in literacy nor numeracy - as measured "
            "by the national Key Stage 2 tests in reading, grammar, "
            "punctuation, and spelling (GPS), and maths - compared to pupils "
            "in the control group. This finding has high security.",
   "trap": "🔴 搜尋摘要會拿 2015 年的**先導試驗**冒充這次的效能試驗,"
           "回「two additional months' progress」—— 方向完全相反。",
 },
 "timeline": [
   {"year": 2007, "what": "91 students, one school", "es": 0.53,
    "es_kind": "beta"},
   {"year": 2019, "what": "5,018 pupils in England, no effect", "es": None},
   {"year": 2019, "what": "lower-achieving students in the US", "es": 0.11,
    "es_kind": "d"},
   {"year": 2019, "what": "higher-achieving students", "es": 0.01,
    "es_kind": "d"},
 ],
 "twist_rows": [
   {"label": "6,320 students", "what": "lower-achieving", "es": 0.11,
    "es_kind": "d"},
   {"label": "6,170 students", "what": "higher-achieving", "es": 0.01,
    "es_kind": "d", "hot": True},
   {"label": "in England", "what": "5,018 pupils, no effect", "es": None},
 ],
 "say_spread": "It became a school programme, a bestseller, and a poster in "
               "a great many classrooms.",
 "say_twist": "So they ran it properly. 65 schools, 12,490 students, "
              "randomised individually, with the analysis plan registered "
              "before the data came in. And they found it. Lower-achieving "
              "students earned 0.10 of a grade point more — an effect size "
              "of 0.11. Then look at the other half of the sample. "
              "Higher-achieving students: 0.01, p equals 0.634. And in "
              "England, a trial with 5,018 pupils found no additional "
              "progress in reading, in grammar, or in maths.",
 "say_verdict": "So this is not a debunking, and the people who say growth "
                "mindset is dead have not read the biggest test of it. What "
                "the evidence supports is much narrower than the poster: a "
                "tenth of a grade point, for the students who were already "
                "behind, in schools where their classmates made it safe to "
                "try something hard.",
 "verdict_display": "higher-achieving students demonstrated no significant "
                    "treatment effects on core course GPAs",
 "reel": {
   "belief": "Teach a child that intelligence can grow, and their grades go up.",
   "weight": "It became a school programme, a bestseller, and a poster in a "
             "great many classrooms.",
   "turn": "So they ran it properly: 65 schools, 12,490 students, randomised "
           "individually, analysis plan registered in advance. And they found "
           "it. Lower-achieving students gained a tenth of a grade point — an "
           "effect size of 0.11. Now the other half of the sample. "
           "Higher-achieving students: 0.01, p equals 0.634. And a trial in "
           "England with 5,018 pupils found nothing at all.",
   "verdict": "It works. For the students who were already behind, by a tenth "
              "of a grade point.",
   "ask": "Is a tenth of a grade point worth an assembly?",
 },
 "missing": ["Blackwell 2007 的 Cohen's d(成績那個結果只報 b/t)",
             "Sisk 2018 兩個統合分析的效果量數值(全文付費牆;流傳的 "
             "d = 0.08 是二手,且 k 值跨來源會漂 43 vs 38、273 vs 129 —— "
             "**不要唸出這個數字**)",
             "英國試驗沒有 DOI"],
},
]

PLAIN = {
 "stanford_prison": (["DO ORDINARY PEOPLE TURN", "CRUEL IN A UNIFORM?"],
                     "Do ordinary people turn cruel when you put them in a uniform?"),
 "sugar_hyperactivity": (["DOES SUGAR MAKE", "CHILDREN HYPERACTIVE?"],
                         "Does sugar actually make children hyperactive?"),
 "mozart_effect": (["DOES LISTENING TO MOZART", "MAKE YOU SMARTER?"],
                   "Does listening to Mozart really make you smarter?"),
 "growth_mindset": (["DOES BELIEVING YOU CAN", "GROW RAISE YOUR GRADES?"],
                    "Does believing your mind can grow actually raise your grades?"),
}

have = {e["slug"] for e in d["episodes"]}
for ep in EPS:
    if ep["slug"] in have:
        print(f"  跳過已存在:{ep['slug']}")
        continue
    d["episodes"].append(ep)
for slug, (lines, spoken) in PLAIN.items():
    v = {"lines": lines, "spoken": spoken}
    pc[f"eps_rechecked/{slug}"] = v
    pc[slug] = v

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
PC.write_text(json.dumps(pc, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"現在共 {len(d['episodes'])} 集")
