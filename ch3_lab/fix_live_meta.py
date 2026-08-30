#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_live_meta.py — 修已上線 Short 的**標題與說明**(不動影片)。

## 為什麼這支比重上傳划算
獨立驗證指出:假來源「Source: FORRT Replication Database (FReD)」同時在
**畫面**和**說明欄**。畫面改不掉(YouTube 沒有替換已發布影片檔的方法),
但說明欄一個 `videos.update` 就改得掉,而**標題也在同一次呼叫裡**。

    16 支 × ~50 = 約 800 單位,重上傳是 26,528。

修得掉的:說明欄的假來源、標題缺可搜尋的效應名。
⚠️ 實際加到效應名的只有 **2 支**(`The bystander effect:` / `Ego depletion:`)
—— `romantic_red`/`sleep_memory` 塞不下,ep000–ep011 是 FReD 列本來就沒有
通俗名。第一版 docstring 寫「16 支全部」是誇大,獨立驗證抓到的。

燒進畫面的東西仍然只能重傳,那是另一件事、另一個決定。

## 這支繼承了隔壁兩支已上過正式機的工具
第一版四個阻斷項全部是「答案就在隔壁檔案裡而我沒抄」:

1. **唯讀欄位**:`body = dict(sn)` 把 `publishedAt` / `channelId` /
   `thumbnails` / `channelTitle` / `liveBroadcastContent` / `localized`
   原樣送回去。最惡的是 `localized` —— 它帶著**舊的** title/description,
   新值在 `title`、舊值在 `localized.title`,兩者打架而且可能舊的贏。
   → 改成 `fix_audio_language.py` 的 **allow-list**(比 pop 清單安全:
   以後 API 多一個唯讀欄位,allow-list 自動不受影響)。
2. **回讀只比 title**:而說明欄的假來源正是這支存在的第一個理由。
   實測假 API 悄悄保留舊 description → 「讀回確認 16 支 ✓、rc=0」,
   而 16 支一個都沒改到。→ 連 description 一起比。
3. **`public_only()` 失敗會把導流連結全部拆掉**:它包在
   `except Exception: return {}` 裡,回 `{}` 之後 `link_line` 走
   「發過但不公開」那條,第一行的 `Full episode: …` 整個消失。
   一次網路抖動 = 16 支失去唯一的導流管道,而工具說成功。→ fail-closed。
4. **update 沒有 try/except**:中途 403 直接 traceback,`settled()`
   永遠不執行,「改了幾支、成功了沒」完全沒有紀錄。
   `retitle_live.py:362` 的註解**逐字寫過這個坑**。→ 每支包起來。

## 配額
每支 `videos.update` 50。另計:`public_only` 的 list 1、`channels.list` 1、
`current()` 的 list 1、回讀每輪 1。全部都記帳 —— memory
`yt-api-quota-structural-overrun` 的結論是「不是用太多,是有人沒記帳」。

用法:
  python fix_live_meta.py --list
  python fix_live_meta.py --dry-run
  python fix_live_meta.py --limit 8
  python fix_live_meta.py --restore --at "2026-08-30 16:05:00"
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
#: videos.update 50。印出來的估算只算這個,零星的 list 另外記帳 ——
#: 舊版用 51/支 而 docstring 又說回讀是批次的,同一件事兩個數字。
COST = 50

#: **畫面上的內容已經跟現在的事實不一致的,不要只修 metadata。**
#:
#: 🔴 `bystander_effect`(LjFyZRTOkU0)08-28 發布時,`make_short` 自己那份
#:    分類器在缺信賴區間的情況下判成 mixed,片中判決卡是
#:    「Smaller — but still there.」。後來 `famous_tone` 改判成 held,
#:    現在產出的說明欄會寫「This one held up.」——
#:    **改了說明欄,說明欄和畫面就當著觀眾的面互相矛盾。**
#:    修好一個問題、製造一個更明顯的問題。
#:
#:    這種只能重傳或先撤下,不能靠 metadata 補。dry-run 印出完整說明欄
#:    才看得到這件事(第一版只印 Source 那一行,就會直接送出去)。
#: 值 = 為什麼要排除。空 dict 表示沒有這種片。
NEEDS_REUPLOAD = {
    "bystander_effect":
        "片中判決卡是舊判定「Smaller — but still there.」,"
        "而現在的說明欄會寫「This one held up.」—— 改了就自相矛盾。"
        "⚠️ 上線版的 mp4 不在版控裡,這是從 08-28 的碼與事實庫重建的推論;"
        "要動它之前先自己開 youtu.be/LjFyZRTOkU0 看那一幀。",
}

#: **可寫欄位白名單。** 送 snippet 是整份覆寫,少送會清空、多送會被拒。
#: 跟 `fix_audio_language.py` 對齊;比 `retitle_live.py` 的 pop 清單安全,
#: 因為 API 以後多一個唯讀欄位時 allow-list 自動不受影響。
WRITABLE = ("title", "description", "categoryId", "tags",
            "defaultLanguage", "defaultAudioLanguage")


def snippet_body(vid, sn, title, desc):
    """要送出去的 snippet。**只帶白名單裡的欄位。**"""
    body = {k: sn.get(k) for k in WRITABLE}
    body["title"], body["description"] = title, desc
    return {"id": vid, "snippet": {k: v for k, v in body.items()
                                   if v is not None}}


def current(yt, ids, why):
    """整批讀回目前的 snippet。**一次 list 讀完**,不要一支一支問。"""
    out = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet",
                             id=",".join(ids[i:i + 50])).execute()
        quota.spend(1, f"fix_meta list ({why})")
        for it in r.get("items", []):
            out[it["id"]] = it["snippet"]
    return out


def settled(yt, want, tries=3, wait=8):
    """讀回確認。**title 與 description 都要比。**

    🔴 第一版只比 title。獨立驗證用假 API 讓 title 生效、description 悄悄
    保留舊值 —— 工具印「讀回確認 16 支 ✓」、rc=0,而說明欄的假來源
    一個都沒改掉。那正是這支工具存在的第一個理由。

    批次 + 延遲重試:`videos.list` 緊接 `videos.update` 會拿到舊值
    (2026-08-26 實測 6 支全寫成功卻報 5 支不符)。
    """
    ids = list(want)
    for i in range(tries):
        got = current(yt, ids, f"readback {i + 1}")
        bad = [v for v in ids
               if (got.get(v, {}).get("title"),
                   got.get(v, {}).get("description")) != want[v]]
        if not bad:
            return []
        if i < tries - 1:
            print(f"    讀回 {len(bad)} 支不符,{wait}s 後重試(可能是快取)")
            time.sleep(wait)
    return bad


def restore(yt, at):
    """把某個時間點的備份寫回去。**紅線動作不該在出事當下才寫工具。**"""
    if not BACKUP.exists():
        print("⛔ 沒有備份檔"); return 1
    hist = json.loads(BACKUP.read_text(encoding="utf-8"))
    snap = next((h for h in hist if h["at"] == at), None)
    if snap is None:
        print(f"⛔ 找不到時間點 {at}。可用的:")
        for h in hist:
            print(f"   {h['at']}  ({len(h['snippets'])} 支)")
        return 1
    print(f"要還原 {len(snap['snippets'])} 支到 {at}")
    bad = 0
    for vid, sn in snap["snippets"].items():
        if not quota.can(COST):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡"); break
        try:
            yt.videos().update(**{"part": "snippet"},
                               body=snippet_body(vid, sn, sn["title"],
                                                 sn["description"])).execute()
            quota.spend(COST, f"restore {vid}")
            print(f"  ✓ {vid}  {sn['title'][:56]}")
        except Exception as e:                                # noqa: BLE001
            bad += 1
            print(f"  ⛔ {vid}:{str(e)[:70]}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", dest="show")
    ap.add_argument("--limit", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--at", help="要還原到哪個備份時間點")
    a = ap.parse_args()

    if a.restore:
        if not a.at:
            print("⛔ --restore 要配 --at <時間戳>(用 --list 看有哪些)")
            return 1
        return restore(PS.svc(), a.at)

    done = json.loads(PS.LEDGER.read_text(encoding="utf-8"))
    # ⚠️ build_meta() 內部會呼叫 public_only() → **真的打一次 videos.list**。
    #    所以連 --list / --dry-run 都會連網花 1 單位。第一版的
    #    「--dry-run:未連網」是一句假話,而這條線的資產就是
    #    「說出口的話都查得到」。
    items = {o["key"]: o for o in PS.build_meta()}
    quota.spend(1, "fix_meta public_only")

    # 🔴 **fail-closed**:`public_only` 整段包在 `except Exception: return {}`,
    #    失敗時回空 dict,而空 dict 會讓 `link_line` 省略導流連結 ——
    #    一次網路抖動就把 16 支線上 Short 的唯一導流管道拆掉,還回報成功。
    if not PS._LONGS_PUB:
        print("⛔ 查不到任何公開的長片。可能是 public_only() 吞掉了例外,"
              "而那會讓新的說明欄**少掉導流連結**。不動任何東西。")
        return 1

    todo, excluded = [], []
    for key, vid in done.items():
        o = items.get(key)
        if not o:
            print(f"  ⛔ {key}:帳本裡有,但現在算不出 metadata —— 跳過")
            continue
        if key in NEEDS_REUPLOAD:
            excluded.append((key, vid, NEEDS_REUPLOAD[key]))
            continue
        todo.append((key, vid, o))
    if excluded:
        print("⛔ 這幾支的**畫面內容**已經跟現在的事實不一致,"
              "只修 metadata 會讓說明欄跟畫面互相矛盾:")
        for key, vid, why in excluded:
            print(f"   {key:<20}{vid}")
            print(f"      {why}")

    if a.show:
        print(f"已上線 {len(done)} 支,可修 {len(todo)} 支(每支 {COST} 單位,"
              f"共 {len(todo) * COST:,});今天還剩 {quota.remaining():,}")
        for key, vid, o in todo:
            print(f"  {key:<20}{vid}  {o['title'][:62]}")
        if BACKUP.exists():
            print("\n可還原的備份時間點:")
            for h in json.loads(BACKUP.read_text(encoding="utf-8")):
                print(f"   {h['at']}  ({len(h['snippets'])} 支)")
        return 0

    todo = todo[:a.limit]
    if a.dry:
        print(f"要修 {len(todo)} 支,估算配額 {len(todo) * COST:,}"
              f"(不含零星 list);今天還剩 {quota.remaining():,}")
        for key, vid, o in todo:
            print(f"\n[{key}] {vid}")
            print(f"  新標題:{o['title']}")
            print(f"  新說明:")
            for ln in o["description"].split(chr(10)):
                print(f"    {ln}")
        print("\n--dry-run:**沒有寫入任何東西**。"
              "(但上面查長片狀態已經打了一次 videos.list,1 單位)")
        return 0

    yt = PS.svc()
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    quota.spend(1, "fix_meta channels.list")
    if me["id"] != PS.EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me['id']}")
        return 1

    ids = [v for _, v, _ in todo]
    was = current(yt, ids, "before")
    need = [(k, v, o) for k, v, o in todo
            if was.get(v) is not None
            and (was[v].get("title") != o["title"]
                 or was[v].get("description") != o["description"])]
    if not need:
        print("所有已上線的 Short 標題與說明都已經是最新的,不用改。")
        return 0

    # 🔴 **有東西要改才寫備份。** 第一版無條件 append,於是重跑一次(明明
    #    一支都沒改)照樣多一筆、內容是**改後**的值 —— 出事時在壓力下拿
    #    `hist[-1]` 是最自然的動作,而那是錯的。
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    hist = json.loads(BACKUP.read_text(encoding="utf-8")) \
        if BACKUP.exists() else []
    stamp = time.strftime("%F %T")
    hist.append({"at": stamp,
                 "snippets": {v: was[v] for _, v, _ in need}})
    BACKUP.write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"  改前的值已備份({len(need)} 支,時間點 {stamp})"
          f"—— 還原用 --restore --at \"{stamp}\"")

    want, ok, failed, stopped = {}, 0, [], False
    for key, vid, o in need:
        if not quota.can(COST):
            print(f"  ⏸ 配額只剩 {quota.remaining():,},停在這裡")
            stopped = True
            break
        sn = was[vid]
        if not sn.get("categoryId"):
            failed.append((key, "線上 snippet 缺 categoryId,不猜分類"))
            print(f"  ⛔ {key}:缺 categoryId,跳過")
            continue
        # 🔴 每支包起來。中途 403 直接 traceback 的話,`settled()` 永遠
        #    不會執行 —— 已經改掉的那幾支沒有任何回讀、沒有任何紀錄。
        #    這條線的配額本來就每天爆,中途 403 不是理論風險。
        try:
            yt.videos().update(
                part="snippet",
                body=snippet_body(vid, sn, o["title"],
                                  o["description"])).execute()
        except Exception as e:                                # noqa: BLE001
            failed.append((key, str(e)[:80]))
            print(f"  ⛔ {key}:{str(e)[:70]}")
            if "quota" in str(e).lower():
                stopped = True
                break
            continue
        quota.spend(COST, f"fix_meta {key}")
        want[vid] = (o["title"], o["description"])
        ok += 1
        print(f"  ✓ {key:<20}{o['title'][:58]}")

    mismatch = settled(yt, want) if want else []
    if mismatch:
        print(f"⛔ 讀回仍不符(標題或說明):{mismatch}")
    left = len(need) - ok - len(failed)
    print(f"\n完成:改了 {ok}/{len(need)} 支"
          + (f",失敗 {len(failed)}" if failed else "")
          + (f",還剩 {left} 支沒動(配額)" if stopped and left else "")
          + f"。配額剩 {quota.remaining():,}。")
    for k, why in failed:
        print(f"   ⛔ {k}:{why}")
    # rc=0 只代表「我做的每一件都成功而且驗過,剩下的我講清楚了」。
    return 1 if (failed or mismatch) else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
