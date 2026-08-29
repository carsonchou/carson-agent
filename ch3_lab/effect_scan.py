#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""effect_scan.py — 幫 ch3 挑題:哪些「有名字的心理效應」值得做。

## 為什麼需要它
ch3 發了 12 支長片 + 16 支 Short,總觀看約 160,**YT_SEARCH 流量是 0**。
2026-08-30 實測出根因:它的題材(FReD 佇列)**在 YouTube 上不存在** ——
搜尋「action identification mind attribution」,20 筆結果裡標題真的在講
那件事的是 **0 筆**。沒有人做,因為沒有人搜。

而同一天測的 `stereotype threat`:20 筆裡 18 筆切題、中位觀看 25,529、
其中 10 支來自小頻道(<1 萬訂閱)。同一個領域,兩個世界。

**所以選題判準不該是「FReD 裡有什麼」,而是「這個名字通不通得過結果頁測試」。**

## 判準(兩個都要過,缺一不可)
1. **有需求**:結果頁裡**標題含該效應名**的片數。有人做 = 有人搜。
   ⚠️ 不能只看中位觀看 —— YouTube 對任何查詢都回 20 筆,查詢詞沒有
   真實需求時它會回一堆泛泛的熱門片。實測 FReD 那幾個題材的中位觀看
   高達 28~31 萬,而切題數是 0。**那個高中位數完全是假訊號**,
   正是 memory 記的「查詢詞寬窄差三個數量級會讓排名整個翻」。
2. **打得進去**:切題片裡有幾支來自小頻道。零小頻道 = 這個位置被
   百萬訂閱頻道佔滿了(實測:bystander effect 中位訂閱 191 萬、
   小頻道 4 支;marshmallow test 235 萬 / 4 支)。

分數 = 切題片數 × 中位觀看 × 小頻道佔比。三者任一為 0 就是 0。

## 配額
`search.list` 100 + `videos.list` 1 + `channels.list` 1 = **每個候選 102**。
結果逐筆附加到 `effect_scan.jsonl`,配額不夠就停在斷點,下次接著跑
(已測過的不重測)。

用法:
  python effect_scan.py                 # 接著跑,直到配額不夠
  python effect_scan.py --report        # 只看排名,不連網
  python effect_scan.py --budget 1000   # 限制這次最多花多少
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "effect_scan.jsonl"
COST = 102          # search.list 100 + videos.list 1 + channels.list 1
SMALL = 10_000      # 「小頻道」的訂閱門檻

#: 候選:重複危機裡**有名字**的效應。有名字才有人搜 —— 這是整個判準的前提。
#: 每一筆是 (查詢詞, 用來判斷標題切不切題的關鍵字)。
#: 關鍵字要比查詢詞短一點(例如 power posing → "power pos"),
#: 才能吃到 "power pose" / "power posing" 兩種寫法。
CANDIDATES = [
    ("stereotype threat", "stereotype threat"),
    ("power posing", "power pos"),
    ("ego depletion", "ego depletion"),
    ("social priming", "priming"),
    ("facial feedback hypothesis", "facial feedback"),
    ("implicit association test", "implicit association"),
    ("growth mindset research", "growth mindset"),
    ("grit angela duckworth", "grit"),
    ("learning styles myth", "learning styles"),
    ("10000 hour rule", "10,000 hour"),
    ("marshmallow test replication", "marshmallow"),
    ("stanford prison experiment", "stanford prison"),
    ("milgram experiment", "milgram"),
    ("bystander effect", "bystander"),
    ("dunning kruger effect", "dunning"),
    ("decision fatigue", "decision fatigue"),
    ("hungry judges effect", "hungry judge"),
    ("broken windows theory", "broken windows"),
    ("mirror neurons", "mirror neuron"),
    ("backfire effect", "backfire effect"),
    ("hot hand fallacy", "hot hand"),
    ("loss aversion", "loss aversion"),
    ("anchoring effect", "anchoring"),
    ("terror management theory", "terror management"),
    ("elderly priming experiment", "elderly priming"),
    ("money priming", "money priming"),
    ("macbeth effect", "macbeth effect"),
    ("choice overload jam study", "choice overload"),
    ("glucose willpower", "glucose"),
    ("romantic red effect", "romantic red"),
    ("targeted memory reactivation", "memory reactivation"),
    ("subliminal priming", "subliminal"),
    ("depletion of self control", "self-control"),
    ("nudge default effect", "nudge"),
    ("cognitive dissonance experiment", "cognitive dissonance"),
    ("halo effect psychology", "halo effect"),
    ("mozart effect", "mozart effect"),
    ("false memory implantation", "false memory"),
    ("weapon focus effect", "weapon focus"),
    ("stereotype boost", "stereotype boost"),
    ("moral licensing", "moral licensing"),
    ("pygmalion effect", "pygmalion"),
    ("bilingual advantage", "bilingual advantage"),
    ("video games aggression research", "video game"),
    ("smiling makes you happier", "smil"),
]


def svc():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    # 用主頻道那個專案:ch3 的配額要留給發片,而搜尋探測跟頻道無關
    tok = ROOT.parent / "youtube_channel" / "token.json"
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.readonly"])
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def probe(yt, q, key):
    r = yt.search().list(part="snippet", q=q, type="video", maxResults=20,
                         regionCode="US", relevanceLanguage="en").execute()
    items = r.get("items", [])
    if not items:
        return {"n": 0, "on": 0, "med_views": 0, "small": 0, "med_subs": 0}
    ids = [x["id"]["videoId"] for x in items]
    chans = list({x["snippet"]["channelId"] for x in items})
    st = {v["id"]: v for v in yt.videos().list(
        part="statistics", id=",".join(ids)).execute()["items"]}
    cs = yt.channels().list(part="statistics",
                            id=",".join(chans[:50])).execute()["items"]
    subs = {c["id"]: int(c["statistics"].get("subscriberCount", 0)) for c in cs}
    # 🔴 只算**標題真的在講這件事**的那幾筆。沒有這一層,YouTube 的
    #    fallback 結果會讓一個零需求的題目看起來有 28 萬中位觀看。
    on = [x for x in items if key.lower() in x["snippet"]["title"].lower()]
    views = sorted(int(st.get(x["id"]["videoId"], {})
                       .get("statistics", {}).get("viewCount", 0)) for x in on)
    sb = [subs.get(x["snippet"]["channelId"], 0) for x in on]
    med = lambda a: sorted(a)[len(a) // 2] if a else 0
    return {"n": len(items), "on": len(on), "med_views": med(views),
            "small": sum(1 for s in sb if s < SMALL), "med_subs": med(sb)}


#: 「這個位置搆得到嗎」的門檻:切題結果的**中位訂閱數**。
#: 🔴 第一版的公式是 `切題數 × 中位觀看 × 小頻道佔比`,化簡之後其實是
#:    `小頻道數 × 中位觀看` —— 它**完全沒有懲罰巨頭佔位**。實測結果:
#:    milgram experiment 被排到第一(中位觀看 416,502、小頻道 6),但它的
#:    **中位訂閱是 753,000**;stanford prison 中位訂閱 534 萬。
#:    317 訂閱的頻道排進那種位置的機率是零,而公式卻說它們最值得做。
#:    這跟今天稍早那些「能跑、有輸出、但答的是另一個問題」的判準同型。
REACH_SUBS = 50_000


def score(d):
    """可搆到的需求量。

    需求 = 切題結果的中位觀看(有人做、有人看)。
    可搆到 = 切題結果的**中位訂閱**低於 REACH_SUBS,而且真的有小頻道在裡面。
    搆不到就是 0 —— 不是打折,是 0,因為排不進去的位置流量再大也拿不到。
    """
    if not d["on"] or not d["med_views"] or not d["small"]:
        return 0.0
    if d["med_subs"] >= REACH_SUBS:
        return 0.0
    return d["med_views"] * (d["small"] / d["on"])


def done_keys():
    if not OUT.exists():
        return set()
    return {json.loads(l)["q"] for l in OUT.read_text(encoding="utf-8").splitlines()
            if l.strip()}


def report():
    if not OUT.exists():
        print("還沒有掃描結果"); return 1
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    for r in rows: r["score"] = score(r["d"])   # 公式改了就重算,不要信舊值
    rows.sort(key=lambda r: -r["score"])
    print(f"{'效應':30s}{'切題':>5s}{'中位觀看':>10s}{'小頻道':>7s}{'中位訂閱':>11s}{'分數':>12s}")
    for r in rows:
        d = r["d"]
        flag = ("" if r["score"] > 0
                else f"   ← 搆不到(中位訂閱 {d['med_subs']:,})"
                if d["med_subs"] >= REACH_SUBS else "   ← 無需求")
        print(f"  {r['q'][:28]:28s}{d['on']:>5d}{d['med_views']:>10,d}"
              f"{d['small']:>7d}{d['med_subs']:>11,d}{r['score']:>12,.0f}{flag}")
    ok = [r for r in rows if r["score"] > 0]
    print(f"\n掃了 {len(rows)} 個,{len(ok)} 個通過(切題>0、有觀看、有小頻道)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--budget", type=int, default=100_000)
    a = ap.parse_args()
    if a.report:
        return report()
    done = done_keys()
    todo = [(q, k) for q, k in CANDIDATES if q not in done]
    n_afford = a.budget // COST
    print(f"候選 {len(CANDIDATES)}、已測 {len(done)}、待測 {len(todo)};"
          f"本次預算 {a.budget:,} → 最多測 {n_afford} 個")
    if not todo:
        print("全部測完了"); return report()
    yt = svc()
    spent = 0
    for q, key in todo[:n_afford]:
        try:
            d = probe(yt, q, key)
        except Exception as e:
            msg = str(e)
            if "quota" in msg.lower():
                print(f"⛔ 配額用完,停在 {q}(已測 {len(done_keys())} 個)")
                break
            print(f"⛔ {q}: {msg[:80]}")
            continue
        spent += COST
        rec = {"q": q, "key": key, "d": d, "score": score(d)}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {q[:28]:28s} 切題 {d['on']:>2d}  中位觀看 {d['med_views']:>8,d}"
              f"  小頻道 {d['small']:>2d}  分數 {rec['score']:>11,.0f}")
    print(f"\n本次花費約 {spent:,} 單位")
    return report()


if __name__ == "__main__":
    sys.exit(main())
