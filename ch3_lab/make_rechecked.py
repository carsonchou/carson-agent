#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_rechecked.py — 第五種集型:**故事類型不是「又倒了一個」**。

## 為什麼要第五種
前四種集型講的都是同一個形狀:原始研究說 X,大規模重測說沒有。那個形狀
講到第二十支就是 YPP `inauthentic` 定義裡點名的「模板化、變化極小、可
大規模複製」—— 那是人工審查的否決項,不是文青堅持。

`facts/rechecked_episodes.json` 那八題**每一題的形狀都不一樣**:

| slug | 形狀 |
|---|---|
| hot_hand | 原始分析有可證明的偏誤,修正後結論**反過來** |
| facial_feedback | 方法倒了,假說還活著(原作者是翻案那篇的共同作者) |
| moral_licensing | 效果隨樣本變大一路縮水,最後翻到反方向 |
| terror_management | 原作者**親自參與設計**,仍然沒重現 |
| backfire_effect | 原作者出面說「你們讀錯了」 |
| false_memory | 重測做出**更高**的比率,然後被重新編碼砍到 4% |
| marshmallow_test | 效果是真的,但三分之二是家庭背景 |
| hungry_judges | 識別假設被質疑,但**沒有**被判定死刑 |

## 這支片為什麼是長片
2026-08-30 實測:16:9 的片 15 支、總觀看 3 次、中位數 0。而其中 14 支
片長是 58 秒到 2 分 14 秒 —— 它們卡在一個沒有出口的格式裡(進不了
Shorts feed、零訂閱沒有推薦流量、標題沒有搜尋量),而**每支照樣燒
1,600 配額**。

即使流量來了算式也不成立:YPP 要 240,000 分鐘,90 秒的片每次觀看最多
給 1.5 分 → 需要 16 萬次觀看;12 分鐘的片每次給 3.5 分 → 6.8 萬次。
同一批內容差 2.4 倍,而**片長是這裡唯一完全由我決定的變數**。

所以這一支的目標長度是 4~5 分鐘(七段,每段 80~110 字),再由
`make_compilation` 把三支併成 15 分鐘的長片。不是把一件事講久一點——
每一段都是這一題**真的多出來的東西**(時間軸的下一步、原作者自己的話)。

## 分工:機器管數字,我管那一段故事
`build_script` 從**結構化欄位**生成骨架(年份、樣本、效果量),那部分
可驗證。而每一題真正的轉折不一樣,所以 `say_twist` 必須逐集手寫,而且
**fail-closed:沒有就不出片**(理由見 make_domains._need —— 這條線出過
「A 集的預設值變成 B 集的結論」)。手寫的那段照樣過數字溯源。

用法:
  python make_rechecked.py --list
  python make_rechecked.py --slug hot_hand --script-only
  python make_rechecked.py --slug hot_hand
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "facts" / "rechecked_episodes.json"

W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8ECF1", "#8A94A6"
ACCENT, REST, GOOD = "#FFC23D", "#252C36", "#5FC98A"

#: 效果量符號跟著論文走。**不要為了版面統一而換單位。**
#: 🔴 這條線踩過:印 `d = 1.12` 而論文報的是 Hedges' g = 1.125 —— 符號錯、
#:    精度也被砍,觀眾拿畫面上的東西去論文裡 grep 兩個都找不到。
UNIT_SYM = {
    "d": "d", "g": "g", "r": "r", "beta": "β", "lambda": "λ",
    "pct": "%", "percentage_points": "pp",
    "raw_diff_10pt_likert": "pts", "raw_diff_7pt_scale": "pts",
}
#: 🔴 掃描稿子用的正則**必須吃小數點**。不吃的話 `0.08` 會被切成 `0` 與
#:    `08` 兩個 token,而 `0` 幾乎不可能在白名單裡 —— 於是每一句帶小數的
#:    旁白都被自己的閘門擋下,看起來像閘門太嚴,其實是切錯了。
#:    反過來更危險:切碎之後 `08` 這種碎片很容易「剛好」在白名單裡,
#:    等於放行一個沒人檢查過的數字。**閘門的解析度必須跟被檢查的東西一致。**
NUM_RE = re.compile(r"\d(?:[\d,]*\d)?(?:\.\d+)?")
#: 中日韓字元。旁白與畫面用的欄位一律不准出現(理由見 audit)。
CJK = re.compile(r"[　-鿿＀-￯]")
#: 這些單位是「幾個」不是「多大」,寫等號會讓它看起來像效果量。
COUNT_KINDS = {
    "count_of_labs_out_of_17", "count_of_bayes_factors_out_of_34",
    "count_of_backfire_effects", "count_of_groups_moving_backwards",
    "count", "proportion_of_issues_improved",
}
#: 自由文字欄位 —— 它們是給人看的證據與警告,**不供給數字溯源白名單**。
#: 🔴 這是本檔最重要的一條規則。事實庫裡每個 quote 都塞滿數字,如果讓
#:    quote 餵白名單,那 audit 等於全通過(隨便講一個數字都「在事實庫裡」)。
#:    只有**結構化欄位**能餵白名單 —— 想講的數字沒過,就把它升格成欄位。
#: 🔴 `say_` 開頭的必須在這裡面,而且這是本檔最容易寫錯的一行。
#:    say_twist / say_verdict / say_spread **就是稿子本身**。讓它們餵白名單,
#:    等於「我寫的數字證明我寫的數字是對的」—— 我實測過:在 say_twist 裡
#:    插一個憑空捏造的 27,閘門回報「數字溯源 ✓」。那正是這條線出過三次的
#:    形狀(測試判斷式永遠不成立 / 完成標記不等於成功),只是這次藏在
#:    「哪些欄位算證據」這個問題裡。**證據和被檢查的東西不能是同一份文字。**
PROSE_KEYS = re.compile(
    r"(^say_|quote|note|warning|trap|traps|missing|_detail|story_type|hook|"
    r"claim|title|authors|journal|doi|kind|name|stat|slug|why|source|"
    r"summary|_words|_check|_limits|final_quote|best_visual|nuance)",
    re.I)


def load(slug):
    d = json.loads(SRC.read_text(encoding="utf-8"))
    for e in d["episodes"]:
        if e["slug"] == slug:
            return e
    have = ", ".join(x["slug"] for x in d["episodes"])
    raise SystemExit(f"⛔ {slug} 不在 {SRC.name} 裡。有:{have}")


def _need(E, field, why):
    raise SystemExit(
        f"⛔ {E['slug']} 缺 `{field}` —— {why}\n"
        f"   這一段沒有可以安全共用的預設值:模板化的產線裡,一個看似無害的 "
        f"fallback 就是一句別人的話。不出片。")


# ─────────────────────────────── 唸法 ───────────────────────────────

def say_exact(x):
    """唸出**存進事實庫的那個精度**,不要自作主張四捨五入。

    這條線唯一的資產是「觀眾自己查得到」。論文寫 1.125,唸成
    「one point one three」之後觀眾 grep 不到,那個資產就磨掉了。
    """
    from make_episode import say_num
    s = f"{abs(x):.6f}".rstrip("0").rstrip(".")
    if "." not in s or len(s.split(".")[1]) <= 2:
        return say_num(x)
    whole, frac = s.split(".")
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
    out = ("minus " if x < 0 else "") + (words.get(whole) or whole)
    return out + " point " + " ".join(words[c] for c in frac)


def say_int(n):
    return f"{int(n):,}"


def say_es(kind, v):
    """把效果量唸成人話,**單位跟著論文**。

    🔴 百分點不能唸成「zero point one three」。hot hand 的 +13 是十三個
       百分點,唸成小數就變成另一個數量級 —— 而且畫面上寫 13pp、旁白唸
       0.13,同一支片自己對不起來。
    """
    if kind == "pct":
        return f"{v:g} percent"
    if kind == "percentage_points":
        # 🔴 正號要唸出來。畫面印 `+4pp` 和 `-8pp`,對比一眼看得到;旁白
        #    唸「four percentage points」和「minus eight percentage points」,
        #    第一個聽起來像沒有方向 —— 而這一集整個論證就是那兩個符號。
        return f"{'minus' if v < 0 else 'plus'} {abs(v):g} percentage points"
    if kind in COUNT_KINDS:
        return say_int(v) if abs(v) >= 1 or v == 0 else say_exact(v)
    if kind == "raw_diff_10pt_likert":
        return f"{say_exact(v)} points on a ten point scale"
    if kind == "raw_diff_7pt_scale":
        return f"{say_exact(v)} points on a seven point scale"
    # 🔴 **裸數字在旁白裡是有歧義的,而畫面上不是。** 畫面印 `r = 0.57` 和
    #    `β = 0.08`,單位看得一清二楚;旁白唸「zero point five seven」和
    #    「zero point zero eight」,聽起來就是同一把尺上的兩個點,而觀眾
    #    會直接得出「掉了 86%」這個我沒有講、也不成立的結論
    #    (一個是相關係數、一個是標準化迴歸係數)。
    #    這正是主頻道「A vs B 兩個數字必須同一組事實」那條的聽覺版本。
    if kind == "r":
        return f"a correlation of {say_exact(v)}"
    if kind == "beta":
        return f"a standardised coefficient of {say_exact(v)}"
    if kind == "g":
        return f"{say_exact(v)}, in Hedges' g"
    if kind == "d":
        return f"an effect size of {say_exact(v)}"
    return say_exact(v)


def val_str(kind, v):
    """畫面上的效果量:符號跟著論文、精度跟著存的值。"""
    if kind == "pct":
        return f"{v:g}%"
    if kind == "percentage_points":
        return f"{v:+g}pp"
    if kind in COUNT_KINDS:
        return f"{v:g}"
    s = f"{abs(v):.6f}".rstrip("0").rstrip(".")
    dec = len(s.split(".")[1]) if "." in s else 0
    sym = UNIT_SYM.get(kind, "d")
    return f"{sym} = {v:.{max(2, min(dec, 3))}f}"


# ─────────────────────────────── 時間軸 ───────────────────────────────

def timeline_rows(E):
    """時間軸的列。有 `timeline` 就用它,沒有就從 original + test 推。

    🔴 **不要畫成有共同刻度的長條圖。** 這八題的單位有 d / g / r / β /
       百分點 / 十點量表原始差 —— 把它們放在同一根軸上,等於發明一個
       觀眾無法解讀的比例尺,而且會暗示「1.34 比 0.57 大兩倍多」這種
       跨單位比較。畫成**逐年的列**,每一列自己帶單位,是唯一誠實的畫法。
    """
    if E.get("timeline"):
        rows = []
        for t in E["timeline"]:
            # 沒有數字的那一列(例如「三次重測全部沒複製出來」)本來就
            # 不需要單位 —— 對它要求單位會把一個正確的事實庫擋在門外,
            # 而那種「閘門對的事情發脾氣」正是後來被放寬的原因。
            # **只在真的要印數字的時候才 fail-closed。**
            rows.append({
                "year": t["year"],
                "what": t["what"],
                "es": t.get("es"),
                "es_kind": (t.get("es_kind") or _tl_kind(E, t))
                           if t.get("es") is not None else None,
                "n": t.get("n"),
            })
        return rows
    o, t = E["original"], E["test"]
    rows = [{"year": o["year"], "what": "the original study",
             "es": o.get("es"), "es_kind": o.get("es_kind"), "n": o.get("n")},
            {"year": t["year"], "what": t.get("kind") or "the retest",
             "es": t.get("es"), "es_kind": t.get("es_kind"), "n": t.get("n")}]
    if E.get("test2"):
        t2 = E["test2"]
        rows.append({"year": t2["year"], "what": t2.get("kind") or "and again",
                     "es": t2.get("es"), "es_kind": t2.get("es_kind"),
                     "n": t2.get("n")})
    if E.get("author_recantation"):
        r = E["author_recantation"]
        rows.append({"year": r["year"], "what": "the original author responds",
                     "es": None, "es_kind": None, "n": None})
    return rows


def twist_rows(E):
    """`twist` 那一段自己的列。

    🔴 為什麼不共用 timeline:twist 是全片最長的一段(hot hand 那集 50 秒),
       而 timeline 只有兩三列 —— 五十秒盯著一張幾乎不動的畫面。更糟的是
       那張畫面講的是**別的東西**:twist 在講「隨機球員應該是 -8」,
       畫面卻停在年份表。旁白與畫面講不同的事,是這條線最貴的那種錯。

    每一列 {label, what, es, es_kind};沒填就退回時間軸(對 backfire /
    hungry judges 這種轉折不是數字的集,時間軸反而是對的)。
    """
    out = []
    for r in E.get("twist_rows") or []:
        if r.get("es") is not None and not r.get("es_kind"):
            _need(E, f"twist_rows[{r.get('label')}].es_kind",
                  "有數字就必須有單位,畫面上百分點與 d 長得一樣。")
        out.append(r)
    return out


def _tl_kind(E, t):
    """timeline 那一列沒寫單位時,跟同年份的主欄位對齊 —— **不要猜**。"""
    for src in (E.get("original") or {}, E.get("test") or {}):
        if src.get("year") == t["year"] and src.get("es_kind"):
            return src["es_kind"]
    return _need(E, f"timeline[{t['year']}].es_kind",
                 "那一列有數字卻沒有單位,而 d / g / β / 百分點畫在一起"
                 "只要標錯一個,整條時間軸就是誤導。")


# ─────────────────────────────── 稿 ───────────────────────────────

def build_script(E):
    o, t = E["original"], E["test"]
    rows = timeline_rows(E)

    if not t.get("doi"):
        _need(E, "test.doi",
              "重測論文沒有 DOI,觀眾就沒辦法自己查 —— 而那是這條線唯一的資產。")
    if not t.get("verdict_quote"):
        _need(E, "test.verdict_quote",
              "沒有作者自己的結論句,收尾就只能由我來下判斷。")

    segs = []
    segs.append(("hook", E["hook"]))

    # 原始研究:年份、樣本、它報了多大。**只講結構化欄位有的東西。**
    origin = f"It starts in {o['year']}. {E['claim'].capitalize()}. "
    if o.get("n"):
        origin += (f"That conclusion came from {say_int(o['n'])} "
                   f"{o.get('n_word', 'people')}. ")
    if o.get("es") is not None and o.get("es_kind"):
        origin += (f"The effect they reported was "
                   f"{say_es(o['es_kind'], o['es'])}. ")
    segs.append(("origin", origin))

    # 它後來去了哪裡。**引用數講「超過 N」不講精確值** —— 那是全片唯一一個
    # 觀眾自己去查會得到不同答案的數字(Scholar / Crossref / Scopus 差很多),
    # 而事實庫存的 approx 是無條件捨去到百位的下界。
    spread = ""
    if o.get("cited_by_approx"):
        spread += (f"That paper has been cited more than "
                   f"{say_int(o['cited_by_approx'])} times. ")
    spread += E.get("say_spread") or _need(
        E, "say_spread",
        "這一段講的是這個宣稱後來被拿去做什麼 —— 每一題都不一樣,"
        "共用一句就是替另外七題編一個它們沒有的傳播史。")
    segs.append(("spread", spread))

    # 重測:誰、多少人、怎麼做的。k 有沒有決定講法。
    # 🔴 `k_word` 有兩類,而句型只對其中一類成立:
    #      · **行為者**(laboratories / teams)→「17 個實驗室回頭做了一次」✔
    #      · **被數的東西**(comparisons / issues)→「91 個比較回頭做了一次」
    #        —— 比較不會回頭做任何事。實測產出「52 issues went back to it」
    #        和「91 comparisons went back to it」,兩句都不是英文。
    #    這種錯不會有任何守門叫,因為數字全對、版面也沒問題;
    #    只有**把稿子唸出來**才聽得到。
    ACTORS = {"laboratories", "labs", "teams", "research groups", "sites"}
    k, kw = t.get("k"), (t.get("k_word") or "").lower()
    if k and kw in ACTORS:
        test_txt = f"In {t['year']}, {say_int(k)} {kw} went back to it"
    else:
        # k 是「被數的東西」時**不要塞進這一句** —— 它屬於方法那一句
        # (「52 個議題」是怎麼測的一部分,不是誰去測的)。
        test_txt = f"In {t['year']}, somebody went back to it"
    if t.get("n"):
        floor = "more than " if t.get("n_is_floor") else ""
        # 🔴 「people」不是每一集都對。hungry judges 的 227 是**裁決**
        #    (不是人也不是天數 —— 那三個數字在原文裡是分開的),
        #    marshmallow 的 918 是**兒童**。單位寫錯就是換掉了樣本的意義,
        #    而說明欄那邊我已經為了同一件事修過一次(`_people`)——
        #    第二個表面。
        # 重分析用的就是原始那批人 —— 講「26 players」聽起來像是**另外**
        # 26 個人。
        # 🔴 這裡一度寫 `"reanalysis" in kind`,而 hungry judges 的 kind 是
        #    「letter — reanalysis **with a different dataset**」—— 於是旁白
        #    說「the same 227 decisions」,意思正好相反。**我在同一個小時內
        #    為了同一個字串比對錯了兩次**(前一次是方法那一句)。
        #    關鍵字比對在「描述裡同時出現兩個方法」時必定挑錯,
        #    而這件事只有兩種狀態、事實庫寫得出來 → 改成明確欄位。
        same = bool(t.get("same_sample"))
        w = t.get("n_word") or (o.get("n_word") if same else None) or "people"
        test_txt += (f" — {'the same ' if same else floor}{say_int(t['n'])} {w}")
    test_txt += ". "
    # 🔴 **這一段一度是關鍵字比對,而它答錯了。** `kind` 寫的是
    #    「letter — reanalysis with a different dataset plus interviews」,
    #    我的 `elif "reanalysis" in kind` 命中,於是旁白說「同一份資料,
    #    重算了一次」—— 而那篇用的是**完全不同的一批聽證資料**,
    #    同一支片的 twist 段兩分鐘後自己說「他們拿到了另一批聽證紀錄」。
    #    片子自己跟自己打架,而每個數字都是對的,所以沒有任何守門會叫。
    #    → 改成**明列**:對得上就用,對不上就要求事實庫寫清楚。
    #      關鍵字比對在「描述裡同時出現兩個方法」時一定會挑錯一個。
    METHOD = {
        "many-labs replication":
            "Many labs, one shared protocol, and every prediction registered "
            "before the data came in. ",
        "preregistered replication and extension":
            "Every prediction was registered before the data came in, so "
            "nobody could decide afterwards what counted. ",
        "registered replication report":
            "Every prediction was registered before the data came in, so "
            "nobody could decide afterwards what counted. ",
        "large-scale replication and extension":
            "Not one retest but five, across {k} separate {k_word}, on a "
            "scale the original could not have afforded. ",
        "conceptual replication":
            "Not the same experiment — the same question, asked of a very "
            "much larger group of children, with far more known about each "
            "of them. ",
        "meta-analysis":
            "Not a new experiment — everything that had already been run, "
            "added up: {k} {k_word} of it. ",
        "reanalysis of the original data":
            "Not a new experiment. The same data, run through the arithmetic "
            "a second time. ",
        "letter — reanalysis with a different dataset plus interviews":
            "Not a retest. A different set of hearings, plus interviews with "
            "the people who were actually in the room. ",
        "simulation":
            "Not a new experiment, and not new data either. A simulation of "
            "what the numbers would look like if nothing were going on. ",
    }
    kind = (t.get("kind") or "").strip().lower()
    if kind not in METHOD:
        _need(E, f"test.kind(「{kind}」不在 METHOD 表裡)",
              "旁白要用一句話講清楚這是哪一種檢驗,而『重測』『重算』"
              "『模擬』對觀眾是三件完全不同的事。把它加進 METHOD,"
              "不要讓關鍵字去猜。")
    test_txt += METHOD[kind].format(k=say_int(k) if k else "",
                                    k_word=t.get("k_word", ""))
    segs.append(("test", test_txt))

    # 時間軸:每一步的數字。
    # 🔴 **單位混不混,講法不一樣。** 全部同單位時每一列都重複一次單位名
    #    很囉唆(「an effect size of…」講五遍);但**單位混著的時候不重複
    #    就是誤導** —— facial feedback 的時間軸上有十點量表的原始差、
    #    Cohen's d、七點量表的原始差三種,裸數字唸出來聽起來就是同一把尺
    #    上的三個點,而觀眾會自己算出一個不存在的降幅。
    #    → 混就逐列標,不混就開頭講一次。
    kinds = {r["es_kind"] for r in rows if r["es"] is not None}
    mixed = len(kinds) > 1
    tl = "Here is what happened to the number. "
    if not mixed and kinds:
        only = next(iter(kinds))
        if only in ("d", "g", "r", "beta"):
            tl = ("Here is what happened to the number — all of these are "
                  "effect sizes, measured the same way. ")
    for r in rows:
        if r["es"] is None:
            tl += f"{r['year']}, {r['what']}. "
        elif mixed:
            tl += (f"{r['year']}, {r['what']} — "
                   f"{say_es(r['es_kind'], r['es'])}. ")
        else:
            tl += f"{r['year']}, {r['what']} — {say_exact(r['es'])}. " \
                if r["es_kind"] in ("d", "g", "r", "beta") \
                else f"{r['year']}, {r['what']} — {say_es(r['es_kind'], r['es'])}. "
    segs.append(("timeline", tl))

    # 這一集真正的轉折。**逐集手寫,沒有就不出片。**
    segs.append(("twist", E.get("say_twist") or _need(
        E, "say_twist",
        f"這一集的故事類型是「{E['story_type']}」,而那個轉折沒有辦法從"
        f"結構化欄位生成 —— 生成出來的會是上一集的形狀。")))

    # 作者自己的話。有 recantation 用 recantation,否則用 verdict_quote。
    if E.get("author_recantation"):
        r = E["author_recantation"]
        segs.append(("authors",
                     f"In {r['year']}, {r['who'].split('(')[0].strip()} "
                     f"wrote this. "))
    segs.append(("verdict", E.get("say_verdict") or _need(
        E, "say_verdict",
        "收尾要說清楚這一集到底證明了什麼、沒有證明什麼,而那取決於"
        "故事類型 —— 共用一句就是把八種結局講成同一種。")))

    segs.append(("close",
                 "Every paper is linked below, with the sentence each "
                 "number came from. One claim, the numbers behind it, "
                 "no adjectives."))
    return segs


# ─────────────────────────────── 溯源 ───────────────────────────────

def _collect(node, out, key=""):
    """把**結構化欄位**裡的數字收進白名單;自由文字欄位一律跳過。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if PROSE_KEYS.search(k):
                continue
            _collect(v, out, k)
    elif isinstance(node, list):
        for v in node:
            _collect(v, out, key)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        out.add(f"{node:g}")
        out.add(f"{abs(node):g}")
        out.add(say_int(node) if float(node).is_integer() else f"{node:g}")
        if float(node).is_integer():
            out.add(str(int(node)))
        s = f"{abs(node):.6f}".rstrip("0").rstrip(".")
        out.add(s)
        if "." in s:
            out.add(s.split(".")[1])          # 「p equals .017」抓到的是 017
        # 帶千分位與不帶,兩種都可能出現在稿子裡
        if float(node).is_integer():
            out.add(f"{int(node):,}")
    elif isinstance(node, str) and not PROSE_KEYS.search(key):
        for tok in NUM_RE.findall(node):
            out.add(tok)


def audit(E, segs):
    """稿子裡每個數字都要在**結構化欄位**找得到。fail-closed。

    ⚠️ 用數字邊界比對,不是子字串 —— `"1" in "12"` 成立過一次,給了
       假綠燈,那支片已經發出去了。
    """
    ok = set()
    _collect(E, ok)
    # 唸出來的年份、樣本數必然來自上面;唸法產生的變體補進去
    for v in list(ok):
        ok.add(v.replace(",", ""))
    bad = []
    for name, txt in segs:
        for num in NUM_RE.findall(txt):
            if num not in ok and num.replace(",", "") not in ok:
                bad.append((name, num))
    if bad:
        raise SystemExit(
            f"⛔ 稿子裡有溯源不到的數字:{bad}\n"
            f"   白名單只收**結構化欄位**(quote / note / trap 那些自由文字"
            f"不算)。想講這個數字,就把它升格成一個欄位。")

    # `_do_not_fill` 點名的東西,稿子裡不准出現。
    top = json.loads(SRC.read_text(encoding="utf-8"))
    for k, why in top.get("_do_not_fill", {}).items():
        if not k.startswith(E["slug"] + "."):
            continue
        raise_if = k.split(".")[-1]
        for name, txt in segs:
            if raise_if.lower().replace("_", " ") in txt.lower():
                raise SystemExit(f"⛔ {name} 碰到 _do_not_fill 的 {k}:{why}")
    print(f"  數字溯源 ✓（{len(ok)} 個結構化可用值）")

    # 🔴 **這是英文頻道,旁白裡不准有中文。** 聽起來像廢話,但實測發生了:
    #    事實庫是我跟中文 fact agent 一起建的,`timeline[].what` 那些欄位
    #    直接抄了 agent 的中文描述,而 build_script 把它們接進旁白 ——
    #    Kokoro 照著唸,`seg_timeline.wav` 產出 **107.6 秒**的雜音
    #    (整支片其他七段加起來才 138 秒),而且畫面上那一欄也是中文。
    #    現有的每一道守門都放行:數字溯源只看數字(數字是對的)、版面守門
    #    只看有沒有出界跟重疊(中文字排得下)、時長比對只看影音對不對得上
    #    (對得上,因為兩邊都是同一份爛稿)。
    #    → 「輸出語言」這件事沒有任何一道既有守門在管,它需要自己一道。
    bad_lang = [(n, CJK.search(t).group())
                for n, t in segs if CJK.search(t)]
    if bad_lang:
        raise SystemExit(
            f"⛔ 旁白裡有中文:{bad_lang} —— 這是英文頻道,TTS 會照著唸。\n"
            f"   事實庫裡給人看的欄位(quote_location / note / trap)可以是"
            f"中文,但**會進旁白或畫面的欄位**(timeline[].what、"
            f"twist_rows[].label/what、say_*)必須是英文。")
    print("  輸出語言 ✓")

    # DOI 陷阱:被撤稿/印錯的那些,不准出現在這一集的任何欄位裡。
    blob = json.dumps(E, ensure_ascii=False)
    for bad_doi, why in top.get("_doi_traps", {}).items():
        # 事實庫自己的警告欄位會提到它(那是正確的),所以只擋 doi 欄位
        for m in re.finditer(r'"doi"\s*:\s*"([^"]+)"', blob):
            if m.group(1) == bad_doi:
                raise SystemExit(f"⛔ {E['slug']} 的 doi 欄位用了 "
                                 f"{bad_doi} —— {why}")
    print("  DOI 陷阱 ✓")


# ─────────────────────────────── 畫面 ───────────────────────────────

#: 量出來的字級快取。
#: 🔴 **一定要快取。** `fit_w` 每次呼叫都開一張 1920×1080 的 matplotlib
#:    figure 再關掉,而我把它放在 `render_scene` 裡 —— 也就是**每一格畫面**
#:    都重量一次,四列的話一格就是八張 figure。實測後果:facial_feedback
#:    渲到一半,九分鐘沒有產出任何一格,CPU 吃滿一核、記憶體以每秒 9 MB
#:    往上爬(16 GB 的機器只剩 2.2 GB),整台機器開始換頁。
#:    看起來像當掉,其實是「對的答案算了一千五百遍」。
#:    量測結果只跟 (字串, 字級, 欄寬, 粗細) 有關,而那四個在一段裡不變。
_FIT_CACHE = {}


def fit_w(plt, text, base, max_frac, weight="bold"):
    """字級用量的,不是挑的 —— 文案長度會變,一個字級不可能同時對。"""
    ck = (text, base, round(max_frac, 4), weight)
    if ck in _FIT_CACHE:
        return _FIT_CACHE[ck]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center",
                fontsize=base, weight=weight)
    fig.canvas.draw()
    frac = t.get_window_extent(
        renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    out = (base if (frac <= max_frac or frac == 0)
           else max(20, int(base * max_frac / frac)))
    _FIT_CACHE[ck] = out
    return out


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


def ease(x):
    return 1 - (1 - max(0.0, min(1.0, x))) ** 3


def _quote_lines(plt, q):
    """引言斷行:**寧可多一行也不要截斷**。

    🔴 這條線出過的形狀是 `wrap(...)[:2]` —— 把論文名切成半句而畫面上
       看起來像正常結尾。這裡改成放寬每行字數直到行數塞得下,一個字都
       不丟;真的塞不下就中止,不要偷偷少講半句。
    """
    for width in (46, 52, 58, 64, 70):
        lines = wrap(q, width)
        if len(lines) <= 7:
            return lines
    raise SystemExit(f"⛔ 引言太長,7 行放不下也不准截斷:{q[:70]}…")


def render_scene(name, t_now, dur, ctx):
    plt, E = ctx["plt"], ctx["E"]
    o, T = E["original"], E["test"]
    rows = ctx["rows"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    a = ease(t_now / 0.7)

    def txt(y, s, fs, col=FG, w="bold", al=None, x=0.5, ha="center"):
        if not s:
            return
        ax.text(x, y, s, ha=ha, va="center", fontsize=fs, color=col,
                weight=w, alpha=a if al is None else al)

    if name == "hook":
        lines = wrap(E["hook"], 34)[:4]
        fs = fit_w(plt, max(lines, key=len), 74, 0.86)
        for i, ln in enumerate(lines):
            txt(0.66 - i * 0.115, ln, fs)
        if t_now > 2.2:
            txt(0.20, E["story_type_short"] if E.get("story_type_short")
                else "they ran it again", 40, ACCENT, "bold",
                ease((t_now - 2.2) / 0.7))

    elif name == "origin":
        txt(0.70, str(o["year"]), 150, DIM)
        cl = wrap(E["claim"], 46)[:3]
        fs = fit_w(plt, max(cl, key=len), 50, 0.88, "normal")
        for i, ln in enumerate(cl):
            txt(0.50 - i * 0.085, ln, fs, FG, "normal")
        if t_now > 2.2 and o.get("n"):
            txt(0.20, f"{say_int(o['n'])} {o.get('n_word', 'people')}",
                56, ACCENT, "bold", ease((t_now - 2.2) / 0.7))

    elif name == "spread":
        if o.get("cited_by_approx"):
            txt(0.66, f"cited more than {say_int(o['cited_by_approx'])} times",
                62, ACCENT)
        sp = wrap(E.get("say_spread", ""), 48)[:4]
        if sp:
            fs = fit_w(plt, max(sp, key=len), 44, 0.86, "normal")
            for i, ln in enumerate(sp):
                txt(0.44 - i * 0.085, ln, fs, DIM, "normal")

    elif name == "test":
        txt(0.68, str(T["year"]), 150, DIM)
        lab = (f"{say_int(T['k'])} {T['k_word']}" if T.get("k")
               and T.get("k_word") else (T.get("kind") or "the retest"))
        txt(0.48, lab, 52, FG, "normal")
        if t_now > 1.8 and T.get("n"):
            floor = "more than " if T.get("n_is_floor") else ""
            txt(0.28, f"{floor}{say_int(T['n'])} people", 62, ACCENT,
                "bold", ease((t_now - 1.8) / 0.7))

    elif name in ("timeline", "twist"):
        # 逐列。**沒有共同刻度** —— 單位不同就不畫共同刻度,那會暗示
        # 「1.34 比 0.57 大兩倍多」這種跨單位比較。
        # timeline 走年份,twist 走這一集自己的關鍵數字(twist_rows)。
        use = ctx["twist_rows"] if (name == "twist" and ctx["twist_rows"]) \
            else rows
        head = ("what happened to the number" if use is rows
                else "the part that gets left out")
        txt(0.93, head, 42, DIM, "normal")
        # 🔴 版面要**置中**,不要從固定的 top_y 往下排。兩列的時候
        #    top-anchored 會把東西全擠在上緣、下面空掉半個畫面 ——
        #    抽幀才看得到,而守門看不到(沒出界也沒重疊)。
        n = max(1, len(use))
        gap = min(0.145, 0.62 / n)
        top_y = 0.50 + (n - 1) * gap / 2
        step = (dur - 1.4) / n
        lefts = [str(r.get("year") or r.get("label", "")) for r in use]
        whats = [r["what"] for r in use] or [""]
        # 左欄 0.08→0.30、中欄 0.32→0.76、數值欄右對齊收在 0.94。
        # 🔴 左欄寬度給太窄(0.13)時,fit_w 會把「a random shooter」縮到
        #    28pt,而中欄還是 40pt —— 抽幀看出來像兩種字級硬拼在一起。
        #    欄寬是版面決定的,不是「塞得下就好」。
        lf = min(fit_w(plt, w, 44, 0.20) for w in lefts if w) if any(lefts) else 44
        nf = min(fit_w(plt, w, 40, 0.42, "normal") for w in whats if w)
        for i, r in enumerate(use):
            if t_now < 0.4 + i * step:
                continue
            b = ease((t_now - 0.4 - i * step) / 0.6)
            y = top_y - i * gap
            hot = bool(r.get("hot")) or (use is rows and name == "twist"
                                         and i == len(use) - 1)
            ax.text(0.08, y, lefts[i], ha="left", va="center",
                    fontsize=lf, color=ACCENT if hot else DIM,
                    weight="bold", alpha=b)
            ax.text(0.32, y, r["what"], ha="left", va="center",
                    fontsize=nf, color=FG if hot else DIM,
                    weight="normal", alpha=b)
            if r.get("es") is not None and r.get("es_kind"):
                ax.text(0.94, y, val_str(r["es_kind"], r["es"]),
                        ha="right", va="center", fontsize=46,
                        color=ACCENT if hot else FG, weight="bold", alpha=b)

    elif name in ("authors", "verdict"):
        # 引號卡:作者自己的話。**逐字,不改寫** —— 改寫就不是引用了。
        if name == "authors":
            r = E["author_recantation"]
            q, by = r["quotes"][0], f"— {r['who'].split('(')[0].strip()}, {r['year']}"
            bycol = ACCENT
        else:
            q, by, bycol = T["verdict_quote"], "— the authors, in the paper", DIM
        lines = _quote_lines(plt, q)
        fs = fit_w(plt, max(lines, key=len), 44, 0.84, "normal")
        # 整塊置中,署名貼在塊的正下方 —— 不是釘在畫面底部。
        # (釘底部的版本:四行引言收在 0.42,署名在 0.14,中間空一大條。)
        lh = 0.098
        top = 0.56 + (len(lines) - 1) * lh / 2
        for i, ln in enumerate(lines):
            txt(top - i * lh, ln, fs, FG, "normal")
        txt(top - len(lines) * lh - 0.06, by, 38, bycol,
            "bold" if name == "authors" else "normal")
        # 🔴 引句是**逐字**的,不能為了好懂改字 —— 改了就不是引用了。
        #    但逐字也會留下圈內縮寫:hot hand 那句寫「GVT's data」,
        #    而觀眾不知道 GVT 是誰(是三位原作者姓氏的縮寫)。
        #    解法是加一行**注解**,不是動引文:引文照抄,旁邊說明它。
        g = E.get("verdict_gloss") if name == "verdict" else None
        if g:
            txt(top - len(lines) * lh - 0.135, g, 30, DIM, "normal")

    else:
        txt(0.60, "THEY RAN IT AGAIN", 92)
        txt(0.42, "one claim · the numbers behind it", 42, DIM, "normal")

    # ── 三道守門 ──
    # 1) 內容存在性:守門只看「有沒有出界」「有沒有重疊」,對**該畫的
    #    東西根本沒畫**是全盲的。這條線出過:修「名稱被畫兩次」時拿掉了
    #    無條件那一行,只在一個分支補回來,於是整排標籤消失。
    if name in ("timeline", "twist"):
        # 🔴 檢查的必須是**這一段真的畫了哪一組列**。原本這裡寫死 rows,
        #    而 twist 改成畫 twist_rows 之後,守門拿 A 的內容去查 B 的畫面
        #    —— 於是它對一張完全正確的畫面報錯。斷言看錯對象和斷言太鬆
        #    一樣糟:前者讓人把守門關掉。
        checked = ctx["twist_rows"] if (name == "twist"
                                        and ctx["twist_rows"]) else rows
        shown = [ob.get_text() for ob in ax.texts
                 if (ob.get_alpha() or 1) >= 0.5]
        for r in checked:
            if r["es"] is None or not r.get("es_kind"):
                continue
            v = val_str(r["es_kind"], r["es"])
            if v in shown and r["what"] not in shown:
                raise SystemExit(
                    f"⛔ {name}:{r['year']} 的數字畫上去了但**說明沒有** "
                    f"—— 觀眾會看到一排沒有標籤的數字。")

    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    boxes = []
    for ob in list(ax.texts):
        bb = ob.get_window_extent(renderer=rend)
        for v, lo, hi, side in ((bb.x0 / W, 0.02, 0.98, "左"),
                                (bb.x1 / W, 0.02, 0.98, "右"),
                                (bb.y0 / H, 0.03, 0.97, "下"),
                                (bb.y1 / H, 0.03, 0.97, "上")):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise SystemExit(f"⛔ {name} 越界:「{ob.get_text()[:24]}」"
                                 f"{side}緣 {v:.3f}")
        if (ob.get_alpha() or 1) >= 0.35:
            boxes.append((ob.get_text()[:24], bb))
    # 2) 兩兩相交 —— 出界守門對「兩個都在界內但壓在一起」結構上全盲,
    #    而那個形狀讓 16 支已上線的 Shorts 全中。
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ta, A), (tb, B) = boxes[i], boxes[j]
            ox = min(A.x1, B.x1) - max(A.x0, B.x0)
            oy = min(A.y1, B.y1) - max(A.y0, B.y0)
            if ox > 2 and oy > 2:
                raise SystemExit(f"⛔ {name} 文字重疊:「{ta}」×「{tb}」"
                                 f"{ox:.0f}×{oy:.0f} 畫素")
    import numpy as np
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    if a.list or not a.slug:
        d = json.loads(SRC.read_text(encoding="utf-8"))
        for e in d["episodes"]:
            ready = "✓" if (e.get("say_twist") and e.get("say_verdict")) \
                else "缺 say_twist/say_verdict"
            print(f"  {e['slug']:20s} {ready:24s} {e['story_type']}")
        return 0

    E = load(a.slug)
    segs = build_script(E)
    rows = timeline_rows(E)
    print(f"[{a.slug}] {E['story_type']}")
    audit(E, segs)
    words = sum(len(t.split()) for _, t in segs)
    print(f"  稿 {words} 字 ≈ {words / 2.6:.0f} 秒")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    out = ROOT / "eps_rechecked" / a.slug
    out.mkdir(parents=True, exist_ok=True)
    for n, t in segs:
        (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    (out / "facts.json").write_text(
        json.dumps(E, ensure_ascii=False, indent=1), encoding="utf-8")
    from render_pipeline import tts, render_and_mux
    tts(out, segs)
    mp4, dur = render_and_mux(out, segs, render_scene, f"{a.slug}.mp4",
                              W, H, FPS,
                              ctx={"plt": _plt(), "E": E, "rows": rows,
                                   "twist_rows": twist_rows(E)})
    print(f"完成 → {mp4}  ({dur:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
