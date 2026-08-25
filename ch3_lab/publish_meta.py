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
from make_episode import build_facts, tone_of        # noqa: E402

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
    "Every number in this video comes from the published record, and both "
    "papers are cited above with their DOIs. Nothing is estimated or rounded "
    "for effect — the narration is generated from the same data fields you "
    "see on screen. Not every finding fails: replications that held up get "
    "their own episodes.\n\n"
    "Replication data: FORRT Replication Database (FReD), osf.io/2tbvd")


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


def fred_meta(row):
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
    held = tone in ("held", "stronger", "shrunk_real")

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

    desc = (
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

    沒有 CI 也沒有 p 值時保守判 gone —— 資料缺漏不該預設過關。
    """
    t = E["test"]
    ci = t.get("ci")
    if ci and ci[0] <= 0 <= ci[1]:
        return "gone"                     # 區間跨零 = 測不出來
    if not ci:
        return "unclear"                  # 沒有區間,不宣稱存在與否
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

    lines = [f"{E['claim'][0].upper() + E['claim'][1:]}.", ""]
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
        title, desc, allowed = fred_meta(row)
        if not check(f"ep{i:03d}", title, desc, allowed):
            dropped.append((f"ep{i:03d}", "數字溯源失敗"))
            continue
        out.append({"kind": "fred", "row": int(i), "dir": f"eps/ep{i:03d}",
                    "video": f"eps/ep{i:03d}/ep{i:03d}.mp4",
                    "tone": tone_of(build_facts(row)), "title": title,
                    "description": desc, "tags": TAGS})

    fam = json.loads(FAMOUS.read_text(encoding="utf-8"))["episodes"]
    for E in fam:
        title, desc, allowed = famous_meta(E)
        if not check(E["slug"], title, desc, allowed):
            dropped.append((E["slug"], "數字溯源失敗"))
            continue
        out.append({"kind": "famous", "slug": E["slug"],
                    "dir": f"eps_famous/{E['slug']}",
                    "video": f"eps_famous/{E['slug']}/{E['slug']}.mp4",
                    "tone": famous_tone(E),
                    "title": title, "description": desc, "tags": TAGS})

    # 🔴 被刷掉的要彙總印出來,不能只是 continue(2026-08-25)。
    #    上一版有 4 集被靜默丟掉(退格字元讓「論文標題那行不掃」失效,
    #    於是「Many Labs 2」的那個 2 被當成編造數字),而 publish_meta.json
    #    看起來有 20 筆一切正常。**少了東西比多了東西難發現。**
    if dropped:
        print(f"\n被擋下 {len(dropped)} 集:")
        for k, why in dropped:
            print(f"  ⛔ {k:<22}{why}")
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
