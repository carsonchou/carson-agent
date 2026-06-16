#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""remake_rejected.py — 把 output/_rejected/ 裡退件的片，去重後逐支重產同主題新片。

去重：近似標題（正規化後前 16 字相同）只重做一支，避免重產出當初被退的重複片。
重產走 produce_batch --topic（剛好 1 支、不發布）。可用 --since-min 只挑最近退的那批。
用法：
  python scripts/remake_rejected.py --since-min 720 --dry   # 預覽近12小時退件去重後要重做哪些
  python scripts/remake_rejected.py --since-min 720         # 實際重做
"""
from __future__ import annotations
import argparse, glob, os, re, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REJECT_DIR = ROOT / "output" / "_rejected"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass


def _norm(t):
    return re.sub(r"[\s，。！？、：；…·\-—()（）%]+", "", (t or "")).lower()


def _title_of(md):
    try:
        return open(md, encoding="utf-8").read().splitlines()[0].replace("# 🎬", "").replace("#", "").strip()
    except Exception:
        return Path(md).stem


def collect(since_min):
    now = time.time()
    seen, items = set(), []
    mds = sorted(glob.glob(str(REJECT_DIR / "*.md")), key=os.path.getmtime, reverse=True)
    for md in mds:
        if since_min and (now - os.path.getmtime(md)) / 60 > since_min:
            continue
        title = _title_of(md)
        key = _norm(title)[:16]
        if key in seen:
            continue  # 近似重複只取一支
        seen.add(key)
        items.append(title)
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-min", type=int, default=0, help="只挑最近 N 分鐘內退的（0=全部）")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not REJECT_DIR.exists():
        print("[info] 沒有 _rejected 資料夾（無退件）。"); return 0
    titles = collect(args.since_min)
    if not titles:
        print("[info] 範圍內無退件可重做。"); return 0

    print(f"== 去重後要重做 {len(titles)} 個主題 ==")
    for i, t in enumerate(titles, 1):
        print(f"  {i}. {t}")
    if args.dry:
        return 0

    py = sys.executable
    angle = "重做版：同主題換更強開場鉤子＋But/Therefore 結構，內容更紮實，守誠實鐵則"
    ok = 0
    for i, t in enumerate(titles, 1):
        print(f"\n[{i}/{len(titles)}] 重產：{t[:30]} …")
        try:
            r = subprocess.run([py, str(ROOT / "scripts" / "produce_batch.py"),
                                "--topic", t, "--angle", angle], cwd=str(ROOT), timeout=600)
            if r.returncode == 0:
                ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {t[:20]} 重產失敗：{str(e)[:80]}", file=sys.stderr)
    log_ops("退件重做", f"批次重做退件 {ok}/{len(titles)} 支")
    print(f"\n[ok] 批次重做完成：{ok}/{len(titles)} 支新片已產（未發布，進倉庫待評分）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
