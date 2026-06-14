#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops.py — 工廠統一日誌（所有部門共用）。寫 STUDIO/ops_log.txt 當單一心跳時間軸。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent / "STUDIO" / "ops_log.txt"


def log_ops(stage: str, msg: str) -> None:
    OPS.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S")
    line = f"[{ts}] {stage}｜{msg}"
    try:
        with OPS.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def tail(n: int = 40) -> str:
    if not OPS.exists():
        return "（尚無日誌，工廠首次運轉後出現）"
    try:
        lines = OPS.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""
