#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_repackage3.py — 舊片重新包裝【第三批 16 支】上線(標題+描述修正+縮圖)。

讀 STUDIO/_repackage_batch3.json(16 支:标题/縮圖 repackage3/、7 支 desc_edits find→replace)。
⚠️ 執行前需先過獨立驗證 V3(零例外);V3 若擋下某支,把該 id 加進 SKIP 再跑。

安全同前兩批:--dry 唯讀檢視;--apply 才 videos.update+thumbnails.set。
描述替換沒對上→放棄改該支描述(只改標題)。log 記 STUDIO/repackage_apply_log.json(可還原);讀回驗證。
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
BATCH = STUDIO / "_repackage_batch3.json"
LOG = STUDIO / "repackage_apply_log.json"
TW = timezone(timedelta(hours=8))
MAX_TITLE = 100

# V3 獨立驗證(2026-07-13)判決:
#   lTR1bE5NH60 REJECT — 標題/縮圖/desc 的 823.1%/380.0%/393.5% 全對不上現行 tw_stock_facts
#   (facts 每日 04:00 重算,batch3 是過期快照;且影片旁白講 824% 會與描述打架)→另案人為決策。
#   VhUxJLlz7aE / czTb06MSIXw / UmWl3Ue6CL0 — 縮圖已重生(無卡+手工完整文案,親眼驗過),移出 SKIP;
#   UmWl3Ue6CL0 標題用 TITLE_OVERRIDE 拿掉「30分鐘」。
SKIP: set = {"lTR1bE5NH60"}
# V3 標題修正
TITLE_OVERRIDE: dict = {
    "868ZDyvf6Q8": "真金白銀跑機器人第18天，帳戶-2.57%——逐筆算給你看 #Shorts",  # 修「剩-2.57%」語病
    "UmWl3Ue6CL0": "『AI網格輕鬆爆賺』的宣傳，我回測後發現了什麼？ #Shorts",  # 拿掉查無出處的「30分鐘」
}


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _svc():
    from decision_dept import yt_service
    return yt_service()


def load_items():
    d = json.loads(BATCH.read_text(encoding="utf-8"))
    items = d["items"] if isinstance(d, dict) and "items" in d else d
    return [it for it in items if it["video_id"] not in SKIP]


def edited_desc(entry, desc):
    new = desc
    unmatched = []
    for ed in entry.get("desc_edits", []) or []:
        f, r = ed.get("find", ""), ed.get("replace", "")
        if f and f in new:
            new = new.replace(f, r)
        elif f:
            unmatched.append(f[:20])
    return new, (new != desc), unmatched


def fetch(svc, ids):
    out = {}
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = it["snippet"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    items = load_items()
    ids = [e["video_id"] for e in items]
    svc = _svc()
    snaps = fetch(svc, ids)
    print(f"[apply_repackage3] {'APPLY' if args.apply else 'DRY'}  {len(snaps)}/{len(ids)} 支(SKIP {len(SKIP)})\n")

    for e in items:
        vid = e["video_id"]; sn = snaps.get(vid)
        if not sn:
            print(f"[{vid}] ❌ 抓不到"); continue
        new_t = TITLE_OVERRIDE.get(vid, e["new_title"])[:MAX_TITLE]
        nd, dch, unm = edited_desc(e, sn.get("description", ""))
        thumb = ROOT / e["thumbnail_path"]
        print(f"[{vid}] 標題新: {new_t[:42]}  縮圖={thumb.is_file()}"
              + (f"  描述:改={dch} 沒對上={unm}" if e.get("desc_edits") else ""))

    if not args.apply:
        print("\n[dry] 未寫任何東西。V3 驗證過後加 --apply 上線。")
        return 0

    log = []
    if LOG.exists():
        try:
            log = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    from googleapiclient.http import MediaFileUpload
    dt = dd = dc = 0
    for e in items:
        vid = e["video_id"]; sn = snaps.get(vid)
        if not sn:
            continue
        old_t = sn.get("title", ""); new_t = TITLE_OVERRIDE.get(vid, e["new_title"])[:MAX_TITLE]
        old_d = sn.get("description", "")
        new_d, dch, unm = edited_desc(e, old_d)
        if dch and unm:
            print(f"[skip 描述] {vid}: 沒對上={unm}", file=sys.stderr)
            new_d, dch = old_d, False
        if (old_t != new_t) or dch:
            try:
                body = dict(sn); body["title"] = new_t
                if dch:
                    body["description"] = new_d
                svc.videos().update(part="snippet", body={"id": vid, "snippet": body}).execute()
                if old_t != new_t:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "title", "old": old_t, "new": new_t}); dt += 1
                    print(f"[ok 標題] {vid}")
                if dch:
                    log.append({"ts": tw_now(), "video_id": vid, "field": "description", "old": old_d, "new": new_d}); dd += 1
                    print(f"[ok 描述] {vid}")
            except Exception as ex:
                print(f"[err] {vid}: {str(ex)[:120]}", file=sys.stderr)
        thumb = ROOT / e["thumbnail_path"]
        if thumb.is_file():
            try:
                svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
                log.append({"ts": tw_now(), "video_id": vid, "field": "thumbnail", "new": str(thumb)}); dc += 1
                print(f"[ok 縮圖] {vid}")
            except Exception as ex:
                print(f"[err 縮圖] {vid}: {str(ex)[:120]}", file=sys.stderr)
        time.sleep(0.4)

    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[apply] 標題 {dt}、描述 {dd}、縮圖 {dc} 已上線。log→{LOG.name}")
    time.sleep(2)
    back = fetch(svc, ids)
    print("\n[讀回驗證]")
    for e in items:
        vid = e["video_id"]
        cur = back.get(vid, {}).get("title", "?")
        ok = cur == TITLE_OVERRIDE.get(vid, e["new_title"])[:MAX_TITLE]
        print(f"  {vid}: {'✅' if ok else '⚠️'} {cur[:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
