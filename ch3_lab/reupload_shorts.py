#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reupload_shorts.py — 把已上線的 Short 換成修好的版本。

## 為什麼需要它
YouTube **不能替換已發布影片的檔案**。要換畫面只有一條路:重新上傳一支新的,
再把舊的收起來。已上線的 16 支 Short 帶著兩個缺陷:

1. **版面重疊**(16 支全部):判決卡壓在「the replication — N people」上。
   根因是版面斷言只驗「出不出界」,對「兩個都在界內但壓在一起」全盲。
2. **假來源**(其中 4 支名案):畫面與說明欄印著「FORRT Replication
   Database」,但它們的數字出自各自的統合分析,FReD 裡根本沒有那些列。
   來源行是觀眾唯一能拿去查證的線索 —— 指錯地方比不寫還糟。

第 2 點是誠信問題,第 1 點是排版問題。**兩者的優先順序不一樣**,所以
`--only-source` 可以只做那 4 支。

## 舊片設成 private,不刪
可逆。刪掉是不可逆的,而這裡沒有任何理由需要不可逆 —— 那 16 支觀看接近零,
private 之後不會出現在搜尋、訂閱 feed 或頻道頁,效果跟刪掉一樣,但改回來
只要一個 API 呼叫。舊 id 會落檔到 `replaced_shorts.json`,不會消失。

⚠️ **改 status 要先讀回完整的 status 再改一個欄位。**
`videos.update` 是整份覆寫:只送 `{"privacyStatus": "private"}` 會把
`selfDeclaredMadeForKids`、`license`、`embeddable` 一起清掉。
retitle.py 就漏過一個可寫欄位(`defaultAudioLanguage`),差點清掉 12 支
線上影片的設定。

## 配額
每支:insert 1600 + 輪詢 6 + 讀舊片 status 1 + 改舊片 status 50 = **1657**。
16 支 = 26,512,而每日上限 10,000 → **至少三天**,而且會直接排擠新片
(目前 6 支/天已經吃掉 9,694)。所以預設 `--limit 4`,不要一次排滿。

用法:
  python reupload_shorts.py --list
  python reupload_shorts.py --only-source --dry-run
  python reupload_shorts.py --only-source --limit 4
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

REPLACED = ROOT / "replaced_shorts.json"
#: insert 1600 + 輪詢 6(已含在 quota.SHORT)+ videos.list 1 + update 50
COST = quota.SHORT + 51

#: 帶假來源的那幾支(名案線)。**誠信問題,優先於排版問題。**
SOURCE_BUG = ("ego_depletion", "romantic_red", "bystander_effect",
              "sleep_memory", "implicit_bias_test")


def settled(yt, want, tries=3, wait=8):
    """讀回確認。**批次讀 + 延遲重試。**

    `videos.list` 緊接在 `videos.update` 之後會拿到**舊值**(快取),
    2026-08-26 實測:6 支全部寫成功,卻報 5 支不符。所以要重試,
    而且一次讀完整批(N 次 list 省成 1 次)。
    """
    ids = list(want)
    for i in range(tries):
        got = {}
        for j in range(0, len(ids), 50):
            r = yt.videos().list(part="status",
                                 id=",".join(ids[j:j + 50])).execute()
            for it in r.get("items", []):
                got[it["id"]] = it["status"].get("privacyStatus")
        bad = [v for v in ids if got.get(v) != want[v]]
        if not bad:
            return []
        if i < tries - 1:
            print(f"    讀回 {len(bad)} 支不符,{wait}s 後重試"
                  f"(很可能只是快取)")
            time.sleep(wait)
    return bad


def hide(yt, vid):
    """把舊片設成 private。**先讀回完整 status 再只改一個欄位。**"""
    got = yt.videos().list(part="status", id=vid).execute().get("items", [])
    if not got:
        return f"讀不到 {vid}"
    st = dict(got[0]["status"])
    if st.get("privacyStatus") == "private":
        return None                      # 已經是了,不要白花 50 單位
    st["privacyStatus"] = "private"
    # 不能送的唯讀欄位
    for k in ("uploadStatus", "failureReason", "rejectionReason",
              "publishAt"):
        st.pop(k, None)
    yt.videos().update(part="status",
                       body={"id": vid, "status": st}).execute()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", dest="show")
    ap.add_argument("--only-source", action="store_true",
                    help="只換帶假來源的那幾支(誠信優先)")
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    a = ap.parse_args()

    done = json.loads(PS.LEDGER.read_text(encoding="utf-8"))
    items = PS.build_meta()
    by_key = {o["key"]: o for o in items}

    todo = []
    for key, old in done.items():
        if a.only_source and key not in SOURCE_BUG:
            continue
        o = by_key.get(key)
        if not o:
            print(f"  ⛔ {key}:帳本裡有,但現在算不出 metadata —— 跳過")
            continue
        todo.append((key, old, o))

    if a.show:
        print(f"已上線 {len(done)} 支,可換 {len(todo)} 支"
              f"(每支 {COST:,} 單位)")
        for key, old, o in todo:
            tag = " ← 假來源" if key in SOURCE_BUG else ""
            print(f"  {key:22s}{old}  {o['title'][:52]}{tag}")
        print(f"\n全部換完要 {len(todo) * COST:,} 單位;"
              f"今天還剩 {quota.remaining():,}")
        return 0

    # 🔴 換上去的檔案必須是**現行碼渲的**。這一整件事就是因為線上的片子
    #    是舊碼渲的,再拿一批舊檔上去等於白花配額。
    st, _ = PS.stale([o for _, _, o in todo])
    changed, unknown = PS.visual_stale([o for _, _, o in todo])
    if st or changed:
        print(f"⛔ 這幾支的 mp4 不是現行碼的產物,不換:"
              f"{st + [k for k, _ in changed]}")
        return 1
    if unknown:
        print(f"⚠️ 這幾支沒有 visual.json,無法比對畫面:"
              f"{[k for k, _ in unknown]}")

    todo = todo[:a.limit]
    print(f"要換 {len(todo)} 支,估算配額 {len(todo) * COST:,};"
          f"今天還剩 {quota.remaining():,}")
    for key, old, o in todo:
        print(f"  {key:22s}{old} → 新片")
    if a.dry:
        print("\n--dry-run:未連網、未上傳。")
        return 0

    yt = PS.svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if me["id"] != PS.EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1

    rec = json.loads(REPLACED.read_text(encoding="utf-8")) \
        if REPLACED.exists() else {}
    swapped = 0
    for key, old, o in todo:
        if not quota.can(COST):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡")
            break
        print(f"\n[{key}] {o['title'][:60]}")
        vid = PS.insert_one(yt, o, ROOT / o["video"])
        # 🔴 **舊 id 先落檔,再動帳本。** 帳本一旦被覆寫,舊 id 就只剩
        #    YouTube 那邊知道;中間掛掉的話我連要收哪一支都查不到。
        rec[key] = {"old": old, "new": vid, "at": time.strftime("%F %T")}
        REPLACED.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        done[key] = vid
        tmp = PS.LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(PS.LEDGER)
        quota.spend(quota.SHORT, f"reupload {key}")
        print(f"    新片 {vid}  https://youtube.com/shorts/{vid}")
        err = hide(yt, old)
        quota.spend(51, f"hide {old}")
        if err:
            print(f"    ⛔ 舊片沒收起來:{err} —— 頻道上會有兩支一樣的,"
                  f"手動處理 {old}")
            continue
        bad = settled(yt, {old: "private"})
        if bad:
            print(f"    ⛔ 讀回仍不是 private:{bad}")
            continue
        print(f"    舊片 {old} 已設為 private ✓")
        swapped += 1
    print(f"\n完成:換掉 {swapped}/{len(todo)} 支。"
          f"對照表 {REPLACED.name}。配額剩 {quota.remaining():,}")
    return 0 if swapped == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
