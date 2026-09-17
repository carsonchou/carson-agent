#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_ch3_nonauth_deadline.py — ch3_remeasure_2026-09-12 非授權原始快照到期告警。

背景:D:\\yt_nonauth_data\\ch3_remeasure_2026-09-12\\ 的 r1/r2/r3 raw json + run_r*.log
依 YouTube API Services ToS III.E.4.d(他人公開資料保存上限30天)必須在 2026-10-12 前刪除,
但 ch3 副線(wA:p2)已於 2026-09-16 結案關閉,原本盯著這個期限的 pane 不會再存在,
之前只靠一份跨 session memory 檔提醒(memory ch3-nonauth-data-deletion-deadline-2026-10-12)。
這支只告警、不刪除——刪除是不可逆操作,留給人工/督導當下確認再動手。
排程:每天(deploy/crontab.txt),到期前7天(2026-10-05)起才開始檢查,之前靜默 no-op。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

DEADLINE = date(2026, 10, 12)
WARN_FROM = DEADLINE - timedelta(days=7)  # 2026-10-05
DATA_DIR = Path(r"D:\yt_nonauth_data\ch3_remeasure_2026-09-12")
FILES = [
    "r1_20260911T1830Z.json", "r2_20260914T0111Z.json", "r3_20260915T0734Z.json",
    "run_r1.log", "run_r2.log", "run_r3.log",
]


def remaining(files: list[str], data_dir: Path | None = None) -> list[str]:
    data_dir = data_dir if data_dir is not None else DATA_DIR
    return [f for f in files if (data_dir / f).exists()]


def _selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "a.json").write_text("x", encoding="utf-8")
        assert remaining(["a.json", "b.json"], d) == ["a.json"]
        assert remaining([], d) == []
        assert remaining(["a.json"], d / "nope") == []
    print("[ch3_nonauth_deadline] selftest OK")


def main() -> int:
    if "--selftest" in sys.argv:
        _selftest()
        return 0

    today = date.today()
    if today < WARN_FROM:
        print(f"[ch3_nonauth_deadline] 未到告警窗({WARN_FROM} 起),略過。")
        return 0

    left = remaining(FILES)
    if not left:
        print("[ch3_nonauth_deadline] 6 個非授權原始檔已不在,無需處理。")
        return 0

    days_left = (DEADLINE - today).days
    msg = (
        f"🚨 距刪除期限({DEADLINE})剩 {days_left} 天,{DATA_DIR} 仍有 {len(left)} 個非授權原始檔未刪:"
        f"{', '.join(left)}。依README表格只刪json/log,ledger與README留著;"
        f"刪除是不可逆操作,不自動刪,人工/督導確認後手動處理。"
    )
    log_ops("ch3非授權資料到期守衛", msg)
    try:
        print(f"[ch3_nonauth_deadline][ALERT] {msg}")
    except UnicodeEncodeError:
        print("[ch3_nonauth_deadline][ALERT] console encoding cannot print this message; see ops_log.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
