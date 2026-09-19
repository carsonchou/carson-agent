#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sponsor_trigger.py — pre-YPP 贊助觸發器(D3)。

誠實前提:37 訂閱時贊助商不會付大錢,所以不在沒觸及時亂寄。用 northstar.json 的觸及數字
監控,達門檻才 ntfy 提醒 Carson「可以開始洽談贊助了」,並備妥(不自動寄,寄走 sponsor_outreach
既有 dry-run→獨立驗證→--send 流程)。

門檻(任一達成即觸發):近28天觀看 >= 30000 或 新增訂閱(28天)>= 200 或 已知有單片破 5000。
用法:python scripts/sponsor_trigger.py [--notify]
"""
from __future__ import annotations
import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
import studio_common as sc

VIEWS28_GATE = 30000
SUBS28_GATE = 200
TOPVIDEO_GATE = 5000


def _max_video_views():
    best = 0
    for f in glob.glob(str(STUDIO / "analytics_cache" / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, dict) and isinstance(v.get("views"), (int, float)):
                    best = max(best, v["views"])
    return best


def main() -> int:
    ns = sc.load_json_safe(STUDIO / "northstar.json", {}) or {}
    reach = ns.get("reach") or {}
    views28 = reach.get("views28") or 0
    subs28 = reach.get("subs28") or 0
    topv = _max_video_views()

    hit = []
    if views28 >= VIEWS28_GATE:
        hit.append(f"近28天觀看 {views28} ≥ {VIEWS28_GATE}")
    if subs28 >= SUBS28_GATE:
        hit.append(f"28天新增訂閱 {subs28} ≥ {SUBS28_GATE}")
    if topv >= TOPVIDEO_GATE:
        hit.append(f"單片最高觀看 {topv} ≥ {TOPVIDEO_GATE}")

    if hit:
        msg = ("🎯 達贊助洽談門檻!" + "、".join(hit)
               + "\n可以開始接贊助了:①跑 sponsor_outreach.py --dry-run 看信 ②獨立驗證 ③--send。"
               + "先跑 gen_media_kit.py 產最新媒體包。")
        print(msg)
        if "--notify" in sys.argv:
            try:
                import notify
                notify.push("量化阿森｜可以接贊助了", msg, tag="moneybag")
            except Exception as e:  # noqa: BLE001
                print(f"[warn] ntfy 失敗:{e}", file=sys.stderr)
    else:
        print(f"[sponsor] 未達門檻(觀看28天 {views28}/{VIEWS28_GATE}、訂閱 {subs28}/{SUBS28_GATE}、"
              f"單片最高 {topv}/{TOPVIDEO_GATE})。觸及夠了才接贊助,現在先衝流量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
