#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unlist_one.py — 把某一支已上線影片轉成「不公開」。

## 為什麼要有這支
`implicit_bias_test`(6ab_RzBqv4E)的 scale 幕**畫面與旁白互相打架**:
旁白唸「for a correlation, 0.1 small / 0.3 medium / 0.5 large」(r 軌,正確),
畫面卻印 0.2 / 0.5 / 0.8(d 軌)。那一幕 15.7 秒,佔全片 80 秒的 **20%**。
根因是 `make_famous.py` 自己寫死了一份門檻,沒有依 es_kind 分軌(已修)。

影片的畫面沒辦法事後修補,只能重傳。但獨立驗證的判斷是**重傳買不到東西**:
那支是 1920×1080 / 80 秒,在零訂閱頻道上沒有任何發行管道,重傳出來還是
0 觀看。所以正解是**先把它從搜尋與頻道頁上撤下來**,等產線成熟再以新片
重新出現。

**用 unlisted 不用 private**:unlisted 仍可用直連觀看,所以引流用的 Short
說明裡那個連結不會斷;它只是不再出現在搜尋與頻道頁。這是最小的介入。

理由是誠信不是流量:這個頻道唯一的資產是「數字可以查證」,而一支自己
跟自己打架 20% 時間的片子,正是它在批評的那種東西。目前 0 觀看 =
現在撤是成本最低的時刻。

## 紅線
`videos.update` 動的是已對外的東西。所以:
- `status` 是整段覆蓋 → 先讀回來,只換 privacyStatus
- 改完**必須回讀**
- 頻道 ID 白名單

配額:videos.list 1 + videos.update 50 + 回讀 1 = 52。

用法:
  python unlist_one.py --id 6ab_RzBqv4E            # 只看,不改
  python unlist_one.py --id 6ab_RzBqv4E --apply
  python unlist_one.py --id 6ab_RzBqv4E --to public --apply    # 還原
"""
import argparse
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--to", default="unlisted",
                    choices=["unlisted", "private", "public"])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tokf = CH2 / ("token_manage.json" if a.apply else "token.json")
    scopes = (["https://www.googleapis.com/auth/youtube.force-ssl",
               "https://www.googleapis.com/auth/youtube.readonly"] if a.apply
              else ["https://www.googleapis.com/auth/youtube.readonly"])
    cr = Credentials.from_authorized_user_file(str(tokf), scopes)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tokf.write_text(cr.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)

    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    if me != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me}")
        return 1
    got = yt.videos().list(part="snippet,status", id=a.id).execute().get("items")
    if not got:
        print(f"⛔ 查無此片:{a.id}")
        return 1
    v = got[0]
    cur = v["status"]["privacyStatus"]
    print(f"{a.id}  {v['snippet']['title'][:70]}")
    print(f"  現在 {cur}  →  要改成 {a.to}")
    if cur == a.to:
        print("  已經是這個狀態了,不動。")
        return 0
    if not a.apply:
        print("\n(沒有 --apply,未改動。配額 52)")
        return 0

    # 🔴 status 是整段覆蓋:讀回來的整包帶上,只換 privacyStatus。
    #    漏掉 selfDeclaredMadeForKids 會讓兒童內容標記被重設。
    st = {k: v["status"][k] for k in
          ("privacyStatus", "selfDeclaredMadeForKids", "license", "embeddable",
           "publicStatsViewable") if k in v["status"]}
    st["privacyStatus"] = a.to
    yt.videos().update(part="status", body={"id": a.id, "status": st}).execute()

    # 🔴 **回讀要延遲重試。** `videos.list` 緊接在 `videos.update` 之後會拿到
    #    **舊值** —— 那是快取,不是沒寫進去。memory `yt-readback-stale-cache`
    #    記過:6 支全部寫成功卻報 5 支不符。
    #    2026-08-30 這支自己又中一次:立刻回讀說 public,10 秒後讀是
    #    unlisted。而它當時回 rc=1,讀起來像「改失敗了」——
    #    **假警報比沒有檢查更糟**,因為它會讓人去做第二次補救。
    import time as _t
    for i in range(4):
        back = yt.videos().list(
            part="status", id=a.id).execute()["items"][0]["status"]
        now = back["privacyStatus"]
        if now == a.to:
            break
        if i < 3:
            print(f"  回讀還是 {now},{6 * (i + 1)}s 後重試(很可能是快取)")
            _t.sleep(6 * (i + 1))
    kids = back.get("selfDeclaredMadeForKids")
    print(f"  回讀:privacyStatus={now}  madeForKids={kids}")
    if now != a.to:
        print(f"⛔ 回讀不符 —— 重試四次仍是 {now}。"
              f"API 回 200 但沒改,這條線有前科。")
        return 1
    print("  ✓ 確認已改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
