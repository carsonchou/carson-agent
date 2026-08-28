#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumb_backfill.py — 把線上縮圖補成現行設計,每天補一點。

## 為什麼需要
`thumbnails.set` 有**速率限制**(跟每日配額是兩回事)。實測一次推 11 支,
即使退避到 35 秒仍有 7 支持續吃 HTTP 429 —— 那不是配額用完,是打太快。
所以「一次全部換好」做不到,只能**每天補幾支,讓它自己收斂**。
主頻道有一支 `thumb_backfill.py --scavenge` 就是為同一件事存在的。

## 怎麼知道哪些還沒換
記一本帳:`thumb_pushed.json` 存「這支影片上次推上去的**本地檔雜湊**」。
本地縮圖重產(設計改了)→ 雜湊變 → 需要重推。

**不用「看圖判斷是新版還舊版」**:那要綁死在當前設計的視覺特徵上
(例如「頂端有沒有那條彩線」),設計一改判斷就失效,而且是**靜默**失效
—— 它會開始說每一張都已經是新的。雜湊沒有這個問題。

## 配額與節流
`thumbnails.set` 每支 50。預設一次最多 3 支、每支間隔 20 秒 ——
刻意保守,因為 429 不扣配額但會浪費一整輪。

用法:
  python thumb_backfill.py --dry-run
  python thumb_backfill.py --max 3
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
STATE = ROOT / "thumb_pushed.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"


def local_thumbs():
    """已上線的影片 → 它現在該用的本地縮圖。"""
    meta = {}
    for o in json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8")):
        for k in (o.get("dir"), o.get("slug")):
            if k:
                meta[k] = o
    out = {}
    for name in ("uploaded.json", "uploaded_comp.json"):
        p = ROOT / name
        if not p.exists():
            continue
        for key, vid in json.loads(p.read_text(encoding="utf-8")).items():
            if name.endswith("comp.json"):
                t = ROOT / "compilations" / key / "thumb.jpg"
                label = f"合輯 {key}"
            else:
                o = meta.get(key)
                if not o or not o.get("thumb"):
                    continue
                t = ROOT / o["thumb"]
                label = o["title"][:46]
            if t.exists():
                out[vid] = (key, t, label)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--gap", type=float, default=20.0, help="每支之間等幾秒")
    ap.add_argument("--dry-run", action="store_true", dest="dry")
    a = ap.parse_args()

    pushed = (json.loads(STATE.read_text(encoding="utf-8"))
              if STATE.exists() else {})
    todo = []
    for vid, (key, path, label) in local_thumbs().items():
        h = hashlib.md5(path.read_bytes()).hexdigest()[:16]
        if pushed.get(vid) != h:
            todo.append((vid, key, path, label, h))
    print(f"已上線且有本地縮圖的 {len(local_thumbs())} 支,"
          f"其中 {len(todo)} 支的縮圖跟線上不同步")
    for vid, key, _p, label, _h in todo[:12]:
        print(f"  {key:<24}{label}")
    if not todo:
        print("  全部同步 ✓")
        return 0
    todo = todo[:a.max]
    print(f"\n這次補 {len(todo)} 支,配額 {len(todo) * 50}"
          f"(其餘留給之後幾天 —— thumbnails.set 有速率限制)")
    if a.dry:
        print("(--dry-run,未推送)")
        return 0

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token_manage.json"
    cr = Credentials.from_authorized_user_file(
        str(tok), ["https://www.googleapis.com/auth/youtube.force-ssl",
                   "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request()); tok.write_text(cr.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    if me != EXPECT_CHANNEL:
        print(f"⛔ 頻道不符:{me}")
        return 1

    # 維運工作也要看共用帳:6 支/天會吃掉幾乎全部配額,那天這些就該讓路。
    # 不讓路的話,最後一支影片會因為縮圖補件先花掉的 150 而發不出去。
    sys.path.insert(0, str(ROOT))
    import quota as _q
    ok = 0
    for i, (vid, key, path, label, h) in enumerate(todo):
        if not _q.can(_q.THUMB):
            print(f"  ⏸ 共用配額只剩 {_q.remaining():,},縮圖補件讓路給發片"
                  f"(明天再補)")
            break
        if i:
            time.sleep(a.gap)
        try:
            yt.thumbnails().set(videoId=vid, media_body=str(path)).execute()
            # 🔴 成功才記帳。記早了會讓下次以為已經推過 —— 那是靜默的漏推,
            #    而漏推不會有任何跡象,只是那支片永遠停在舊縮圖。
            pushed[vid] = h
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(pushed, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(STATE)
            _q.spend(_q.THUMB, f"thumb/{key}")
            ok += 1
            print(f"  ✓ {key}")
        except Exception as e:                                # noqa: BLE001
            msg = str(e)
            hint = "(速率限制,不是配額 —— 明天會自動再試)" if "429" in msg else ""
            print(f"  ⛔ {key}:{msg[:80]} {hint}")
    print(f"\n補上 {ok}/{len(todo)} 支;還剩 {len(local_thumbs()) - len(pushed)} "
          f"支未同步")
    return 0


if __name__ == "__main__":
    sys.exit(main())
