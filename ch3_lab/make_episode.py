#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_episode.py — 吃 FReD 的一列,吐一支完整影片。

## 架構決定的理由
- **數字全部走模板填空,不經 LLM**。稿子裡每個數字都直接來自 FReD 欄位,
  生成後再過一次審核:稿中出現的數字必須在事實庫找得到,否則阻擋。
  (編造統計是主頻道踩過的紅線,這條產線從結構上不給它機會。)
- **畫面只做圖表**。效果量長條、樣本數對比、信賴線 —— 都是資料的直接呈現,
  不是美術。這是我唯一被證明做得好的形態。
- **白話主張用 FReD 的 description 欄**(claim_text_o 是論文結果段原文,不能唸)。

用法:
  python make_episode.py --list             # 看佇列
  python make_episode.py --row 0            # 產第 0 集
  python make_episode.py --row 0 --script-only
"""
import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import wave

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent                      # 絕對路徑:腳本可能從任何 cwd 被呼叫
QUEUE = ROOT / "facts" / "episode_queue.csv"
W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8EAED", "#8A9099"
ACCENT, WARN = "#4EA3F5", "#F5A54E"


# ── 事實 ────────────────────────────────────────────────────────────
_TYPO = {"criminial": "criminal", "positvely": "positively",
          "foregiveness": "forgiveness"}
_LEADIN = re.compile(r"^(we\s+(find|found|show|investigated)\s+(that\s+)?"
                     r"(the\s+hypothesis\s+that\s+)?)", re.I)


def speakable(claim):
    """把來源主張整成唸得出口的句子——只動唸稿,畫面上的引用仍是原文。

    來源是別人維護的資料庫,有拼字錯(criminial)、殘留的引號、以及
    作者第一人稱的開場(We investigated the hypothesis that …)。
    TTS 會照著唸,而唸錯字比看錯字更傷可信度。
    """
    c = claim.strip().strip('"').strip("“”").strip()
    c = _LEADIN.sub("", c)
    # 來源是論文摘要剪下來的,帶著清單標記與編號:
    #   「are perceived as: (d) thicker」「[84] Data Replicada #3」
    # 唸出來完全不知所云,而且那些數字還會被溯源守門當成可疑數字。
    c = re.sub(r"^\s*\[\d+\]\s*", "", c)          # 開頭的 [84]
    c = re.sub(r"\s*\([a-z]\)\s*", " ", c)         # 句中的 (d)
    c = re.sub(r"\s*:\s*$", "", c)
    # 來源殘片:「…easy abilities; using a mouse.」分號後是懸空的片語;
    # 「are perceived as: thicker」冒號在句中。唸出來都是壞句子。
    c = re.sub(r";\s*(using|with|in)\s+[^;.]{1,40}$", "", c, flags=re.I)
    c = re.sub(r"\s+as:\s+", " as ", c)
    c = re.sub(r"\s{2,}", " ", c)
    for bad, good in _TYPO.items():
        c = re.sub(bad, good, c, flags=re.I)
    return c.strip().rstrip(".")


def build_facts(row):
    """把一列 FReD 轉成本集事實庫。每個值都標明來源欄位。"""
    f = lambda k: (None if pd.isna(row.get(k)) else row.get(k))
    facts = {
        "claim": str(f("description") or "").strip().rstrip("."),
        "es_type": str(f("es_type_o") or "d").lower(),
        "orig": {"n": int(float(f("no"))), "es": round(float(f("eo")), 2),
                 "year": int(float(f("year_o"))) if f("year_o") else None,
                 "title": str(f("title_o") or "")[:120],
                 "author": str(f("author_o") or "")[:80],
                 "doi": str(f("doi_o") or ""),
                 "url": str(f("url_o") or "")},
        "repl": {"n": int(float(f("nr"))), "es": round(float(f("er")), 2),
                 "year": int(float(f("year_r"))) if f("year_r") else None,
                 "title": str(f("title_r") or "")[:120],
                 "doi": str(f("doi_r") or ""),
                 "url": str(f("url_r") or "")},
        "verdict": str(f("reported_success") or ""),
        # 顯著性:分開「測不出來」與「證明沒有」的唯一現成判準
        "p_repl": (float(f("pval_value_r"))
                   if f("pval_value_r") is not None else None),
        "p_type_repl": str(f("pval_type_r") or ""),
        # 🔴 單尾 p 值要換算成雙尾再比(2026-08-26 獨立驗證指出)。
        #    19 列裡有 1 列是單尾(ep016,0.115 → 雙尾約 0.23,結論不變),
        #    但只要哪一集的單尾 p 落在 0.025~0.05,tone_of 會判它顯著,
        #    定調就從 gone 翻成 shrunk_real,畫面直接打出
        #    「Smaller — but still there」。現在看不出來,擴到更多集就會出事。
        "p_tails_repl": str(f("pval_tails_r") or ""),
        "source": "FORRT Replication Database (FReD), OSF 2tbvd",
        # 「我們實際讀的那一列」——攤在畫面上比論文截圖更誠實,因為論文全文
        # 我根本沒讀過(出版社的反機器人保護擋住自動抓取,即使是 CC-BY)。
        "record": {
            "fred_id": str(f("fred_id") or ""),
            "effect_id": str(f("effect_id") or ""),
            "prereg": str(f("prereg_r") or ""),
        },
    }
    facts["n_ratio"] = round(facts["repl"]["n"] / max(1, facts["orig"]["n"]), 1)
    # 🔴 tone 要寫進 facts.json(2026-08-25 獨立驗證抓到第五次同型錯誤)。
    #    publish_meta 與 make_thumbs 走的是 CSV 的 `track`(HOLD/FALL)——
    #    那是一套**平行分類**,判定改成五分法時它沒跟著改,於是 ep005
    #    旁白說「效應存活」而縮圖用的是跟「沒撐住」那集一樣的橘色。
    #    同檔案內的 guard 結構上看不到別的檔案裡的平行分類,所以正解是
    #    讓 tone 成為唯一來源,而不是再加一道 guard。
    facts["tone"] = tone_of(facts)
    return facts


def size_phrase(es, kind):
    """畫面與旁白共用的說法。size_word 在最小那一檔回傳的是一整句
    (「below what the convention calls small」),後面再接 " effect" 會變成
    「below what the convention calls small effect」——不通。"""
    w = size_word(es, kind)
    return w if w.startswith("below") or w.startswith("essentially")         else w + " effect"


def thresholds(kind):
    """Cohen(1988)的慣例門檻,依效果量型別分軌。回傳 (小, 中, 大, 地板)。

    🔴 這張表是**唯一來源**。旁白、畫面刻度、size_word 都必須從這裡取 ——
    先前畫面那份自己寫死了 d 的 0.2/0.5/0.8,而 19 集裡有 6 集是 r 型,
    於是同一集裡耳朵聽到「zero point five is large」、眼睛看到 0.5 標著
    medium。**同型錯誤(修一份漏另一份)的第七次**,而且溯源守門結構上
    看不見它:旁白裡的門檻是英文字("zero point one"),抓數字的正則
    抓不到。
    """
    return (0.5, 0.3, 0.1, 0.03) if kind.startswith("r") else \
           (0.8, 0.5, 0.2, 0.05)


def size_word(es, kind):
    """Cohen(1988)的慣例門檻。說「按慣例算是大的」而不是斷言它就是大的。

    🔴 「小」之下要再分一層(2026-08-25)。舊版把 d=0.12 講成 essentially nothing,
    但那配上 N=6,608 多半是**統計上測得到、實務上很小**——講成「什麼都沒有」是
    過度打臉,而這個頻道的可信度全押在不過度打臉上。佇列裡 14/34 集落在這一帶,
    所以這不是邊角案例。真的可以說「幾乎是零」的門檻是 |d|<0.05。
    """
    a = abs(es)
    hi, mid, lo, floor = thresholds(kind)
    return ("large" if a >= hi else "medium" if a >= mid else "small" if a >= lo
            else "below what the convention calls small" if a >= floor
            else "essentially nothing")


def say_num(x):
    """讓 TTS 唸對小數:0.04 → 'zero point zero four'。

    🔴 負號要唸(2026-08-25)。舊版 abs() 讓 ep001(+0.27 → **−0.07**)、
    ep004(−0.54 → **+0.13**)、ep012(−0.37 → **+0.03**)這三集
    **方向翻轉**的重測,被唸成單純的數字變小。方向相反和變小是兩個結論。
    """
    out = ("minus " if x < 0 else "")
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
    out += words[whole] if whole in words else whole
    return out + " point " + " ".join(words[c] for c in frac)


# 每一種定調在畫面上對應的字。放在這裡而不是塞在 render_scene 裡面,
# 是因為**新增一種定調時,漏掉這張表會在渲染到一半才炸**。
#
# 🔴 實際發生過(2026-08-25):我把定調從三種擴成五種、也照規矩共用了
#    tone_of(),但收尾視覺卡的字典還留著舊的三個 key，於是三個 worker
#    各自跑了十分鐘的 TTS、渲染到最後一幕才 KeyError。
#    **集中「判定」不等於集中「用判定的地方」** —— 這是同型錯誤的第四次
#    (閘門兩份、縮圖兩份、判定兩份、現在是判定的消費端沒跟上)。
#    所以 build_script() 一開始就先查這張表,缺 key 立刻中止,不浪費 TTS。
CARD_TEXT = {
    "gone": "The effect did not survive.",
    "shrunk_real": "Smaller — but still there.",
    "flipped": "It reversed.",
    "held": "This one held up.",
    "stronger": "It came back larger.",
}

# 🔴 每一個「依定調而不同」的東西都放進這張表(2026-08-25,同型錯誤第六次)。
#
#    前五次我學到的是「共用判定」「消費端要跟上」,但每次都只補剛好爆掉的
#    那一個。第六次是 `pool = HOOKS_HELD if tone == "held" else HOOKS_FALL`
#    —— 新增的 stronger 掉進 FALL 池,於是一支「效果量回來更大」的片子,
#    開場是「It sounded plausible…」的打臉鋪陳。
#
#    所以改成:任何跟定調有關的分支都必須從這張表取值,不准再寫
#    `if tone == "..."`。新增一個定調時,漏填任何一欄都會 KeyError,
#    而且是在 build_script 一開頭就爆,不是渲染到最後一幕。
#
#    `bucket` 是給**別的檔案**用的三分類(縮圖顏色、標題句式)。三分不是
#    二分:shrunk_real 兩邊都不是,把它歸進 FALL 等於說它垮了(它的旁白
#    明講 not a debunking),歸進 HELD 又等於說它守住了(它掉了 73%)。
TONE_META = {
    "gone":        {"hooks": "fall", "bucket": "fail"},
    "flipped":     {"hooks": "fall", "bucket": "fail"},
    "shrunk_real": {"hooks": "fall", "bucket": "mixed"},
    "held":        {"hooks": "held", "bucket": "held"},
    "stronger":    {"hooks": "held", "bucket": "held"},
}


CLOSES_ALL = {
    "gone": [
        ("A bigger sample is not a guarantee of truth. But the filter runs "
         "one way: a study that finds nothing is harder to publish than one "
         "that finds something, so the first number to reach print is drawn "
         "from the lucky tail. That is publication bias — a property of the "
         "filter, not an accusation against anyone. "),
        ("The honest summary is not that the finding was fake. It is that "
         "with this many people, the effect cannot be told apart from zero. "
         "Those are different sentences, and only the second one is "
         "supported here. "),
        ("Small samples move around a lot. That is not a flaw in the "
         "original researchers — it is arithmetic. The fewer people you "
         "measure, the further a result can drift from the truth by chance "
         "alone. "),
    ],
    "shrunk_real": [
        ("So the effect is real, and it is much smaller than the first "
         "study said. Both halves of that sentence matter, and popular "
         "write-ups tend to carry only the first. "),
        ("This is the outcome that gets reported worst. It is not a "
         "debunking and it is not a confirmation — it is a correction of "
         "size. The direction survived; the magnitude did not. "),
    ],
    "flipped": [
        ("Read that again: the replication did not just fail to find the "
         "effect. It found one pointing the other way, and found it clearly "
         "enough to be unlikely by chance. "),
        ("A reversal is a stronger result than a null. It says the "
         "original description of what is going on may have had the sign "
         "backwards. "),
    ],
    "stronger": [
        ("So the replication did not just hold — it came back bigger than "
         "the original. That happens, and it is a useful reminder that "
         "a small first study is noisy in both directions, not only the "
         "flattering one. "),
        ("This is the shape nobody expects: the larger test found more, "
         "not less. Whatever else is going on here, it is not the story "
         "of a finding that evaporated. "),
    ],
    "held": [
        ("This one held up. That matters as much as the ones that don't, "
         "because a finding that survives a much larger test is one you can "
         "actually build on. "),
        ("Nothing dramatic happened here, and that is the point. The "
         "number moved a little and stayed where it was. Most of what you "
         "have heard about this field is about the findings that broke. "),
        ("So the original was, broadly, right. Worth saying out loud — a "
         "channel that only covered collapses would be giving you a "
         "distorted picture of the same evidence. "),
    ],
}


# ── 稿子(模板填空,數字不經 LLM)──────────────────────────────────
def tone_of(F):
    """由**數字**決定這一集的定調,verdict 欄位只是參考。

    🔴 這個函式存在的唯一理由是「不要有第二份實作」(2026-08-25)。
    先前旁白走三分法而收尾視覺卡走 `verdict != "failed" → held up` 的二分法,
    於是 ep005 旁白說「效應不在那裡」、畫面同時打出「This one held up」,
    ep008 更是畫面/旁白/標題三種說法。修好一份、漏掉另一份,是這個專案
    重複發生的模式(閘門兩份、縮圖兩份)——所以判定只能有一個來源。

    🔴 只看「縮多少」會把話講反(2026-08-25 獨立驗證抓到)。
    舊版只算 `|er|/|eo|`,於是:
    - **ep005**:r 從 0.82 掉到 0.22,比值 0.27 → 判 gone → 旁白說
      「效應不在那裡」。但同一列 CSV 寫著 **p < 0.001**(n=823),
      Fisher z 反算 95% CI = [0.156, 0.286],離零很遠。重測團隊登記
      successful 是因為他們**測到了**,不是「成功證明沒有」。
    - **ep004**:效果量從 −0.54 變成 **+0.13**,方向整個相反而且
      **p = 0.042 顯著**,舊版卻判 gone、講成「效應沒了」。

    「測不出來」和「證明沒有」是兩件事,分開它們的判準是**顯著性**,
    而 `pval_value_r` 就躺在同一個 CSV 裡(19 列有 18 列有值),
    產線卻從來沒讀過。方向也一樣要看:絕對值比會把「反向且大小相近」
    判成 held。
    """
    o, r = F["orig"], F["repl"]
    shrink = abs(r["es"]) / max(abs(o["es"]), 1e-6)
    same_sign = (o["es"] >= 0) == (r["es"] >= 0)
    p = F.get("p_repl")
    if p is not None and "1" in str(F.get("p_tails_repl", "")):
        p = min(1.0, p * 2)                   # 單尾 → 雙尾
    sig = p is not None and p < 0.05          # 缺 p 值時視為測不出來(保守)
    if not same_sign:
        return "flipped" if sig else "gone"
    if shrink > 1.15:
        # 🔴 held 原本沒有上限。ep011 是 0.37 → 0.65(shrink 1.75,效果量
        #    幾乎翻倍),卻抽到「The number moved a little and stayed where
        #    it was」——而同一集前兩句才說它從 small 變成 medium。
        return "stronger"
    if shrink > 0.7:
        return "held"
    return "shrunk_real" if sig else "gone"


def _sig(x):
    """畫面上的數字要帶負號(2026-08-25)。

    🔴 縮圖印 -0.25、影片印 0.25 —— 同一個數字在兩個地方長得不一樣。
    在相關係數這裡負號不是小數點後的細節,它是方向:「負相關」和「正相關」
    是相反的結論。長條的**長度**仍用絕對值(長度表示強度),方向交給符號。
    """
    return f"{x:.2f}" if x >= 0 else "−" + f"{abs(x):.2f}"


def is_doi(v):
    """真的是 DOI 才算。FReD 有些列的 DOI 欄放的是內部鍵值(wiebe_2004),
    有些是空的(pandas 讀成 nan)——兩種都會被印成對外文案裡的假引用。"""
    v = str(v or "").strip().lower()
    return v.startswith("10.") or "doi.org/10." in v


def cite_of(side):
    """畫面上要印的來源。DOI 優先,沒有就退到 url —— 兩者都是可查證的引用,
    而 fail-closed 的判準是「有沒有可查證的來源」,不是「有沒有 DOI」。
    跟 publish_meta.cite_of 是同一套判準,兩邊要一致。"""
    d = side.get("doi")
    if is_doi(d):
        return "doi:" + str(d).replace("https://doi.org/", "")
    u = str(side.get("url") or "").strip()
    if u.startswith(("http://", "https://")) and "." in u:
        # ⚠️ 不要截斷。舊版收尾卡對 DOI 做 [:60],而 ep007 的 DOI 是 63 字元
        #    ——螢幕上那個 DOI 貼進瀏覽器會 404。半個 DOI 比沒有 DOI 更糟,
        #    因為它看起來是可查證的。太長就縮字級,不砍字。
        return u.replace("https://", "").replace("http://", "")
    return None


def build_script(F):
    o, r = F["orig"], F["repl"]
    kind = F["es_type"]
    big, small = size_word(o["es"], kind), size_word(r["es"], kind)
    claim = speakable(F["claim"])
    claim = claim[0].upper() + claim[1:] if claim else claim
    verdict = F["verdict"].lower()

    # 🔴 收尾必須由**數字**決定,不能只看 verdict 欄位:
    #    實測第 3 集 verdict='mixed' 但 0.85→0.07,舊模板卻說「This one held up」,
    #    旁白與畫面上的長條圖直接矛盾。凡是宣稱都要能被畫面驗證。
    tone = tone_of(F)
    # 下游每一張以 tone 為 key 的表都要有它,否則現在就中止——
    # 不要等到跑完十分鐘 TTS、渲染到最後一幕才 KeyError。
    missing = [n for n, tbl in (("CARD_TEXT", CARD_TEXT),
                                ("TONE_META", TONE_META),
                                ("CLOSES", CLOSES_ALL))
               if tone not in tbl]
    if missing:
        raise SystemExit(f"⛔ 定調 {tone!r} 在 {missing} 裡沒有對應文字。"
                         f"新增定調時這些表都要一起補。")

    # 收尾:每個 tone 有多種寫法,依本集資料挑一個(不是隨機——同一集
    # 重跑要得到同一句)。獨立驗證量測到 90% 的旁白逐字相同,而 YouTube 的
    # inauthentic 政策點名的正是「模板化、變化極小」。變化度要從這裡長出來。
    #
    # ⚠️ 這裡一度寫著「A small study **only** gets published if it finds
    #    something」「the first number published is **usually** the luckiest」
    #    「this **keeps happening** in one direction」——三句都是**我沒有計算過的
    #    頻率宣稱**,而且是片中唯一不能溯源的部分。改成講機制,不講頻率。
    CLOSES = CLOSES_ALL
    close_txt = CLOSES[tone][(o["year"] + r["n"]) % len(CLOSES[tone])]

    # 🔴 開場要分軌(2026-08-25):舊版一律用「It sounded plausible」起手,
    #    那是在預告要打臉。用在 HOLD 集上等於掉包觀眾。
    #
    #    ⚠️ HOLD 開場一度寫成「Most findings from that era did not survive」——
    #    那是斷言一個我沒計算的基準率。就算拿 FReD 去算也不能講:348 列是篩過的
    #    子集,拿它當「那個年代的心理學」的比例就是拿替身值當真值。
    # 🔴 開場先給落差,不要先給主張(2026-08-28)。
    #    舊版前 15 秒還在鋪陳「某年某研究說了什麼」,而這個頻道最強的鉤子
    #    **就是那個落差本身** —— 兩個數字並排就是全部的戲,而且它可驗證。
    #    記憶裡有實測:非碎句、直接給結論的開場讓訂閱轉化翻倍、完播率
    #    24.6% vs 17.1%。長片尤其吃這個,因為觀眾在前 30 秒決定去留。
    #
    #    ⚠️ 不能因為想要戲劇性就把話講重。開場只陳述兩組數字與樣本數,
    #    判決留給後面的段落 —— 那裡才有信賴區間與顯著性可以撐。
    ratio = F["n_ratio"]
    HOOKS_FALL = [
        (f"{o['n']:,} people. That is how many it took to establish this: "
         f"{claim}. "
         f"Then {r['n']:,} people — {ratio} times as many — were put through "
         f"the same study."),
        (f"In {o['year']}, {o['n']:,} people produced an effect of "
         f"{say_num(o['es'])}. "
         f"In {r['year'] or 'a later study'}, {r['n']:,} people produced "
         f"{say_num(r['es'])}. "
         f"Same claim, same design: {claim}."),
        (f"Here is a finding you may have heard: {claim}. "
         f"It came from {o['n']:,} people. "
         f"It has since been run on {r['n']:,}."),
    ]
    HOOKS_HELD = [
        (f"{o['n']:,} people said this: {claim}. "
         f"Then {r['n']:,} people — {ratio} times as many — were asked the "
         f"same question. Most findings do not come back the same. "
         f"Watch this one."),
        (f"In {o['year']}, {o['n']:,} people produced an effect of "
         f"{say_num(o['es'])}. "
         f"On {r['n']:,} people it came back {say_num(r['es'])}. "
         f"The claim: {claim}."),
    ]
    pool = {"held": HOOKS_HELD, "fall": HOOKS_FALL}[TONE_META[tone]["hooks"]]
    hook_txt = pool[(o["year"] + o["n"]) % len(pool)]

    # 🔴 慣例門檻依效果量**型別**分軌。r 的慣例是 .1/.3/.5,d 是 .2/.5/.8。
    #    舊版旁白寫死 d 的門檻,而 size_word() 用的是正確的 r 門檻,於是
    #    ep002 在同一集裡自打嘴巴:先說「0.5 是中等」,四十秒後說 0.30 是中等。
    #    而且「how far apart two groups are」是 d 的定義,對相關係數是錯的。
    is_r = kind.startswith("r")
    # 🔴 scale 段一度 19 集一字不差,佔每支片 20 秒 = 全片的 20%(獨立驗證
    #    量到「90% 旁白逐字相同」時,這一段是最大的單一來源)。而 YouTube 的
    #    inauthentic 政策點名的正是「模板化、變化極小」。
    #
    #    解法不是換句話說同一件事 —— 那還是同一件事。是**依本集自己的數字
    #    選一個真的相關的切角**:原始樣本特別小就講小樣本為什麼會漂;
    #    落差特別大就講那個落差有多大;是相關係數就講相關不等於因果。
    #    每一種都是這一集真的需要的解釋,不是填充。
    SCALE_R = (
        "A correlation is how tightly two things move together — not whether "
        "one causes the other. Around zero point one is small, zero point "
        "three is medium, zero point five is large.")
    SCALE_D = (
        "Effect size is not whether something is true. It is how far apart "
        "two groups are. Around zero point two is small, zero point five is "
        "medium, zero point eight is large.")
    base = SCALE_R if is_r else SCALE_D
    # ⚠️ 第一版的 `o["n"] <= 100` 一條就吃掉 19 集裡的 12 集(實測 scale 段
    #    最大宗佔 47%,而它是全片最長的一段)。再切的條件都綁本集數字。
    if o["n"] <= 70 and abs(o["es"]) >= 0.5:
        # 這不是隨便挑的切角,是檢定力的直接後果:樣本越小,能被測到並
        # 通過顯著門檻的效應就必須越大。所以「小樣本 + 大效果量」這個
        # 組合本身就告訴你,你看到的是能穿過那道篩子的那一種數字。
        angle = (f"Those two numbers sit oddly together. With {o['n']} people, "
                 f"only a fairly large effect could have cleared the "
                 f"significance threshold at all — so a small study reporting "
                 f"{say_num(o['es'])} is exactly the shape of result that gets "
                 f"through that filter.")
    elif o["n"] <= 70:
        angle = (f"{o['n']} people is a small study. That does not make it "
                 f"wrong, but it does mean the number it produced had a wide "
                 f"range of places it could have landed.")
    elif o["n"] <= 100:
        angle = (f"And with only {o['n']} people in the original, that number "
                 f"had a lot of room to move by chance. Small samples do not "
                 f"just give you less certainty — they give you a wider spread "
                 f"of possible answers, in both directions.")
    elif F["n_ratio"] >= 20:
        angle = (f"Keep the sample sizes in mind too. The replication is "
                 f"{F['n_ratio']} times larger, and that is what makes the "
                 f"second number the harder one to argue with.")
    elif abs(o["es"]) >= 0.6:
        angle = ("A number that large is unusual in this field. That is worth "
                 "knowing before we look at what happened next.")
    else:
        angle = ("And the smaller the study, the more that number can move by "
                 "chance alone.")
    # 開場那一句原本 19 集一字不差,等於在骨架比對上把所有 scale 段綁在
    # 一起。依本集的量型換說法 —— 唸的是不同的東西,說法本來就該不同。
    opener = ("Before the second number, one line on what a correlation is. "
              if is_r else
              f"One line on what {say_num(o['es'])} means, "
              f"because the rest of this depends on it. ")
    scale_txt = opener + base + " " + angle

    # 結果段:顯著性決定能不能說「效應在那裡」。
    # ⚠️ 這裡一度寫著「what they successfully showed is that the effect is not
    #    there」——ep005 的 p < 0.001,那句話是**講反**,不是講重。
    res = f"The effect they measured was {say_num(r['es'])}. "
    res += (f"That is {small}. " if small != "essentially nothing"
            else "That is, essentially, nothing. ")
    res += f"The original number was {say_num(o['es'])}. "
    p = F.get("p_repl")
    if tone == "flipped":
        res += ("Notice the sign. It did not shrink towards zero — it crossed "
                "over, and the replication reports that as statistically "
                "significant.")
    elif tone == "shrunk_real":
        res += ("And it is still there: the replication reports this as "
                "statistically significant. The effect survived. Its size "
                "did not.")
    elif tone in ("held", "stronger") and p is not None and p < 0.05:
        res += ("And the replication reports it as statistically significant "
                "— on this many people, that is a much harder number to "
                "dismiss than the original.")
    elif tone == "gone" and p is not None:
        # ⚠️ 一度寫「what you would expect from chance alone」——p ≥ .05 的
        #    意思是**與零區分不開**,不是「就是隨機」。同一集的 close 池裡
        #    早就有正確的措辭,這裡卻用了比較強的那個。
        res += ("With this many people, an effect this size cannot be told "
                "apart from zero.")
    # 「證據攤開來」那一幕。它做三件事:讓觀眾看到我們的來源長什麼樣、
    # 給每一集獨一無二的畫面(獨立驗證量到 90% 旁白逐字相同)、把片長拉長。
    rec = F.get("record", {})
    # record 段也依本集實際有什麼而變 —— 有預先登記就講預先登記(那是這條
    # 產線最硬的證據),沒有就講資料庫本身。硬講同一段話是模板化,而且會
    # 講到本集沒有的東西。
    pre = rec.get("prereg", "").startswith("http")
    # 🔴 分支條件要**細到足以真的分開**。第一版只有三條(有預登+大倍數 /
    #    有預登 / 沒預登),而 19 集裡 18 集有預登、大多數倍數不到 10 ——
    #    結果 14 支裡有 12 支拿到逐字相同的那一段(實測 86%)。那正是 YPP
    #    inauthentic 政策點名的「模板化、變化極小」。
    #    分法一律綁**本集真的有的事實**,不是亂數:亂數是假的多樣性,
    #    而且不可重現。
    if pre and F["n_ratio"] >= 10:
        body = (f"The replication was preregistered — the team wrote down what "
                f"they were going to test before they collected a single data "
                f"point, and then tested it on {r['n']:,} people. "
                f"That order matters: it is what stops a study from finding "
                f"whatever it happens to find and calling that the hypothesis.")
    elif pre and o["n"] <= 80:
        body = (f"The replication was preregistered. That matters most here, "
                f"because the original ran on {o['n']:,} people — at that size, "
                f"there are a lot of ways to slice a result, and writing the "
                f"analysis down first removes all of them.")
    elif pre and abs(r["es"]) < 0.1:
        body = ("The replication was preregistered, which is why this null is "
                "worth something. A study designed to find an effect and then "
                "not finding one is evidence. A study that went looking for "
                "any effect at all would not be.")
    elif pre and r["n"] >= 500:
        body = (f"The replication was preregistered and it is not small: "
                f"{r['n']:,} people, with the design and the analysis both "
                f"filed before anyone was recruited.")
    elif pre:
        body = ("The replication was preregistered. The team wrote down what "
                "they were going to test before they collected any data, so "
                "the analysis could not be chosen after seeing the result.")
    else:
        body = ("Both papers are linked, and so is the row itself — the "
                "database is public, and it carries the same fields you have "
                "been looking at on screen.")
    lead = ("Everything you just heard comes from one row of a public "
            "database. Here it is. " if F["n_ratio"] < 5 else
            "None of this is my reading of the papers. It is one row of a "
            "public database, and this is the row. ")
    tail = (" You do not have to take my word for any of it."
            if o.get("doi") and r.get("doi") else
            " Both papers are linked below, so you can check it yourself.")
    record_txt = lead + body + tail

    segs = [("hook", hook_txt),
            ("original",
             f"The study was run on {o['n']:,} people. "
             f"The effect it measured was {say_num(o['es'])} — "
             f"by the usual convention, "
             + (f"a {big} effect." if not big.startswith(("below", "essentially"))
                else f"that is {big}.")),
            ("scale", scale_txt),
            # 🔴 這一段原本 19 集**逐字同一個骨架**(實測 100%),只有數字
            #    在換。跟 record 一樣,分支綁本集真的有的事實。
            ("replication", _replication_txt(F, o, r, rec)),
            ("result", res),
            ("record", record_txt),
            ("close", close_txt + "Both papers are linked below.")]
    return segs


def _replication_txt(F, o, r, rec):
    """「他們又跑了一次」那一段。

    ## 為什麼要分這麼多支
    這一段原本只有一種寫法,19 集把數字抽掉之後**骨架完全相同**。單集看
    沒問題,但整個頻道就是同一句話講 19 遍,而那是 YPP inauthentic 政策
    白紙黑字點名的「模板化、變化極小、可大規模複製」。

    每一支的選擇條件都是**本集真的有的事實**(年份差、倍數、絕對人數、
    是不是多實驗室),不是亂數 —— 亂數看起來也是多樣,但它不可重現,
    而且會把「講哪一件事」跟「這一集實際是什麼」脫鉤。
    """
    n, ratio = r["n"], F["n_ratio"]
    yr_o, yr_r = o.get("year"), r.get("year")
    title = (r.get("title") or "").lower()
    multi = any(k in title for k in ("multi-lab", "multilab", "many labs",
                                     "multiple laborator"))
    if multi:
        return (f"Then it was run again — not by one team, but by several, "
                f"each following the same written protocol. "
                f"{n:,} people in total, {ratio} times the original.")
    # ⚠️ 分支順序決定分佈。第一版把「年份差」排第二,結果它一條就吃掉
    #    19 集裡的 14 集(句子不同但骨架一樣),等於白分。**最有辨識度的
    #    條件要排前面**,泛用的當收尾。
    #    es_type 排第二不只是為了分散:相關係數和組間差本來就是兩種不同的
    #    量,講「同一個相關」比講「同一個研究」更準確。
    if F.get("es_type") == "r":
        return (f"Another team measured the same correlation again, this time "
                f"across {n:,} people — {ratio} times the original sample, "
                f"with the same two variables.")
    if ratio >= 20:
        return (f"Then someone ran it again at {ratio} times the scale. "
                f"Not a variation on the design — the same study, "
                f"put to {n:,} people.")
    if n >= 1000:
        return (f"So another team ran it again, and this one is not small: "
                f"{n:,} people went through the same procedure.")
    if ratio < 3:
        return (f"Another team ran the same study again with {n:,} people. "
                f"That is {ratio} times the original — not a huge jump, "
                f"but the design did not change, so the two numbers are "
                f"measuring the same thing.")
    # ⚠️ 到這裡還有一大半集數會落在同一句。再切的條件必須是**看得到、
    #    但還沒洩漏結果**的事實 —— 樣本大小、相關係數還是組間差、原研究
    #    的年代。**不能用 tone 去切**:那會在 result 段之前就把判決講出來。
    if o["n"] <= 60:
        return (f"The original had {o['n']:,} people. The replication had "
                f"{n:,} — same materials, same procedure, "
                f"{ratio} times the participants.")
    if o.get("year") and o["year"] < 2005:
        return (f"The original is from {o['year']}. The re-test used the same "
                f"design on {n:,} people, {ratio} times as many, and it is the "
                f"version we can actually check.")
    if n - o["n"] >= 400:
        return (f"Then the same study was put to {n:,} people, against "
                f"{o['n']:,} the first time. "
                f"Nothing about the design changed.")
    # 🔴 **唸出口的數字必須是事實庫裡查得到的原值**,不能是推導出來的。
    #    分支的**條件**可以用差值(那不會被唸出來),但句子裡不行。
    #    第一版寫「{yr_r - yr_o} years later」「{n - o['n']} more than the
    #    first time」—— 溯源守門把 19 集裡的 10 集擋下,擋得完全正確:
    #    那些數字在事實庫裡找不到對應欄位。年份差改成直接講那一年。
    if yr_o and yr_r and yr_r - yr_o >= 5:
        return (f"In {yr_r}, another team ran the same study. "
                f"Same design, same measure — {n:,} people this time, "
                f"{ratio} times as many.")
    return (f"So another team ran the same study again. "
            f"This time with {n:,} people — {ratio} times the original "
            f"sample. Same design. More people.")


def audit(segs, F):
    """稿中每個數字都必須能從事實庫反推,否則阻擋。"""
    allowed = set()
    for v in (F["orig"]["n"], F["repl"]["n"], F["orig"]["year"], F["repl"]["year"]):
        if v is not None:
            allowed |= {str(v), f"{v:,}"}
    allowed.add(str(F["n_ratio"]))
    # 主張原文本身帶的數字是**來源欄位逐字帶過來的**,不是我產生的 → 放行。
    # 審核的目的是擋「我編出來的數字」,不是擋引用。
    allowed |= set(re.findall(r"\b\d[\d,\.]*\b", F["claim"]))
    for v in (F["orig"]["es"], F["repl"]["es"]):
        allowed |= {f"{abs(v):.2f}", f"{abs(v):g}"}
    bad = []
    for name, text in segs:
        for tok in re.findall(r"\b\d[\d,\.]*\b", text):
            if tok not in allowed:
                bad.append((name, tok))
    return bad


# ── 畫面 ────────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fam in ("Segoe UI", "Arial", "DejaVu Sans"):
        if any(fam.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams.update({"text.color": FG, "axes.labelcolor": DIM,
                         "xtick.color": DIM, "ytick.color": DIM})
    return plt


def ease(x):
    return x * x * (3 - 2 * x)


def wrap(s, n):
    out, line = [], ""
    for w in s.split():
        if len(line) + len(w) + 1 > n:
            out.append(line); line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def render_scene(plt, name, t, dur, F):
    o, r = F["orig"], F["repl"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(BG)

    if name == "hook":
        lines = wrap(F["claim"] + ".", 44)[:4]
        for i, ln in enumerate(lines):
            st = 0.3 + i * 0.65
            if t > st:
                q = ease(min(1.0, (t - st) / 1.3))
                ax.text(0.5, 0.66 - i * 0.10, ln, ha="center", va="center",
                        fontsize=52, color=FG, alpha=q, weight="bold")
        if t > dur * 0.62:
            q = ease(min(1.0, (t - dur * 0.62) / 1.3))
            ax.text(0.5, 0.24, f"{o['author'].split(',')[0]}, {o['year']}",
                    ha="center", fontsize=24, color=DIM, alpha=q)

    elif name == "scale":
        # 🔴 門檻**依效果量型別分軌**,而且從 thresholds() 取 —— 這裡曾經
        #    寫死 d 的 0.2/0.5/0.8,而佇列 19 集裡有 6 集是 r 型,於是同一
        #    集裡旁白唸「zero point five is large」、畫面把 0.5 標成 medium。
        hi, mid, lo, _fl = thresholds(F.get("es_type", "d"))
        marks = [(lo, "small"), (mid, "medium"), (hi, "large")]
        # 🔴 這一幕有 20 多秒,而第一版的軸只佔畫面 16% 高、字級 16~20pt ——
        #    抽幀看成品時,整幕**大部分是黑的**。它叫「What the number
        #    means」,是全片唯一解釋效果量的地方,不該是最空的一幕。
        #    軸拉高到 30%、字級全部放大,標題與副標往下靠近軸收掉上方留白。
        ax2 = fig.add_axes([0.12, 0.28, 0.76, 0.30]); ax2.set_facecolor(BG)
        for sp in ("top", "right", "left"):
            ax2.spines[sp].set_visible(False)
        ax2.spines["bottom"].set_color("#2A2F36")
        ax2.set_yticks([])
        ax2.set_xlim(0, max(hi * 1.3, abs(o["es"]) * 1.15))
        # 🔴 **ylim 必鎖**。文字先畫(當時 ylim 還是預設 0~1),後面
        #    `ax2.scatter([es], [0])` 會觸發自動縮放把 ylim 壓成 ±0.055,
        #    於是畫在 y=0.55 和 y=-0.75 的 small/medium/large 與「this
        #    study」**整組被擠出畫布**。19 集全中、10 支已發布,而那一幕
        #    的標題正是「What the number means」—— 觀眾看到三條沒有標籤
        #    的虛線,什麼也沒說明。
        #    這是「全版面 axes 被 autoscale 裁掉文字」的**第二個現場**,
        #    第一個早就修好了 —— 又是同一份修改只套了一半。
        ax2.set_ylim(-1, 1)
        ax2.set_xlabel("effect size", fontsize=26, labelpad=16)
        ax2.tick_params(labelsize=22)
        p = ease(min(1.0, t / (dur * 0.5)))
        xmax = ax2.get_xlim()[1]
        for v, lab in marks:
            if p > v / xmax:
                ax2.axvline(v, color=DIM, lw=1.6, ls=(0, (4, 4)))
                ax2.text(v, 0.62, lab, ha="center", fontsize=30, color=DIM)
        if t > dur * 0.6:
            q = ease(min(1.0, (t - dur * 0.6) / 1.3))
            ax2.scatter([abs(o["es"])], [0], s=520, color=FG, zorder=5, alpha=q)
            # ⚠️ 值落在門檻線上時(ep006 的 0.80 正好等於 large),「this
            #    study」會跟門檻標籤疊在一起。往離最近門檻的反方向讓開。
            near = min(marks, key=lambda mv: abs(mv[0] - abs(o["es"])))[0]
            xmax2 = ax2.get_xlim()[1]
            shift = (0.045 if abs(near - abs(o["es"])) < xmax2 * 0.06
                     else 0.0) * xmax2 * (1 if abs(o["es"]) <= near else -1)
            ax2.text(abs(o["es"]) - shift, -0.62, "this study", ha="center",
                     fontsize=28, color=FG, weight="bold", alpha=q)
        fig.text(0.12, 0.80, "What the number means", fontsize=54,
                 color=FG, weight="bold")
        fig.text(0.12, 0.72, "Smaller studies swing further by chance.",
                 fontsize=30, color=DIM)

    elif name in ("original", "replication"):
        cur = o if name == "original" else r
        label = "THE ORIGINAL STUDY" if name == "original" else "THE REPLICATION"
        col = DIM if name == "original" else ACCENT
        ax.text(0.5, 0.80, label, ha="center", fontsize=26, color=col,
                weight="bold", alpha=ease(min(1.0, t / 1.0)))
        if t > 1.0:
            q = ease(min(1.0, (t - 1.0) / 1.4))
            shown = int(cur["n"] * q)
            ax.text(0.5, 0.58, f"{shown:,}", ha="center", fontsize=118,
                    color=FG, weight="bold")
            ax.text(0.5, 0.47, "participants", ha="center", fontsize=30, color=DIM)
        if t > dur * 0.55:
            q = ease(min(1.0, (t - dur * 0.55) / 1.3))
            ax.text(0.5, 0.31, f"{F['es_type']} = {_sig(cur['es'])}",
                    ha="center", fontsize=52, color=col, weight="bold", alpha=q)
            ax.text(0.5, 0.23, size_phrase(cur["es"], F["es_type"]),
                    ha="center", fontsize=24, color=DIM, alpha=q)

    elif name == "result":
        ax2 = fig.add_axes([0.16, 0.30, 0.68, 0.36]); ax2.set_facecolor(BG)
        for s in ("top", "right", "left"):
            ax2.spines[s].set_visible(False)
        ax2.spines["bottom"].set_color("#2A2F36")
        mx = max(abs(o["es"]), abs(r["es"])) * 1.25
        p = ease(min(1.0, t / (dur * 0.5)))
        ax2.barh([1], [abs(o["es"]) * p], height=0.42, color=DIM)
        ax2.barh([0], [abs(r["es"]) * p], height=0.42, color=WARN)
        ax2.set_yticks([1, 0])
        ax2.set_yticklabels([f"original\n{o['n']:,} people",
                             f"replication\n{r['n']:,} people"], fontsize=19)
        # ⚠️ ylim 一併鎖死。這一幕目前是安全的(文字畫在 y=1 與 y=0,正好
        #    等於 barh 的位置,autoscale 出來的 (-0.28, 1.28) 蓋得住),但
        #    「文字被 autoscale 擠出畫布」這個 pattern 在這條線已經咬過兩次,
        #    補一行是零成本的保險。
        # 數值刻意等於 autoscale 本來就會算出來的那一組(barh 在 y=0/1、
        # height=0.42 → 資料範圍 −0.21~1.21,加 5% 邊距):**鎖住但不改變
        # 畫面**,所以這行可以在批次渲染中途加進來而不會讓前後集數長得不一樣。
        ax2.set_ylim(-0.281, 1.281)
        ax2.set_xlim(0, mx); ax2.set_xlabel(f"effect size ({F['es_type']})",
                                            fontsize=19, labelpad=12)
        ax2.tick_params(labelsize=16)
        ax2.text(abs(o["es"]) * p, 1, f"  {_sig(o['es'])}", va="center",
                 fontsize=26, color=FG, weight="bold")
        if t > dur * 0.45:
            ax2.text(abs(r["es"]) * p, 0, f"  {_sig(r['es'])}", va="center",
                     fontsize=26, color=WARN, weight="bold")
        fig.text(0.16, 0.80, "Same study. Bigger sample.", fontsize=44,
                 color=FG, weight="bold")

    elif name == "record":
        # 「我們讀的那一列」。刻意做成資料表的樣子而不是美術:它要看起來像
        # 一筆可以自己去查的紀錄,不是像一張投影片。每個值都必須是旁白唸過、
        # 而且審核放行過的數字 —— 這一幕不引入任何新數字。
        rec = F.get("record", {})
        kind = F["es_type"]
        ax.text(0.5, 0.90, "The record this episode is built from",
                ha="center", fontsize=34, color=FG, weight="bold")
        ax.text(0.5, 0.845, F["source"], ha="center", fontsize=20, color=DIM)

        cols = (0.30, 0.68)
        heads = ("ORIGINAL", "REPLICATION")
        rows = [
            ("participants", f"{o['n']:,}", f"{r['n']:,}"),
            (f"effect size ({kind})", _sig(o["es"]), _sig(r["es"])),
            ("year", str(o["year"] or "—"), str(r["year"] or "—")),
        ]
        pv = F.get("p_repl")
        if pv is not None:
            tail = " (one-tailed)" if "1" in str(F.get("p_tails_repl", "")) else ""
            rows.append(("p-value", "—", f"{pv:g}{tail}"))

        for cx, h, col in zip(cols, heads,
                              (DIM, ACCENT if tone_of(F) != "gone" else WARN)):
            if t > 0.4:
                ax.text(cx, 0.74, h, ha="center", fontsize=24, color=col,
                        weight="bold", alpha=ease(min(1.0, (t - 0.4) / 0.9)))
        for i, (label, a_, b_) in enumerate(rows):
            y = 0.65 - i * 0.085
            st = 0.9 + i * 0.55
            if t <= st:
                continue
            q = ease(min(1.0, (t - st) / 0.9))
            ax.text(0.055, y, label, ha="left", fontsize=23, color=DIM, alpha=q)
            ax.plot([0.05, 0.95], [y - 0.032, y - 0.032], color="#1B222C",
                    lw=1.2, alpha=q)
            ax.text(cols[0], y, a_, ha="center", fontsize=30, color=FG, alpha=q,
                    weight="bold")
            ax.text(cols[1], y, b_, ha="center", fontsize=30, color=FG, alpha=q,
                    weight="bold")

        pre = rec.get("prereg", "")
        if pre.startswith("http") and t > 0.9 + len(rows) * 0.55:
            q = ease(min(1.0, (t - (0.9 + len(rows) * 0.55)) / 1.1))
            ax.text(0.5, 0.235, "preregistered before data collection",
                    ha="center", fontsize=25, color="#5FC98A", alpha=q,
                    weight="bold")
            ax.text(0.5, 0.175,
                    pre.replace("https://", "").replace("http://", "")[:48],
                    ha="center", fontsize=21, color=ACCENT, alpha=q * 0.9)
        if rec.get("fred_id") and t > 1.6:
            q = ease(min(1.0, (t - 1.6) / 1.1))
            ax.text(0.5, 0.09, f"FReD record {rec['fred_id']}", ha="center",
                    fontsize=18, color=DIM, alpha=q * 0.75)

    else:  # close
        # 用同一份 tone_of,不要在這裡重寫判斷(見 tone_of 的說明)
        msg = CARD_TEXT[tone_of(F)]
        if t > 0.5:
            q = ease(min(1.0, (t - 0.5) / 1.3))
            ax.text(0.5, 0.66, msg, ha="center", fontsize=48, color=FG,
                    alpha=q, weight="bold")
        if t > 3.0:
            q = ease(min(1.0, (t - 3.0) / 1.4))
            ax.text(0.5, 0.46, "Every number in this video comes from",
                    ha="center", fontsize=22, color=DIM, alpha=q)
            ax.text(0.5, 0.40, "the published replication record.",
                    ha="center", fontsize=22, color=DIM, alpha=q)
            shown = 0
            for side in (o, r):
                c = cite_of(side)
                if c:
                    ax.text(0.5, 0.30 - shown * 0.055, c, ha="center",
                            fontsize=18 if len(c) <= 46 else 14,
                            color=ACCENT, alpha=q * 0.9)
                    shown += 1
            if shown < 2:
                ax.text(0.5, 0.30 - shown * 0.055,
                        "(one source has no citation recorded in the database)",
                        ha="center", fontsize=17, color=DIM, alpha=q * 0.8)
            ax.text(0.5, 0.15, F["source"], ha="center", fontsize=16,
                    color=DIM, alpha=q * 0.7)
    return fig


# ── 主流程 ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    ap.add_argument("--voice", default="am_michael")
    a = ap.parse_args()

    q = pd.read_csv(QUEUE)
    if a.list or a.row is None:
        print(f"佇列 {len(q)} 集:")
        for i, (_, r) in enumerate(q.head(25).iterrows()):
            print(f"  {i:>3}. {abs(float(r['eo'])):.2f}→{abs(float(r['er'])):.2f}  "
                  f"N {int(float(r['no']))}→{int(float(r['nr']))}  "
                  f"{str(r['description'])[:64]}")
        return 0

    row = q.iloc[a.row]
    F = build_facts(row)
    segs = build_script(F)
    bad = audit(segs, F)
    if bad:
        print("⛔ 稿中有事實庫查無來源的數字:", bad)
        return 1
    slug = f"ep{a.row:03d}"
    out = ROOT / "eps" / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "facts.json").write_text(json.dumps(F, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    words = sum(len(t.split()) for _, t in segs)
    print(f"[{slug}] {F['claim'][:66]}")
    print(f"  {F['es_type']} {abs(F['orig']['es']):.2f}→{abs(F['repl']['es']):.2f}  "
          f"N {F['orig']['n']:,}→{F['repl']['n']:,}  判定 {F['verdict']}")
    print(f"  稿 {words} 字 ≈ {words / 155 * 60:.0f} 秒   數字溯源 ✓")
    for name, text in segs:
        (out / f"narr_{name}.txt").write_text(text, encoding="utf-8")
    if a.script_only:
        for name, text in segs:
            print(f"\n  [{name}] {text}")
        return 0

    # 旁白(3.11 venv 跑 Kokoro)
    # 🔴 每集一個獨立的暫存腳本(2026-08-26)。舊版寫死 `_tts_ep.py`,
    #    三個 worker 並行時會互相覆蓋:A 寫好指向 ep015 的腳本、B 覆蓋成
    #    指向 ep017,A 的子程序讀到 B 的內容 → 音檔產到 ep017 去,ep015
    #    的 seg_*.wav 從來沒出現過。實測 ep015 就是這樣掛的。
    #    (它至少是**大聲失敗**——下一步開 wav 就 FileNotFoundError,
    #     不會靜默配上別集的聲音。)
    tts = out / "_tts_ep.py"
    tts.write_text(
        "import sys, pathlib, soundfile as sf\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "from kokoro_onnx import Kokoro\n"
        f"out = pathlib.Path(r'{out}')\n"
        "k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')\n"
        # 🔴 段落名從 segs 推導,不寫死:先前加了 scale 段卻沒同步,
        #    整條產線到混音階段才炸(seg_scale.wav 不存在)。
        f"for n in {tuple(n for n, _ in segs)!r}:\n"
        "    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()\n"
        f"    s, sr = k.create(t, voice='{a.voice}', speed=0.98, lang='en-us')\n"
        "    sf.write(out / f'seg_{n}.wav', s, sr)\n"
        "    print(f'  {n:<12}{len(s)/sr:6.1f}s', flush=True)\n",
        encoding="utf-8")
    subprocess.run([str(REPO / "_ttslab311" / "Scripts" / "python.exe"), str(tts)],
                   check=True, cwd=str(REPO))

    plt = _plt()
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    for p in frames.glob("*.png"):
        p.unlink()
    idx, durs, parts, sr = 0, [], [], 24000
    for name, _ in segs:
        with wave.open(str(out / f"seg_{name}.wav")) as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
            nch = w.getnchannels()
            dur = w.getnframes() / sr + 0.7
        x = np.frombuffer(raw, np.int16)
        if nch > 1:
            x = x.reshape(-1, nch).mean(axis=1).astype(np.int16)
        parts.append(np.concatenate([x, np.zeros(max(0, int(dur * sr) - len(x)),
                                                 np.int16)]))
        durs.append(dur)
        for i in range(int(dur * FPS)):
            fig = render_scene(plt, name, i / FPS, dur, F)
            fig.savefig(frames / f"f{idx:05d}.png", facecolor=BG, dpi=100)
            plt.close(fig)
            idx += 1
        print(f"  畫面 {name:<12}{dur:5.1f}s")
    with wave.open(str(out / "voice.wav"), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.concatenate(parts).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(frames / "f%05d.png"), "-i", str(out / "voice.wav"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart",
                    str(out / f"{slug}.mp4")], check=True)
    for p in frames.glob("*.png"):
        p.unlink()
    frames.rmdir()
    print(f"完成 → {out / (slug + '.mp4')}  ({sum(durs):.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
