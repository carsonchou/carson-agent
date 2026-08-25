#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_bank.py — 驗證題庫真實存量(這條路的承重假設)。

## 為什麼先做這個
「有 30-60 個題目」是我的估計不是查證。如果真實只有 10 個,頻道跑三個月就斷炊,
而那時已經投入了產線與改版。先付最小代價取得這個答案 —— 這正是氛圍片那輪
沒做、結果做了好幾天才發現方向不對的事。

## 判準(每題必須有可播的硬數字)
STRONG  = 摘要同時有「樣本數 + 效果量」或「效果量 + 信賴區間」→ 可直接開一集
PARTIAL = 只有其中之一,或只有研究數 → 要人工翻正文才知道能不能用
WEAK    = 摘要無任何量化陳述 → 這題先不排

只用官方公開 API(OpenAlex),不爬網頁。
"""
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
UA = "carson-agent/1.0 (mailto:moneycometomywallet@gmail.com)"

# 候選:著名心理學說法 + 用來查它重複驗證/整合分析的檢索詞
CLAIMS = [
    ("Ego depletion", "multilab preregistered replication ego depletion effect"),
    ("Power posing", "power posing replication Ranehill assessing the robustness"),
    ("Facial feedback", "registered replication report Strack facial feedback hypothesis"),
    ("Marshmallow test", "revisiting the marshmallow test conceptual replication"),
    ("Stanford Prison Experiment", "investigating the Stanford Prison Experiment historical"),
    ("Growth mindset", "to what extent and under which circumstances are growth mindset"),
    ("Elderly social priming", "behavioral priming it's all in the mind but whose mind"),
    ("Implicit Association Test", "meta-analysis predictive validity implicit association test"),
    ("Mozart effect", "mozart effect meta-analysis Pietschnig"),
    ("Learning styles", "learning styles concepts and evidence"),
    ("Money priming", "money priming replication Rohrer Pashler"),
    ("Macbeth effect cleanliness", "replication cleanliness priming moral judgment"),
    ("Mortality salience", "registered replication report terror management mortality salience"),
    ("Grit", "much ado about grit meta-analytic synthesis"),
    ("Self-esteem and success", "does high self-esteem cause better performance"),
    ("Bilingual advantage", "cognitive advantage bilingualism publication bias"),
    ("Brain training", "working memory training does not improve meta-analytic review"),
    ("Deliberate practice 10000 hours", "deliberate practice and performance meta-analysis"),
    ("Stereotype threat", "stereotype threat girls mathematics meta-analysis publication bias"),
    ("Nudging effect size", "publication bias nudge effectiveness meta-analysis"),
    ("Oxytocin and trust", "does oxytocin increase trust in humans critical review"),
    ("Video games and aggression", "violent video games aggression meta-analysis publication bias"),
    ("Hot hand fallacy", "surprised by the hot hand fallacy truth in the law of small numbers"),
    ("Anchoring", "many labs replication anchoring effects"),
    ("Weapons effect", "weapons effect meta-analysis"),
    ("Mindfulness meditation", "meditation programs for psychological stress meta-analysis"),
    ("Serotonin and depression", "serotonin theory of depression systematic umbrella review"),
    ("Implicit bias training", "meta-analysis of procedures to change implicit measures"),
    ("Pygmalion teacher expectancy", "teacher expectations self-fulfilling prophecy accuracy"),
    ("Social rejection and pain", "acetaminophen reduces social pain replication"),
    ("Red color attractiveness", "red and romantic attraction replication"),
    ("Bystander effect", "the bystander effect a meta-analytic review intervention"),
    ("Dunning-Kruger", "dunning kruger effect statistical artifact better than average"),
    ("Emotional intelligence job performance", "emotional intelligence job performance meta-analysis"),
    ("Positive psychology interventions", "positive psychology interventions meta-analysis effect"),
    ("Loss aversion", "acceptable losses the debatable origins of loss aversion"),
    ("Media multitasking", "media multitasking cognitive control replication"),
    ("Sleep and memory consolidation", "sleep and memory consolidation meta-analysis effect size"),
    ("Priming achievement goals", "goal priming replication failure"),
    ("Chameleon effect mimicry", "chameleon effect replication mimicry"),
    ("Expressive writing", "expressive writing health outcomes meta-analysis"),
    ("Placebo open-label", "open-label placebo meta-analysis effect size"),
    ("Testosterone and risk taking", "testosterone risk taking meta-analysis"),
    ("Birth order and personality", "examining the effects of birth order on personality"),
    ("Blue light and sleep", "evening screen light melatonin suppression meta-analysis"),
    ("Sunk cost fallacy", "sunk cost effect meta-analysis"),
    ("Choice overload", "choice overload meta-analytic review"),
    ("Ovulatory cycle preference shifts", "ovulatory cycle shifts preferences meta-analysis"),
    ("Stereotype accuracy", "stereotype accuracy one of the largest effects social psychology"),
    ("Cognitive dissonance effort justification", "effort justification replication cognitive dissonance"),
]

PAT_N = re.compile(r"\bN\s*=\s*[\d,]+|\b\d[\d,]{2,}\s+participants\b|"
                   r"\bk\s*=\s*\d+\b|\b\d+\s+(?:studies|labs|laboratories|samples)\b")
PAT_D = re.compile(r"\b[dgr]\s*=\s*-?0?\.\d+|\bHedges[^\.]{0,12}=\s*-?0?\.\d+|"
                   r"effect size[s]?\s+(?:of|was|were)\s+-?0?\.\d+|\bOR\s*=\s*\d")
PAT_CI = re.compile(r"95%\s*(?:CI|confidence interval)")


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 + i * 2)


def abstract_of(w):
    inv = w.get("abstract_inverted_index") or {}
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def main():
    rows = []
    for name, query in CLAIMS:
        try:
            u = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query) +
                 "&per-page=3&select=title,publication_year,cited_by_count,doi,"
                 "abstract_inverted_index")
            res = json.loads(get(u)).get("results", [])
        except Exception as e:
            rows.append((name, "ERROR", 0, "", str(e)[:40], 0))
            continue
        best = None
        for w in res:
            ab = abstract_of(w)
            has_n = bool(PAT_N.search(ab))
            has_d = bool(PAT_D.search(ab))
            has_ci = bool(PAT_CI.search(ab))
            score = (2 if (has_n and has_d) or (has_d and has_ci) else
                     1 if (has_n or has_d) else 0)
            cand = (score, w, ab, has_n, has_d, has_ci)
            if best is None or score > best[0]:
                best = cand
            if score == 2:
                break
        if not best:
            rows.append((name, "NONE", 0, "", "", 0))
            continue
        score, w, ab, has_n, has_d, has_ci = best
        tag = {2: "STRONG", 1: "PARTIAL", 0: "WEAK"}[score]
        marks = ("N" if has_n else "-") + ("d" if has_d else "-") + ("CI" if has_ci else "--")
        rows.append((name, tag, w["publication_year"], w.get("doi", "") or "",
                     marks, w["cited_by_count"]))
        time.sleep(0.15)

    order = {"STRONG": 0, "PARTIAL": 1, "WEAK": 2, "NONE": 3, "ERROR": 4}
    rows.sort(key=lambda r: (order.get(r[1], 9), -r[5]))
    print(f"{'說法':<38}{'判定':<9}{'年':>6}{'訊號':>7}{'被引':>8}")
    for name, tag, yr, doi, marks, cites in rows:
        print(f"{name:<38}{tag:<9}{yr:>6}{marks:>7}{cites:>8}")
    from collections import Counter
    c = Counter(r[1] for r in rows)
    print(f"\n共 {len(rows)} 題候選 → STRONG {c['STRONG']} / PARTIAL {c['PARTIAL']} / "
          f"WEAK {c['WEAK']} / 查無 {c['NONE'] + c['ERROR']}")
    print(f"可直接開集(STRONG):{c['STRONG']} 集")
    print(f"加上人工翻正文的 PARTIAL:最多 {c['STRONG'] + c['PARTIAL']} 集")
    out = ROOT / "facts" / "bank_scan.json"
    out.write_text(json.dumps(
        [{"claim": r[0], "verdict": r[1], "year": r[2], "doi": r[3],
          "signals": r[4], "cited_by": r[5]} for r in rows],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n明細寫入 {out}")


if __name__ == "__main__":
    main()
