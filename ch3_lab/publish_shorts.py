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
videos.insert 同樣 1600/支。Shorts 與長片共用同一個每日 10,000。
所以排程要**分流**:長片一天 3 支、Shorts 一天 2 支,合計約 8,455 單位。

用法:
  python publish_shorts.py --list
  python publish_shorts.py --limit 2 --dry-run
  python publish_shorts.py --limit 2
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded_shorts.json"
LONG_LEDGER = ROOT / "uploaded.json"
META = ROOT / "publish_meta.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
COST = 1600 + 41

#: build_meta 查過的長片狀態,供 cta_gate 沿用(不重查、不重印警告)
_LONGS_ALL, _LONGS_PUB = {}, {}

TAGS = ["Shorts", "psychology", "replication crisis", "science", "research",
        "effect size", "statistics"]


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
                slug=None if key.startswith("ep") else key,
                row=int(key[2:]) if key.startswith("ep") else None))
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
        D = collect(slug=None if key.startswith("ep") else key,
                    row=int(key[2:]) if key.startswith("ep") else None)
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
        lk = key if not key.startswith("ep") else key.replace("ep", "eps/ep")
        d = ROOT / "shorts" / key
        said = False
        for f in d.glob("narr_*.txt"):
            t = f.read_text(encoding="utf-8").lower()
            if any(c in t for c in CLAIM):
                said = True
                break
        # 片尾卡的畫面文字是寫死的,只要有 end 段就一定印了那兩行
        if (d / "narr_end.txt").exists():
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
    if f.get("n_r") is None:
        return q[:100]
    scale = SCALE[f.get("is_replication", True)].format(
        n=int(f["n_r"]), k=f.get("k"), k_word=f.get("k_word") or "studies")
    cand = f"{q} {scale}"
    return cand if len(cand) <= 100 else q[:100]


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
    scale = (f"{D['k']} {D['k_word']}, {D['n_r']:,} people" if D.get("k")
             else f"{D['n_r']:,} people")
    desc = (link + head + "\n\n"
            + f"Measured effect: {D['es_r']:+.2f} ({scale})\n".replace("+", "")
            + (f"{D['card']}\n" if D["card"] else "")
            + "\nSource: FORRT Replication Database (FReD), osf.io/2tbvd\n"
              "#Shorts")
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
    # 排序讓名案排在前面 —— 那是唯一有人認得、會主動搜的題材,而這個
    # 頻道現在最缺的是「被發現」,不是「有貨」。
    dirs = sorted((ROOT / "shorts").iterdir(),
                  key=lambda d: (d.name.startswith("ep"), d.name))
    for d in dirs:
        mp4 = d / f"{d.name}_short.mp4"
        if not mp4.exists():
            continue
        if not d.name.startswith("ep"):
            o = by_dir.get(f"eps_famous/{d.name}")
            if not o:
                continue
            out.append(famous_meta(d, o, mp4, longs, longs_all))
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

    todo = todo[:a.limit]
    if not todo:
        print("沒有待上傳的 Short")
        return 0
    # build_meta 已經查過一次長片狀態,這裡沿用它算好的 —— 重查會多花
    # 配額,而且會把同一行警告印兩遍。
    blocked = cta_gate(todo, _LONGS_PUB, _LONGS_ALL)
    if blocked:
        keys = {k for k, _ in blocked}
        print("⛔ 這幾支片子自己會說「完整版在本頻道」,但那句話現在不成立:")
        for k, why in blocked:
            print(f"   {k:<22}{why}")
        print("   → 先跳過它們,改發下一批。長片轉回 public 之後那句話"
              "自己就成立了,不必重渲。")
        todo = [o for o in todo if o["key"] not in keys]
        # 被擋掉幾支就從候補補幾支上來,不要讓當天的發布名額憑空少掉
        rest = [o for o in items
                if o["key"] not in done and o["key"] not in keys
                and o not in todo]
        todo += rest[:a.limit - len(todo)]
    vchanged, vunknown = visual_stale(todo)
    if vchanged:
        print("⛔ 這幾支的**畫面**已經跟現行碼不一樣了(旁白沒變所以陳舊檢查看不到):")
        for k_, w in vchanged:
            print(f"   {k_:<22}差在:{w}")
        todo = [o for o in todo if o["key"] not in {k_ for k_, _ in vchanged}]
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
    print(f"要上傳 {len(todo)} 支,估算配額 {len(todo) * COST:,}")
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
    from googleapiclient.http import MediaFileUpload
    import quota
    for o in todo:
        # 🔴 逐支問額度,不是整批估一次。三支發布器共用同一個每日 10,000,
        #    而排程一天跑兩個時段 —— 各自估自己那批,就會各自以為還有滿額。
        if not quota.can(quota.SHORT):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡"
                  f"(下一支要 {quota.SHORT:,})—— 明天續發")
            break
        p = ROOT / o["video"]
        print(f"\n[{o['key']}] {o['title'][:60]}")
        req = yt.videos().insert(part="snippet,status", body={
            "snippet": {"title": o["title"], "description": o["description"],
                        "tags": o["tags"], "categoryId": "27",
                        "defaultLanguage": "en"},
            "status": {"privacyStatus": "public",
                       "selfDeclaredMadeForKids": False,
                       "license": "youtube", "embeddable": True},
        }, media_body=MediaFileUpload(str(p), chunksize=4 * 1024 * 1024,
                                      resumable=True, mimetype="video/mp4"))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        vid = resp["id"]
        # 拿到 id 立刻寫帳本(insert 之後的任何例外都不該造成重傳)
        done[o["key"]] = vid
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(LEDGER)
        quota.spend(quota.SHORT, o["key"])      # 成功才記
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
    print(f"\n完成。Shorts 帳本共 {len(done)} 支。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
