#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""independent_demand_probe.py — 獨立量測員專用,只讀不寫。

不採信任何既有結論,自己重新量 14 個主題是否值得 1 訂閱頻道做長片。
條件 A:自動完成吐得出該字串/近似變體(尤其 debunked/myth/real 類) 且
       search.list 前 10 筆裡至少一支觀看 >= 10,000。
條件 B:search.list 前 4 名頻道不是 Veritasium/Vsauce/Kurzgesagt/SciShow/
       TED/Numberphile/BBC 這個量級 —— 用訂閱數實測,不用「感覺」。
拉不到就寫「拉不到」,不用估計值頂替。
"""
import json
import pathlib
import sys
import time
import urllib.request
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")

MEGA_CHANNELS = {
    "veritasium", "vsauce", "kurzgesagt", "scishow", "ted", "ted-ed",
    "tededucation", "numberphile", "bbc", "bbc earth", "bbc news",
    "asapscience", "crashcourse", "mindyourdecisions",
}


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), [
        "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


# 🔴 2026-09-03 事後補記(督導):這支的判準有兩個坑,照抄前先讀。
#   坑一:suggest 端點**會把你打的完整字串原樣回吐**。所以「建議清單裡出現
#         了那個字串」不是需求證據。要用 prefix_probe() 打前綴,看它補不補得出來。
#         實例:`hungry judge effect` 打完整字串會拿到它自己;但打前綴
#         `hungry judge` 也真的補得出來 → 那才是真需求(本支據此判 0 是錯的)。
#         反例:`does sugar cause` 補出的是 diabetes/cholesterol/acne/cancer,
#         所以 `does sugar cause hyperactivity` 只是回吐 → 沒有需求(本支判有,錯)。
#   坑二:條件 A 用「前 10 筆最高觀看 >= 10,000」當需求代理是壞的。那個數字量的是
#         **頻道觸及**不是 query 的量:hungry judge effect 第一頁 StarTalk 806,627
#         觀看來自它 588 萬訂閱,同頁小頻道只有 14~593。要看**同頁小頻道**的觀看數。
#   完整記錄:docs/ch3-distribution-evidence-2026-09-01.md、memory
#   search-demand-measurement-traps。


def prefix_probe(base, want, drop=3):
    """把 base 砍掉尾巴 drop 個字當前綴,看 suggest 補不補得出 want。
    這是判「真需求 vs 回吐」的唯一可靠方法。"""
    prefix = base[:-drop] if drop and len(base) > drop else base
    sug = autocomplete(prefix)
    if isinstance(sug, dict):
        return None, sug          # 拉不到就說拉不到
    return any(want.lower() in x.lower() for x in sug), sug


def autocomplete(q):
    """免費、不吃配額。回傳建議清單,拉不到回傳 None。
    ⚠️ 直接餵完整字串會拿到回吐,判需求請改用 prefix_probe()。"""
    url = ("https://suggestqueries.google.com/complete/search?"
           + urllib.parse.urlencode({"client": "firefox", "ds": "yt", "q": q}))
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
            return data[1] if len(data) > 1 else []
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def search_top10(y, q):
    try:
        r = y.search().list(part="snippet", q=q, type="video",
                             maxResults=10, order="relevance").execute()
        return {"ok": True, "items": r.get("items", [])}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": f"{type(e).__name__}: {str(e)[:200]}"}


def videos_stats(y, video_ids):
    if not video_ids:
        return {}
    try:
        r = y.videos().list(part="statistics,snippet", id=",".join(video_ids)).execute()
        return {it["id"]: it for it in r.get("items", [])}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def channels_stats(y, channel_ids):
    if not channel_ids:
        return {}
    try:
        r = y.channels().list(part="statistics,snippet", id=",".join(channel_ids)).execute()
        return {it["id"]: it for it in r.get("items", [])}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


TOPICS = {
    "mozart_effect": ["mozart effect debunked", "mozart effect myth", "mozart effect"],
    "hot_hand": ["hot hand fallacy debunked", "hot hand fallacy real or fake", "hot hand fallacy"],
    "grit": ["grit angela duckworth debunked", "grit theory debunked", "does grit matter myth"],
    "terror_management": ["terror management theory debunked", "terror management theory explained", "terror management theory"],
    "growth_mindset": ["growth mindset debunked", "growth mindset myth", "growth mindset does it work"],
    "dunning_kruger": ["dunning kruger effect debunked", "dunning kruger effect myth", "dunning kruger effect real"],
    "backfire_effect": ["backfire effect debunked", "backfire effect myth", "backfire effect real or fake"],
    "hungry_judges": ["hungry judge effect debunked", "hungry judge effect", "judges hungry parole study debunked"],
    "stanford_prison": ["stanford prison experiment debunked", "stanford prison experiment fake", "stanford prison experiment myth"],
    "false_memory": ["false memory experiment debunked", "false memory myth", "false memory real"],
    "facial_feedback": ["facial feedback hypothesis debunked", "facial feedback hypothesis myth", "facial feedback hypothesis"],
    "sugar_hyperactivity": ["sugar hyperactivity myth", "does sugar cause hyperactivity debunked", "sugar makes kids hyper myth"],
    "marshmallow_test": ["marshmallow test debunked", "marshmallow experiment myth", "marshmallow test fake"],
    "moral_licensing": ["moral licensing debunked", "moral licensing myth", "moral licensing real"],
}

DEBUNK_WORDS = ("debunk", "myth", "real", "fake", "true", "false", "actually", "wrong", "lie")


def main():
    y = svc()
    results = {}
    units_used = 0
    for topic, queries in TOPICS.items():
        print(f"\n########## {topic} ##########", flush=True)
        topic_result = {"queries": []}
        for qtext in queries:
            ac = autocomplete(qtext)
            time.sleep(0.3)
            if isinstance(ac, dict) and "error" in ac:
                print(f"  [{qtext}] autocomplete 拉不到: {ac['error']}")
                topic_result["queries"].append({"q": qtext, "ac_error": ac["error"]})
                continue
            ac_hits_debunk = [s for s in ac if any(w in s.lower() for w in DEBUNK_WORDS)]
            print(f"  [{qtext}] autocomplete({len(ac)}): {ac[:6]}")
            topic_result["queries"].append({
                "q": qtext, "autocomplete": ac, "ac_debunk_variants": ac_hits_debunk,
            })
        results[topic] = topic_result

    out_path = pathlib.Path(r"D:\carson-agent\ch3_lab\_independent_probe_autocomplete.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入 autocomplete 結果: {out_path}")


if __name__ == "__main__":
    main()
