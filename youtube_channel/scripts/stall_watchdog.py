#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stall_watchdog.py — 管線停擺偵測守衛(治「壞了不吭聲」的系統性 meta-fix)。

背景:2026-07 一連串問題(TikTok cron 用錯 python 靜默跳過、IG tunnel 死掉、產線卡)的共同病根是
**靜默失敗**——cron 顯示「✓ 完成」卻沒真做事,ledger/output 悄悄停更好幾天才被發現。
這支守衛每天檢查各管道「最後一次真的有動」的時間,超過門檻=疑似停擺→ntfy 推 Carson,別再默默壞掉。

檢查(看『最後活動時戳』,非看 cron 有沒有跑——因為 cron 跑了不代表有做事):
  產片(output/*.voice.txt)、渲染(output/*.mp4)、YT發布(uploaded_ledger)、
  TikTok(tiktok_ledger)、IG(ig_ledger)。
排程:cron 每天一次(建議 10:00,各管道當天該動的都動完了)。手動:python scripts/stall_watchdog.py [--dry]
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

H = 3600
# (名稱, 判定用的最新時戳來源, 停擺門檻小時) — 門檻=正常間隔 + 緩衝
CHECKS = [
    ("產片(腳本)", "glob", "S_*.voice.txt", 20),
    ("渲染(成片)", "glob", "S_*.mp4", 22),
    ("YT 發布", "ledger", "uploaded_ledger.json", 30),
    ("TikTok 跨發", "ledger", "tiktok_ledger.json", 30),
    ("IG 跨發", "ledger", "ig_ledger.json", 40),
]


def _newest_glob(pattern: str) -> float:
    """output/ 下符合 pattern(排除 _ytcta 衍生)的最新 mtime;無檔回 0。"""
    latest = 0.0
    for p in OUT.glob(pattern):
        if p.name.endswith("_ytcta.voice.txt") or p.name.endswith("_ytcta.mp4"):
            continue
        try:
            latest = max(latest, p.stat().st_mtime)
        except Exception:  # noqa: BLE001
            pass
    return latest


def _ledger_mtime(fn: str) -> float:
    p = STUDIO / fn
    try:
        return p.stat().st_mtime if p.exists() else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def main() -> int:
    dry = "--dry" in sys.argv
    now = time.time()
    stalled = []
    lines = []
    for name, kind, arg, thr_h in CHECKS:
        ts = _newest_glob(arg) if kind == "glob" else _ledger_mtime(arg)
        age_h = (now - ts) / H if ts else 9999
        ok = age_h <= thr_h
        lines.append(f"  [{'ok ' if ok else 'STALL'}] {name}: 最後活動 {age_h:.1f}h 前(門檻{thr_h}h)")
        if not ok:
            stalled.append(f"{name}(停{age_h:.0f}h)")
    print("[stall_watchdog] 管線活動檢查:")
    print("\n".join(lines))

    if not stalled:
        log_ops("停擺守衛", "各管道正常,無停擺")
        print("[stall_watchdog] 全部正常")
        return 0

    msg = "⚠️ 管線疑似停擺:" + "、".join(stalled) + "。cron 可能『跑了✓完成卻沒真做事』(靜默失敗),去查對應 log/ledger。"
    print(f"[stall_watchdog][ALERT] {msg}")
    log_ops("停擺守衛", msg)
    if not dry:
        try:
            from notify import push
            push("量化阿森·停擺守衛", msg[:190], tag="rotating_light")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
