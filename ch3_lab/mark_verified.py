#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mark_verified.py — 把一支短片標成「已通過獨立驗證」。

## 為什麼需要這支
2026-09-01 實測:我砍掉一批渲染,有幾支殘留程序在砍完之後才把 mp4 寫出來;
**08:25 的排程把其中一支發了出去** —— 那支早於當天的版面修正,帶著表格
破洞,而且從來沒有人驗過它。

我先前加的 `--only` 只保護**手動**執行(「驗過什麼就發什麼」),而排程走的
是另一條路。**「修在一條路上,而實際走的是另一條」在這條線上已經第 N 次。**

## 判準
標記裡記的是**驗證當下那個 mp4 的 mtime**。成片一旦重渲,mtime 就變,
標記自動失效 —— 所以不會出現「驗過舊版、發出新版」,也不會出現反過來。
這是刻意的:標記綁的是**那個檔案**,不是那個名字。

用法:
  python mark_verified.py dunning_kruger false_memory   # 標記
  python mark_verified.py --list                        # 看現況
  python mark_verified.py --clear dunning_kruger        # 撤銷
"""
import argparse
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REELS = ROOT / "reels"


def state(d):
    mp4 = d / f"{d.name}_reel.mp4"
    vf = d / "VERIFIED"
    if not mp4.exists():
        return "沒有成片"
    if not vf.exists():
        return "未驗證"
    try:
        stamp = float(vf.read_text(encoding="utf-8").split()[0])
    except Exception:                                        # noqa: BLE001
        return "標記壞了"
    if abs(mp4.stat().st_mtime - stamp) > 2:
        return "標記過期(成片重渲過)"
    return "已驗證 ✓"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--list", action="store_true", dest="show")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()

    if a.show or not a.slugs:
        for d in sorted(REELS.iterdir()) if REELS.exists() else []:
            if d.is_dir():
                print(f"  {d.name:<24}{state(d)}")
        return 0

    for slug in a.slugs:
        d = REELS / slug
        mp4 = d / f"{slug}_reel.mp4"
        if a.clear:
            (d / "VERIFIED").unlink(missing_ok=True)
            print(f"  {slug}:標記已撤銷")
            continue
        if not mp4.exists():
            print(f"  ⛔ {slug}:沒有成片,不標記")
            continue
        (d / "VERIFIED").write_text(
            f"{mp4.stat().st_mtime} verified_at="
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}", encoding="utf-8")
        print(f"  {slug}:已標記(綁 mtime "
              f"{time.strftime('%H:%M:%S', time.localtime(mp4.stat().st_mtime))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
