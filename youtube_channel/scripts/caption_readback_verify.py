#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caption_readback_verify.py — 字幕backfill分批`--apply`的獨立讀回驗證工具。

## 為什麼(2026-09-15)
`fix_captions_sync.py --apply`本身印出的✅只代表「已送出、HTTP回應成功」,
不代表YouTube那端真的生效——已知案例:30秒內讀回9/9顯示private,50分鐘後
兩支打回public(`yt-readback-stale-cache`)。本工具用**獨立的**
`captions().list()`唯讀呼叫(不重用`--apply`那次呼叫的回應),在間隔一段
時間之後重新查詢,比對前後是否真的變化。

## 只做兩件事,唯讀
- `snapshot`:對一批videoId各打一次`captions().list()`,記錄非ASR字幕軌的
  `id`+`lastUpdated`(或不存在/呼叫失敗),存成JSON快照。
- `compare`:比對兩份快照(pre/post),用**陽性判斷**邏輯(缺欄位/無法解析
  一律標記「無法判斷」,不用`!=`或`.get(...,"")`這種可能把「兩邊都拿不到」
  誤判成「一致」的寫法)算出每支的驗證結果。

本工具不呼叫`captions().update`/`captions().insert`,不做任何寫入。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _load_ids(path: str) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = raw.get("videoIds", []) if isinstance(raw, dict) else raw
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise ValueError(f"{path}: 預期videoId字串陣列,實際格式不符(raw={raw!r})")
    return list(ids)


def _snapshot_one(yt, vid: str) -> dict:
    """對單一videoId打一次唯讀captions().list(),回傳track_id/lastUpdated/error。"""
    try:
        lst = yt.captions().list(part="id,snippet", videoId=vid).execute()
        tracks = [it for it in lst.get("items", [])
                  if it["snippet"].get("trackKind") != "ASR"]
        if not tracks:
            return {"track_id": None, "lastUpdated": None, "error": None}
        t = tracks[0]
        return {
            "track_id": t.get("id"),
            "lastUpdated": t["snippet"].get("lastUpdated"),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"track_id": None, "lastUpdated": None, "error": str(exc)[:200]}


def cmd_snapshot(args) -> int:
    import daily_publish as dp

    ids = _load_ids(args.ids_file)
    yt = dp.get_service()
    videos = {}
    for i, vid in enumerate(ids, 1):
        videos[vid] = _snapshot_one(yt, vid)
        print(f"  [{i}/{len(ids)}] {vid}: {videos[vid]}")
    out = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "videos": videos,
    }
    out_path = Path(args.out)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    written = json.loads(tmp.read_text(encoding="utf-8"))
    assert written == out, "讀回比對失敗,不覆蓋既有檔"
    tmp.replace(out_path)
    print(f"[snapshot] 已寫入 {out_path}({len(ids)} 支)")
    return 0


def _parse_ts(s):
    """解析ISO時戳。Python 3.9的fromisoformat只接受0/3/6位小數秒,但Google
    Captions API偶爾會回傳尾端0被省略的小數秒(如5位)——先正規化成6位再parse,
    不改動小數秒本身代表的時間值(只是把被省略的尾端0補回去/多餘位數截斷)。"""
    if not s or not isinstance(s, str):
        return None
    try:
        normalized = re.sub(
            r"\.(\d+)",
            lambda m: "." + (m.group(1) + "000000")[:6],
            s,
            count=1,
        )
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _verdict_one(pre: dict, post: dict) -> str:
    """陽性判斷:任一邊API本身失敗一律「無法判斷」,不做任何比較。"""
    if pre.get("error") or post.get("error"):
        return "無法判斷(API呼叫失敗)"

    pre_track = pre.get("track_id")
    post_track = post.get("track_id")

    if pre_track is None:
        # insert情境:pre沒有非ASR軌,post出現才算已生效
        return "已生效" if post_track is not None else "未生效"

    # update情境:pre已有非ASR軌
    if post_track is None:
        return "無法判斷(track消失異常)"

    pre_ts = _parse_ts(pre.get("lastUpdated"))
    post_ts = _parse_ts(post.get("lastUpdated"))
    if pre_ts is None or post_ts is None:
        return "無法判斷(lastUpdated缺欄位或無法解析)"

    return "已生效" if post_ts > pre_ts else "未生效"


def cmd_compare(args) -> int:
    pre = json.loads(Path(args.pre).read_text(encoding="utf-8"))
    post = json.loads(Path(args.post).read_text(encoding="utf-8"))
    pre_v, post_v = pre["videos"], post["videos"]

    ids = sorted(set(pre_v) | set(post_v))
    results = {}
    counts = {}
    for vid in ids:
        p = pre_v.get(vid, {"track_id": None, "lastUpdated": None, "error": "缺pre快照"})
        q = post_v.get(vid, {"track_id": None, "lastUpdated": None, "error": "缺post快照"})
        v = _verdict_one(p, q)
        results[vid] = {"verdict": v, "pre": p, "post": q}
        counts[v] = counts.get(v, 0) + 1
        print(f"  {vid}: {v}")

    out = {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "pre_captured_at": pre.get("captured_at"),
        "post_captured_at": post.get("captured_at"),
        "counts": counts,
        "results": results,
    }
    out_path = Path(args.out)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    written = json.loads(tmp.read_text(encoding="utf-8"))
    assert written == out, "讀回比對失敗,不覆蓋既有檔"
    tmp.replace(out_path)
    print(f"[compare] {counts}")
    print(f"[compare] 已寫入 {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_snap = sub.add_parser("snapshot", help="對一批videoId各打一次唯讀captions().list(),存快照")
    sp_snap.add_argument("--ids-file", required=True, help="JSON陣列或{'videoIds':[...]}物件的檔路徑")
    sp_snap.add_argument("--out", required=True, help="快照輸出路徑")
    sp_snap.set_defaults(func=cmd_snapshot)

    sp_cmp = sub.add_parser("compare", help="比對兩份快照,陽性判斷邏輯")
    sp_cmp.add_argument("--pre", required=True)
    sp_cmp.add_argument("--post", required=True)
    sp_cmp.add_argument("--out", required=True)
    sp_cmp.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
