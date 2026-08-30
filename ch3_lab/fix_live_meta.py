#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_live_meta.py — 修已上線 Short 的**標題與說明**(不動影片)。

## 為什麼這支比重上傳重要得多
獨立驗證指出:那句假來源「Source: FORRT Replication Database (FReD)」
同時在**畫面**和**說明欄**。畫面改不掉(YouTube 沒有替換已發布影片檔
的方法),但說明欄一個 `videos.update` 就改得掉。

順著再往下一層:**標題也在同一次 update 裡**。所以一次呼叫可以同時修好

  1. 說明欄的假來源(4 支名案)
  2. 標題缺可搜尋的效應名(16 支全部)——「The bystander effect: …」

    16 支 × 51 = **816 單位**,不到重上傳(26,528)的 3%。

燒進畫面的東西仍然只能重傳,但那是另一件事、另一個決定。

## 一定要先讀回再寫
`videos.update` 的 `part="snippet"` 是**整份覆寫**。只送 title 與
description 會把 `categoryId`、`tags`、`defaultLanguage`、
`defaultAudioLanguage` 一起清掉。`retitle.py` 就漏過 `defaultAudioLanguage`,
差點清掉 12 支線上影片的設定 —— 那次是回讀才發現的。

## 配額
每支:`videos.list` 1 + `videos.update` 50 = 51。回讀是批次的(整批 1 次)。

用法:
  python fix_live_meta.py --list
  python fix_live_meta.py --dry-run
  python fix_live_meta.py --limit 8
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import publish_shorts as PS                                  # noqa: E402
import quota                                                 # noqa: E402

BACKUP = ROOT / "_backup" / "live_shorts_meta.json"
COST = 51


def current(yt, ids):
    """整批讀回目前的 snippet。**一次 list 讀完**,不要一支一支問。"""
    out = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet",
                             id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = it["snippet"]
    return out


def settled(yt, want, tries=3, wait=8):
    """讀回確認。**批次 + 延遲重試** —— `videos.list` 緊接 `videos.update`
    會拿到舊值(2026-08-26 實測 6 支全寫成功卻報 5 支不符)。"""
    ids = list(want)
    for i in range(tries):
        got = current(yt, ids)
        bad = [v for v in ids if got.get(v, {}).get("title") != want[v]]
        if not bad:
            return []
        if i < tries - 1:
            print(f"    讀回 {len(bad)} 支不符,{wait}s 後重試(很可能是快取)")
            time.sleep(wait)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", dest="show")
    ap.add_argument("--limit", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    a = ap.parse_args()

    done = json.loads(PS.LEDGER.read_text(encoding="utf-8"))
    items = {o["key"]: o for o in PS.build_meta()}
    todo = []
    for key, vid in done.items():
        o = items.get(key)
        if not o:
            print(f"  ⛔ {key}:帳本裡有,但現在算不出 metadata —— 跳過")
            continue
        todo.append((key, vid, o))

    if a.show:
        print(f"已上線 {len(done)} 支,可修 {len(todo)} 支(每支 {COST} 單位,"
              f"共 {len(todo) * COST:,});今天還剩 {quota.remaining():,}")
        for key, vid, o in todo:
            print(f"  {key:<20}{vid}  {o['title'][:62]}")
        return 0

    todo = todo[:a.limit]
    print(f"要修 {len(todo)} 支,估算配額 {len(todo) * COST:,};"
          f"今天還剩 {quota.remaining():,}")
    if a.dry:
        for key, vid, o in todo:
            print(f"\n[{key}] {vid}")
            print(f"  新標題:{o['title']}")
            src = [ln for ln in o["description"].split(chr(10))
                   if ln.startswith("Source:")]
            print(f"  新來源:{src[0] if src else '(說明欄沒有 Source 行)'}")
        print("\n--dry-run:未連網、未修改。")
        return 0

    yt = PS.svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != PS.EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1

    ids = [v for _, v, _ in todo]
    was = current(yt, ids)
    # 🔴 改之前先把**現況**存起來。線上的舊標題與說明在別的地方都沒有
    #    副本(帳本只有 videoId),改掉就回不去了。
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    hist = json.loads(BACKUP.read_text(encoding="utf-8")) \
        if BACKUP.exists() else []
    hist.append({"at": time.strftime("%F %T"), "snippets": was})
    BACKUP.write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"  舊 metadata 已備份到 {BACKUP.name}({len(was)} 支)")

    want, ok = {}, 0
    for key, vid, o in todo:
        if not quota.can(COST):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡")
            break
        sn = was.get(vid)
        if sn is None:
            print(f"  ⛔ {key}:讀不到線上 snippet,跳過")
            continue
        if sn.get("title") == o["title"] and \
                sn.get("description") == o["description"]:
            print(f"  = {key}:已經是最新的,不花配額")
            continue
        # 🔴 **整份覆寫**:把讀回來的 snippet 原樣帶上,只換兩個欄位。
        #    只送 title/description 會清掉 categoryId、tags、
        #    defaultLanguage、defaultAudioLanguage。
        body = dict(sn)
        body["title"] = o["title"]
        body["description"] = o["description"]
        yt.videos().update(part="snippet",
                           body={"id": vid, "snippet": body}).execute()
        quota.spend(50, f"fix_meta {key}")
        want[vid] = o["title"]
        ok += 1
        print(f"  ✓ {key:<20}{o['title'][:60]}")

    if want:
        quota.spend(1, "fix_meta readback")
        bad = settled(yt, want)
        if bad:
            print(f"⛔ 讀回仍不符:{bad} —— 這幾支請手動確認")
            return 1
        print(f"    讀回確認 {len(want)} 支 ✓")
    print(f"\n完成:修了 {ok}/{len(todo)} 支。配額剩 {quota.remaining():,}。"
          f"舊值在 {BACKUP.name},要還原就從那裡拿。")
    return 0 if ok == len([1 for k, v, o in todo
                           if was.get(v, {}).get("title") != o["title"]
                           or was.get(v, {}).get("description")
                           != o["description"]]) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
