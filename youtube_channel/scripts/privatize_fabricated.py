#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""privatize_fabricated.py — 把含編造統計的已發布影片設為不公開(可逆)。

## ⚠️ 這支預設不跑,等 Carson 拍板
下架已發布內容是**新類型的正式機變更**(CLAUDE.md 紅線),不在常駐授權範圍。
本支只準備好「一句話就能執行」,不自行執行。決策依據見
STUDIO/REPORTS/2026-08-17_編造統計盤點.md。

## 為什麼是 private 不是 delete
private 可隨時改回 public,videoId／觀看數／搜尋排名全部保留;delete 不可逆。
先止血,之後若決定重製旁白再逐支放回。

## 範圍
STUDIO/_fabricated_stats_published.json —— 由 audit_video.find_fabricated_stats
掃描 uploaded_ledger 全部已發布片產出。判準:事實庫 3,887 組事實裡機率/勝率/
夏普/散戶行為 0 組,故這些數字產線算不出來,必然是 LLM 編的。

## 安全
- 只改 status.privacyStatus,其他欄位原樣送回(videos.update 是整包覆蓋)。
- 原 status 備份到 STUDIO/privatize_backup/<vid>.json,可一鍵還原(--restore)。
- --tier 選處置範圍:all / high(近期有流量的) / worst(假借權威+編造行為統計)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
SRC = STUDIO / "_fabricated_stats_published.json"
BK = STUDIO / "privatize_backup"

# 最嚴重:假借權威(宣稱有研究/量化資料支持)或編造投資人行為——這兩類是無中生有,
# 而不是「引用了一個我們沒算過的指標」。
WORST = ("量化資料顯示", "研究顯示", "統計顯示", "學術研究", "散戶", "機率")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true", help="從備份還原成 public")
    ap.add_argument("--tier", choices=["all", "high", "worst"], default="worst")
    ap.add_argument("--max", type=int, default=30)
    args = ap.parse_args()

    import daily_publish as dp
    yt = dp.get_service()

    if args.restore:
        n = 0
        for p in sorted(BK.glob("*.json")):
            st = json.loads(p.read_text(encoding="utf-8"))
            if not args.apply:
                print(f"[dry] 還原 {p.stem} → {st.get('privacyStatus')}")
                n += 1
                continue
            yt.videos().update(part="status", body={"id": p.stem, "status": st}).execute()
            p.unlink()
            n += 1
            print(f"[ok] 還原 {p.stem}")
        print(f"{'已' if args.apply else '將'}還原 {n} 支")
        return 0

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    if args.tier == "worst":
        rows = [r for r in rows if any(w in "".join(r[2]) for w in WORST)]
    elif args.tier == "high":
        try:
            import yt_analytics as ya
            from datetime import date, timedelta
            svc = ya._service()
            rr = svc.reports().query(
                ids="channel==MINE", startDate=(date.today() - timedelta(days=30)).isoformat(),
                endDate=date.today().isoformat(), dimensions="video", metrics="views",
                sort="-views", maxResults=200).execute()
            vm = {x[0]: x[1] for x in (rr.get("rows") or [])}
            rows = [r for r in rows if vm.get(r[1], 0) > 0]
        except Exception:  # noqa: BLE001
            pass
    print(f"tier={args.tier} → {len(rows)} 支")

    BK.mkdir(exist_ok=True)
    n = 0
    for slug, vid, hits in rows[:args.max]:
        print(f"  [{'設私密' if args.apply else 'dry'}] {slug[:44]}  {hits[:3]}")
        if not args.apply:
            n += 1
            continue
        try:
            r = yt.videos().list(part="status", id=vid).execute()
            items = r.get("items") or []
            if not items:
                continue
            st = items[0]["status"]
            (BK / f"{vid}.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            new = dict(st)
            new["privacyStatus"] = "private"
            yt.videos().update(part="status", body={"id": vid, "status": new}).execute()
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"     [warn] {str(exc)[:110]}", file=sys.stderr)
    print(f"\n{'已設私密' if args.apply else '將設私密'} {n} 支"
          f"{'(可用 --restore --apply 還原)' if args.apply else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
