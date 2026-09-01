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
#: 長片不只 eps_rechecked/ —— 舊的 FReD/famous 那批在 eps/ 與 eps_famous/,
#: 而排程發的是 publish_meta.json 裡的全部。閘門蓋得到的目錄,標記工具就
#: 要蓋得到,否則會變成「擋得住但解不開」。
EPS_DIRS = [ROOT / d for d in
            ("eps_rechecked", "eps", "eps_famous", "eps_lineup",
             "eps_domain", "compilations")]


def _mp4(d, long_form=False):
    if not long_form:
        return d / f"{d.name}_reel.mp4"
    cand = d / f"{d.name}.mp4"
    if cand.exists():
        return cand
    # 合輯那批的檔名不是 <dir>.mp4
    got = sorted(d.glob("*.mp4"))
    return got[0] if got else cand


def _find(slug):
    """在所有長片目錄裡找這個 slug —— 找不到或撞名都中止,不猜。"""
    hits = [d / slug for d in EPS_DIRS if (d / slug).is_dir()]
    if not hits:
        raise SystemExit(f"⛔ 找不到長片目錄 {slug}(找過 "
                         f"{', '.join(d.name for d in EPS_DIRS)})")
    if len(hits) > 1:
        raise SystemExit(f"⛔ {slug} 在多個目錄裡都有:"
                         f"{[str(h) for h in hits]} —— 指明哪一個,不要用猜的")
    return hits[0]


def state(d, long_form=False):
    mp4 = _mp4(d, long_form)
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
    # 🔴 長片那條路一開始沒有閘門 —— 而排程發長片走的正是那一條。
    ap.add_argument("--long", action="store_true",
                    help="標的是 eps_rechecked/ 的長片,不是 reels/ 的短片")
    a = ap.parse_args()

    if a.show or not a.slugs:
        print("— 短片 —")
        for d in sorted(REELS.iterdir()) if REELS.exists() else []:
            if d.is_dir():
                print(f"  {d.name:<24}{state(d, False)}")
        for root in EPS_DIRS:
            if not root.exists():
                continue
            print(f"— 長片 {root.name} —")
            for d in sorted(root.iterdir()):
                if d.is_dir():
                    print(f"  {d.name:<24}{state(d, True)}")
        return 0

    for slug in a.slugs:
        d = _find(slug) if a.long else (REELS / slug)
        mp4 = _mp4(d, a.long)
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
