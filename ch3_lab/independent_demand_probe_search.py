#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""independent_demand_probe_search.py — 條件 A(觀看數)/ 條件 B(頻道量級)實測。
只對 autocomplete 篩選通過的主題花 search.list 配額。"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")


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


QUERIES = {
    "dunning_kruger": ["dunning kruger effect debunked", "is the dunning kruger effect real"],
    "marshmallow_test": ["marshmallow test debunked"],
    "hot_hand": ["hot hand fallacy"],
    "stanford_prison": ["stanford prison experiment real"],
    "sugar_hyperactivity": ["does sugar cause hyperactivity"],
}


def main():
    y = svc()
    out = {}
    for topic, qs in QUERIES.items():
        out[topic] = []
        for q in qs:
            print(f"\n===== {topic} :: {q} =====")
            try:
                r = y.search().list(part="snippet", q=q, type="video",
                                     maxResults=10, order="relevance").execute()
                items = r.get("items", [])
            except Exception as e:  # noqa: BLE001
                print(f"  search.list 拉不到: {type(e).__name__}: {str(e)[:200]}")
                out[topic].append({"q": q, "err": str(e)[:200]})
                continue
            vids = [it["id"]["videoId"] for it in items if "videoId" in it.get("id", {})]
            chans = []
            seen = set()
            for it in items:
                cid = it["snippet"]["channelId"]
                if cid not in seen:
                    seen.add(cid)
                    chans.append(cid)
            try:
                vr = y.videos().list(part="statistics,snippet", id=",".join(vids)).execute()
                vstats = {it["id"]: it for it in vr.get("items", [])}
            except Exception as e:  # noqa: BLE001
                print(f"  videos.list 拉不到: {e}")
                vstats = {}
            try:
                cr_ = y.channels().list(part="statistics,snippet", id=",".join(chans[:4])).execute()
                cstats = {it["id"]: it for it in cr_.get("items", [])}
            except Exception as e:  # noqa: BLE001
                print(f"  channels.list 拉不到: {e}")
                cstats = {}

            rows = []
            for it in items:
                vid = it["id"].get("videoId")
                title = it["snippet"]["title"]
                chan_title = it["snippet"]["channelTitle"]
                chan_id = it["snippet"]["channelId"]
                views = None
                if vid in vstats:
                    views = int(vstats[vid]["statistics"].get("viewCount", 0))
                subs = None
                if chan_id in cstats:
                    st = cstats[chan_id]["statistics"]
                    subs = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", -1))
                rows.append({"title": title, "channel": chan_title, "channel_id": chan_id,
                             "views": views, "channel_subs": subs})
                print(f"  {views if views is not None else '?':>10} views | "
                      f"{chan_title:30.30s} | subs={subs} | {title[:60]}")
            out[topic].append({"q": q, "rows": rows})

    out_path = pathlib.Path(r"D:\carson-agent\ch3_lab\_independent_probe_search.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入: {out_path}")


if __name__ == "__main__":
    main()
