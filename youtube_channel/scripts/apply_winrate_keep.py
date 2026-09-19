#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_winrate_keep.py — 假勝率清理「B 徹底去農場」保留的 24 支:改誠實標題 + 清描述捏造勝率。

讀 STUDIO/_winrate_B_plan.json 的 keep_and_fix(24 支;其中 20 支有 desc_edits_exact)。
已過獨立驗證 V(冤案 -wjWqNiewCc/BkxYZOTUKh0 已移回保留)+ 描述 craft(20/20 精準對上、改後零殘留)。

安全:--dry 唯讀檢視;--apply 才 videos.update(part=snippet,保留 categoryId/tags,只改 title/description)。
殘留守衛:desc_edits 沒對上或改完仍殘留 desc_flags→放棄改該支描述(只改標題),不推可疑版本。
old→new 記 STUDIO/repackage_apply_log.json(可還原);讀回驗證。認證 decision_dept.yt_service。
下架的 44 支走另一支 set_private_by_ids.py,不在本腳本。
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
PLAN = STUDIO / "_winrate_B_plan.json"
LOG = STUDIO / "repackage_apply_log.json"
TW = timezone(timedelta(hours=8))
MAX_TITLE = 100


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _svc():
    from decision_dept import yt_service
    return yt_service()


def load_keep():
    d = json.loads(PLAN.read_text(encoding="utf-8"))
    return d.get("keep_and_fix", [])


def edited_desc(entry, desc):
    """套用 desc_edits_exact;回 (new, changed, unmatched, residual)。"""
    new = desc
    unmatched = []
    for ed in entry.get("desc_edits_exact", []):
        f, r = ed.get("find", ""), ed.get("replace", "")
        if f and f in new:
            new = new.replace(f, r)
        elif f:
            unmatched.append(f[:20])
    residual = [t for t in entry.get("desc_flags", []) if t in new]
    return new, (new != desc), unmatched, residual


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
    keep = load_keep()
    ids = [e["video_id"] for e in keep]
    svc = _svc()
    snaps = fetch(svc, ids)
    print(f"[apply_winrate_keep] {'APPLY' if args.apply else 'DRY'}  keep {len(snaps)}/{len(ids)} 支\n")

    for e in keep:
        vid = e["video_id"]; sn = snaps.get(vid)
        if not sn:
            print(f"[{vid}] ❌ 抓不到"); continue
        nd, dch, unm, resid = edited_desc(e, sn.get("description", ""))
        print(f"[{vid}] 標題新: {e['honest_new_title'][:44]}"
              + (f"  描述:改={dch} 沒對上={unm} 殘留={resid}" if e.get("desc_edits_exact") else "  (描述無需改)"))

    if not args.apply:
        print("\n[dry] 未寫任何東西。加 --apply 上線。")
        return 0

    log = []
    if LOG.exists():
        try:
            log = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []
    dt = dd = 0
    for e in keep:
        vid = e["video_id"]; sn = snaps.get(vid)
        if not sn:
            continue
        old_t = sn.get("title", ""); new_t = e["honest_new_title"][:MAX_TITLE]
        old_d = sn.get("description", "")
        new_d, dch, unm, resid = edited_desc(e, old_d)
        if dch and (unm or resid):
            print(f"[skip 描述] {vid}: 沒對上={unm} 殘留={resid}(不推可疑描述)", file=sys.stderr)
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
        time.sleep(0.4)

    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[apply] 標題 {dt}、描述 {dd} 已上線。log→{LOG.name}")
    time.sleep(2)
    back = fetch(svc, ids)
    print("\n[讀回驗證]")
    for e in keep:
        vid = e["video_id"]; sn2 = back.get(vid, {})
        cur = sn2.get("title", "?"); ok = cur == e["honest_new_title"][:MAX_TITLE]
        resid = [t for t in e.get("desc_flags", []) if t in sn2.get("description", "")]
        print(f"  {vid}: {'✅' if ok and not resid else '⚠️'} {cur[:40]}{('  殘留'+str(resid)) if resid else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
