#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_playlists.py — 把已上線的片補進對應的播放清單。

## 為什麼需要
主頻道的發片模式裡,新片會進播放清單;ch3 的三支發布器(upload / shorts /
comp)**都沒碰清單** —— 清單是 `channel_setup.py` 一次性建好之後就沒再動。
實測:15 支公開影片,只有 10 支在清單裡。

播放清單對這個頻道特別重要,因為它是**連播的入口**:觀眾看完一支會自動
接下一支,那是把「單次觀看」變成「多次觀看」唯一不需要演算法幫忙的機制。
對一個 0 訂閱、進不了推薦的頻道,那是少數自己控制得了的槓桿之一。

## 放什麼、不放什麼
- **長片單集** → 依結局進 fail / mixed / held 三條清單
- **合輯** → 進同一條清單,而且**排在最前面**(它是那個主題的入口,
  而且 12 分鐘的連播起點比 2 分鐘的好)
- **Shorts 不進** —— 它跟對應的長片是同一個發現,放同一條清單等於
  同樣的內容在連播裡出現兩次

## 配額
`playlistItems.insert` 每支 **50**、`playlistItems.list` 每頁 1。
一次補 5 支 = 約 255。⚠️ 這條線的配額每天很緊,跑之前先看 `--dry-run`。

用法:
  python sync_playlists.py --dry-run
  python sync_playlists.py --apply
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
sys.path.insert(0, str(ROOT))

#: 清單標題 → bucket。跟 channel_setup.py 建的那三條對應。
BUCKET_OF_TITLE = {
    "Findings that did not survive": "fail",
    "Smaller than you were told": "mixed",
    "Findings that held up": "held",
}


def want():
    """算出「每支已上線的長片/合輯該在哪條清單」。

    定調一律從事實庫重算(`TONE_META`),不從檔名或標題猜 —— 這條線出過
    「平行分類跟不上」的事故(CSV 的 track vs facts 的 tone)。
    """
    from make_episode import build_facts, TONE_META
    import pandas as pd
    q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    meta = {(o.get("slug") or o["dir"]): o for o in
            json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))}
    out = {}          # videoId -> (bucket, 排序用的鍵, 說明)

    led = json.loads((ROOT / "uploaded.json").read_text(encoding="utf-8"))
    for key, vid in led.items():
        o = meta.get(key)
        if not o:
            continue
        if o.get("kind") == "fred":
            F = build_facts(q.iloc[o["row"]])
            b = TONE_META[F["tone"]]["bucket"]
        else:
            b = TONE_META.get(o.get("tone", ""), {}).get("bucket")
        if b:
            out[vid] = (b, 1, o["title"][:52])

    comp = ROOT / "uploaded_comp.json"
    if comp.exists():
        for b, vid in json.loads(comp.read_text(encoding="utf-8")).items():
            # 合輯排在最前面:它是那個主題的入口,而且 12 分鐘的連播起點
            # 比 2 分鐘的好。
            out[vid] = (b, 0, f"【合輯】{b}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", dest="dry")
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

    # 現有清單與成員
    pls, members = {}, {}
    for p in yt.playlists().list(part="snippet,contentDetails", mine=True,
                                 maxResults=25).execute()["items"]:
        b = BUCKET_OF_TITLE.get(p["snippet"]["title"])
        if not b:
            continue
        pls[b] = p["id"]
        got, tok = set(), None
        # 🔴 分頁一定要走完。這條線踩過「909 列只有 874 唯一 ID」——
        #    不分頁就會把已經在清單裡的當成不在,然後重複加一次。
        while True:
            r = yt.playlistItems().list(part="contentDetails", playlistId=p["id"],
                                        maxResults=50, pageToken=tok).execute()
            got |= {i["contentDetails"]["videoId"] for i in r["items"]}
            tok = r.get("nextPageToken")
            if not tok:
                break
        members[b] = got
    missing_pl = [b for b in ("fail", "mixed", "held") if b not in pls]
    if missing_pl:
        print(f"⛔ 找不到這幾條清單:{missing_pl} —— 先跑 channel_setup.py")
        return 1

    todo = []
    for vid, (b, order, label) in sorted(want().items(), key=lambda x: x[1][1]):
        if vid in members[b]:
            continue
        todo.append((b, vid, order, label))

    print(f"三條清單目前共 {sum(len(v) for v in members.values())} 支;"
          f"該補 {len(todo)} 支")
    for b, vid, order, label in todo:
        print(f"  {b:<6}{vid}  {'(排最前)' if order == 0 else '':<10}{label}")
    if not todo:
        print("  沒有要補的 ✓")
        return 0
    print(f"  配額約 {len(todo) * 50 + len(pls)}")
    if not a.apply:
        print("\n(沒有 --apply,未改動)")
        return 0

    ok = fail = 0
    for b, vid, order, label in todo:
        if not _q.can(50):
            print(f"  ⏸ 共用配額只剩 {_q.remaining():,},清單同步讓路給發片"
                  f"(明天再補)")
            break
        body = {"snippet": {"playlistId": pls[b], "resourceId":
                            {"kind": "youtube#video", "videoId": vid}}}
        if order == 0:
            body["snippet"]["position"] = 0
        try:
            yt.playlistItems().insert(part="snippet", body=body).execute()
            _q.spend(50, f"playlist/{b}")
            ok += 1
            print(f"  ✓ {b:<6}{label}")
        except Exception as e:                                # noqa: BLE001
            fail += 1
            print(f"  ⛔ {b:<6}{label}:{str(e)[:90]}")
    print(f"\n補進 {ok} 支,失敗 {fail} 支")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
