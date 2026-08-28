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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
META = ROOT / "publish_meta.json"
LEDGER = ROOT / "uploaded.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"

# 結尾由 tone 決定。標題不能比片子講得重 —— gone 是「測不出來」不是「假的」。
TAIL = {
    "gone":        "A bigger replication couldn't find it.",
    "shrunk_real": "It's real — but much smaller than the first study said.",
    "flipped":     "The replication found the opposite.",
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
    tail = TAIL.get(o["tone"], "")
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
    by_key = {(o.get("slug") or o["dir"]): o for o in meta}
    print(f"\n改 {len(led)} 支已上線的影片:")
    for key, vid in led.items():
        o = by_key.get(key)
        if not o:
            continue
        got = yt.videos().list(part="snippet", id=vid).execute().get("items", [])
        if not got:
            print(f"  {key:<14}⛔ 查無此片")
            continue
        sn = got[0]["snippet"]
        if sn["title"] == o["title"]:
            print(f"  {key:<14}標題已是新的")
            continue
        # 🔴 整包帶齊:videos.update 沒帶到的欄位會被清空
        yt.videos().update(part="snippet", body={
            "id": vid,
            "snippet": {"title": o["title"],
                        "description": sn.get("description", ""),
                        "tags": sn.get("tags", []),
                        "categoryId": sn.get("categoryId", "27"),
                        "defaultLanguage": sn.get("defaultLanguage", "en")},
        }).execute()
        back = yt.videos().list(part="snippet",
                                id=vid).execute()["items"][0]["snippet"]
        ok = back["title"] == o["title"]
        print(f"  {key:<14}{'✓' if ok else '⚠️ 不符'}  {back['title'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
