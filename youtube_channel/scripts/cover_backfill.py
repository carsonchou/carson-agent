#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cover_backfill.py — 把『已發布的舊片』縮圖批次換成 make_cover 高質感封面。

來源＝STUDIO/uploaded_ledger.json（slug→videoId）。每支：make_cover 生封面 → thumbnails().set。
YouTube thumbnails().set 約 50 配額/支，每日上限 10000，故每輪有 --max（預設 40）。
防重：做過的記到 STUDIO/cover_redone_ledger.json，排程每天補一批直到清空。

用法：python scripts/cover_backfill.py [--max 40] [--dry-run]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
DONE = STUDIO / "cover_redone_ledger.json"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _title(slug):
    md = OUT / f"{slug}.md"
    if md.exists():
        try:
            return md.read_text(encoding="utf-8").splitlines()[0].replace("#", "").replace("🎬", "").strip()
        except Exception:
            pass
    return slug


def pending():
    led = _load(LEDGER)
    done = _load(DONE)
    out = []
    for slug, vid in led.items():
        if slug in done:
            continue
        if not (slug.startswith("S_") or slug.startswith("L_")):
            continue
        if not (OUT / f"{slug}.voice.txt").exists() and not (OUT / f"{slug}.md").exists():
            continue  # 沒素材生不出對主題的封面
        out.append((slug, vid))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    todo = pending()
    print(f"[info] 待重生封面：{len(todo)} 支，本輪上限 {a.max}")
    if a.dry_run:
        for s, _ in todo[:a.max]:
            print("  -", s[:40])
        return 0
    if not todo:
        print("[ok] 沒有待重生的，全部跟上。")
        return 0
    import make_cover
    from googleapiclient.http import MediaFileUpload
    from decision_dept import yt_service
    yt = yt_service()
    done = _load(DONE)
    n = 0
    for slug, vid in todo[:a.max]:
        try:
            cov = make_cover.make_cover(slug, _title(slug))
            if not cov or not Path(cov).exists():
                print(f"[skip] {slug[:30]} 封面沒產出"); continue
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(cov), mimetype="image/jpeg")).execute()
            done[slug] = vid
            DONE.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
            print(f"[ok] ({n}) {slug[:30]} → 換新封面")
            time.sleep(3)  # 拉長間隔避免 Pollinations 429 限流
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {slug[:30]} 失敗：{str(e)[:80]}", file=sys.stderr)
    remain = len(pending())
    log_ops("封面重生", f"本輪換 {n} 支，剩 {remain} 支")
    print(f"\n[done] 本輪換新封面 {n} 支，剩 {remain} 支留下輪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
