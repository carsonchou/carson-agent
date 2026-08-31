#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_shorts.py — Shorts 的 metadata 與上傳。

## 為什麼跟長片分開
Shorts 的角色不一樣,所以文案規則也不一樣:
- **標題要短**:手機上 Shorts 標題只顯示一行,長片那種完整問句會被截斷
- **說明第一行就要導回完整版** —— Short 的工作是把人帶到長片,不是取代它
- **`#Shorts` 標籤**:雖然 YouTube 主要靠長寬比與片長判定,加上去沒壞處

## 判定成 Short 的條件(實測)
垂直或方形 + 片長 ≤ 3 分鐘。我們的是 1080x1920、20~30 秒 → 會被判為 Short。
**16:9 的長片就算只有 90 秒也不會**,這是先前的誤解。

## 誠信
標題與說明的數字全部來自該集事實庫,跟長片走同一套溯源。Short 沒有版面
放信賴區間,所以它**不下存在性結論**——結論在完整版裡。

## 配額
videos.insert 同樣 1600/支,Shorts 與長片共用同一本帳(`quota.py`)。
**每日上限不要在這裡寫死** —— 它已經被寫錯過兩次(先是 8,455 跟 crontab
對不上,接著是 10,000 而實測那天做了 13 支)。判準只有一個地方:
`quota.DAILY`,而它的註解裡有那個數字的觀測來源。要看今天還剩多少就跑
`python quota.py`。

用法:
  python publish_shorts.py --list
  python publish_shorts.py --limit 2 --dry-run
  python publish_shorts.py --limit 2
"""
import argparse
import json
import pathlib
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded_shorts.json"
sys.path.insert(0, str(ROOT))
import quota  # noqa: E402  (同目錄;COST 要引用它)

LONG_LEDGER = ROOT / "uploaded.json"
META = ROOT / "publish_meta.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
#: 印給人看的估算 —— **引用預算判準那一份**,不要自己再寫一個。
#: 舊版寫死 1600+41,而真正的判準是 quota.SHORT(1600+6,輪詢
#: 已經從 20 次降到 6 次)。同一件事兩個數字,而印出來給人
#: 做決定的是錯的那個。
COST = quota.SHORT

#: build_meta 查過的長片狀態,供 cta_gate 沿用(不重查、不重印警告)
_LONGS_ALL, _LONGS_PUB = {}, {}

TAGS = ["Shorts", "psychology", "replication crisis", "science", "research",
        "effect size", "statistics"]


#: 一個資料夾是不是「FReD 那批」。
#: 🔴 **不能用 `startswith("ep")`。** 新的頻道戰績 Short 叫 `ep0`,前綴一樣,
#:    於是 `int(key[2:])` 算出 row=0 —— 它會被當成 ep000 的 Short,
#:    掛上 ep000 的標題與說明送出去。前綴約定看起來夠用,直到有第二個
#:    以它開頭的名字為止。改成精確比對三位數字。
_EPN = re.compile(r"^ep\d{3}$")


def is_row(name):
    return bool(_EPN.match(name))



def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token_manage.json"          # 寫入一律用 manage token
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def stale(items):
    """檢查 mp4 是不是舊碼的產物。

    長片那條線有 preflight 做這件事,Shorts 這條**原本沒有** —— 而排程
    16:25 會無人看管地送出 4 支。這條線的歷史就是「碼修好了、檔案也在,
    但 mp4 是舊碼渲的」,而且每次都是靜默的:沒有東西會報錯,只是送出去
    的片子跟你以為的不一樣。

    ## mtime 只能當觸發條件,不能當判準
    第一版直接比 mp4 mtime 和程式碼 mtime。那會**誤擋**:`make_short`
    匯入 `make_episode`,而 make_episode 大部分的改動(例如長片畫面的
    座標軸設定)對 Short 的產出根本沒有影響 —— 卻會讓整批 Short 被判成
    舊的,然後那天一支都不發。

    正解跟 preflight 一樣:mtime 舊只是**觸發**,真正的判準是把稿子
    **重新生一次逐字比對**。一樣的字 = 那次改動對這支是輸出中性的。
    """
    # 🔴 觸發集合要含**資料檔**,不只程式碼。旁白那句現在來自手寫的
    #    `facts/plain_claims.json`(經 `plain.py`),但這兩個檔一開始不在
    #    集合裡 —— 於是 08-29 改完 24 句白話句之後,mtime 閘門把 18/24 支
    #    直接跳過,連稿子都不會重生。那次剛好被 `visual_stale` 接住
    #    (兩行大寫跟著改了),但只要哪天**只潤了 spoken、兩行沒動**,
    #    visual_stale 比的是 claim_lines → 一樣 → 放行,這裡被 mtime 跳過
    #    → 放行,兩道全開,發出一支開場唸舊句子的片,而且完全靜默。
    #    判準沒錯(重生稿子逐字比),錯在觸發集合漏了真正會變的那個檔。
    src = max((ROOT / n).stat().st_mtime for n in
              ("make_short.py", "make_episode.py", "plain.py",
               "facts/plain_claims.json") if (ROOT / n).exists())
    sys.path.insert(0, str(ROOT))
    from make_short import collect, build_script
    bad = []
    for o in items:
        p = ROOT / o["video"]
        if not p.exists():
            bad.append(f"{o['key']}(檔案不在)")
            continue
        if p.stat().st_mtime >= src:
            continue
        d = ROOT / "shorts" / o["key"]
        try:
            key = o["key"]
            segs = build_script(collect(
                slug=None if is_row(key) else key,
                row=int(key[2:]) if is_row(key) else None))
        except Exception as e:                                # noqa: BLE001
            bad.append(f"{o['key']}(稿子重生失敗:{str(e)[:40]})")
            continue
        for n, txt in segs:
            f = d / f"narr_{n}.txt"
            if not f.exists() or f.read_text(encoding="utf-8").strip() != txt.strip():
                bad.append(f"{o['key']}(旁白已經不一樣了:{n})")
                break
    return bad, src


def visual_stale(items):
    """畫面有沒有變。

    陳舊檢查比旁白,對「**畫面的碼改了、旁白一字沒動**」是全盲的。
    `make_short` 渲染時會把「這支片的畫面計畫」落成 `visual.json`
    (字級、片尾卡那兩行、判決句、顏色),這裡把它用現行碼重算一次比對。

    比的是**產出**不是程式碼 —— 輸出中性的改動不會誤擋(理由見
    `make_short.visual_plan`)。

    ⚠️ **沒有 visual.json 的回報成「無法判斷」,不是「通過」。**
    那是舊版渲的片子,我不知道它的畫面是不是現行版本 —— 說不知道,
    不要用沉默假裝沒問題。
    """
    import wave as _wave
    sys.path.insert(0, str(ROOT))
    from make_short import collect, visual_plan, frame_digest, _plt
    plt = _plt()
    changed, unknown = [], []
    for o in items:
        d = ROOT / "shorts" / o["key"]
        p = d / "visual.json"
        if not p.exists():
            # 🔴 **沒有計畫檔不等於無從得知**。舊版渲的片子我算不出它當時
            #    的計畫,但我可以**直接量那個檔案** —— 成本是幾次 ffmpeg
            #    抽幀,大約十秒。回報「無法判斷」而答案其實查得到,會訓練
            #    人接受未知;那是「沉默假裝沒問題」的近親 —— 不是假裝,
            #    是**放棄追問**。
            try:
                import lint_short
                tmp = ROOT / "_lint_tmp_pub"
                tmp.mkdir(exist_ok=True)     # check() 不會自己建
                probs = lint_short.check(ROOT / o["video"], tmp)
            except Exception as e:                            # noqa: BLE001
                probs = [f"量不了({str(e)[:50]})"]
            unknown.append((o["key"], probs))
            continue
        key = o["key"]
        D = collect(slug=None if is_row(key) else key,
                    row=int(key[2:]) if is_row(key) else None)
        now = visual_plan(plt, D)
        # 🔴 幀雜湊要**用現行碼重畫**再比。只讀已渲好的檔只能證明「mp4 沒
        #    被換掉」,答不了真正的問題:「現行碼渲出來會不會不一樣」。
        #    重畫 9 幀約兩秒,而它是唯一連寫死的 y 座標與淡入時點都蓋得到的。
        durs = {}
        for f in d.glob("seg_*.wav"):
            with _wave.open(str(f)) as w:
                durs[f.stem[4:]] = w.getnframes() / w.getframerate()
        D["_fs"] = now["fs"]
        try:
            now["frames"] = frame_digest(plt, D, durs) if durs else None
        except SystemExit as e:      # 版面斷言 —— 現行碼畫出來就是越界的
            changed.append((key, f"現行碼畫出來會越界:{str(e)[:60]}"))
            continue
        was = json.loads(p.read_text(encoding="utf-8"))
        if json.dumps(now, sort_keys=True) != json.dumps(was, sort_keys=True):
            diff = [k for k in now if json.dumps(now[k], sort_keys=True)
                    != json.dumps(was.get(k), sort_keys=True)]
            changed.append((key, ", ".join(diff)))
    return changed, unknown


def scoreboard_gate(items):
    """戰績 Short 的數字必須等於**發布當下重算**的戰績。

    🔴 2026-08-30 實測:預告片一進 publish_meta,`make_ep0.tally()` 就把
    自己也數進去 → facts.json 變成 26 集 / 117,306 人。我發現長片有問題、
    修好了長片,**卻沒檢查同一份 facts 也餵給了 Short** —— 於是第二支
    帶錯數字的片照樣上線(bCV0bHwob6k 說「26 of them, 117,306 people,
    9 held up」,三個數字全錯)。
    「修在一條路上,而實際走的是另一條」——長片那道守門加了,這條沒加。
    """
    bad = []
    for o in items:
        if o["key"] != "ep0":
            continue
        try:
            from make_ep0 import tally
            now = tally()
            F = json.loads((ROOT / "eps_lineup" / "ep0" /
                            "facts.json").read_text(encoding="utf-8"))
        except Exception as e:                                # noqa: BLE001
            bad.append((o["key"], f"重算戰績失敗:{str(e)[:50]}"))
            continue
        for fld in ("k", "n_sum", "gone", "shrunk", "flipped", "survived"):
            if F.get(fld) != now.get(fld):
                bad.append((o["key"],
                            f"片裡的戰績跟現在重算的對不上:{fld} "
                            f"片中 {F.get(fld)} vs 現在 {now.get(fld)}"))
                break
    return bad


def cta_gate(items, longs_pub, longs_all):
    """擋下「片子自己講了一件當下不成立的事」的 Short。

    ## 為什麼閘門要在這裡,不是在算 metadata 的時候
    「完整版在本頻道」這句宣稱在一支 Short 裡有**三份**:說明欄、旁白、
    片尾卡的滿版大字。說明欄是動態組的(`link_line` 會依長片狀態調整),
    但旁白與片尾卡在渲染當下就烘進 mp4 了 —— 事後改不了。

    而長片的狀態**會在渲染之後改變**:`implicit_bias_test` 的長片因為畫面
    缺陷被轉成 unlisted,它的 Short 卻還在片尾用滿版大字說「Full episode
    on the channel」。當時我只修了說明欄那一份,等於把假話從最安靜的管道
    拿掉、留在最大聲的兩個。

    所以判準不能是「渲的時候對不對」,而是**發的當下對不對**:
    片子裡只要有那句宣稱,對應的長片就必須是 public。不是就不發 ——
    這條線的誠信全押在「說出口的話都查得到」。
    """
    CLAIM = ("is on the channel", "on this channel")
    blocked = []
    for o in items:
        key = o["key"]
        lk = f"eps/{key}" if is_row(key) else key
        d = ROOT / "shorts" / key
        said = False
        for f in d.glob("narr_*.txt"):
            t = f.read_text(encoding="utf-8").lower()
            if any(c in t for c in CLAIM):
                said = True
                break
        # 片尾卡的**實際兩行**在 `visual.json` 裡(渲染當下落檔),讀它。
        # 🔴 舊版寫「只要有 end 段就一定印了那兩行」—— 那在片尾卡是寫死的
        #    年代成立,但 `make_short.render` 早就改成依 `has_full` 分流:
        #    長片還沒發的那批渲進去的是中性卡「Every number / from the
        #    record」,**根本沒有宣稱**。舊假設讓這 13 支全部被誤擋,
        #    而我今天把補件也納入閘門之後,可發數量從 5 掉到 4。
        #    近似值在它所近似的東西改掉之後,就只是個錯的值。
        #
        #    這是**放寬**閘門,所以判準要比原本更硬,不是更軟:
        #    讀的是渲染當下落檔的實際字串,而 `visual_stale` 會用現行碼
        #    重算 + 重畫 9 幀比對,確認 visual.json 真的等於畫面。
        #    沒有 visual.json 就退回舊的保守假設(fail-closed)。
        vj = d / "visual.json"
        if vj.exists():
            try:
                card = " ".join(json.loads(
                    vj.read_text(encoding="utf-8")).get("end_card") or []).lower()
                if any(c.replace("is on the channel", "on the channel") in card
                       for c in CLAIM):
                    said = True
            except Exception:                                # noqa: BLE001
                said = True                                  # 讀不了就當有
        elif (d / "narr_end.txt").exists():
            said = True
        if not said:
            continue
        vid = longs_pub.get(lk) or longs_pub.get(key)
        if not vid:
            why = ("長片發過但目前不是 public" if (lk in longs_all or key in longs_all)
                   else "長片還沒發布")
            blocked.append((key, why))
    return blocked


def ledger(p):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(f"⛔ 帳本 {p} 讀不了({e})——繼續跑會重傳。")


def with_search_name(cand, q, o):
    """把可搜尋的效應名補到標題最前面。**所有回傳路徑都要經過這裡。**

    🔴 第一版寫在 short_title 的最後一行,而 `n_r is None` 的那條路
    **在它之前就 return 了** —— 於是 bystander_effect 與
    implicit_bias_test 這兩支(正好是需求分數有過關的)照樣沒有名字。
    「修在一條路上,而實際走的是另一條」,今天第三次。

    白話句是刻意寫成不含術語的,對已經在看的人好讀,但**沒有人會搜
    那句話** —— 有人搜的是 implicit bias test、IAT、ego depletion。
    這條線 40% 的入口來自搜尋。
    ⚠️ 長片與 Short 不掛同一個標題(模板化紅旗):只借名字,後面接的
    規模句跟長片的定調結語不同。
    """
    def lower1(s):
        return s[0].lower() + s[1:] if s else s

    name = (o["title"].split(":")[0].strip()
            if ":" in o.get("title", "") else "")
    key = name.lower()
    key = key[4:] if key.startswith("the ") else key
    have = bool(name) and bool(key) and key not in cand.lower()

    # 🔴 **候選要照「名字優先於規模句」排。**
    #    第一版只試「名字 + 完整候選」,塞不下就整個放棄退回裸問句。
    #    而 bystander_effect 的完整候選本來就已經 101 字元 —— 於是加不加
    #    名字都超長,兩個都被丟掉,結果是**最不該留的那個版本**留下來:
    #    沒有名字、也沒有規模。規模句沒有名字重要:規模在說明欄裡有,
    #    而名字是搜尋唯一的入口。
    for c in ((f"{name}: {lower1(cand)}",) if have else ()) + (cand,) + \
             ((f"{name}: {lower1(q)}",) if have else ()) + (q,):
        if len(c) <= 100:
            return c
    return q[:100]


def short_title(key, o):
    """Short 的標題。**兩個分支共用一份**,而且不放裸的效果量。

    ## 這是同一個毛病的第四、五處
    今天已經把標題、縮圖、Short 開場卡、說明第一行都從論文語言 + 裸小數
    換成手寫白話句。Short 的標題有**兩份各自的實作**,兩份都還在接
    「0.30 → 0.08 on 723 people」:
      - FReD 那份把長片標題切到問號、再接兩個效果量
      - 名案那份接「0.04 across 2,141 people」
    「0.30 → 0.08」對滑過去的人不構成任何訊息,而 Shorts 的標題本來就
    只露一行 —— 把那一行讓給兩個小數,等於沒有標題。

    切長片標題來當問句還有第二個問題:那是**拿衍生值當來源**。長片標題
    後面接了定調結語,切法依賴「問號在哪」;結語措辭一改,切出來的東西
    就變了。直接讀手寫的那句就好。

    ## 跟長片標題的差別
    長片是「白話句 + 定調結語」,Short 是「白話句 + 規模」。刻意不一樣:
    兩支片掛一模一樣的標題,對觀眾是重複、對 YPP 的模板化審查是紅旗。
    規模那句沿用 `make_thumbs.SCALE`(重做 vs 統合分流),不寫第三份。
    """
    import plain
    from make_thumbs import SCALE
    q = plain.spoken(key, o.get("dir"), o.get("slug"))
    if not q:
        return None                       # fail-closed
    f = o.get("facts") or {}
    # 🔴 **可搜尋的效應名要在標題裡。** 這一集之所以被做,就是因為
    #    「10000 hour rule」在 effect_scan 拿到 22 個候選裡的第一名。
    #    只放白話問句(「Is how much you practise what separates the
    #    best?」)整句不含那五個字 = 需求測試白做。長片標題今晚已經修過
    #    同一件事,Short 這份漏掉 —— 同一個錯的第二個表面,今晚第四次。
    # 效應名取長片標題冒號前那一段(publish_meta 已經把它放在最前面)。
    name = o["title"].split(":")[0] if ":" in o["title"] else ""
    if o.get("kind") == "trailer":
        # 🔴 **不要跟長片掛一模一樣的標題。** 長片是「25 famous psychology
        #    claims, retested on 58,653 people. 8 held up.」——同一句再用一次,
        #    對觀眾是重複,對 YPP 的模板化審查是紅旗(見本函式 docstring)。
        return (f"We checked {f['k']} famous psychology claims. "
                f"{f['n_sig']} held up.")
    if o.get("kind") == "domains":
        # kind=domains 底下有兩種形狀。**分開處理,不要假設有 pct_best** ——
        # outcomes 那種沒有百分比,直接 KeyError 把整個 build_meta 炸掉,
        # 連帶讓當晚一支 Short 都發不出去。
        if f.get("arc") == "outcomes":
            # 🔴 **「N 個裡回來 M 個」只有在 N 項都在測同一個宣稱時才對。**
            #    長片端已經改成「先講宣稱本身怎麼了」,這份漏掉 ——
            #    於是 learning styles 的 Short 掛著「3 個裡回來 2 個」出去,
            #    讀起來像理論部分成立,而真相是**要成立的那一個沒回來**。
            #    同一個錯的第二個表面,而且這次是在片子已經送出之後才發現。
            if f.get("claim_p") is not None and not f.get("claim_sig"):
                cand = (f"{name}: the one thing the idea needs came back at "
                        f"p = {f['claim_p']:.2f}.")
            else:
                cand = (f"{name}: they measured {f['k']} things. "
                        f"{f['n_kept']} came back.")
            return cand if len(cand) <= 100 else q[:100]
        best, worst = f.get("best"), f.get("worst")
        cand = (f"{name}: practice explained {f['pct_best']}% in {best}, "
                f"under {f['pct_worst']}% in {worst}.")
        return cand if len(cand) <= 100 else q[:100]
    if o.get("kind") == "lineup":
        cand = (f"{name}: {f['k']} replications, {f['n_r']:,} people, "
                f"{f['n_sig']} worked.")
        return cand if len(cand) <= 100 else q[:100]
    if f.get("n_r") is None:
        return with_search_name(q, q, o)
    scale = SCALE[f.get("is_replication", True)].format(
        n=int(f["n_r"]), k=f.get("k"), k_word=f.get("k_word") or "studies")
    cand = f"{q} {scale}"
    # 🔴 **可搜尋的名字要在標題裡。** 這一批的白話句是刻意寫成不含術語的
    #    (「Can a reaction-time test reveal your hidden bias?」),對「已經
    #    在看」的人很好讀,但**沒有人會搜那句話** —— 有人搜的是
    #    「implicit bias test」「IAT」「ego depletion」。而這條線 40% 的
    #    入口來自搜尋(memory yt-search-capture-engine)。
    #    長片標題冒號前那一段就是那個名字,publish_meta 已經把它放在最前面。
    #    ⚠️ 長片與 Short **不掛同一個標題**(模板化紅旗),所以只借名字,
    #    後面接的規模句跟長片的定調結語不同。
    return with_search_name(cand, q, o)


def famous_meta(d, o, mp4, longs, longs_all):
    """名案 Short 的標題與說明。

    跟 FReD 那批的差別在**標題賣的東西不一樣**:FReD 集賣的是落差
    (0.63 → 0.00),名案賣的是**這個說法你聽過**(意志力會用完、旁觀者
    效應)。零訂閱頻道能被搜到的只有後者,所以標題以那句主張開頭。
    數字一律沿用該集已通過審核的 metadata,不重算。
    """
    sys.path.insert(0, str(ROOT))
    from make_short import collect
    D = collect(slug=d.name)
    title = short_title(d.name, o)
    if not title:
        return None                       # fail-closed:缺白話句就不發
    # 🔴 長片帳本的 key 對名案是**裸 slug**(`ego_depletion`),不是 dir。
    #    查 `eps_famous/{slug}` 會 miss,然後**靜默**退回「完整版在本頻道」
    #    —— 而導流到完整版正是 Short 存在的唯一理由,連結掉了等於這支
    #    Short 白發。兩種 key 都試。(縮圖那邊犯過同一個錯,我當時只修了
    #    那一處 —— 又是「同一件事兩個地方」。)
    link = link_line(d.name, longs, longs_all)
    head = as_claim(o["description"].split("\n")[0])
    # 🔴 數字那一行**依這一集真的有什麼而定**。舊版寫死「Measured
    #    effect: X (N people)」,對跨領域集(數字是每個領域的百分比,
    #    沒有 es_r 也沒有 n_r)直接丟 TypeError;對效應家族則會把
    #    6 種做法、12 次重測的中位數講成單一個效果量。
    if D.get("scoreboard"):
        T = D["scoreboard"]
        nums = (f"{T['k']} claims, {T['n_sum']:,} people in the "
                f"replications\n"
                f"  {T['gone']} gone\n"
                f"  {T['shrunk']} smaller, still there\n"
                f"  {T['flipped']} went the other way\n"
                f"  {T['survived']} held up\n")
    elif D.get("outcomes"):
        # 有 d 就寫 d,沒有的寫它真正報的統計式 —— **不硬換算**。
        # (長片端已經處理過這件事,這份漏掉:同一個錯的第二個表面,
        #  而 outcomes 這條路徑今天已經因為「假設某個欄位一定在」炸了四次。)
        nums = ("What the replication found:\n"
                + "\n".join(
                    f"  {x.get('name_long') or x['name']:<26} "
                    + (f"d = {x['d']:+.2f}  " if x.get("d") is not None
                       else f"{x.get('stat') or ''}  ")
                    # 🔴 註解就在上面兩行,寫著「outcomes 這條路徑今天已經
                    #    因為假設某個欄位一定在炸了四次」—— 然後同一個
                    #    運算式裡的 p 還是直接格式化。**第五次,同一段。**
                    #    loss aversion 報的是 lambda 中位數,論文對那些
                    #    數字沒有做顯著性檢定,p 是 None。
                    + (f"p = {x['p']:.3f}  " if x.get("p") is not None
                       else "")
                    + ("significant" if x["sig"] else "not significant")
                    for x in D["outcomes"]) + "\n")
    elif D.get("domains"):
        from make_domains import fmt_pct
        nums = ("Percent of the variance in performance explained:\n"
                + "\n".join(f"  {x['name']}: {fmt_pct(x)}"
                            for x in D["domains"]) + "\n")
    elif D.get("k_distinct"):
        nums = (f"{D['k_distinct']} setups, {D['k']} replications, "
                f"{D['n_r']:,} people\n"
                f"Typical original {D['es_o']:+.2f} then typical replication "
                f"{D['es_r']:+.2f}\n".replace("+", ""))
    else:
        scale = (f"{D['k']} {D['k_word']}, {D['n_r']:,} people" if D.get("k")
                 else f"{D['n_r']:,} people")
        nums = f"Measured effect: {D['es_r']:+.2f} ({scale})\n".replace("+", "")
    # 🔴 來源也寫死了 FReD。名案的數字出自各自的統合分析、跨領域那集
    #    出自 2014 年一篇統合分析 —— 指錯地方比不寫還糟,而說明欄是
    #    觀眾唯一能複製貼上去查的地方。**這是同一個假來源的第二份**
    #    (第一份在 make_short 的旁白與畫面,今晚一起修)。
    src = str(D.get("source_full") or D.get("source") or "")
    src_line = ("\nSource: FORRT Replication Database (FReD), osf.io/2tbvd\n"
                if ("FORRT" in src or "FReD" in src)
                else f"\nSource: {src}\n")
    desc = (link + head + "\n\n" + nums
            + (f"{D['card']}\n" if D["card"] else "")
            + src_line + "#Shorts")
    from publish_meta import api_safe
    title, desc = api_safe(title, d.name), api_safe(desc, d.name)
    return {"key": d.name, "video": str(mp4.relative_to(ROOT)),
            "title": title, "description": desc, "tags": TAGS,
            "tone": "famous"}


def public_only(longs):
    """把帳本裡**目前不是 public** 的長片剔掉。

    Short 說明第一行是「Full episode: <連結>」。如果那支長片被轉成不公開
    (例如發現畫面有缺陷而撤下),這行就會把觀眾送到一支我自己認為不該
    出現在搜尋裡的片 —— 那是自相矛盾。實際發生過:`implicit_bias_test`
    的 scale 幕畫面與旁白打架 20% 的時間,轉成 unlisted 之後,它的 Short
    仍然指著它。

    配額 1 單位(一次 videos.list 查全部),換掉一個結構性的自打嘴巴。
    查不到就**保守地當作不可連**——寧可少一行導流,不要送錯地方。
    """
    ids = [v for v in longs.values() if v]
    if not ids:
        return {}
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        cr = Credentials.from_authorized_user_file(
            str(CH2 / "token.json"),
            ["https://www.googleapis.com/auth/youtube.readonly"])
        yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
        ok = set()
        for i in range(0, len(ids), 50):
            for v in yt.videos().list(part="status",
                                      id=",".join(ids[i:i + 50])).execute()["items"]:
                if v["status"]["privacyStatus"] == "public":
                    ok.add(v["id"])
    except Exception as e:                                   # noqa: BLE001
        print(f"  (查不到長片狀態,導流連結一律省略:{str(e)[:60]})")
        return {}
    dropped = [k for k, v in longs.items() if v and v not in ok]
    if dropped:
        print(f"  ⚠️ 這幾支長片目前不是 public,Short 不會連過去:"
              f"{', '.join(dropped)}")
    return {k: v for k, v in longs.items() if v in ok}


def as_claim(line):
    """把主張句標成**主張**,不是斷言。

    說明欄第一行常被當預覽顯示。「Willpower is a limited resource that runs
    out as you use it.」單獨看,讀起來像這個頻道在主張它 —— 而整支片的
    內容正好是「量出來只有 0.04」。這條線的立場是把兩邊都攤開,不是替
    任何一方背書,所以那句話必須看得出來是**被檢驗的東西**。

    已經是問句的不動(問句本來就不是斷言)。
    """
    t = (line or "").strip()
    if not t or t.endswith("?"):
        return t
    return "The claim being tested: " + t[0].lower() + t[1:]


def link_line(key, longs_pub, longs_all):
    """Short 說明第一行。三種情況,每一種都要講真話。

    - **有公開的完整版** → 直接給連結,那是 Short 唯一的工作
    - **完整版還沒發** → 「即將上架」是實話(它就在 publish_meta 的佇列裡,
      每天的排程會發)
    - **完整版發過但被撤下** → **什麼都不說**。原本無論哪種都印
      「The full episode is on this channel」,而那對被轉成不公開的片是
      **假的** —— 它已經不在頻道頁上了。這條線的誠信全押在「說出口的話
      都查得到」,不能為了版面留一句漂亮但不成立的話。
    """
    vid = longs_pub.get(key)
    if vid:
        return f"Full episode: https://youtu.be/{vid}\n\n"
    if key in longs_all:
        return ""                      # 發過但目前不公開 → 不做任何宣稱
    return "The full episode goes up on this channel.\n\n"


def build_meta():
    """從各集的 Short 稿子與長片 metadata 組出 Shorts 的標題與說明。"""
    sys.path.insert(0, str(ROOT))
    from make_episode import build_facts, CARD_TEXT
    import pandas as pd
    q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    global _LONGS_ALL, _LONGS_PUB
    longs_all = _LONGS_ALL = ledger(LONG_LEDGER)
    longs = _LONGS_PUB = public_only(longs_all)
    meta = {o.get("row"): o for o in json.loads(META.read_text(encoding="utf-8"))
            if o.get("kind") == "fred"}
    by_dir = {o.get("dir"): o for o in
              json.loads(META.read_text(encoding="utf-8"))}
    out = []
    # 名案的資料夾名是 slug(bystander_effect…),FReD 那批是 ep013。
    # ── 新格式的 35~45 秒短片(reels/)────────────────────────────
    # 🔴 這一批**排在最前面**,而且理由是量出來的,不是偏好:
    #    2026-08-31 實測 28 支舊 Short(14~26 秒)拿到 289 次觀看、
    #    **0 留言 0 分享 1 個讚**。Analytics 顯示 feed 有在推(131/141)、
    #    留存 64.6~79.3% 也不差 —— 沒有人有理由反應才是問題。
    #    Shorts 的分發靠前一批曝光回收的訊號決定要不要放大,所以
    #    **再發一批同樣不會被回應的片,不會改變任何事**。
    rd = ROOT / "reels"
    if rd.exists():
        for d in sorted(rd.iterdir()):
            mp4 = d / f"{d.name}_reel.mp4"
            fj = d / "facts.json"
            if not (mp4.exists() and fj.exists()):
                continue
            E = json.loads(fj.read_text(encoding="utf-8"))
            r = E.get("reel") or {}
            if not r.get("belief") or not r.get("ask"):
                print(f"  ⛔ {d.name}:reel 文案不全,不發")
                continue
            T, O = E["test"], E["original"]
            if not T.get("doi") or not O.get("doi"):
                print(f"  ⛔ {d.name}:缺 DOI,不發")
                continue
            nl = chr(10)
            title = f"{E['popular_name']}: {E['story_type_short']}"
            if len(title) > 95:
                title = title[:95].rsplit(" ", 1)[0]
            desc = (
                f"{r['belief']}{nl}{nl}"
                f"{r['verdict']}{nl}{nl}"
                f"{r['ask']}{nl}{nl}"
                f"Original: {O.get('title', '')} ({O['year']}){nl}"
                f"  doi:{O['doi']}{nl}"
                f"Retest: {T.get('title', '')} ({T['year']}){nl}"
                f"  doi:{T['doi']}{nl}{nl}"
                f"Every number here was read out of the paper itself and is "
                f"stored with the sentence it came from.{nl}#Shorts")
            out.append({"key": f"reel_{d.name}",
                        "video": str(mp4.relative_to(ROOT)),
                        "title": title, "description": desc, "tags": TAGS,
                        "tone": E.get("tone", "shrunk_real")})

    # 排序讓名案排在前面 —— 那是唯一有人認得、會主動搜的題材,而這個
    # 頻道現在最缺的是「被發現」,不是「有貨」。
    dirs = sorted((ROOT / "shorts").iterdir(),
                  key=lambda d: (is_row(d.name), d.name))
    for d in dirs:
        mp4 = d / f"{d.name}_short.mp4"
        if not mp4.exists():
            continue
        if not is_row(d.name):
            # 🔴 **不要只找一個前綴。** 舊版只查 `eps_famous/`,於是
            #    eps_lineup(效應家族)與 eps_domain(跨領域)那兩支
            #    渲好的 Short 被**靜默跳過** —— 片子在、metadata 在、
            #    清單裡就是沒有它,而且一個字都不會印。
            #    這條線今晚已經修過三次同型的靜默跳過。
            o = next((by_dir.get(f"{pre}/{d.name}")
                      for pre in ("eps_famous", "eps_lineup", "eps_domain")
                      if by_dir.get(f"{pre}/{d.name}")), None)
            if not o:
                print(f"  ⛔ {d.name}:有成片但 publish_meta 裡找不到"
                      f"(查過 eps_famous / eps_lineup / eps_domain)——"
                      f"不發,但你現在知道了")
                continue
            # 🔴 famous_meta 缺白話句時回 None。FReD 那條分支有
            #    `if not title: continue` 擋著,這條**沒有** —— None 進了
            #    items,下一步 `o["key"]` 就 TypeError,整輪一支都發不出去。
            #    同一分支兩套標準(獨立驗證抓到的)。
            m = famous_meta(d, o, mp4, longs, longs_all)
            if m is None:
                print(f"  ⛔ {d.name}:算不出標題(缺白話句)—— 跳過")
                continue
            out.append(m)
            continue
        row = int(d.name.replace("ep", ""))
        F = build_facts(q.iloc[row])
        o = meta.get(row)
        if not o:
            continue
        # 標題:短、給落差、不下結論。
        # 🔴 太長時要退回**問句**,不是退回數字。舊版的 fallback 會產出
        #    「0.25 → 0.01 on 6,608 people」這種純數字標題(21 支裡有 6 支
        #    中招)—— 滑過的人看不懂那是什麼,搜尋也搜不到,等於把唯一
        #    能被發現的那半句丟掉,留下最沒用的那半句。
        title = short_title(f"ep{row:03d}", o)
        if not title:
            continue                      # fail-closed:缺白話句就不發

        link = link_line(f"eps/ep{row:03d}", longs, longs_all)
        desc = (link
                + f"{as_claim(o['description'].split(chr(10))[0])}\n\n"
                + f"Original study: {F['orig']['n']:,} people, "
                  f"effect size {F['orig']['es']:+.2f}\n".replace("+", "")
                + f"Replication: {F['repl']['n']:,} people, "
                  f"effect size {F['repl']['es']:+.2f}\n".replace("+", "")
                + f"{CARD_TEXT[F['tone']]}\n\n"
                + "Source: FORRT Replication Database (FReD), osf.io/2tbvd\n"
                  "#Shorts")
        out.append({"key": d.name, "video": str(mp4.relative_to(ROOT)),
                    "title": title, "description": desc, "tags": TAGS,
                    "tone": F["tone"]})
    return out


def insert_one(yt, o, path):
    """把一支 Short 上傳成 public,回傳 videoId。**唯一一份 insert。**

    重上傳(reupload_shorts.py)走的是同一個函式 —— 兩份 insert 就會有
    一份先被改對、另一份留著舊的欄位組合,而那種差異在成品上是看不出來的。
    這條線上「同一件事兩份實作」已經數不清第幾次。
    """
    from googleapiclient.http import MediaFileUpload
    req = yt.videos().insert(part="snippet,status", body={
        "snippet": {"title": o["title"], "description": o["description"],
                    "tags": o["tags"], "categoryId": "27",
                    "defaultLanguage": "en"},
        "status": {"privacyStatus": "public",
                   "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }, media_body=MediaFileUpload(str(path), chunksize=4 * 1024 * 1024,
                                  resumable=True, mimetype="video/mp4"))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def reel_gate(batch):
    """新格式(reels/)的發布前閘門。回傳 [(key, 理由)]。

    這一批**沒有** `visual.json`,也沒有「完整版在本頻道」那種 CTA,
    所以舊的四道對它們算不出東西。它要驗的是它自己的那些前提:

    1. 直式、30~60 秒 —— **片長就是這次改版的處置本身**,不驗等於
       「改了設定當成改了東西」(這條剛在同一天踩過)。
    2. 影音時長對得上 —— 兩個實例互刪影格時 ffmpeg 照樣 mux 成功。
    3. **磁碟上的旁白 == 事實庫現在的 reel 文案**。文案是手寫的,
       手寫的東西沒有任何機械守門看得住;改了文案沒重渲的話,
       片子唸舊版、說明欄用新版,而兩個表面都會出去。
    4. 兩篇論文的 DOI 都在說明欄裡 —— 這條線唯一的資產是查得到。
    """
    import subprocess as _sp
    out = []
    for o in batch:
        key = o["key"]
        slug = key[len("reel_"):]
        d = ROOT / "reels" / slug
        mp4 = ROOT / o["video"]
        if not mp4.exists():
            out.append((key, "mp4 不見了")); continue
        try:
            def _dur(stream):
                r = _sp.run(["ffprobe", "-v", "error", "-select_streams",
                             stream, "-show_entries", "stream=duration,width,height",
                             "-of", "default=nw=1", str(mp4)],
                            capture_output=True, text=True)
                return r.stdout
            v = _dur("v:0"); a = _dur("a:0")
            vd = float([x for x in v.splitlines()
                        if x.startswith("duration=")][0].split("=")[1])
            ad = float([x for x in a.splitlines()
                        if x.startswith("duration=")][0].split("=")[1])
            wpx = int([x for x in v.splitlines()
                       if x.startswith("width=")][0].split("=")[1])
            hpx = int([x for x in v.splitlines()
                       if x.startswith("height=")][0].split("=")[1])
        except Exception as e:                               # noqa: BLE001
            out.append((key, f"量不到影片規格({str(e)[:40]})")); continue
        if hpx <= wpx:
            out.append((key, f"不是直式({wpx}x{hpx})—— 進不了 Shorts feed"))
            continue
        if not (30 <= vd <= 60):
            out.append((key, f"片長 {vd:.0f} 秒,不在 30~60 秒"))
            continue
        if abs(vd - ad) > 1.0:
            out.append((key, f"影像 {vd:.1f}s 對不上音軌 {ad:.1f}s"))
            continue
        # 旁白 vs 事實庫
        try:
            E = json.loads((d / "facts.json").read_text(encoding="utf-8"))
            src = json.loads((ROOT / "facts" / "rechecked_episodes.json")
                             .read_text(encoding="utf-8"))
            cur = next(x for x in src["episodes"] if x["slug"] == slug)
        except Exception as e:                               # noqa: BLE001
            out.append((key, f"讀不了事實庫({str(e)[:40]})")); continue
        drift = [k for k in ("belief", "weight", "turn", "verdict", "ask")
                 if (d / f"narr_{k}.txt").exists()
                 and (d / f"narr_{k}.txt").read_text(encoding="utf-8").strip()
                 != (cur.get("reel") or {}).get(k, "").strip()]
        if drift:
            out.append((key, f"片裡唸的跟事實庫現在的 reel 對不上:{drift}"
                             f" —— 要重渲"))
            continue
        for who, p in (("原始", E.get("original") or {}),
                       ("重測", E.get("test") or {})):
            if not p.get("doi"):
                out.append((key, f"{who}論文沒有 DOI")); break
            if p["doi"] not in o["description"]:
                out.append((key, f"{who}論文的 DOI 不在說明欄裡")); break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    ap.add_argument("--list", action="store_true", dest="show")
    a = ap.parse_args()

    items = build_meta()
    done = ledger(LEDGER)
    todo = [o for o in items if o["key"] not in done]
    if a.show:
        for o in items:
            mark = done.get(o["key"], "未上傳")
            print(f"  {o['key']:<20}{o['tone']:<12}{mark:<10}{o['title'][:56]}")
        print(f"\n共 {len(items)} 支,已上傳 {len(done)},待上傳 {len(todo)}")
        return 0

    # ── 閘門 + 補件:**單一入口** ────────────────────────────────
    # 🔴 舊版 cta_gate 擋了會補件、visual_stale 擋了不補。後果不是少發
    #    一支:排序把名案排在最前面,前幾支被畫面閘門擋住之後,
    #    ep012–ep018 那幾支乾淨的片**永遠輪不到**。實測明天 16:25 只發
    #    得出 1 支(排程要 2)、22:25 只發得出 1 支(要 3)。
    #    一個補了不檢查、一個檢查了不補 —— 同一個位置的鏡像問題,
    #    而我上一次只修了前者。
    def _gate(batch):
        """所有發布前閘門跑一遍。回傳 ({key: 理由}, 無法判斷的)。"""
        bad = {}
        # 🔴 舊格式的四道閘門全部綁 `shorts/<key>` 的路徑與 visual.json,
        #    對 `reel_*` 不是「通過」而是**算不出來**。直接讓它們跳過就是
        #    fail-open —— 這條線上「認不得 ≠ 不用檢查」已經寫過一次
        #    (upload.semantic_gate 的新集型分支)。所以把 reels 分流到
        #    它自己的閘門,不是繞過。
        reels = [o for o in batch if o["key"].startswith("reel_")]
        olds = [o for o in batch if not o["key"].startswith("reel_")]
        for k, why in reel_gate(reels):
            bad[k] = why
        if olds:
            for k, why in cta_gate(olds, _LONGS_PUB, _LONGS_ALL):
                bad[k] = why
            ch, unk = visual_stale(olds)
            for k, w in ch:
                bad.setdefault(k, f"畫面已跟現行碼不同(差在 {w})")
            for k, why in scoreboard_gate(olds):
                bad.setdefault(k, why)
        else:
            unk = []
        return bad, unk

    pool = todo
    todo, rest = pool[:a.limit], pool[a.limit:]
    blocked_all, vunknown = {}, []
    for _round in range(12):          # 有界:候補用完或名額補滿就停
        bad, vunknown = _gate(todo)
        if not bad:
            break
        blocked_all.update(bad)
        todo = [o for o in todo if o["key"] not in bad]
        if not rest:
            break
        while len(todo) < a.limit and rest:
            todo.append(rest.pop(0))
    if blocked_all:
        print("⛔ 這幾支被閘門擋下(已從候補補件):")
        for k_, why in blocked_all.items():
            print(f"   {k_:<22}{why}")
    if not todo:
        print("沒有待上傳的 Short")
        return 0
    if vunknown:
        print("❗ 這幾支沒有畫面計畫檔(舊版渲的)。算不出它當時的計畫,"
              "所以改成**直接量檔案**:")
        for key, probs in vunknown:
            if probs:
                print(f"   {key:<22}已知缺陷:{probs[0]}")
            else:
                print(f"   {key:<22}四個邊都量過,沒有越界 ✓"
                      f"(但仍非「畫面是最新版」的證明)")
        print("   → 不擋。這是**已知狀態**,不是未知 —— 判斷已經做過了。")
    bad, src = stale(todo)
    if bad:
        import datetime as _dt
        print('⛔ 這幾支是舊碼的產物,不上傳:')
        for b in bad:
            print(f'   {b}')
        print(f"   程式碼最後修改 "
              f"{_dt.datetime.fromtimestamp(src):%Y-%m-%d %H:%M},"
              f"重跑 make_short.py 後再發。")
        return 1
    sent, planned = 0, len(todo)
    print(f"要上傳 {planned} 支,估算配額 {planned * COST:,}")
    for o in todo:
        print(f"  {o['key']:<20}{o['title'][:70]}")
    if a.dry:
        print("\n--dry-run:未連網、未上傳。")
        return 0

    yt = svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1
    for o in todo:
        # 🔴 逐支問額度,不是整批估一次。三支發布器共用同一個每日 10,000,
        #    而排程一天跑兩個時段 —— 各自估自己那批,就會各自以為還有滿額。
        if not quota.can(quota.SHORT):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡"
                  f"(下一支要 {quota.SHORT:,})—— 明天續發")
            break
        p = ROOT / o["video"]
        print(f"\n[{o['key']}] {o['title'][:60]}")
        # 🔴 insert 外面**必須有 try/except**。舊版 403 直接往上炸:
        #    後面的片不會試、`note_exhausted()` 不會執行、
        #    「發了幾支、為什麼停」完全沒有紀錄。
        #    而配額被擋是這條線的常態,不是理論風險。
        try:
            vid = insert_one(yt, o, p)
        except Exception as e:                                # noqa: BLE001
            if "quota" in str(e).lower():
                quota.note_exhausted(f"shorts insert {o['key']}")
                print(f"  ⛔ 配額被 API 擋下,停在 {o['key']}")
                break
            print(f"  ⛔ {o['key']} 上傳失敗:{str(e)[:80]}")
            continue
        # 拿到 id 立刻寫帳本(insert 之後的任何例外都不該造成重傳)
        done[o["key"]] = vid
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(LEDGER)
        quota.spend(quota.SHORT, o["key"])      # 成功才記
        sent += 1
        print(f"    videoId={vid}  https://youtube.com/shorts/{vid}"
              f"  (配額剩 {quota.remaining():,})")
        # 15 秒的直式影片處理很快,實測幾秒內就 processed。
        # 輪詢每次 1 單位 —— 20 次是白花的,而在 6 支/天的
        # 天花板下,每支省 14 單位就是省 84。
        for _ in range(6):
            got = yt.videos().list(part="status", id=vid).execute().get("items", [])
            if got and got[0]["status"].get("uploadStatus") == "processed":
                print("    處理完成 ✓")
                break
            time.sleep(15)
    # 🔴 「停在這裡」和「什麼都沒做」都**不是成功**。舊版無條件 return 0:
    #    配額不足在第 2 支 break 是 0、閘門把 todo 清空(for 迴圈根本不跑)
    #    也是 0 —— 而後者讀起來像「完成」。`if not todo: return 0` 那道檢查
    #    排在閘門**之前**,閘門之後沒有再看一次。
    #    跟 retitle.py 配額不足回 0 是同一個模式。
    print(f"\n完成:上傳 {sent}/{planned} 支。Shorts 帳本共 {len(done)} 支。")
    return 0 if (planned and sent == planned) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
