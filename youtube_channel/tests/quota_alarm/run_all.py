#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""daily_health 配額告警的五輪回歸套件 —— 再動那段之前先跑這支。

用法(必須在 youtube_channel/ 底下跑,因為各支用相對路徑讀 STUDIO/):
    cd /d/carson-agent/youtube_channel
    .venv/Scripts/python.exe tests/quota_alarm/run_all.py

每一支都把 `quota_meter.STATE` 指到暫存假帳本,**不會碰到真帳本**。
背景與每個門檻的校準基礎見 docs/ops/2026-09-03_quota_alarm_closure.md。
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ["anomaly", "ledger_broken", "round3", "round4", "round5"]

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total_p = total_f = 0
    for s in SUITES:
        r = subprocess.run([sys.executable, "-X", "utf8", str(HERE / f"{s}.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout or ""
        p, f = out.count("PASS"), out.count("FAIL")
        total_p += p
        total_f += f
        print(f"  {s:<16} PASS={p:<4} FAIL={f}" + ("   ← 看 stdout" if f else ""))
        if f:
            for ln in out.splitlines():
                if "FAIL" in ln:
                    print("      " + ln.strip())
    print(f"\n合計 PASS={total_p}  FAIL={total_f}")
    print("另有 replay10.py:拿真帳本回放 10 天,預期紅字只有 08-27(單獨跑)")
    return 1 if total_f else 0

if __name__ == "__main__":
    raise SystemExit(main())
