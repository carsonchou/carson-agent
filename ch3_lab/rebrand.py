#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebrand.py — 副頻道改版:One Quiet Hour → They Ran It Again。

## 三個層次共存(Carson 要的)
- 頻道名走**白話**:不懂統計的人也敢點
- 簡介走**學術可信**:每個數字附 DOI、來源資料庫具名
- 集標題走**戲劇性**:原始 vs 重複的落差本身就是戲

## API 事實(踩過的坑)
- `brandingSettings` 是**整包覆寫**:必須先讀回再改,否則沒帶到的欄位會被清空
- **handle(@代號)API 設不了**,只能在 Studio UI 改 —— 這支只做能做的,
  handle 另外處理,不假裝做到了
- 舊的氛圍片改**不公開→私人**(可逆),不刪:刪除不可逆,而私人已達成同樣效果

用法:
  python rebrand.py --dry-run
  python rebrand.py --apply
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

TITLE = "They Ran It Again"
DESC = """Famous studies, tested again — with the numbers.

Every episode takes one published finding, shows what the original study measured, and then shows what happened when a larger team ran the same study again with more people.

How this channel works:
• Every number comes from the published replication record — the FORRT Replication Database (FReD) and the original papers. Both DOIs appear at the end of every video.
• Nothing is estimated, rounded for effect, or written to fit a story. The narration is generated from the same data fields you see on screen.
• Not everything fails. Replications that succeeded get their own episodes — a finding that survives a larger test is worth knowing about.
• No voice actor, no stock footage. The charts are the data."""

KEYWORDS = ("replication crisis" " " "psychology" " " "effect size" " " "science"
            " " "research" " " "statistics" " " "meta-analysis" " "
            "\"replication study\" \"open science\" \"social psychology\"")

AMBIENT = ["tnefbfU9XKw", "UnFJzyo03lM", "3vR2Aj7IBLM"]


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    print(f"新頻道名:{TITLE}")
    print(f"簡介 {len(DESC)} 字元 / 上限 1000")
    print(f"關鍵字 {len(KEYWORDS)} 字元 / 上限 500")
    print(f"舊氛圍片轉私人:{len(AMBIENT)} 支")
    print("⚠️  @代號 API 設不了,要在 Studio UI 改成 @theyranitagain(已確認未被使用)")
    if not a.apply:
        print("\n--dry-run:未連網。")
        return 0

    yt = svc()
    ch = yt.channels().list(part="snippet,brandingSettings", mine=True).execute()["items"][0]
    if ch["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{ch['id']}")
        return 1
    print(f"\n目標頻道:{ch['snippet']['title']} ({ch['snippet'].get('customUrl')})")

    # 🔴 brandingSettings 整包覆寫 → 先讀回再改
    bs = ch["brandingSettings"]
    bs.setdefault("channel", {})
    bs["channel"]["title"] = TITLE
    bs["channel"]["description"] = DESC
    bs["channel"]["keywords"] = KEYWORDS
    yt.channels().update(part="brandingSettings",
                         body={"id": ch["id"], "brandingSettings": bs}).execute()
    got = yt.channels().list(part="snippet,brandingSettings",
                             mine=True).execute()["items"][0]
    gb = got["brandingSettings"]["channel"]
    print(f"回讀:標題「{got['snippet']['title']}」 "
          f"{'✓' if got['snippet']['title'] == TITLE else '⚠️ 不符'}")
    print(f"      簡介 {len(gb.get('description', ''))} 字元 "
          f"{'✓' if gb.get('description', '').startswith('Famous studies') else '⚠️'}")

    # 氛圍片轉私人。status 整包帶齊,否則 selfDeclaredMadeForKids 會被清掉
    print("\n舊氛圍片:")
    for vid in AMBIENT:
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if not items:
            print(f"  {vid} 查無(可能已刪)")
            continue
        st = items[0]["status"]
        if st["privacyStatus"] == "private":
            print(f"  {vid} 已是私人")
            continue
        yt.videos().update(part="status", body={
            "id": vid,
            "status": {"privacyStatus": "private",
                       "selfDeclaredMadeForKids": st.get("selfDeclaredMadeForKids", False),
                       "license": st.get("license", "youtube"),
                       "embeddable": st.get("embeddable", True)},
        }).execute()
        back = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
        print(f"  {vid} → {back['privacyStatus']}  "
              f"兒童宣告 {back.get('selfDeclaredMadeForKids')} "
              f"{'✓' if back.get('selfDeclaredMadeForKids') is False else '⚠️ 被清掉了'}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
