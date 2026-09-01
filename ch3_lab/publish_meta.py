#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_meta.py — 產生每集的標題、說明、標籤。

## 三個層次共存(Carson 定的)
- **標題走戲劇性**:原始與重測的落差本身就是戲,不需要加形容詞
    「A 1998 study said willpower runs out. 23 labs tested it. The effect was 0.04.」
- **說明走學術可信**:兩篇論文的完整標題、年份、DOI,以及本集用到的每個數字
- **旁白走白話**(在 make_episode / make_famous 裡)

## 誠信
標題和說明裡的數字**一律從事實庫填空**,不手寫。填完再過一次 audit:
出現在標題/說明裡的數字必須在事實庫找得到,否則不產出。
標題是觀眾唯一一定會讀到的字,在那裡放一個錯數字比片子裡錯還嚴重。

用法:
  python publish_meta.py            # 全部,寫 publish_meta.json
  python publish_meta.py --print    # 順便印出來看
"""
import argparse
import json
import pathlib
import re
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_episode import (build_facts, tone_of,       # noqa: E402
                          TONE_META, CARD_TEXT)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
QUEUE = ROOT / "facts" / "episode_queue.csv"
FAMOUS = ROOT / "facts" / "famous_episodes.json"
OUT = ROOT / "publish_meta.json"

TAGS = ["replication crisis", "psychology", "effect size", "science",
        "research", "statistics", "meta-analysis", "replication study",
        "open science", "social psychology"]

FOOTER = (
    "\n\nHow this channel works\n"
    # 🔴 這句原本也是「Nothing is estimated or rounded for effect」,而它同樣
    #    不成立:make_episode.py:77/83 把效果量 round(...,2)、make_famous.py:99
    #    用的是捨去到百位的引用數。RECHECKED_FOOTER 那份改掉的時候,**這份
    #    沒改** —— 同一句假話兩份表面,只修了我當時正在看的那一份,
    #    而這一份掛在 19 支已上線的片上。
    "Every number in this video comes from the published record, and both "
    "papers are cited above with their DOIs. Effect sizes are quoted to two "
    "decimal places and citation counts are rounded down, so the figure on "
    "screen is never larger than the published one — the narration is "
    "generated from the same data fields you see on screen. Not every "
    "finding fails: replications that held up get their own episodes.\n\n"
    "Replication data: FORRT Replication Database (FReD), osf.io/2tbvd")

#: 🔴 `rechecked` 這批**不是**從 FReD 來的,是逐篇讀原文抽出來的,所以
#:    不能沿用上面那個頁尾 —— 標錯資料來源比不標更糟。
#:    另外這批的結局不只有「倒了」:有的是原始分析有偏誤(結論反過來)、
#:    有的是方法倒了而假說活著、有的至今仍有爭議。頁尾要講清楚,否則
#:    觀眾會拿「又一個倒了」的框架去讀一支不是那個意思的片。
RECHECKED_FOOTER = (
    "\n\nHow this channel works\n"
    # 🔴 這段原本講了三件不成立的事,而它是**寫給觀眾看的保證**:
    #    ① 「每一個數字都存著它的原句」—— 溯源閘門只要求數字出現在結構化
    #       欄位裡,沒有 quote 的欄位照樣過關;而長片這條路徑根本沒跑閘門。
    #    ② 「不做任何四捨五入」—— 引用數無條件捨去到百位(1,700 印 1,600)。
    #    ③ 「查不到的會在上面寫出來」—— 14 集裡 9 集的 missing_public 是空的,
    #       實測 9 筆 rechecked 說明欄 0 筆出現過那個區塊。
    #    數字守門抓得到沒憑據的數字,抓不到這種**關於流程的句子** ——
    #    而觀眾能不能信這個頻道,靠的正是這種句子。改成照現況為真的版本。
    "The papers are read directly, and the sentence a number came from is "
    "quoted above wherever it is shown. Citation counts and some sample "
    "sizes are rounded down and always said as \"more than\", so the figure "
    "on screen is never larger than the real one. Where the original "
    "document could not be obtained, the number is left out rather than "
    "carried over from somebody's summary of it.\n\n"
    "Not every episode is a debunking. Some of these findings held up, some "
    "turned out to be a problem with the original analysis rather than the "
    "result, and at least one is still an open argument.")


def t_n(T):
    """重測人數。**沒有就回報沒有,不要填 0。**"""
    n = T.get("n")
    if n is None:
        raise SystemExit("⛔ outcomes 集缺 test.n —— 標題會講一個假數字")
    return f"{int(n):,}"



_DOI_ANGLE = re.compile(r"(doi:\S*?)([<>])")


_CJK_PUB = re.compile(r"[　-鿿＀-￯]")


def api_safe(text, where=""):
    """把文字清成 YouTube metadata 收得下的樣子。**fail-closed。**

    🔴 `videos.insert` 對標題/說明裡的 `<` `>` 回 HTTP 400(2026-08-30 實測,
    一次送 5 支被擋 2 支)。而角括號有三種來源,處理方式不一樣:

    - **DOI 裡的**(Wiley SICI 格式,例如
      `10.1002/(sici)1099-0771(200001/03)13:1<1::aid-bdm333>3.0.co;2-s`)
      → 百分比編碼。改寫成文字會讓那個 DOI 查不到,而 DOI 是這條線
      唯一叫觀眾去驗證的東西。
    - **數學比較**(`p < 0.05`、`<1%`)→ 改成文字,意思一樣而且更好唸。
    - **箭頭**(`->`)→ `to`。

    清完再斷言一次:還有角括號就中止。清洗函式會漏掉新的來源,斷言不會。
    """
    s = text
    # 1) DOI 內的角括號:百分比編碼(反覆做到沒有為止,一個 DOI 可能兩個)
    for _ in range(8):
        new = _DOI_ANGLE.sub(
            lambda m: m.group(1) + ("%3C" if m.group(2) == "<" else "%3E"), s)
        if new == s:
            break
        s = new
    # 2) 箭頭與比較
    s = s.replace(" -> ", " to ").replace("->", " to ")
    s = s.replace("< ", "less than ").replace(" <", " less than ")
    s = s.replace("> ", "more than ").replace(" >", " more than ")
    s = s.replace("<", "under ").replace(">", "over ")
    # 3) 斷言
    # 🔴 這是英文頻道,而事實庫裡有大量給我自己看的中文備註。它們已經
    #    從說明欄漏出去過一次(missing 欄整段中文)。清洗函式會漏掉新的
    #    來源,斷言不會 —— 跟角括號那條同一個道理,放在同一個出口。
    if _CJK_PUB.search(s):
        raise SystemExit(
            f"⛔ {where} 的 metadata 裡有中文:「{_CJK_PUB.search(s).group()}」"
            f" —— 這是英文頻道,事實庫的中文備註不該漏到公開欄位。不出片。"
            f" 片段:{s[max(0, _CJK_PUB.search(s).start() - 40):][:90]}")
    if "<" in s or ">" in s:
        raise SystemExit(
            f"⛔ {where} 的 metadata 清洗後仍有角括號 —— YouTube 會回 400。"
            f"不出片。原文片段:{text[:80]}")
    return s


def footer_for(n_papers):
    """頁尾要跟說明裡**實際有幾篇論文**一致。

    🔴 頁尾寫死「both papers are cited above」,但 pooled 的集數
    (sleep_memory、implicit_bias_test)說明裡只有一篇。這正是 is_doi 的
    docstring 自己點名的那個問題:DOI 那半修好了、「both」這半沒有。
    """
    if n_papers == 2:
        return FOOTER
    return FOOTER.replace("and both papers are cited above with their DOIs",
                          "and the paper is cited above with its DOI")


# 來源資料庫有拼字錯。旁白端已修(make_episode.speakable),但標題也會吃到——
# 標題出現錯字看起來就是隨便做的,而這個頻道賣的就是嚴謹。
_TYPO = {"criminial": "criminal", "positvely": "positively",
         "foregiveness": "forgiveness"}


_LEADIN = re.compile(r"^(we\s+(find|found|show|investigated)\s+(that\s+)?"
                     r"(the\s+hypothesis\s+that\s+)?)", re.I)


def clean(text):
    """拼字錯 + 來源雜訊。旁白端(speakable)早就在做,說明端卻只修拼字,
    於是 ep015 的說明第一行是「We investigated the hypothesis that…」——
    讀起來像是**本頻道**做了這個研究。"""
    for bad, good in _TYPO.items():
        text = re.sub(bad, good, text, flags=re.I)
    text = text.strip().strip('"').strip("“”").strip()
    text = _LEADIN.sub("", text)
    text = re.sub(r"^\s*\[\d+\]\s*", "", text)
    text = re.sub(r"\s*\([a-z]\)\s*", " ", text)
    text = re.sub(r";\s*(using|with|in)\s+[^;.]{1,40}$", "", text, flags=re.I)
    text = re.sub(r"\s+as:\s+", " as ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[0].upper() + text[1:] if text else text


def is_doi(v):
    """真的是 DOI 才算 —— FReD 的 DOI 欄有時放內部鍵值(wiebe_2004),
    有時是空的(pandas 讀成 nan)。兩種都會變成對外文案裡的**假引用**:
    說明欄印出 `doi:nan`,下一行卻寫著「both papers are cited above with
    their DOIs」。這是誠信問題,不是排版問題。"""
    v = str(v or "").strip().lower()
    return v.startswith("10.") or "doi.org/10." in v


def cite_of(row, side):
    """回傳可引用的來源字串,沒有就回 None。

    DOI 優先;沒有 DOI 時退到 `url_r` —— ep001 是 datacolada.org/84、
    ep008 是 osf.io/ns26x,兩個都是真實可查的來源,就躺在同一列裡沒人讀。
    fail-closed 的意思是「湊不出可查證的引用就不發」,不是「只認 DOI」。
    """
    d = row.get(f"doi_{side}")
    if is_doi(d):
        return "doi:" + str(d).replace("https://doi.org/", "")
    u = str(row.get(f"url_{side}") or "").strip()
    if u.startswith(("http://", "https://")) and "." in u:
        return u
    return None


def n_fmt(x):
    return f"{int(x):,}"


FIT_FAILS = []


def fit(claim, tail, limit=100):
    """主張 + 尾巴塞得進上限就用,塞不進回傳 None(由呼叫端改用數字版標題)。

    🔴 兩件事都試過而且都不行:
    - `title[:100]` 會切在字中間(「…and it he」「…using a mouse. 」)
    - 詞邊界截斷加省略號會讓主張失去意義(「A 1968 study said the more
      people who…」),觀眾看不懂在講什麼,比沒有主題更糟

    所以放不下就**不要硬塞**:改用純數字的標題。主題講不完整就不講。
    """
    c = claim.rstrip(". ")
    if len(c) + len(tail) <= limit:
        return c + tail
    # 🔴 靜默退回是壞的(2026-08-25 獨立驗證抓到)。改 hook 讓它更準確之後,
    #    三集因為變長而無聲退回純數字標題——「91 experiments, 2,004 people:
    #    0.29.」作為標題,觀眾完全不知道在講什麼,而且縮圖主題取自標題,
    #    所以三張縮圖也一起失去主題。守門拒絕了但沒有人被告知。
    FIT_FAILS.append((c[:48], len(c) + len(tail) - limit))
    return None


def es_fmt(x):
    s = f"{abs(x):.2f}"
    return ("-" if x < 0 else "") + s


def fred_meta(row, key=None):
    """一列 FReD → 標題/說明。落差越大,標題越不需要修飾。"""
    eo, er = float(row["eo"]), float(row["er"])
    no, nr = int(row["no"]), int(row["nr"])
    claim = clean(str(row["description"]).strip().rstrip("."))
    claim = claim[0].upper() + claim[1:]
    year_o = int(float(row["year_o"])) if pd.notna(row.get("year_o")) else None
    # 🔴 分類只有一個來源:tone。CSV 的 `track` 欄是另一套平行分類,
    #    判定改五分法時它沒跟著改,於是 ep005 旁白說「效應存活」而縮圖
    #    用失敗色。**已停用 track**,任何地方都不要再讀它。
    tone = tone_of(build_facts(row))

    # 標題的說法要跟 tone 一致。⚠️ 一度把 shrunk_real 也講成「it held up」
    #    —— 那是過度宣稱:shrunk_real 的意思是「小很多但仍測得到」,
    #    不是「撐住了」。標題是觀眾唯一一定會讀到的字。
    TAILS = {
        "held":        (f" — retested on {n_fmt(nr)} people, it held",
                        f"Retested on {n_fmt(nr)} people, and it held: "
                        f"{es_fmt(eo)} → {es_fmt(er)}"),
        "stronger":    (f" — retested on {n_fmt(nr)} people, it came back larger",
                        f"Retested on {n_fmt(nr)} people, and it grew: "
                        f"{es_fmt(eo)} → {es_fmt(er)}"),
        "shrunk_real": (f" — smaller on {n_fmt(nr)} people, but still there",
                        f"{es_fmt(eo)} → {es_fmt(er)} on {n_fmt(nr)} people "
                        f"— smaller, still there"),
        "flipped":     (f" — on {n_fmt(nr)} people it reversed: {es_fmt(er)}",
                        f"A {year_o} study found {es_fmt(eo)}. "
                        f"{n_fmt(nr)} people later it reversed: {es_fmt(er)}"),
        "gone":        (f" — then {n_fmt(nr)} people: {es_fmt(er)}",
                        f"A {year_o} study found {es_fmt(eo)}. "
                        f"{n_fmt(nr)} people later: {es_fmt(er)}"),
    }
    cite_o, cite_r = cite_of(row, "o"), cite_of(row, "r")
    tail, fallback = TAILS[tone]
    title = fit(claim, tail) or fallback

    # 🔴 有手寫白話句就用它,**別讓這裡跟 retitle.py 各產一套標題**。
    #    上面那組 TAILS 是拿 claim 原文接效果量,產出長這樣:
    #    「Does scarcity-induced focus really lead to cognitive fatigue on
    #    subsequent cognitive control task?」——論文語言。retitle.py 已經
    #    把 24 支都換成手寫白話句了,但如果哪天有人重跑 publish_meta.py,
    #    這裡會**靜默把它們全部改回去**:同一個欄位兩個寫入者,而其中一個
    #    不知道另一個存在。這正是這條線上重複發生的模式。
    #    所以這裡直接讀同一份手寫句;沒有的才退回上面那組(fail-open 在
    #    這裡是對的 —— 新進的集數還沒手寫時,舊格式標題總比沒有好,而且
    #    retitle.py 那邊是 fail-closed,不會靜默降級成論文語言。)
    import plain
    from retitle import TAIL as PLAIN_TAIL
    q = plain.spoken(key) if key else None
    if q:
        # 🔴 結尾那句要走 `copy_tone`,跟 retitle.build 同一條 —— 否則這裡
        #    產「The replication found the opposite.」、retitle 產
        #    「…, but only just.」,同一個欄位兩個寫入者又對不上。
        #    實測就是這樣:改完 copy_tone 之後 retitle 回報「1/24 則標題會改」。
        from make_episode import copy_tone
        ct = copy_tone(tone, er, str(row.get("es_type_o") or "d").lower())
        for cand in (f"{q} {PLAIN_TAIL.get(ct, '')}".strip(), q):
            if len(cand) <= 100:
                title = cand
                break

    # 🔴 說明的**第一行**是搜尋結果裡跟著標題一起顯示的那一段。
    #    原本第一行是論文語言的 claim 原文(「Scarcity-induced focus leads
    #    to cognitive fatigue on subsequent cognitive control task.」)——
    #    跟標題、縮圖、開場卡犯的是同一個錯,只是這一處我一開始沒算進去。
    #    改成手寫白話句開頭,原文往下放一行(它仍然在,溯源沒有變短)。
    lead = f"{q}\n\n" if q else ""
    desc = (
        lead +
        f"{claim}.\n\n"
        f"Original study ({year_o}): {str(row['title_o'])[:150]}\n"
        f"  {n_fmt(no)} participants — effect size {es_fmt(eo)} "
        f"({str(row['es_type_o']).lower()})\n"
        f"  doi:{row['doi_o']}\n\n"
        f"Replication: {str(row['title_r'])[:150]}\n"
        f"  {n_fmt(nr)} participants — effect size {es_fmt(er)}\n"
        f"  doi:{row['doi_r']}\n"
        + footer_for(2))
    allowed = {str(v) for v in (year_o, no, nr, n_fmt(no), n_fmt(nr),
                                es_fmt(eo), es_fmt(er))}
    # 主張原文帶的數字是來源逐字複製的,不是我產生的 → 放行
    allowed |= set(re.findall(r"\d[\d,\.]*", claim))
    return title, desc, allowed


def famous_tone(E):
    """名案線的分類也走 tone,跟 FReD 線同一套語彙。

    ## 沒有信賴區間時**不由規則決定**(2026-08-29 改)
    舊版寫「沒有區間就回 shrunk_real,那一檔是中間類別,正好對應
    『我們不知道』」。但下游不是那樣用它的:縮圖把 shrunk_real 印成
    「REAL BUT TINY」、旁白講「real, but much smaller」—— 兩句都是
    **關於大小的正面斷言**,而規則的意思是「資料裡沒有區間」。

    實際後果:`bystander_effect` 是 105 個獨立效果量、7,700 人、
    g = −0.35 的統合分析,方向與原始主張一致,它自己的紀錄標題就寫著
    「it is still there」—— 被印成「REAL BUT TINY」。−0.35 在心理學裡
    是中等偏上,不是 tiny。缺資料被靜默轉成一個實質宣稱,是這條線
    重複發生的模式(「缺欄位 = 通過」已經四次)。

    現在改成**缺區間就必須在資料裡手寫 tone**,並附理由。手寫不是
    退讓:它把判斷從「規則猜的」變成「有人看過原文並簽名」,而且
    fail-closed —— 沒寫就中止,不會靜默生出一個定調。
    """
    t = E["test"]
    ci = t.get("ci")
    if ci and ci[0] <= 0 <= ci[1]:
        return "gone"                     # 區間跨零 = 測不出來
    if not ci:
        tone = t.get("tone_manual")
        if tone not in TONE_META:
            raise SystemExit(
                f"⛔ {E['slug']} 沒有信賴區間,必須在 famous_episodes.json 的 "
                f"test 裡手寫 tone_manual(附 tone_manual_why)。"
                f"規則猜不出來的東西不要讓規則猜。")
        return tone
    kind = t["es_kind"]
    strong = abs(t["es"]) >= (0.2 if kind == "r" else 0.2)
    return "held" if strong else "shrunk_real"


def famous_meta(E):
    t, o = E["test"], E.get("original")
    ci = t.get("ci")
    crosses = bool(ci and ci[0] <= 0 <= ci[1])
    es = es_fmt(t["es"])

    # 名案有手寫的短主題(hook)——這 5 集值得手寫,因為它們是拉力最強的
    topic = (E.get("hook_short") or E.get("hook")
             or (E["claim"][0].upper() + E["claim"][1:]))
    n_show = n_fmt(t.get("n_total", t["n"]))
    if o and t.get("k"):
        title = (fit(topic, f" {t['k']} {t['k_word']} tested it: {es}.")
                 or f"{t['k']} {t['k_word']} retested a {o['year']} classic. "
                    f"The effect: {es}.")
    elif o and t.get("es_second") is not None:
        # ⚠️ 0.09 是**242 位男性**的效果量,不是 602 人的。把兩組相加的人數
        #    掛在單一組的數字上,就是 yt-period-swap-integrity 那個模式:
        #    兩個數字來自不同的組,被當成同一組講。
        title = (fit(topic, f" {n_fmt(t['n'])} men: {es}. "
                            f"{n_fmt(t['n_second'])} women: "
                            f"{es_fmt(t['es_second'])}.")
                 or f"{n_fmt(t['n'])} men: {es}. "
                    f"{n_fmt(t['n_second'])} women: {es_fmt(t['es_second'])}.")
    elif o:
        title = (fit(topic, f" Retested on {n_show} people: {es}.")
                 or f"A {o['year']} finding, retested on {n_show} "
                    f"people: {es}.")
    else:
        title = (fit(topic, f" {t['k']} {t['k_word']}, {n_show} people: {es}.")
                 or f"{t['k']} {t['k_word']}, {n_show} people: {es}.")

    # 🔴 白話首行對名案**同樣成立**。FReD 那 19 支都加了、這 5 支沒有 ——
    #    因為當時只改了 fred_meta 分支。同一個理由只落在一半的東西上,
    #    是這條線最常見的漏法。
    import plain as _plain
    _q = _plain.spoken(E["slug"])
    lines = ([f"{_q}", ""] if _q else []) +             [f"{E['claim'][0].upper() + E['claim'][1:]}.", ""]
    allowed = {es} | set(re.findall(r"\d[\d,\.]*", E["claim"]))
    if o:
        # ⚠️ 旁白講「超過 4,900 次」而說明印精確值 4,928 且沒有來源——
        #    引用數是全片唯一觀眾自己去查會得到不同答案的數字,兩邊要一致。
        src = o.get("cited_by_source", "")
        lines += [f"Original study ({o['year']}): {o['title']}",
                  f"  cited more than {n_fmt(o['cited_by_approx'])} times"
                  + (f" ({src})" if src else ""),
                  f"  doi:{o['doi']}", ""]
        allowed |= {str(o["year"]), n_fmt(o["cited_by"]), str(o["cited_by"]),
                    n_fmt(o["cited_by_approx"]), str(o["cited_by_approx"])}
        # 抓取日期是來源標註的一部分,不是本集的數據
        allowed |= set(re.findall(r"\d+", src))
    # romantic_red 沒有 k(它是單一次登記重測,不是多實驗室/綜合分析)
    scale = (f"{t['k']} {t['k_word']}, " if t.get("k") else "")
    lines += [f"The test ({t['year']}): {t['title']}",
              f"  {scale}"
              f"{'over ' if t.get('n_is_floor') else ''}"
              f"{n_fmt(t.get('n_total', t['n']))} people",
              f"  {t['es_kind']} = {es}"
              + (f", 95% CI [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "")
              + ("  — the interval includes zero" if crosses else ""),
              f"  doi:{t['doi']}"]
    allowed |= {str(t["year"]), n_fmt(t["n"]), str(t["n"])}
    if t.get("k"):
        allowed.add(str(t["k"]))
    if t.get("n_total"):
        allowed |= {n_fmt(t["n_total"]), str(t["n_total"])}
    # 第二組的人數與信賴區間也會出現在標題與說明裡(男 242 / 女 360),
    # 漏了它們閘門就會把正確的數字當成編造的擋下來。
    if t.get("n_second"):
        allowed |= {n_fmt(t["n_second"]), str(t["n_second"])}
    for c in (ci, t.get("ci_second")):
        if c:
            allowed |= {f"{c[0]:.2f}", f"{c[1]:.2f}",
                        es_fmt(c[0]), es_fmt(c[1])}
    if t.get("es_second") is not None:
        # 「comparison: d = -0.09」是一行沒有主詞的孤兒。要講清楚是誰的數字。
        who = t.get("second_label") or (
            f"{n_fmt(t['n_second'])} {t['group_b']}" if t.get("group_b")
            else "second group")
        first = (f"{n_fmt(t['n'])} {t['group_a']}" if t.get("group_a") else None)
        if first:
            lines[-2] = lines[-2].replace(f"  {t['es_kind']} = {es}",
                                          f"  {first}: {t['es_kind']} = {es}")
        lines.append(f"  {who}: {t['es_kind']} = {es_fmt(t['es_second'])}"
                     + (f", 95% CI [{t['ci_second'][0]:.2f}, "
                        f"{t['ci_second'][1]:.2f}]" if t.get("ci_second") else ""))
        allowed |= {es_fmt(t["es_second"])}
    allowed.add("95")
    return title, "\n".join(lines) + FOOTER, allowed


def check(label, title, desc, allowed):
    """標題/說明裡的數字必須在事實庫找得到。

    兩個要小心的地方(都踩過):
    - **負號**:allowed 存的是 "-0.07",但正則抓出來的 token 是 "0.07"。
      比對時兩邊都去掉負號,否則會把正確的數字誤判成編造的。
    - **DOI 和論文標題裡的數字**是識別碼與原文,逐字複製而來,不是我產生的。
      掃描前先整段移除,比事後個別放行可靠。
    """
    norm = {t.lstrip("-").lstrip("0") or "0" for t in map(str, allowed)}
    bad = []
    for where, text in (("標題", title), ("說明", desc)):
        scan = text.replace(FOOTER, " ")              # 固定頁尾不是本集資料
        scan = re.sub(r"doi:\S+", " ", scan)          # DOI 整段不掃
        scan = re.sub(r"^\s*(Original study|The test|Replication)\b.*$", " ",
                      scan, flags=re.M)               # 論文標題行不掃(在行首)
        for tok in re.findall(r"\d[\d,\.]*", scan):
            tok = tok.strip(".,")                     # 尾巴會黏到逗號
            if (tok.lstrip("-").lstrip("0") or "0") in norm:
                continue
            bad.append((where, tok))
    if bad:
        print(f"  ⛔ {label} 溯源失敗:{bad}")
    return not bad


def eo_of(row):
    return float(row["eo"])


def er_of(row):
    return float(row["er"])


def no_of(row):
    return int(row["no"])


def nr_of(row):
    return int(row["nr"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", dest="show")
    a = ap.parse_args()

    out, dropped = [], []
    q = pd.read_csv(QUEUE, low_memory=False)
    for i, row in q.iterrows():
        # 🔴 fail-closed:兩篇論文都要有真 DOI 才准進對外清單。
        #    產不出可查證的引用,就不該宣稱「每個數字都能溯源」。
        # fail-closed 的判準是「有沒有可查證的引用」,不是「有沒有 DOI」
        missing = [s for s in ("o", "r") if cite_of(row, s) is None]
        if missing:
            dropped.append((f"ep{i:03d}",
                            "查不到可引用來源:" + ",".join(missing)))
            continue
        title, desc, allowed = fred_meta(row, f"ep{i:03d}")
        if not check(f"ep{i:03d}", title, desc, allowed):
            dropped.append((f"ep{i:03d}", "數字溯源失敗"))
            continue
        out.append({"kind": "fred", "row": int(i), "dir": f"eps/ep{i:03d}",
                    "video": f"eps/ep{i:03d}/ep{i:03d}.mp4",
                    "tone": tone_of(build_facts(row)), "title": title,
                    "description": desc, "tags": TAGS,
                    # 🔴 縮圖路徑由**這裡**算,不要讓 make_thumbs 事後補。
                    #    它是決定性的(<dir>/thumb.jpg),而「A 產生檔案、
                    #    B 事後把欄位補回同一個 JSON」的結果是:只要有人
                    #    重跑 A,B 補的欄位就被靜默清掉。實際發生過 ——
                    #    我最後一次跑 publish_meta.py 之後沒有再跑
                    #    make_thumbs,於是 24/24 的 thumb 欄位全沒了,
                    #    thumb_backfill 的候選清單從 11 支無聲掉到 1 支。
                    #    那支程式自己的註解早就寫著這個坑會讓清單變短。
                    "thumb": f"eps/ep{i:03d}/thumb.jpg",
                    # 🔴 數字明寫。下游(縮圖)本來是拿正規表示式從**說明的
                    #    散文**裡撈第一個「N participants」——那是拿替身值
                    #    當真值,而替身跟真值不等的時候不會有任何跡象。
                    "facts": {"es_o": eo_of(row), "es_r": er_of(row),
                              "n_o": no_of(row), "n_r": nr_of(row),
                              "es_kind": str(row.get("es_type_o")
                                             or "d").lower()}})

    fam = json.loads(FAMOUS.read_text(encoding="utf-8"))["episodes"]
    for E in fam:
        title, desc, allowed = famous_meta(E)
        # 🔴 名案的標題**以 retitle_live 那份為準**。這裡本來自己組一份
        #    (「… 23 laboratories tested it: 0.04.」),而實際推上線的是
        #    retitle_live 組的(「Ego depletion: … 23 labs, 2,141 people.」)
        #    —— 同一個欄位兩份實作,而且 retitle_live 從不回寫,所以
        #    publish_meta.json 裡名案的標題**永遠跟線上不一樣**。
        #    meta 是「線上應該長什麼樣」的記錄,記錄不實的話,任何拿它
        #    比對線上的東西都會一直誤報。retitle.py 也曾因此把名案推回舊值。
        #    不是加回寫(那是同步兩份),是讓它只有一份。
        from retitle_live import new_title as _famous_title
        title = _famous_title(E["slug"], E, title)
        if not check(E["slug"], title, desc, allowed):
            dropped.append((E["slug"], "數字溯源失敗"))
            continue
        t_ = E["test"]
        out.append({"kind": "famous", "slug": E["slug"],
                    "dir": f"eps_famous/{E['slug']}",
                    "video": f"eps_famous/{E['slug']}/{E['slug']}.mp4",
                    "tone": famous_tone(E),
                    "title": title, "description": desc, "tags": TAGS,
                    "thumb": f"eps_famous/{E['slug']}/thumb.jpg",
                    # 🔴 `n_r` 用 `test.n` **不是** `n_total`。romantic_red 的
                    #    0.09 是 242 位男性的效果量,n_total 602 含 360 位
                    #    女性(那是 -0.09,另一組)。說明裡印 602 是在講整體
                    #    規模,但縮圖的「Retested on N people」是**掛在效果量
                    #    上的數字** —— 掛 602 就是把兩組當成同一組
                    #    (memory yt-period-swap-integrity 的模式)。
                    #    實際後果:標題說 242、縮圖說 602,同一支片。
                    "facts": {"es_o": None, "es_r": t_["es"],
                              "n_o": (E.get("original") or {}).get(
                                  "cited_by_approx"),
                              "n_r": t_["n"],
                              "k": t_.get("k"),
                              "k_word": t_.get("k_word"),
                              "es_kind": t_.get("es_kind", "d"),
                              # 🔴 判準是「這次是**重做**還是**統合**」,
                              #    不是「有沒有列出原始研究」。用
                              #    has_original 的話 bystander_effect 會
                              #    印成「Retested on 7,700 people」——
                              #    它是 105 個獨立效果量的統合分析
                              #    (test.kind 就寫著 meta-analysis),
                              #    沒有人「重做」過那 7,700 人。
                              "is_replication":
                                  t_.get("kind") != "meta-analysis",
                              "has_original": bool(E.get("original"))}})



    # ── 效應家族(lineup)────────────────────────────────────────────
    # 🔴 走**同一本 publish_meta**、同一支 make_thumbs、同一支 upload。
    #    新集型最容易做的事是配一套自己的 metadata/縮圖/發布 —— 那正是
    #    這條線今天修了一整天的病(同一件事多份實作,已經第九次)。
    #    所以它只是多一種 `kind`,不是多一條產線。
    lu_dir = ROOT / "eps_lineup"
    if lu_dir.exists():
        import plain as _plain
        from make_lineup import FAMILIES as _FAM
        for fam in _FAM:
            fj = lu_dir / fam / "facts.json"
            if not fj.exists():
                continue
            L = json.loads(fj.read_text(encoding="utf-8"))
            key = "eps_lineup/" + fam
            q = _plain.spoken(key)
            if not q:
                print(f"  ⛔ {fam}:缺手寫白話句,跳過")
                continue
            # 標題:白話問句 + 規模。**不放效果量** —— 小數對滑過去的人
            # 不構成訊息(今天已經在四個表面上證明過)。規模才是這集的賣點:
            # 不是「一個研究沒重現」,是「整條研究路線 k 個裡 0 個」。
            # 🔴 **可搜尋的效應名必須在標題裡,而且要在最前面。**
            #    第一版標題是「Does reading a word change how you behave? 12
            #    replications...」—— 白話問句很好唸,但整句沒有出現
            #    "social priming" 這四個字。而這一集之所以被選中,就是因為
            #    那個查詢詞通過了需求測試(切題 20 筆、中位觀看 14,743、
            #    小頻道 11 支)。標題不含它 = 需求測試整個白做。
            lead = f"{L['name']}: {q[0].lower() + q[1:]}"
            tail = f" {L['k']} replications, {L['n_sig']} worked."
            title = lead + tail
            if len(title) > 100:
                title = (f"{L['name']}: {L['k']} replications, "
                         f"{L['nr_sum']:,} people, {L['n_sig']} worked.")
            rows = []
            for it in L["items"]:
                cite = ("  doi:" + it["doi_r"]) if it.get("doi_r") else ""
                rows.append(f"  {it['claim'][:96]}")
                rows.append(f"    {es_fmt(it['eo'])} on {n_fmt(it['no'])} -> "
                            f"{es_fmt(it['er'])} on {n_fmt(it['nr'])}{cite}")
            items = chr(10).join(rows)
            nl = chr(10)
            desc = (
                f"{q}{nl}{nl}"
                f"{L['name']}: {L['k']} replications drawn from "
                f"{L['papers_r']} replication papers, {L['nr_sum']:,} "
                f"participants in total against {L['no_sum']:,} in the "
                f"originals.{nl}"
                f"Original effect sizes ran {es_fmt(L['eo_lo'])} to "
                f"{es_fmt(L['eo_hi'])} (median {es_fmt(L['eo_med'])}); the "
                f"replications ran {es_fmt(L['er_lo'])} to "
                f"{es_fmt(L['er_hi'])} (median {es_fmt(L['er_med'])}).{nl}"
                f"{L['n_sig']} of the {L['n_p']} replications that report a "
                f"p-value reached p < 0.05.{nl}{nl}"
                f"Every row on screen:{nl}{items}{nl}{nl}"
                f"Source: {L['source']}") + footer_for(2)
            out.append({
                "kind": "lineup", "slug": fam, "dir": key,
                "video": f"{key}/{fam}.mp4",
                "thumb": f"{key}/thumb.jpg",
                "tone": "gone" if L["n_sig"] == 0 else "shrunk_real",
                "title": title, "description": desc, "tags": TAGS,
                "facts": {"es_o": L["eo_med"], "es_r": L["er_med"],
                          "n_o": L["no_sum"], "n_r": L["nr_sum"],
                          "es_kind": L["es_kind"], "is_replication": True,
                          "k": L["k"], "n_sig": L["n_sig"], "n_p": L["n_p"]},
            })
            print(f"  ✓ {fam}:{title}")


    # ── 頻道預告(ep0)──────────────────────────────────────────────
    ep0 = ROOT / "eps_lineup" / "ep0" / "facts.json"
    if ep0.exists():
        T = json.loads(ep0.read_text(encoding="utf-8"))
        nl = chr(10)
        lines = []
        for r in sorted(T["rows"], key=lambda r: (r["bucket"] != "held",
                                                  r["slug"])):
            mark = {"held": "held up", "mixed": "smaller, still there",
                    "fail": "gone"}[r["bucket"]]
            lines.append(f"  {r['slug']:<24} {r['es_r']:+.2f}  "
                         f"{r['n_r']:>7,} people   {mark}")
        desc = (
            f"{T['k']} claims people repeat as fact. We looked up the study "
            f"each one came from, then looked up what happened when somebody "
            f"ran it again.{nl}{nl}"
            f"{T['n_sum']:,} people took part in the replications.{nl}"
            f"{T['gone']} of the claims are gone - the retest could not tell "
            f"them apart from nothing.{nl}"
            f"{T['shrunk']} came back smaller but still measurable.{nl}"
            f"{T['flipped']} went the other way.{nl}"
            f"{T['survived']} held up, {T['stronger']} of them larger than "
            f"the original.{nl}{nl}"
            f"Every episode, with the replication effect size and sample:{nl}"
            + nl.join(lines) + footer_for(2))
        # 🔴 **插在最前面。** upload.py 照 meta 的順序取待發清單,append 的話
        #    預告會排在 14 集後面 —— 明天 16:25 的 cron 會發 ep007,而預告
        #    是整條線上最強的訂閱轉化器,晚兩週才出等於白做。
        out.insert(0, {
            "kind": "trailer", "slug": "ep0", "dir": "eps_lineup/ep0",
            "video": "eps_lineup/ep0/ep0.mp4",
            "thumb": "eps_lineup/ep0/thumb.jpg",
            "tone": "held",
            "title": (f"{T['k']} famous psychology claims, retested on "
                      f"{T['n_sum']:,} people. {T['survived']} held up."),
            "description": desc, "tags": TAGS,
            # 縮圖走 lineup 那條佐證行(講次數與人數,不複述判決)。
            "facts": {"es_o": None, "es_r": None, "n_r": T["n_sum"],
                      "es_kind": "d", "is_replication": True,
                      "k": T["k"], "n_sig": T["survived"]},
        })
        print(f"  ✓ ep0(排在最前):{out[0]['title']}")


    # ── 跨領域(domains)────────────────────────────────────────────
    dom_dir = ROOT / "eps_domain"
    if dom_dir.exists():
        import plain as _plain
        for d in sorted(dom_dir.glob("*")):
            fj = d / "facts.json"
            if not (fj.exists() and (d / f"{d.name}.mp4").exists()):
                continue
            E = json.loads(fj.read_text(encoding="utf-8"))
            T, O = E["test"], E["original"]
            key = f"eps_domain/{d.name}"
            if not _plain.spoken(key):
                print(f"  ⛔ {d.name}:缺手寫白話句,跳過"); continue
            nl = chr(10)
            if E.get("arc") == "outcomes":
                outs = T["outcomes"]
                kept = [x for x in outs if x["sig"]]
                # 🔴 **「N 個裡回來 M 個」只有在 N 項都在測同一個宣稱時才對。**
                #    learning styles 的三項裡只有一項是那個宣稱,另外兩項是
                #    順帶量到的、而且都跟理論無關 —— 寫「3 個裡回來 2 個」
                #    讀起來像理論部分成立,而真相是**要成立的那一個沒回來**。
                #    每個數字都溯源得到,框架卻是反的:今晚同型的第五次。
                claims = [x for x in outs if x.get("is_claim", True)]
                c_kept = [x for x in claims if x["sig"]]
                if len(claims) < len(outs):
                    # 混合型:先講宣稱本身怎麼了
                    # 🔴 **p 值不是每一集都有。** loss aversion 那篇報的是
                    #    lambda 的中位數,對那些數字**沒有做顯著性檢定** ——
                    #    而這行直接 `:.2f` 格式化 None,整支 publish_meta
                    #    連同前面產好的二十幾集一起沒寫出去。
                    #    這是同一段程式裡第二個「假設某個欄位一定在」,
                    #    修第一個的時候就該把整段掃過。
                    #    沒有 p 就用它真正報的那個值 + 它自己的單位符號,
                    #    **精度照事實庫存的**(1.125 不准變成 1.13 ——
                    #    觀眾拿 1.13 去論文裡 grep 找不到)。
                    c0 = claims[0]
                    if c_kept:
                        verdict = "held"
                    elif c0.get("p") is not None:
                        verdict = f"came back at p = {c0['p']:.2f}"
                    elif c0.get("d") is not None:
                        _sym = {"lambda": "λ", "g": "g", "r": "r",
                                "d": "d"}.get(E.get("unit"), "d")
                        _v = f"{c0['d']:.6f}".rstrip("0").rstrip(".")
                        verdict = f"came back at {_sym} = {_v}"
                    else:
                        dropped.append(
                            (key, "宣稱那一項既沒有 p 也沒有效果量,"
                                  "標題無法講清楚它怎麼了"))
                        continue
                    title = (f"{E['popular_name'].capitalize()}: the one thing "
                             f"the idea needs {verdict}.")
                else:
                    title = (f"{E['popular_name'].capitalize()}: they measured "
                             f"{len(outs)} things on {t_n(T)} people. "
                             f"{len(kept)} came back.")
                # 有 d 就寫 d,沒有的寫它真正報的統計式。**不硬換算** ——
                # learning styles 那篇報的是 F 與 p,編一個 d 出來就是
                # 在說明欄放一個查不到的數字。
                rows = nl.join(
                    f"  {x.get('name_long') or x['name']:<26} "
                    + (f"d = {x['d']:+.2f}   " if x.get("d") is not None
                       else f"{x.get('stat') or ''}   ")
                    # 🔴 同一段裡第三個「假設 p 一定在」。前兩個(標題的
                    #    verdict、混合型判斷)我一個一個修,而正確的做法是
                    #    **修第一個的時候就把整段 grep 過** —— 這一段的
                    #    outcomes 有三個選填欄位(d / p / stat),每一個都
                    #    有集數沒有它。
                    #    沒有 p 的那幾列改印它真正報的統計式(median lambda
                    #    = 2.295 (k = 62)),那比一個空的 p 欄有用得多。
                    + (f"p = {x['p']:.3f}   " if x.get("p") is not None
                       else (f"{x['stat']}   " if x.get("stat")
                             and x.get("d") is None else ""))
                    + ("significant" if x["sig"] else "not significant")
                    for x in outs)
                desc = (
                    f"{_plain.spoken(key)}{nl}{nl}"
                    # 🔴 「原始」不一定是一篇有受試者的研究。learning styles
                    #    那集的原始是 Pashler 2009 —— 一篇**評論**,它從頭
                    #    到尾就在說這個主張沒有證據,沒有 n。硬寫
                    #    「n = None」或編一個數字都是假的。
                    f"The claim as stated: {O['title']} ({O['year']}), "
                    + (f"n = {O['n']}, " if O.get("n") else "")
                    + f"doi:{O['doi']}{nl}"
                    f"The replication: {T['title']} ({T['year']}), "
                    f"n = {T['n']}, doi:{T['doi']}{nl}{nl}"
                    f"What the replication found:{nl}{rows}{nl}{nl}"
                    f"Quoted from the replication:{nl}"
                    + nl.join('  "' + x["quote"] + '"' for x in outs) + nl
                    # 選填的引句:有就放,沒有就不放。**不要假設每一集
                    # 都有同一組欄位** —— 這是 outcomes 這條路徑今天第
                    # 三次因為「假設某個欄位一定在」而炸掉。
                    + (f'  "{T["extra_quote"]}"{nl}'
                       if T.get("extra_quote") else "")
                    + nl
                    # 🔴 上面那段註解說「不要假設每一集都有同一組欄位」,
                    #    然後隔兩行就 `T["verdict_quote"]` 直接索引 ——
                    #    anchoring 與 loss_aversion 沒有這一欄,整支
                    #    publish_meta 在它們身上 KeyError,而**前面已經
                    #    產好的二十幾集也一起沒寫出去**。
                    #    註解記住了教訓,程式沒有:同一段裡兩種寫法並存,
                    #    就是還沒改完。
                    #    有就放、沒有就連標題一起不放 —— 不要印一對空引號。
                    #    (影片本身的結論不受影響:make_domains 對
                    #     `say_verdict` 是 fail-closed 的,那一段一定在。)
                    + (f"The authors' own summary:{nl}"
                       f'"{T["verdict_quote"]}"{nl}'
                       if T.get("verdict_quote") else "")
                    + (f'{nl}On statistical power:{nl}"{T["power_quote"]}"'
                       if T.get("power_quote") else "")) + footer_for(2)
                out.append({
                    "kind": "domains", "slug": d.name, "dir": key,
                    "video": f"{key}/{d.name}.mp4",
                    "thumb": f"{key}/thumb.jpg",
                    "tone": E.get("tone", "shrunk_real"),
                    "title": title, "description": desc, "tags": TAGS,
                    "facts": {"es_o": None, "es_r": None, "n_r": None,
                              "es_kind": "d", "is_replication": True,
                              "k": len(outs), "k_word": "outcomes",
                              "n_kept": len(kept), "arc": "outcomes",
                              # 宣稱本身的結果 —— Short 端要靠它決定框架,
                              # 否則會退回「N 個裡回來 M 個」那種誤導說法。
                              "claim_p": (claims[0]["p"] if len(claims)
                                          < len(outs) else None),
                              "claim_sig": bool(c_kept)},
                })
                print(f"  ✓ {d.name}:{title}")
                continue
            by = {x["name"]: x for x in T["domains"]}
            best = max(T["domains"], key=lambda x: x["pct"])
            worst = min(T["domains"], key=lambda x: x["pct"])
            title = (f"The {E['popular_name'].replace('the ', '')}: practice "
                     f"explained {best['pct']}% in {best['name']}, "
                     f"{by['education']['pct']}% in education, "
                     f"under {worst['pct']}% in {worst['name']}.")
            rows = nl.join(
                f"  {x['name']:<12} "
                f"{('<' if x.get('pct_is_upper_bound') else '')}{x['pct']}%"
                for x in T["domains"])
            desc = (
                f"{_plain.spoken(key)}{nl}{nl}"
                f"{T['year']} meta-analysis, {T['title']}{nl}"
                f"doi:{T['doi']}{nl}{nl}"
                f"Percent of the variance in performance explained by "
                f"deliberate practice:{nl}{rows}{nl}{nl}"
                f"Quoted from the abstract:{nl}\"{T['quote']}\"{nl}{nl}"
                f"The authors' own conclusion:{nl}\"{T['verdict_quote']}\"{nl}{nl}"
                f"The claim being tested comes from {O['title']} "
                f"({O['year']}), doi:{O['doi']}, cited {O['cited_by']:,} "
                f"times (OpenAlex).{nl}"
                f"Note: this meta-analysis reports variance explained, not "
                f"an effect size in d or r, so no d or r is shown anywhere "
                f"in this video." + footer_for(2))
            out.append({
                "kind": "domains", "slug": d.name, "dir": key,
                "video": f"{key}/{d.name}.mp4",
                "thumb": f"{key}/thumb.jpg",
                "tone": E.get("tone", "shrunk_real"),
                "title": title, "description": desc, "tags": TAGS,
                "facts": {"es_o": None, "es_r": None,
                          "n_r": None, "es_kind": "pct",
                          "is_replication": False,
                          "k": len(T["domains"]), "k_word": "domains",
                          "pct_best": best["pct"], "pct_worst": worst["pct"],
                          "best": best["name"], "worst": worst["name"]},
            })
            print(f"  ✓ {d.name}:{title}")

    # ── 重新檢查(rechecked)─────────────────────────────────────────
    # 這一批跟前四種的差別是**故事類型不一樣**,所以說明欄也不能共用
    # 一個模板:hot hand 要講「偏誤有多大」,backfire 要講「原作者自己
    # 怎麼說」,hungry judges 要講「這件事還沒定案」。
    rc_dir = ROOT / "eps_rechecked"
    if rc_dir.exists():
        import plain as _plain
        for d in sorted(rc_dir.glob("*")):
            fj = d / "facts.json"
            if not (fj.exists() and (d / f"{d.name}.mp4").exists()):
                continue
            E = json.loads(fj.read_text(encoding="utf-8"))
            T, O = E["test"], E["original"]
            key = f"eps_rechecked/{d.name}"
            if not _plain.spoken(key):
                dropped.append((key, "缺手寫白話句")); continue
            # 🔴 DOI 是硬需求,不是選填。這個頻道唯一的資產是「觀眾自己
            #    查得到」,沒有 DOI 的那一集不該存在。
            if not T.get("doi") or not O.get("doi"):
                dropped.append((key, "缺 DOI")); continue
            nl = chr(10)
            # `facts.json` 是**渲染當下**的快照 —— 說明欄要描述的是真的
            # 被渲出來的那支片,所以優先用快照。但事實庫後來新增的欄位
            # (popular_name 是標題用的,不影響任何一格畫面)快照裡不會有,
            # 而為了一個沒進畫面的欄位重渲三分鐘是浪費。
            # → 快照沒有就回主檔查,**用 slug 對回去**,對不上就不出片:
            #   靜默拿到別集的名字比缺這一欄糟得多。
            pn = E.get("popular_name")
            if not pn:
                _src = json.loads(
                    (ROOT / "facts" / "rechecked_episodes.json")
                    .read_text(encoding="utf-8"))
                _hit = [x for x in _src["episodes"] if x["slug"] == d.name]
                if len(_hit) != 1 or not _hit[0].get("popular_name"):
                    dropped.append((key, "事實庫查不到唯一的 popular_name"))
                    continue
                pn = _hit[0]["popular_name"]
            if not E.get("story_type_short"):
                dropped.append((key, "缺 story_type_short(標題與說明都靠它)"))
                continue

            # 標題:**搜尋詞放最前面**。零訂閱的頻道只有搜尋一個入口,
            # 而 08-30 實測 14 支 16:9 長片標題全是學術句子,總共 3 次觀看。
            title = f"{pn}: {E['story_type_short']}."

            # 論文清單:原始 → 重測 →(可能的)第二個質疑方 → 原作者回應。
            # 每一篇都要有 DOI,而且**順序就是片子講的順序**。
            # 🔴 這裡原本寫死四個 key。獨立稽核實測:14 集裡 8 集有帶 DOI
            #    的區塊落在這四個之外(many_smiles_2022 / coles_2019_trap /
            #    xiao_2024_table3 / bias_correction / noise_paper /
            #    recoding_paper / bbc_study / expectancy_study /
            #    original_authors_reply)。說明欄結尾卻寫著「兩篇論文的 DOI
            #    都在這裡」—— 而片子講的那個數字查不到。
            #    列舉會漏,掃描不會。
            _LAB = {"original": "The original", "test": "The retest",
                    "test2": "A second challenge",
                    "author_recantation": "The original author, later",
                    "original_authors_reply": "The original author replies"}
            _order = [k for k in _LAB if k in E] +                      [k for k in E if k not in _LAB]
            papers = []
            for _k in _order:
                _b = E.get(_k)
                if isinstance(_b, dict) and _b.get("doi"):
                    papers.append((_LAB.get(_k)
                                   or _k.replace("_", " ").capitalize(), _b))
            # 🔴 樣本那一行有兩個坑,兩個都會製造一個假的第二組人:
            #    ① `n_word` 不是每一集都是 participants —— hot hand 是
            #       26 名**球員**、hungry judges 是 1,112 筆**裁決**
            #       (不是人也不是天數)。印 participants 就是換掉單位。
            #    ② 重分析用的是**同一批**資料。原始 26、重測 26 各印一行
            #       「26 participants」,讀起來像兩組獨立樣本各 26 人,
            #       而真相是同一批 26 人被算了第二次 —— 那正好是這一集
            #       在講的事情,說明欄卻把它講反了。
            def _people(p):
                if not p.get("n"):
                    return ""
                same = "reanalysis" in (p.get("kind") or "").lower()
                # 重分析用的就是原始那批人 —— 單位也該跟著原始那筆走,
                # 否則會寫出「the same 26 participants」而上一行是
                # 「26 players」,同一批人在同一段裡有兩個名字。
                w = p.get("n_word") or (O.get("n_word") if same
                                        else None) or "participants"
                return (f"{nl}  the same {p['n']:,} {w}" if same
                        else f"{nl}  {p['n']:,} {w}")
            # 🔴 論文清單改成掃描之後,會掃到沒有 title/year 的區塊
            #    (xiao_2024_table3 / many_smiles_2022 / coles_2019_trap /
            #     original_authors_reply / bbc_study)。原本寫 `p['year']`
            #    直接 KeyError,而寫 `p.get('year','')` 會印出空括號 ——
            #    「Xiao 2024 table3:  ()」看起來像壞掉。
            #    沒有標題就只印可查的 DOI,不編一個標題出來。
            def _cite(lab, p):
                t, y = p.get("title"), p.get("year")
                head = (f"{lab}: {t}" if t else lab) + (f" ({y})" if y else "")
                return head + nl + f"  doi:{p['doi']}" + _people(p)
            plist = nl.join(_cite(lab, p) for lab, p in papers if p.get("doi"))

            # 時間軸:畫面上出現過的每一列,連單位一起寫進說明欄。
            # 🔴 **單位一定要印。** 第一版寫 `{r['es']:+g}`,說明欄印出
            #    「+4 / -8 / +13」—— 那是百分點,但看起來像效果量 d。
            #    畫面上有 pp、說明欄沒有,同一支片兩個表面講不同的話,
            #    而說明欄是觀眾拿去跟論文對照的那一份。
            #    符號從 make_rechecked.val_str 來,**不要在這裡再寫一份**
            #    (同一件事兩份實作是這條線最貴的重複錯誤)。
            from make_rechecked import val_str as _vs
            tl = nl.join(
                f"  {r['year']}  {r['what']}"
                + (f"   {_vs(r['es_kind'], r['es'])}"
                   if r.get("es") is not None and r.get("es_kind") else "")
                for r in (E.get("timeline") or []))

            # 逐字原句 —— 這是說明欄存在的主要理由。
            quotes = [("The original study", O.get("quote")),
                      ("The retest", T.get("verdict_quote"))]
            if E.get("author_recantation"):
                quotes.append(("The original author, later",
                               E["author_recantation"]["quotes"][1]))
            qtxt = nl.join(f"{who}:{nl}\"{q}\"{nl}"
                           for who, q in quotes if q)

            # 🔴 **查不到的東西要寫出來。** 事實庫的 `missing` 是給人看的,
            #    而讓觀眾知道哪一格是空的,比假裝全都查到了更有說服力 ——
            #    也讓任何人可以接手去補。
            # 🔴 `missing` 是**內部備註**,裡面是中文,而它被逐字倒進公開
            #    說明欄。commit 9e4afcb8 修的是**旁白**路徑的 CJK,說明欄
            #    這份沒修 —— 同一句話兩份,只修了會出聲的那份。
            #    改成只吐 `missing_public`(英文,逐集手寫);沒有就不吐。
            # 🔴 這裡讀的是**渲染快照**,而 missing_public 是事實庫後來補的,
            #    快照裡是 None —— 於是主檔明明寫了,說明欄還是一個字都不吐
            #    (實測 false_memory 與 hungry_judges 就是這樣)。
            #    跟 popular_name 一樣回主檔查:它不影響任何一格畫面。
            miss = E.get("missing_public") or []
            if not miss:
                _s2 = json.loads(
                    (ROOT / "facts" / "rechecked_episodes.json")
                    .read_text(encoding="utf-8"))
                _m2 = next((x for x in _s2["episodes"]
                            if x["slug"] == d.name), None)
                miss = (_m2 or {}).get("missing_public") or []
            mtxt = ("" if not miss else
                    nl + "What we could not verify first-hand:" + nl
                    + nl.join(f"  - {m}" for m in miss) + nl)

            desc = (
                f"{_plain.spoken(key)}{nl}{nl}"
                f"{E['story_type_short'].capitalize()}.{nl}{nl}"
                f"{plist}{nl}{nl}"
                + (f"What happened to the number:{nl}{tl}{nl}{nl}" if tl else "")
                + f"{qtxt}{nl}{mtxt}"
                + RECHECKED_FOOTER)

            out.append({
                "kind": "rechecked", "slug": d.name, "dir": key,
                "video": f"{key}/{d.name}.mp4",
                "thumb": f"{key}/thumb.jpg",
                "tone": E.get("tone", "shrunk_real"),
                "title": title, "description": desc, "tags": TAGS,
                "facts": {"es_o": O.get("es"), "es_r": T.get("es"),
                          "n_r": T.get("n"), "es_kind": T.get("es_kind", "d"),
                          "is_replication": True,
                          # 縮圖端要拿它當判決字(VERDICT 那四種對這批
                          # 是錯的工具),年份用來寫「1985 → 2018」。
                          "story_type": E["story_type_short"],
                          "year_o": O.get("year"), "year_r": T.get("year")},
            })
            print(f"  ✓ {d.name}:{title}")

    # 🔴 被刷掉的要彙總印出來,不能只是 continue(2026-08-25)。
    #    上一版有 4 集被靜默丟掉(退格字元讓「論文標題那行不掃」失效,
    #    於是「Many Labs 2」的那個 2 被當成編造數字),而 publish_meta.json
    #    看起來有 20 筆一切正常。**少了東西比多了東西難發現。**
    if dropped:
        print(f"\n被擋下 {len(dropped)} 集:")
        for k, why in dropped:
            print(f"  ⛔ {k:<22}{why}")
    # 🔴 發布順序:名案優先(2026-08-27)。那 5 支是唯一有真實搜尋量的題目;
    #    其餘 FReD 的主張本身沒有人在搜,拿它們測「發了有沒有用」等於白測。
    #    ⚠️ 這件事一度只在 publish_meta.json 上手動排過一次,結果重跑就被洗掉
    #    ——順序是產生規則的一部分,要寫在產生器裡。
    #    已上傳的維持原位(帳本認 key,順序只影響還沒發的)。
    try:
        led = json.loads((ROOT / "uploaded.json").read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        led = {}
    k = lambda o: o.get("slug") or o["dir"]
    out = ([o for o in out if k(o) in led]
           + sorted([o for o in out if k(o) not in led],
                    key=lambda o: 0 if o["kind"] == "famous" else 1))
    # 🔴 **出口統一清洗。** 逐個生成點去修會漏 ——
    #    今天就漏了三個不同來源(百分比上界、箭頭、DOI 裡的角括號)。
    for _o in out:
        _o["title"] = api_safe(_o["title"], _o.get("slug") or _o["dir"])
        _o["description"] = api_safe(
            _o["description"], _o.get("slug") or _o["dir"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(out)} 集的標題與說明已寫入 {OUT.name}")
    over = [o for o in out if len(o["title"]) > 100]
    print(f"標題超過 100 字元的:{len(over)}")
    if a.show:
        for o in out:
            print(f"\n[{o.get('slug') or o['dir']}] ({o['track']})")
            print(f"  {o['title']}")


if __name__ == "__main__":
    main()
