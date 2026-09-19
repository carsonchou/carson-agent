# -*- coding: utf-8 -*-
"""抓六個「通過需求測試」題目的原始 + 重測論文摘要。

## 為什麼是這六個
`effect_scan.py` 量過 22 個候選,判準是「切題結果裡有沒有小頻道」。
分數前段而且我手上真的有可靠重測證據的,就是這六個:

    10000 hour rule    24,311
    loss aversion      10,460
    power posing        9,484
    learning styles     7,988
    anchoring effect    6,989
    stereotype threat   6,136

FReD 對這六個幾乎沒有資料(0~2 列),所以它們只能走 `famous` 那條路
—— 手工核對、每個數字附出處句。

## 這支不寫事實庫
它只把摘要與正則抓到的候選數字落檔到 `facts/famous/`。
**要不要用、用哪個數字,我逐句看過才手寫進 famous_episodes.json。**
自動抓到什麼就填什麼,正是這條線上出過事的那個模式。
"""
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from famous_facts import harvest, OUT           # noqa: E402

# (題目, 角色, 我認為的論文, DOI)
# ⚠️ DOI 是我從記憶寫的 —— 抓回來之後**必須核對 title 對不對得上**,
#    對不上就是抓錯篇,不能用。這一欄不是證據,是查詢鍵。
TARGETS = [
    ("10000_hour_rule", "original",
     "Ericsson, Krampe & Tesch-Romer 1993 deliberate practice",
     "10.1037/0033-295X.100.3.363"),
    ("10000_hour_rule", "test",
     "Macnamara, Hambrick & Oswald 2014 meta-analysis",
     "10.1177/0956797614535810"),

    ("loss_aversion", "original",
     "Kahneman & Tversky 1979 prospect theory",
     "10.2307/1914185"),
    ("loss_aversion", "test",
     "Gal & Rucker 2018 the loss of loss aversion",
     "10.1002/jcpy.1047"),

    ("power_posing", "original",
     "Carney, Cuddy & Yap 2010 power posing",
     "10.1177/0956797610383437"),
    ("power_posing", "test",
     "Ranehill et al. 2015 assessing the robustness of power posing",
     "10.1177/0956797614553946"),

    ("learning_styles", "original",
     "Pashler et al. 2008 learning styles concepts and evidence",
     "10.1111/j.1539-6053.2009.01038.x"),
    ("learning_styles", "test",
     "Rogowsky, Calhoun & Tallal 2015 matching learning style to instruction",
     "10.1037/edu0000013"),

    ("anchoring", "original",
     "Tversky & Kahneman 1974 judgment under uncertainty",
     "10.1126/science.185.4157.1124"),
    ("anchoring", "test",
     "Klein et al. 2014 Many Labs 1",
     "10.1027/1864-9335/a000178"),

    ("stereotype_threat", "original",
     "Steele & Aronson 1995 stereotype threat",
     "10.1037/0022-3514.69.5.797"),
    ("stereotype_threat", "test",
     "Flore & Wicherts 2015 meta-analysis girls stereotyped domains",
     "10.1016/j.jsp.2014.10.002"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "demand6.json"
    recs = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else []
    done = {(r["topic"], r["role"]) for r in recs}
    for topic, role, label, doi in TARGETS:
        if (topic, role) in done:
            continue
        r = harvest(label, doi)
        r["topic"], r["role"] = topic, role
        recs.append(r)
        f = r.get("found", {})
        print(f"  {topic:18s}{role:9s}{r['status']:12s}"
              f"n={len(f.get('n', []))} es={len(f.get('effect', []))} "
              f"k={len(f.get('k', []))}  {str(r.get('title'))[:52]}")
        dest.write_text(json.dumps(recs, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        time.sleep(1.5)
    print(f"\n落檔 {dest}({len(recs)} 筆)")
    bad = [r for r in recs if r["status"] in ("FETCH_FAIL", "NO_ABSTRACT")]
    if bad:
        print("⛔ 這幾筆沒有摘要,要我自己去讀原文:")
        for r in bad:
            print(f"   {r['topic']:18s}{r['role']:9s}{r['status']}  {r['doi']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
