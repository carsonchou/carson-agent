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
import re
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

# 陳述句 → 問句。保持原強度:correlated 只問「有關聯嗎」不問「會造成嗎」。
RULES = [
    (r"^(.+?) is positively correlated with (.+)$",
     lambda m: f"Are {dc(m[1])} and {m[2]} really linked?"),
    (r"^(.+?) is negatively correlated with (.+)$",
     lambda m: f"Are {dc(m[1])} and {m[2]} really linked?"),
    (r"^(.+?) is associated with (.+)$",
     lambda m: f"Is {dc(m[1])} really associated with {m[2]}?"),
    (r"^(.+?) leads to (.+)$",
     lambda m: f"Does {dc(m[1])} really lead to {m[2]}?"),
    (r"^(.+?) increases (.+)$",
     lambda m: f"Does {dc(m[1])} really increase {m[2]}?"),
    (r"^(.+?) reduces (.+)$",
     lambda m: f"Does {dc(m[1])} really reduce {m[2]}?"),
    (r"^(.+?) can (.+)$",
     lambda m: f"Can {dc(m[1])} really {m[2]}?"),
    (r"^People tend to (.+)$",
     lambda m: f"Do people really {m[1]}?"),
    (r"^People (expect|judge|value) (.+)$",
     lambda m: f"Do people really {m[1]} {m[2]}?"),
    (r"^(.+?) are judged to be (.+)$",
     lambda m: f"Are {dc(m[1])} really judged {m[2]}?"),
    (r"^(.+?) find (.+)$",
     lambda m: f"Do {dc(m[1])} really find {m[2]}?"),
    (r"^The more (.+?), the less (.+)$",
     lambda m: f"Does a crowd really make each person less likely to {m[2].split('is to ')[-1]}?"
     if "help" in m[2] else f"The more {m[1]}, the less {m[2]}?"),
    (r"^Effects? of (.+?) on (.+)$",
     lambda m: f"Do {m[1]} really affect {m[2]}?"),
    (r"^(.+?) should be more (.+)$",
     lambda m: f"Are {dc(m[1])} really more {m[2]}?"),
    (r"^(.+?) should (.+)$",
     lambda m: f"Do {dc(m[1])} really {m[2]}?"),
    (r"^(.+?) would be (.+)$",
     lambda m: f"Are {dc(m[1])} really {m[2]}?"),
    (r"^Whether (.+?) (decreases|increases|reduces) (.+)$",
     lambda m: f"Does {m[1]} really {m[2][:-1]} {m[3]}?"),
    (r"^(.+?) made more (.+)$",
     lambda m: f"Do {dc(m[1])} really make more {m[2]}?"),
    (r"^(.+?) reported more (.+)$",
     lambda m: f"Do people really report more {m[2]}?"),
    (r"^(.+?) using the (.+?) (increases|reduces) (.+)$",
     lambda m: f"Does {dc(m[1])} really {m[3][:-1]} {m[4]}?"),
    (r"^(.+?) is perceived as (.+)$",
     lambda m: f"Is {dc(m[1])} really perceived as {m[2]}?"),
    (r"^(.+?) are perceived as (.+)$",
     lambda m: f"Are {dc(m[1])} really perceived as {m[2]}?"),
]


# 主張本身就超過 100 字元的那幾則,規則救不了 —— 而**砍掉它的限定子句會改變
# 意思**(「when the number of lives at risk was small」拿掉就變成另一個發現)。
# 所以這幾則手寫,跟名案的 hook_short 同一個做法。每一句都對照原主張確認過
# 沒有加強語氣、沒有丟掉限定條件。
HAND = {
    "Consumers with": "Do people cling to products that define them when unsure who they are?",
    "Products with brand names": "Do brand names that sound 'thicker' really feel thicker?",
    "Life-saving interventions": "Do we value a life more when fewer lives are at stake?",
    "Participants reported more intense": "Is looking forward to a trip better than the trip?",
    "Knowledge of one": "Does what you do reveal more about you than what you own?",
    "Whether holding decision makers": "Does holding people accountable stop them throwing good money after bad?",
    "Group members would reject": "Do groups punish outside criticism more than the same words from inside?",
    "People expect more corruption": "Do people expect more corruption in hierarchical organisations?",
}


def dc(t):
    """只降**第一個字母**,不要整串 lower —— 那會把縮寫毀掉(CRT → crt)。"""
    return t[0].lower() + t[1:] if t else t


def to_question(claim):
    c = claim.strip().rstrip(".")
    for pat, fn in RULES:
        m = re.match(pat, c, re.I)
        if m:
            q = fn([m.group(0)] + list(m.groups()))
            return re.sub(r"\s{2,}", " ", q)[0].upper() + \
                re.sub(r"\s{2,}", " ", q)[1:]
    return None


def build(o):
    """回傳新標題,或 None 表示保留原樣。

    ⚠️ 名案那 5 支的標題來自手寫的 `hook_short`(「Willpower runs out as you
    use it?」),那比任何規則產得出來的都好 —— 它們本來就是可搜尋的字串。
    規則只用來救 FReD 那批數字開頭、讀不懂的標題。
    """
    if o.get("kind") == "famous":
        return None
    claim = o["description"].split("\n")[0].strip()
    tail = TAIL.get(o["tone"], "")
    for pre, hand in HAND.items():
        if claim.startswith(pre):
            cand = f"{hand} {tail}"
            return cand if len(cand) <= 100 else hand
    q = to_question(claim)
    c = claim.rstrip(".")
    # 由好到次好,取第一個塞得下的。最後一層只有主張本身 —— 它讀得懂,
    # 而數字開頭的標題(「A 2015 study found 0.57」)對任何管道都是死的。
    for cand in ([f"{q} {tail}", q] if q else []) + [f"{c} — {tail}", c]:
        if cand and len(cand) <= 100:
            return cand
    return None


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
