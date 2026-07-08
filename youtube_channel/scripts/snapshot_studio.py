#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_studio.py — 每天把關鍵 STUDIO json 複製一份存檔，補本機沒有 backups 的安全網。

只複製「壞了會很痛」的關鍵檔到 STUDIO/_snapshots/YYYY-MM-DD/，保留最近 7 天、舊的自動刪。
純標準庫、防缺檔(缺哪個就跳過那個，不中斷)。

用法：python scripts/snapshot_studio.py
"""
from __future__ import annotations
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
SNAP_ROOT = STUDIO / "_snapshots"
TW = timezone(timedelta(hours=8))
KEEP_DAYS = 7

# 關鍵檔：STUDIO 內的用檔名，ROOT 內的用相對路徑
KEY_FILES = [
    STUDIO / "uploaded_ledger.json",
    STUDIO / "boss_directives.json",
    STUDIO / "quality_scores.json",
    STUDIO / "topic_bank.json",
    STUDIO / "ep_data.json",
    ROOT / "token_manage.json",
    ROOT / "token_analytics.json",
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _today() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def snapshot_once() -> int:
    dest = SNAP_ROOT / _today()
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in KEY_FILES:
        try:
            if f.exists():
                shutil.copy2(f, dest / f.name)
                copied += 1
            else:
                print(f"[skip] 不存在，略過：{f.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 複製失敗 {f.name}: {e}", file=sys.stderr)
    print(f"[ok] 快照完成：{dest}（{copied}/{len(KEY_FILES)} 個檔）")
    return copied


def prune_old() -> int:
    """保留最近 KEEP_DAYS 天的快照資料夾，舊的刪掉。"""
    if not SNAP_ROOT.exists():
        return 0
    days = sorted([d for d in SNAP_ROOT.iterdir() if d.is_dir()], key=lambda d: d.name)
    removed = 0
    for d in days[:-KEEP_DAYS] if len(days) > KEEP_DAYS else []:
        try:
            shutil.rmtree(d)
            removed += 1
            print(f"[ok] 刪除過期快照：{d.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 刪除失敗 {d.name}: {e}", file=sys.stderr)
    return removed


def main() -> int:
    copied = snapshot_once()
    pruned = prune_old()
    log_ops("STUDIO快照", f"快照 {copied} 個檔，清掉 {pruned} 個過期資料夾")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
