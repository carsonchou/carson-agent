#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumb_backfill.py — 縮圖補掛引擎(治 quota 爆掉後「影片上了、縮圖沒上」的裸奔片)。

背景(2026-07-15 實查)
--------------------
YouTube Data API 每日 10,000 quota 在台灣時間 15:00 重置,但 crontab 把
playlist_engine/desc_backfill/zombie_sweep 排在 15:05-15:30,一重置就先燒掉大半;
之後三班 daily_publish(合計 30 支嘗試=48,000 quota)全在撞牆。結果:影片本體
(videos.insert)有些成功,但緊接著的 thumbnails.set 403 quotaExceeded——
logs/job_stderr.log 撈出 66 支已發布卻沒有自訂縮圖的片(縮圖=門面,直接吃 CTR)。

做法
----
1. 佇列 STUDIO/pending_thumbs.json:{"pending": {video_id: {"slug":..}}, "done": {..}}。
   - daily_publish.py 縮圖失敗時即時入列(見該檔 thumbnails().set 的 except)。
   - --scavenge:掃 logs/job_stderr.log 的「縮圖設定失敗」行回收歷史受害者(冪等)。
2. 逐支補掛 assets/thumbnails/{slug}.jpg → thumbnails.set(50 quota/支)。
   - 成功→移到 done;縮圖檔不存在→記 done(no-thumb) 不再重試;
   - 403 quotaExceeded→優雅停止,剩下的留在佇列下次接續(絕不空轉重試)。
3. 排程:每天 15:10(quota 重置後第一個 job,搶在其他維運前用少量新糧把門面補齊;
   --max 40 上限 2,000 quota,佇列清空後每天實際只花 0~數百)。

用法
----
    python scripts/thumb_backfill.py --scavenge          # 掃日誌入列+補掛
    python scripts/thumb_backfill.py                     # 只處理既有佇列
    python scripts/thumb_backfill.py --dry               # 只看不動
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from studio_common import save_json_atomic, load_json_safe  # noqa: E402

STATE = ROOT / "STUDIO" / "pending_thumbs.json"
THUMBS = ROOT / "assets" / "thumbnails"
STDERR_LOG = ROOT / "logs" / "job_stderr.log"

# 同一行同時有 slug 與 videoId,直接配對;slug 無空白所以 \S+ 安全
_WARN_RE = re.compile(r"縮圖設定失敗 (\S+): .*?videoId=([A-Za-z0-9_-]{6,})")


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def load_state() -> dict:
    st = load_json_safe(STATE, default={}) or {}
    st.setdefault("pending", {})
    st.setdefault("done", {})
    return st


def scavenge(st: dict) -> int:
    """掃 job_stderr.log 回收縮圖失敗的 (slug, video_id) 進佇列。冪等。"""
    if not STDERR_LOG.exists():
        return 0
    added = 0
    text = STDERR_LOG.read_text(encoding="utf-8", errors="replace")
    for m in _WARN_RE.finditer(text):
        slug, vid = m.group(1), m.group(2)
        if vid in st["done"] or vid in st["pending"]:
            continue
        st["pending"][vid] = {"slug": slug, "added": _now(), "src": "scavenge"}
        added += 1
    return added


def find_thumb(slug: str) -> Path | None:
    p = THUMBS / f"{slug}.jpg"
    if p.exists():
        return p
    # 保險:slug 若有出入,用前綴比對(取最長前綴命中)
    cands = [f for f in THUMBS.glob("*.jpg") if f.stem.startswith(slug[:20])]
    return cands[0] if len(cands) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scavenge", action="store_true", help="先掃日誌回收失敗案例入列")
    ap.add_argument("--max", type=int, default=40, help="本輪最多補掛幾支(40≈2000 quota)")
    ap.add_argument("--dry", action="store_true", help="只列出不動")
    args = ap.parse_args()

    st = load_state()
    if args.scavenge:
        n = scavenge(st)
        print(f"[scavenge] 新入列 {n} 支(佇列現有 {len(st['pending'])})")
        save_json_atomic(STATE, st)

    if not st["pending"]:
        print("佇列空,無事可做")
        return 0

    if args.dry:
        for vid, info in list(st["pending"].items())[: args.max]:
            t = find_thumb(info.get("slug", ""))
            print(f"[dry] {vid} {info.get('slug','?')[:40]} thumb={'OK' if t else '缺檔'}")
        return 0

    from googleapiclient.errors import HttpError  # noqa: E402
    from googleapiclient.http import MediaFileUpload  # noqa: E402
    from daily_publish import get_service  # noqa: E402  # 沿用同一組 token_manage.json

    yt = get_service()
    done_n = miss_n = 0
    for vid, info in list(st["pending"].items()):
        if done_n >= args.max:
            break
        slug = info.get("slug", "")
        thumb = find_thumb(slug)
        if thumb is None:
            st["done"][vid] = {"at": _now(), "result": "no-thumb", "slug": slug}
            st["pending"].pop(vid, None)
            miss_n += 1
            continue
        try:
            yt.thumbnails().set(
                videoId=vid,
                media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
            ).execute()
        except RuntimeError as exc:
            # 配額(含預留額度)是 RuntimeError,原本只 catch HttpError 會整支噴掉;
            # 而狀態檔是在迴圈**外**才寫,崩掉等於賠掉本輪已完成的紀錄(下輪重做、白燒配額)。
            if "quota" in str(exc).lower():
                print(f"[quota] 停止本輪,先落地已完成的部分(冪等):{str(exc)[:70]}")
                break
            raise
        except HttpError as exc:
            msg = str(exc)
            if "quota" in msg.lower():
                print(f"[stop] quotaExceeded,已補 {done_n} 支,剩 {len(st['pending'])} 支下次接續")
                break
            # 非 quota 錯(如影片被刪/private 轉刪):記 done 不再重試,避免佇列卡死
            st["done"][vid] = {"at": _now(), "result": f"error:{msg[:80]}", "slug": slug}
            st["pending"].pop(vid, None)
            print(f"[skip] {vid}: {msg[:100]}", file=sys.stderr)
            continue
        st["done"][vid] = {"at": _now(), "result": "ok", "slug": slug}
        st["pending"].pop(vid, None)
        done_n += 1
        print(f"[ok] {vid} {slug[:40]}")
    save_json_atomic(STATE, st)
    print(f"完成:補掛 {done_n} 支、缺檔跳過 {miss_n} 支、佇列剩 {len(st['pending'])} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
