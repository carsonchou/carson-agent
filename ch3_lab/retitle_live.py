#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retitle_live.py — 把已上線影片的標題換成「搜得到」的版本。

## 為什麼要改已經發出去的片
這個頻道現在是 **10 支片、總觀看 2 次、訂閱 0** —— 沒有任何分發管道。
零訂閱、零觀看歷史的頻道進不了推薦與瀏覽,唯一剩下的入口是**搜尋**,
而搜尋只匹配標題與說明裡真的出現的字。

現行標題是純問句:「Willpower runs out as you use it?」。它讀起來不錯,
但搜「ego depletion」的人**不會**匹配到它 —— 那個詞根本沒出現。名案這
五支是全頻道唯一有真實搜尋量的題材,而它們的標題正好漏掉了那個詞。

所以改法很單純:**把學界通用的名字放到標題最前面**,問句留在後面當鉤子。
不加任何新宣稱,不改數字。

## 這是紅線動作
`videos.update` 改的是已經對外的東西。兩個必守的規矩:
1. **snippet 是整段覆蓋**:沒帶到的欄位會被清空。所以先 `videos.list`
   把現有 snippet 讀回來,只換 title,其餘原樣送回。
2. **改完必須回讀**。這條線的歷史是「API 回 200 但東西沒變」
   (channels.update 改名就是這樣靜默失敗的)。

## 配額
videos.list 1 + videos.update 50。五支 = 255 單位。

用法:
  python retitle_live.py             # 只列出 舊 → 新,不連網改
  python retitle_live.py --apply
"""
import argparse
import json
import pathlib
import time
import sys

import quota  # noqa: E402  (同目錄)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"

#: 學界/大眾**實際在搜的詞**。左邊是 slug,右邊是要放到標題最前面的名字。
#  這不是我編的別名 —— 每一個都是該研究在文獻與科普裡的通用稱呼。
#  romantic_red 沒有廣為人知的名字(「romantic red effect」幾乎沒人搜),
#  所以它保留原本的問句,不硬塞一個沒人用的詞進去充數。
SEARCH_TERM = {
    "ego_depletion": "Ego depletion",
    "bystander_effect": "The bystander effect",
    "implicit_bias_test": "The implicit association test",
    # 🔴 曾經寫「Learning while you sleep」——那是 hypnopaedia(睡眠中
    #    學新東西)的通俗名字,而且早就被推翻。這篇研究是 targeted memory
    #    reactivation:**醒著學會**之後,睡眠中重播提示音強化**已存在**的
    #    記憶。把那個詞放在 0.29 前面,搜尋者讀到的是「睡覺學習有效」——
    #    這篇統合分析完全沒支持那件事。
    #    這條的規則本來就寫著「該研究在文獻與科普裡的通用稱呼」,TMR 是
    #    文獻裡的正式名字;搜尋量低,但它是對的,而錯的詞比沒有詞更糟。
    "sleep_memory": "Targeted memory reactivation",
    "romantic_red": None,
}


#: 加上搜尋詞之後,原本的問句有時會重複(「implicit association test」
#  後面再接「the hidden-bias test」)。這幾支改寫問句,語意不變。
QUESTION = {
    "implicit_bias_test": "does it predict what you do?",
    "sleep_memory": "can a sound strengthen what you learned?",
}
#: 標題版面很窄,規模詞要縮。縮的是修飾語不是數字 ——
#  「105 independent effect sizes」→「105 effect sizes」,完整說法在說明裡。
SHORT_KW = {"laboratories": "labs", "independent effect sizes": "effect sizes",
            "independent samples": "samples", "experiments": "experiments"}


def new_title(slug, E, cur):
    """組出新標題。數字全部來自事實庫,不重算也不新增。

    ## 兩個 2026-08-29 的改動

    **問句改用手寫的白話句**(`facts/plain_claims.json` 的 `spoken`)——
    跟縮圖那兩行、Short 開場卡是同一句。`QUESTION` 的覆寫留著:加了通用
    搜尋詞之後,原句有時會跟搜尋詞重複(「the implicit association test」
    後面再接「a test that reveals your hidden bias」),那幾支要改寫。

    **結尾不再放裸的效果量。** 我原本寫著「太長要丟規模、留數字,那個
    數字是這個頻道跟一般科普頻道的差別」。那句話對**我**成立,對滑過
    標題的人不成立 —— 「0.04」在標題裡跟亂碼沒有兩樣。我兩天前才因為
    同一個理由把縮圖上最大的元素從效果量換成白話主張,標題卻留著它。
    改成講規模:「23 labs, 2,141 people」是一般人讀得懂的具體性,而
    結論本來就在縮圖上(NOT FOUND / IT HELD UP)。
    """
    import plain
    t = E["test"]
    # SEARCH_TERM 是 None 只表示「沒有通用搜尋詞可以放在最前面」,
    # **不表示整個標題不用改**。第一版在這裡直接 return cur,結果
    # romantic_red 兩邊都沒接到:retitle.py 對 famous 回 None、這裡回原樣,
    # 於是只有它留著舊標題「Does red make women more attractive?
    # 242 men: 0.09. 360 women: -0.09.」—— 論文語言加兩個裸小數,
    # 正好是這次要改掉的東西。沒有搜尋詞就不加前綴,其他照走。
    term = SEARCH_TERM.get(slug)
    q = QUESTION.get(slug) or plain.spoken(slug)
    if not q:
        return cur          # fail-closed
    if not q.endswith("?"):
        q += "?"
    q = q[0].lower() + q[1:]                    # 接在冒號後面
    kw = SHORT_KW.get(t.get("k_word") or "", t.get("k_word") or "")
    people = f"{t['n']:,} people"
    # 由詳到簡,取第一個塞得下的。最後一層只剩問句 —— 它本身讀得懂。
    tails = ([f" {t['k']:,} {kw}, {people}."] if t.get("k") else []) +             [f" Retested on {people}.", f" {people}.", ""]
    head = f"{term}: {q}" if term else q[0].upper() + q[1:]
    for tail in tails:
        cand = f"{head}{tail}"
        if len(cand) <= 100:
            return cand
    return head[:100]


def push_thumbs(yt, led, apply_):
    """把已上線影片的縮圖換成現行版本。

    縮圖是**純贏**的改動:`thumbnails.set` 只換圖,videoId、發布時間、
    觀看數全部保留(不像重新上傳會歸零)。而這 10 支現在掛的還是舊版
    縮圖 —— 舊版把整句標題重印在圖上、兩個效果量並排,在手機上是一團
    灰字(改版理由見 make_thumbs.py 的說明)。

    配額:每支 50。
    """
    # 🔴 帳本的 key 有兩種寫法:FReD 那批是 dir(`eps/ep000`),名案是
    #    slug(`ego_depletion`)。只用 dir 去查會**靜默漏掉全部 5 支名案**
    #    —— 而那 5 支正好是最需要換縮圖的(唯一有搜尋量的題材)。
    #    漏掉不會報錯,只會少做,所以兩種 key 都建進來。
    meta = {}
    for o in json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8")):
        for k in (o.get("dir"), o.get("slug")):
            if k:
                meta[k] = o
    # 🔴 跳過的要**大聲印出來**。「帳本裡有、線上已發布、但本地縮圖不在」
    #    是最該被看見的狀態,原本卻是唯一被靜默忽略的。實際咬過:重產長片
    #    時會先 `rm -rf` 整個集數目錄再重建,那段期間跑這支,清單會從 10 支
    #    無聲地掉到 8 支 —— 而少掉的正好是這輪修正要處理的那一集。
    jobs, skipped = [], []
    for key, vid in led.items():
        o = meta.get(key)
        if not o or not o.get("thumb"):
            skipped.append(f"{key}(publish_meta 裡沒有縮圖欄位)")
            continue
        p = ROOT / o["thumb"]
        if p.exists():
            jobs.append((key, vid, p))
        else:
            skipped.append(f"{key}(本地檔案不在:{o['thumb']})")
    if skipped:
        print(f"\n⚠️ 已發布但**推不了**縮圖的 {len(skipped)} 支:")
        for s in skipped:
            print(f"   {s}")
        print("   (如果背景正在重產集數,等它跑完再來 —— 現在推會少推這幾支)")
    print(f"\n── 縮圖 ── {len(jobs)} 支已上線、且本地有現行縮圖")
    for key, _v, p in jobs:
        import datetime as _dt
        print(f"   {key:<24}{_dt.datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M}"
              f"  {p.stat().st_size // 1024} KB")
    if not apply_:
        print(f"   (未套用,會用掉配額 {len(jobs) * 50})")
        return 0
    # 🔴 回讀不能比 URL。`i.ytimg.com/vi/<id>/maxresdefault.jpg` **換圖之後
    #    網址不變**,所以「URL 有回來」不構成任何證據。要真的把線上那張抓
    #    下來比對內容。這裡比的是尺寸與前 64KB 的雜湊 —— YouTube 會重新
    #    壓縮,所以不會逐位元相同,但「跟舊圖不同、且尺寸對得上」就足以
    #    證明換上去了。
    import hashlib
    import urllib.request

    def live_fp(vid_):
        for name in ("maxresdefault", "hqdefault"):
            try:
                with urllib.request.urlopen(
                        f"https://i.ytimg.com/vi/{vid_}/{name}.jpg",
                        timeout=15) as r:
                    b = r.read()
                return hashlib.md5(b).hexdigest()[:12], len(b)
            except Exception:                            # noqa: BLE001
                continue
        return None, 0

    # 🔴 回傳三個數,不是一個。實測過:單一個 int 時,「全部失敗」回 0、
    #    「根本沒套用」也回 0 —— 三種狀態共用同一個值,自動化分不出來,
    #    人只能靠讀 log 才知道。而 exit code 用的正是自動化那條路。
    before = {}
    for _k, vid, _p in jobs:
        before[vid] = live_fp(vid)[0]
    sent, ok, failed, unknown = [], 0, 0, 0
    # 🔴 `thumbnails.set` 有**速率限制**,跟每日配額是兩回事。一口氣連打
    #    11 支,實測第 4 支之後全部吃 HTTP 429(Too Many Requests)——
    #    而 429 不扣配額,純粹是打太快。所以要放慢並重試。
    #    我第一版沒有任何節流,於是 11 支只成功 4 支,而失敗訊息看起來
    #    很像配額用完,差點讓我做出「今天不能再推了」的錯誤結論。
    import random
    for i, (key, vid, p) in enumerate(jobs):
        if i:
            time.sleep(4)                # 間隔,不是重試才等
        for attempt in range(4):
            try:
                if not quota.can(quota.THUMB):
                    print(f"   ⛔ 配額不足({quota.remaining():,}),{key} 不送")
                    break
                yt.thumbnails().set(videoId=vid, media_body=str(p)).execute()
                # 🔴 記在 429 重試**之外**:429 不吃配額,只有真的送出才記。
                quota.spend(quota.THUMB, f"thumb {key}")
                sent.append((key, vid))
                print(f"   送出 {key}")
                break
            except Exception as e:                       # noqa: BLE001
                msg = str(e)
                if "429" in msg and attempt < 3:
                    wait = 8 * (2 ** attempt) + random.uniform(0, 3)
                    print(f"   … {key} 被限速,{wait:.0f} 秒後重試"
                          f"(第 {attempt + 1} 次)")
                    time.sleep(wait)
                    continue
                failed += 1
                print(f"   ⛔ {key} 送出失敗:{msg[:110]}")
                break
    if sent:
        time.sleep(20)          # YouTube 換圖不是即時的
        for key, vid in sent:
            fp, size = live_fp(vid)
            if before.get(vid) is None:
                # 🔴 **基準抓不到不能算通過**。原本寫 `if fp and fp !=
                #    before.get(vid)`,而 before 是 None 時 `fp != None`
                #    恆真 → 每一支都自動判「已換」,實際上什麼都沒比對。
                unknown += 1
                print(f"   ？{key} 送出成功,但**換圖前的基準抓不到**,"
                      f"無法證明真的換了 —— 請自己開頁面確認")
            elif fp and fp != before[vid]:
                ok += 1
                print(f"   ✓ {key} 回讀已換({size // 1024} KB)")
            else:
                # ⚠️ 「跟舊圖一樣」**不代表沒換成功**:`i.ytimg.com` 是 CDN,
                #    換圖之後舊的位元組還會被快取一段時間。實測送出成功的
                #    四支全部在 20 秒後仍讀回舊圖。所以這裡算「驗不到」
                #    而不是「失敗」—— 但也不能算成功,那就是憑空宣稱。
                unknown += 1
                print(f"   ？{key} 回讀仍是舊圖 —— YouTube 的 CDN 會快取,"
                      f"這不代表失敗,但**現在證明不了成功**")
    return {"sent": len(sent), "verified": ok, "failed": failed,
            "unverified": unknown, "total": len(jobs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--thumbs", action="store_true",
                    help="順便把已上線影片的縮圖換成現行版本")
    a = ap.parse_args()

    eps = {e["slug"]: e for e in json.loads(
        (ROOT / "facts" / "famous_episodes.json").read_text(encoding="utf-8")
    )["episodes"]}
    led = json.loads(LEDGER.read_text(encoding="utf-8"))
    todo = [(s, v) for s, v in led.items() if s in eps]
    if not todo:
        print("帳本裡沒有名案影片")
        return 1

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    # 唯讀階段用唯讀 token;真的要寫才換 manage token。
    tokf = CH2 / ("token_manage.json" if a.apply else "token.json")
    #   ⚠️ 寫入(改標題/設縮圖)只有 manage token 有權限,
    #      token.json 是唯讀的 —— 用錯會拿到 403 insufficient scopes。
    scopes = (["https://www.googleapis.com/auth/youtube.force-ssl",
               "https://www.googleapis.com/auth/youtube.readonly"] if a.apply
              else ["https://www.googleapis.com/auth/youtube.readonly"])
    cr = Credentials.from_authorized_user_file(str(tokf), scopes)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tokf.write_text(cr.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
    # 🔴 頻道守門原本只是定義了常數卻**從來沒被引用**(獨立驗證 grep 到)。
    #    寫了閘門沒接上等於沒有閘門,而這支會改動已對外的影片。0 配額。
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    if me != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me} != {EXPECT_CHANNEL},中止。")
        return 1

    ids = [v for _s, v in todo]
    got = {v["id"]: v for v in yt.videos().list(
        part="snippet,status", id=",".join(ids)).execute()["items"]}

    plans = []
    for slug, vid in todo:
        v = got.get(vid)
        if not v:
            print(f"  ⛔ {slug}: 查無此片 {vid}")
            continue
        cur = v["snippet"]["title"]
        nt = new_title(slug, eps[slug], cur)
        mark = "─同─" if nt == cur else "改"
        print(f"[{slug}] {mark}  {len(nt)} 字")
        print(f"   舊 {cur}")
        print(f"   新 {nt}")
        if nt != cur:
            plans.append((slug, vid, v, nt))
    tr = push_thumbs(yt, led, a.thumbs and a.apply) if a.thumbs else None
    if not a.apply:
        # 配額:channels.list(1) + videos.list(1) + N×update(50) + 回讀 list(1)
        print(f"\n(沒有 --apply,未改動。會改 {len(plans)} 支標題,"
              f"標題配額 {len(plans) * 50 + 3})")
        return 0
    # 🔴 縮圖的結果**必須進 exit code**。原本只看標題,於是「標題已經改過、
    #    這次只補縮圖」的重跑情境下 plans 是空的,就算 10 支縮圖全部 403,
    #    也會印出成功並回傳 0。
    thumb_bad = bool(tr and (tr["failed"] or tr["unverified"]))
    if tr:
        print(f"\n縮圖:送出 {tr['sent']}/{tr['total']}、"
              f"回讀確認 {tr['verified']}、失敗 {tr['failed']}、"
              f"驗不到 {tr['unverified']}")
    if not plans:
        print("沒有標題要改")
        return 1 if thumb_bad else 0

    # 🔴 每一支各自包 try/except。原本整段沒有例外處理,而 push_thumbs
    #    排在前面 —— 縮圖跑到第 6 支吃 403 就整個 traceback 死掉,回讀那段
    #    永遠不會執行,於是「改了幾支、成功了沒」完全沒有紀錄。
    #    這條線的配額本來就每天爆(memory yt-api-quota-structural-overrun),
    #    中途 403 不是理論風險。
    sent = []
    for slug, vid, v, nt in plans:
        sn = dict(v["snippet"])          # 🔴 整包帶回去,只換 title
        sn["title"] = nt
        # 🔴 只 pop **唯讀**欄位。`defaultAudioLanguage` 一度也被 pop 掉,
        #    那是錯的 —— 它是**可寫**的:`youtube_channel/scripts/
        #    fix_audio_language.py` 整支腳本的工作就是用 videos.update 設它,
        #    而 ch3_lab/upload.py 的註解記著設成 "zxx" 會回
        #    INVALID_REQUEST_METADATA(API 有讀有驗 = 不是忽略)。
        #    snippet 是全欄覆蓋,可寫欄位沒帶就會被清空 → 那 4 支片會失去
        #    自動翻譯字幕的來源語言與 auto-dubbing 資格。
        #    這份 pop 清單跟 fix_audio_language.py 的 body 對齊。
        for k in ("thumbnails", "publishedAt", "channelTitle",
                  "liveBroadcastContent", "localized", "channelId"):
            sn.pop(k, None)              # 唯讀欄位,帶回去會被拒
        try:
            if not quota.can(quota.TITLE):
                print(f"  ⛔ 配額不足({quota.remaining():,}),{slug} 不送")
                break
            yt.videos().update(part="snippet",
                               body={"id": vid, "snippet": sn}).execute()
            quota.spend(quota.TITLE, f"title {slug}")
            sent.append((slug, vid, nt))
            print(f"  送出 {slug}")
        except Exception as e:           # noqa: BLE001
            print(f"  ⛔ {slug} 送出失敗:{str(e)[:120]}")
    plans = [(s_, v_, None, t_) for s_, v_, t_ in sent]
    if not plans:
        print("\n一支都沒送出")
        return 1
    back = {v["id"]: v["snippet"]["title"] for v in yt.videos().list(
        part="snippet", id=",".join(p[1] for p in plans)).execute()["items"]}
    ok = 0
    for slug, vid, _v, nt in plans:
        got_t = back.get(vid)
        if got_t == nt:
            ok += 1
            print(f"  ✓ {slug}  回讀相符")
        else:
            print(f"  ⛔ {slug}  回讀不符!實際是:{got_t!r}")
    print(f"\n標題 {ok}/{len(plans)} 支確認改成功")
    # 縮圖的結果也要進 exit code —— 否則「標題全對、縮圖全失敗」會回 0。
    return 0 if (ok == len(plans) and not thumb_bad) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
