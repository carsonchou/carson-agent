#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retitle.py — 把標題改成人會搜、人看得懂的問句。

## 為什麼要改
第一版標題是數字開頭的:「A 2019 study found 0.27. 1,283 people later: -0.07」。
它對**任何**管道都是死的 —— 沒有人會搜它,推薦系統也讀不出主題。
發了 18 小時、5 支片、總共 2 次觀看。

## 但要先講清楚它救不了什麼
多數 FReD 集數的主張本身就沒有搜尋需求(「消費者線索對別人該少用水的信念
的影響」)。改成問句不會創造不存在的需求。真正有量的是名案那幾支。
**這支解決的是「標題讀不懂」,不是「沒有人想看這個題目」。**

## 誠信
問句一律**保持原主張的強度**:相關就講相關(不講因果)、有條件的保留條件。
結尾那句由 tone 決定,跟片子裡的結論一致 —— 標題不能比片子講得更重。

## API
`videos.update` 是**整包覆寫**:snippet 沒帶到的欄位會被清空。所以一律
先讀回現值、整包帶齊(title/description/tags/categoryId/defaultLanguage)、
再讀回驗證。只換標題不動影片,觀看數與 videoId 都保留。

用法:
  python retitle.py                # 只印新舊對照,不連網
  python retitle.py --apply        # 寫回 publish_meta.json
  python retitle.py --apply --live # 連同已上線的影片一起改
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime

import quota  # noqa: E402  (同目錄)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
META = ROOT / "publish_meta.json"
LEDGER = ROOT / "uploaded.json"
BACKUP = ROOT / "_backup"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"

# 結尾由 tone 決定。標題不能比片子講得重 —— gone 是「測不出來」不是「假的」。
TAIL = {
    "gone":        "A bigger replication couldn't find it.",
    "shrunk_real": "It's real — but much smaller than the first study said.",
    "flipped":     "The replication found the opposite.",
    # 方向翻了但量級不到慣例的「小」—— 見 make_episode.copy_tone。
    "flipped_tiny": "The replication found the opposite, but only just.",
    "held":        "It held up.",
    "stronger":    "It came back stronger.",
}

def build(o):
    """回傳新標題,或 None 表示保留原樣。

    ## 問句從哪來(2026-08-29 改)
    以前是一套正規表示式把論文語言的 claim 轉成問句,再加一張手寫表補
    規則救不了的。產出長這樣:

        Does scarcity-induced focus really lead to cognitive fatigue on
        subsequent cognitive control task?

    文法沒錯、意思沒錯、**沒有人看得懂**。而標題和縮圖是這條線上唯二
    在觀眾點進來之前就要說服他的東西 —— 兩個都用圈內語言,等於沒有。

    現在直接用手寫的白話句(`facts/plain_claims.json` 的 `spoken`),
    跟縮圖那兩行、Short 開場那張卡是**同一句話**。整套規則和手寫表已經
    刪掉,不是留著當備援:留著就是留一條沒人走的路,而這條線上
    「閘門修在沒人走的那份實作上」已經栽過一次。

    名案那 5 支回 None —— 它們要在前面加通用搜尋詞,由 `retitle_live`
    負責(那裡才有 famous_episodes.json 的規模數字)。
    """
    if o.get("kind") == "famous":
        return None
    import plain
    q = plain.spoken(o.get("dir"), o.get("slug"))
    if not q:
        # fail-closed:沒有手寫白話句就不動它。退回論文語言等於這次改版
        # 沒發生,而那種退化是靜默的。
        return None
    from make_episode import copy_tone
    f = o.get("facts") or {}
    tail = TAIL.get(copy_tone(o["tone"], f.get("es_r"),
                              f.get("es_kind", "d")), "")
    for cand in (f"{q} {tail}", q):
        if cand and len(cand) <= 100:
            return cand
    return q[:100]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--live", action="store_true",
                    help="連同已上線的影片一起改(videos.update 整包帶齊)")
    a = ap.parse_args()

    meta = json.loads(META.read_text(encoding="utf-8"))
    changed = 0
    for o in meta:
        new = build(o)
        if not new or new == o["title"]:
            print(f"  ─ {o['title'][:74]}")
            continue
        changed += 1
        print(f"  舊 {o['title'][:74]}")
        print(f"  新 {new[:74]}")
        print()
        if a.apply:
            o["title"] = new
    print(f"{changed}/{len(meta)} 則標題會改")

    if not a.apply:
        print("(未寫入,加 --apply)")
        return 0
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"已寫回 {META.name}")

    if not a.live:
        print("已上線的影片未動,加 --live 才會改")
        return 0

    led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    if not led:
        print("帳本是空的,沒有已上線的影片")
        return 0
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build as gbuild
    # ch2 有兩個 token:token.json 只有 readonly,**寫入要用 token_manage.json**
    tok = CH2 / "token_manage.json"
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    yt = gbuild("youtube", "v3", credentials=cr, cache_discovery=False)
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1
    # ⚠️ 這兩個計數器**一定要在迴圈外初始化**。上一版忘了(我以為 sed 插進去
    #    了,但那個 replace 的目標字串因為前一次編輯已經不存在,靜默沒中),
    #    於是新寫的 exit-code 程式碼**一次都沒有被執行過**:第一支
    #    `bad += 0 if ok else 1` 就 UnboundLocalError,而那時 update 已經送出、
    #    配額已經記帳。這正是 memory verification-that-cannot-fail 的
    #    「寫完檢查先故意讓它失敗一次」—— 我寫了檢查,沒讓它跑過。
    bad = done = 0
    sent = []
    by_key = {(o.get("slug") or o["dir"]): o for o in meta}
    print(f"\n改 {len(led)} 支已上線的影片:")
    for key, vid in led.items():
        o = by_key.get(key)
        if not o:
            continue
        # 🔴 名案 5 支跳過。`build()` 對 famous 回 None(它們要加通用搜尋詞,
        #    由 retitle_live 負責),所以 publish_meta 裡它們的標題**永遠是
        #    舊的論文語言版**。而這個迴圈走訪的是整本帳本、送出的是
        #    `o["title"]` 而不是 build() 的結果 —— 於是 retitle_live 剛推好的
        #    「Ego depletion: willpower runs out as you use it? 23 labs,
        #    2,141 people.」會被推回「… 23 laboratories tested it: 0.04.」。
        #    5 支全中。「產生新值的那份跳過、送出的那份沒跳過」是同一個
        #    半套毛病:閘門只接上一半。
        if o.get("kind") == "famous":
            print(f"  {key:<14}名案,交給 retitle_live(這裡不動)")
            continue
        got = yt.videos().list(part="snippet", id=vid).execute().get("items", [])
        if not got:
            print(f"  {key:<14}⛔ 查無此片")
            continue
        sn = got[0]["snippet"]
        # 說明也一起更新:`publish_meta` 是說明的唯一來源(upload.py 上傳時
        # 原封不動送 `o["description"]`,發布後沒有任何地方會再改它),
        # 而說明的第一行現在是白話句 —— 那是搜尋結果裡跟標題一起顯示的
        # 那一段。只改標題會讓線上的第一行停在論文語言。
        same = (sn["title"] == o["title"]
                and sn.get("description", "") == o["description"])
        if same:
            print(f"  {key:<14}標題與說明都已是新的")
            continue
        # 🔴 整包帶齊:videos.update 沒帶到的欄位會被清空。
        #    ⚠️ `defaultAudioLanguage` **是可寫欄位**,不是唯讀 ——
        #    漏掉它就會被清空,而 repo 裡有 fix_audio_language.py 專門
        #    在設它。姊妹檔 retitle_live 已經因為同一個欄位被抓過一次,
        #    這裡當時沒一起補:「同一句話三份只修最安靜的那份」。
        #    先讀回來再原樣帶上去,不是寫死預設值。
        snip = {"title": o["title"],
                "description": o["description"],
                "tags": sn.get("tags", []),
                "categoryId": sn.get("categoryId", "27")}
        for k in ("defaultLanguage", "defaultAudioLanguage"):
            if sn.get(k):
                snip[k] = sn[k]
        # 🔴 覆蓋線上說明之前先留一份。`publish_meta.json` 不知道線上發生過
        #    什麼:如果曾經在 Studio 手動加過連結、更正、或 #hashtag,
        #    這裡會直接蓋掉,而且**沒有退路** —— YouTube 沒有版本歷史。
        #    程式手上就有線上的 sn,卻只在事後印一行「不符」。
        #    存檔很便宜,不可逆的動作沒有理由不留備份。
        live_desc = sn.get("description", "")
        if live_desc and live_desc != o["description"]:
            BACKUP.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            (BACKUP / f"desc_{vid}_{stamp}.txt").write_text(
                live_desc, encoding="utf-8")
            # 只有**線上有、新版沒有**的行才值得看 —— 這次的改動是純插入,
            # 所以正常情況這裡應該是空的。不是空的就代表線上被人改過。
            lost = [ln for ln in live_desc.split("\n")
                    if ln.strip() and ln not in o["description"]]
            if lost:
                print(f"  {key:<14}⚠️ 線上說明有 {len(lost)} 行不在新版裡"
                      f",已備份:{lost[0][:60]}")
        if not quota.can(quota.TITLE):
            # 🔴 「停在這裡」**不是成功**。舊版只 break、`bad` 還是 0,
            #    於是 return 0 —— 用 `retitle.py && retitle_live.py` 串起來
            #    時,第一支的假成功會讓第二支接著跑,而那時配額已經見底。
            #    跟 exit code 恆為 0 是同一類毛病:停下來也要說出來。
            print(f"  {key:<14}⛔ 配額不足({quota.remaining():,}),停在這裡")
            bad += 1
            break
        try:
            yt.videos().update(part="snippet",
                               body={"id": vid, "snippet": snip}).execute()
        except Exception as e:                                # noqa: BLE001
            # 每支各自包:整批中途 traceback 死掉的話,已經改掉的那幾支
            # 不會出現在任何輸出裡 —— 而它們已經被改了。
            print(f"  {key:<14}⛔ 送出失敗:{str(e)[:110]}")
            bad += 1
            continue
        quota.spend(quota.TITLE, f"title {key}")
        sent.append((key, vid, o))
        print(f"  {key:<14}送出  {o['title'][:56]}")

    # 🔴 回讀要**等全部送完再一次批次讀**,不能一支送完立刻讀自己那支。
    #    實測(2026-08-29 第一次真的推上線):6 支全部成功寫進去,但逐支
    #    回讀有 5 支讀到**舊值** —— `videos.list` 緊接在 `videos.update`
    #    之後拿到的是快取,而且不確定(最後一支剛好讀到新的)。
    #    於是我剛修好「結構上不可能失敗」的檢查,立刻換成另一半的毛病:
    #    **結構上幾乎一定誤報**。會叫的假警報跟不會叫的真警報一樣糟,
    #    而且它會讓 `retitle.py && retitle_live.py` 這種串接斷掉。
    #    批次讀順便省配額:N 次 list(N 單位)變成 1 次(1 單位)。
    #    回讀驗兩個欄位 —— 只驗標題的話,說明被清空我也看不見,
    #    而 videos.update 整包覆蓋,說明正是最容易被清掉的那個。
    miss = []
    if sent:
        import time
        for attempt in range(3):
            if attempt:
                time.sleep(6)          # 傳播延遲,不是重試才等
            back = {v["id"]: v["snippet"] for v in yt.videos().list(
                part="snippet",
                id=",".join(v for _, v, _ in sent)).execute()["items"]}
            miss = [(k, v, o) for k, v, o in sent
                    if back.get(v, {}).get("title") != o["title"]
                    or back.get(v, {}).get("description", "")
                    != o["description"]]
            if not miss:
                break
        done = len(sent)
        bad += len(miss)
        for k, _v, _o in miss:
            print(f"  {k:<14}⚠️ 回讀不符")
    # 🔴 回讀結果要收進 exit code。舊版把兩個欄位都比對了、也印了「⚠️ 不符」,
    #    然後無條件 `return 0` —— 11 支全部不符也是成功。
    #    這支的驗證**結構上不可能失敗**(memory verification-that-cannot-fail),
    #    而姊妹檔 retitle_live 做對了:同一件事兩份實作,又只修了其中一份。
    print(f"\n{done - bad}/{done} 支回讀相符")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
