#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_shorts.py — Shorts 的 metadata 與上傳。

## 為什麼跟長片分開
Shorts 的角色不一樣,所以文案規則也不一樣:
- **標題要短**:手機上 Shorts 標題只顯示一行,長片那種完整問句會被截斷
- **說明第一行就要導回完整版** —— Short 的工作是把人帶到長片,不是取代它
- **`#Shorts` 標籤**:雖然 YouTube 主要靠長寬比與片長判定,加上去沒壞處

## 判定成 Short 的條件(實測)
垂直或方形 + 片長 ≤ 3 分鐘。我們的是 1080x1920、20~30 秒 → 會被判為 Short。
**16:9 的長片就算只有 90 秒也不會**,這是先前的誤解。

## 誠信
標題與說明的數字全部來自該集事實庫,跟長片走同一套溯源。Short 沒有版面
放信賴區間,所以它**不下存在性結論**——結論在完整版裡。

## 配額
videos.insert 同樣 1600/支。Shorts 與長片共用同一個每日 10,000。
所以排程要**分流**:長片一天 3 支、Shorts 一天 2 支,合計約 8,455 單位。

用法:
  python publish_shorts.py --list
  python publish_shorts.py --limit 2 --dry-run
  python publish_shorts.py --limit 2
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
LEDGER = ROOT / "uploaded_shorts.json"
LONG_LEDGER = ROOT / "uploaded.json"
META = ROOT / "publish_meta.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
COST = 1600 + 41

TAGS = ["Shorts", "psychology", "replication crisis", "science", "research",
        "effect size", "statistics"]


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token_manage.json"          # 寫入一律用 manage token
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def ledger(p):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(f"⛔ 帳本 {p} 讀不了({e})——繼續跑會重傳。")


def build_meta():
    """從各集的 Short 稿子與長片 metadata 組出 Shorts 的標題與說明。"""
    sys.path.insert(0, str(ROOT))
    from make_episode import build_facts, CARD_TEXT
    import pandas as pd
    q = pd.read_csv(ROOT / "facts" / "episode_queue.csv", low_memory=False)
    longs = ledger(LONG_LEDGER)
    meta = {o.get("row"): o for o in json.loads(META.read_text(encoding="utf-8"))
            if o.get("kind") == "fred"}
    out = []
    for d in sorted((ROOT / "shorts").iterdir()):
        mp4 = d / f"{d.name}_short.mp4"
        if not mp4.exists():
            continue
        row = int(d.name.replace("ep", ""))
        F = build_facts(q.iloc[row])
        o = meta.get(row)
        if not o:
            continue
        # 標題:短、給落差、不下結論
        title = (f"{F['orig']['es']:+.2f} → {F['repl']['es']:+.2f} "
                 f"on {F['repl']['n']:,} people").replace("+", "")
        q_text = o["title"].split(" — ")[0].split("? ")[0]
        if "?" in o["title"]:
            q_text = o["title"][:o["title"].index("?") + 1]
        cand = f"{q_text} {title}"
        title = cand if len(cand) <= 100 else title

        vid = longs.get(f"eps/ep{row:03d}")
        link = (f"Full episode: https://youtu.be/{vid}\n\n" if vid else
                "The full episode is on this channel.\n\n")
        desc = (link
                + f"{o['description'].split(chr(10))[0]}\n\n"
                + f"Original study: {F['orig']['n']:,} people, "
                  f"effect size {F['orig']['es']:+.2f}\n".replace("+", "")
                + f"Replication: {F['repl']['n']:,} people, "
                  f"effect size {F['repl']['es']:+.2f}\n".replace("+", "")
                + f"{CARD_TEXT[F['tone']]}\n\n"
                + "Source: FORRT Replication Database (FReD), osf.io/2tbvd\n"
                  "#Shorts")
        out.append({"key": d.name, "video": str(mp4.relative_to(ROOT)),
                    "title": title, "description": desc, "tags": TAGS,
                    "tone": F["tone"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    ap.add_argument("--list", action="store_true", dest="show")
    a = ap.parse_args()

    items = build_meta()
    done = ledger(LEDGER)
    todo = [o for o in items if o["key"] not in done]
    if a.show:
        for o in items:
            mark = done.get(o["key"], "未上傳")
            print(f"  {o['key']:<10}{o['tone']:<12}{mark:<14}{o['title'][:52]}")
        print(f"\n共 {len(items)} 支,已上傳 {len(done)},待上傳 {len(todo)}")
        return 0

    todo = todo[:a.limit]
    if not todo:
        print("沒有待上傳的 Short")
        return 0
    print(f"要上傳 {len(todo)} 支,估算配額 {len(todo) * COST:,}")
    for o in todo:
        print(f"  {o['key']:<10}{o['title'][:66]}")
    if a.dry:
        print("\n--dry-run:未連網、未上傳。")
        return 0

    yt = svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1
    from googleapiclient.http import MediaFileUpload
    for o in todo:
        p = ROOT / o["video"]
        print(f"\n[{o['key']}] {o['title'][:60]}")
        req = yt.videos().insert(part="snippet,status", body={
            "snippet": {"title": o["title"], "description": o["description"],
                        "tags": o["tags"], "categoryId": "27",
                        "defaultLanguage": "en"},
            "status": {"privacyStatus": "public",
                       "selfDeclaredMadeForKids": False,
                       "license": "youtube", "embeddable": True},
        }, media_body=MediaFileUpload(str(p), chunksize=4 * 1024 * 1024,
                                      resumable=True, mimetype="video/mp4"))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        vid = resp["id"]
        # 拿到 id 立刻寫帳本(insert 之後的任何例外都不該造成重傳)
        done[o["key"]] = vid
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(LEDGER)
        print(f"    videoId={vid}  https://youtube.com/shorts/{vid}")
        for _ in range(20):
            got = yt.videos().list(part="status", id=vid).execute().get("items", [])
            if got and got[0]["status"].get("uploadStatus") == "processed":
                print("    處理完成 ✓")
                break
            time.sleep(15)
    print(f"\n完成。Shorts 帳本共 {len(done)} 支。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
