#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pin_question.py — 每支片發完之後,由頻道自己貼出**第一則留言**並置頂。

## 為什麼
2026-08-31 量到的:289 次觀看換到 **0 則留言、0 次分享、1 個讚**。
Shorts 的分發靠前一批曝光回收到的訊號決定要不要放大 —— 回收接近零,
它就不放大。片子改版之後片尾會問一個外行答得出來的問題,但**問完之後
留言區是空的**,而空的留言區本身就是「不用回應」的訊號。

第一則留言是最便宜的破冰:它把問題從「影片裡的一句話」變成「一個可以
按回覆的東西」。成本 50 配額(commentThreads.insert)。

## 誠信
- **問題逐字取自該集的 `reel.ask`** —— 就是片尾唸的那一句,不另外寫一個。
  片裡問 A、留言問 B 會讓人覺得是罐頭。
- **不假裝是觀眾**。這是頻道帳號自己的留言,YouTube 會顯示成頻道名稱,
  不做任何「路人發問」的偽裝。
- **不放連結、不求訂閱**。它只做一件事:讓問題有地方可以回答。

## 🔴 置頂這件事 API 做不到
`comments.setModerationStatus` 不能置頂,而 `commentThreads` 沒有 pin 欄位
—— **置頂只能在 Studio UI 手動點**。所以這支只負責「貼出第一則」,
置頂與否不影響它要做的事(留言區不再是空的)。
**不要在輸出裡宣稱已置頂** —— 那會是一句沒有機制支撐的話,而這條線
今天才因為那種句子修了一整天。

用法:
  python pin_question.py --list
  python pin_question.py --dry-run
  python pin_question.py --only reel_hot_hand
  python pin_question.py --apply --max 6
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SRC = ROOT / "facts" / "rechecked_episodes.json"
SHORTS_LEDGER = ROOT / "uploaded_shorts.json"
DONE = ROOT / "pinned_questions.json"
COST = 50           # commentThreads.insert


def ledger(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def asks():
    """slug → 片尾那一句問題(逐字)。"""
    d = json.loads(SRC.read_text(encoding="utf-8"))
    return {e["slug"]: (e.get("reel") or {}).get("ask") for e in d["episodes"]}


def candidates():
    """已上線、還沒貼過第一則留言的短片。"""
    up, done, A = ledger(SHORTS_LEDGER), ledger(DONE), asks()
    out = []
    for key, vid in up.items():
        if not key.startswith("reel_"):
            continue                      # 舊格式沒有 ask,不處理
        if key in done:
            continue
        q = A.get(key[len("reel_"):])
        if not q:
            print(f"  ⚠️ {key}:事實庫裡沒有 ask,跳過(不自己編一個)")
            continue
        out.append((key, vid, q.strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    ap.add_argument("--list", action="store_true", dest="show")
    ap.add_argument("--only", default="")
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args()

    todo = candidates()
    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        miss = want - {k for k, _, _ in todo}
        if miss:
            raise SystemExit(f"⛔ --only 指名的不在候選裡:{sorted(miss)}")
        todo = [t for t in todo if t[0] in want]
    # 🔴 **不公開的片不要貼。** 下架待重傳的片貼了留言也沒人看得到,
    #    而且那則留言會跟著舊版本留在那裡。實測候選裡有兩支是 unlisted。
    if todo and not a.show:
        from publish_shorts import svc as _s
        _y = _s()
        import quota as _q
        ids = ",".join(v for _k, v, _q2 in todo)
        r = _y.videos().list(part="status", id=ids).execute()
        _q.spend(1, "privacy check")
        pub = {i["id"] for i in r.get("items", [])
               if i["status"]["privacyStatus"] == "public"}
        skipped = [k for k, v, _ in todo if v not in pub]
        if skipped:
            print(f"  ⚠️ 這幾支不是 public,不貼:{skipped}")
        todo = [t for t in todo if t[1] in pub]
    todo = todo[:a.max]

    if a.show or not (a.apply or a.dry):
        for key, vid, q in todo:
            print(f"  {key:<28}{vid}  「{q}」")
        print(f"\n共 {len(todo)} 支待貼")
        return 0

    import quota
    if not a.dry and not quota.can(COST * len(todo)):
        raise SystemExit(f"⛔ 配額不足:要 {COST * len(todo)},"
                         f"剩 {quota.remaining()}")

    if a.dry:
        for key, vid, q in todo:
            print(f"[dry] {key} → {vid}\n      {q}")
        return 0

    from publish_shorts import svc
    y = svc()
    done = ledger(DONE)
    for key, vid, q in todo:
        body = {"snippet": {"videoId": vid,
                            "topLevelComment": {"snippet": {"textOriginal": q}}}}
        r = y.commentThreads().insert(part="snippet", body=body).execute()
        quota.spend(COST, f"comment {key}")
        cid = r["snippet"]["topLevelComment"]["id"]
        # 🔴 回讀 —— 這條線今天已經抓到一個「回 200 但沒改」的 API,
        #    而且回讀是本專案的合約,不是選配。
        back = y.commentThreads().list(part="snippet", videoId=vid,
                                       maxResults=100).execute()
        quota.spend(1, "comment readback")
        got = [t["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
               for t in back.get("items", [])]
        if q not in got:
            print(f"  ⛔ {key}:貼了但回讀找不到 —— 不記帳,下次會重試")
            continue
        done[key] = cid
        DONE.write_text(json.dumps(done, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"  ✓ {key}:{cid}")
    print(f"\n{len(done)} 支已有開場留言。"
          f"置頂只能在 Studio UI 點 —— 這支不做,也不宣稱做了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
