#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""daily_health 配額告警的五輪回歸套件 —— 再動那段之前先跑這支。

用法(在**任何**目錄下都可以跑,cwd 由本支自己設):
    youtube_channel/.venv/Scripts/python.exe youtube_channel/tests/quota_alarm/run_all.py

每一支都把 `quota_meter.STATE` 指到暫存假帳本,**不會碰到真帳本**。
背景與每個門檻的校準基礎見 docs/ops/2026-09-03_quota_alarm_closure.md。

🔴 2026-09-03:上一版把「必須在 youtube_channel/ 底下跑」寫進 docstring,
   而在別的目錄跑時五個子套件全部 ModuleNotFoundError 崩潰、stdout 為空,
   於是 PASS=0 FAIL=0、**exit 0 = 綠燈**。
   一套用來守「不會叫的警報」的回歸測試,自己就是一個不會叫的檢查
   (memory verification-that-cannot-fail 的第①種)。
   把陷阱寫進文件不是修好它 —— cwd 現在由程式自己設,另加兩道獨立的失敗判準:
   ① 子行程 returncode 非 0 → FAIL(附 stderr 尾巴)
   ② 實際 PASS 數少於該套件已知最小值 → FAIL(「零個測試通過」不是通過)
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]      # youtube_channel/ —— 子套件用相對路徑讀 STUDIO/,cwd 必須在這
# 每套件已知的 PASS 數;跑出來少於這個數 = 有測試沒被執行到,判 FAIL。
# 用「小於」而不是「等於」,是為了加測試時不必回來改這裡。
MIN_PASS = {"anomaly": 6, "ledger_broken": 7, "round3": 11, "round4": 15, "round5": 26, "disproven_wall": 6}
SUITES = list(MIN_PASS)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total_p = total_f = 0
    broken = []
    for s in SUITES:
        r = subprocess.run([sys.executable, "-X", "utf8", str(HERE / f"{s}.py")],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(BASE))
        out = r.stdout or ""
        p, f = out.count("PASS"), out.count("FAIL")
        total_p += p
        total_f += f
        note = ""
        if r.returncode != 0:
            broken.append((s, "returncode=%d" % r.returncode,
                           (r.stderr or "").strip().splitlines()[-3:]))
            note = "   🔴 子行程崩潰"
        elif p < MIN_PASS[s]:
            broken.append((s, "PASS=%d < 預期 %d" % (p, MIN_PASS[s]), []))
            note = "   🔴 只跑到 %d/%d" % (p, MIN_PASS[s])
        elif f:
            note = "   ← 看 stdout"
        print(f"  {s:<16} PASS={p:<4} FAIL={f}{note}")
        if f:
            for ln in out.splitlines():
                if "FAIL" in ln:
                    print("      " + ln.strip())
    print(f"\n合計 PASS={total_p}  FAIL={total_f}")
    if broken:
        print("\n🔴 套件本身壞掉(不是測試失敗,是測試沒跑成):")
        for _s, _why, _tail in broken:
            print("  %s: %s" % (_s, _why))
            for _ln in _tail:
                print("      " + _ln)
        print("  ⚠️ 這種狀態下「PASS=0 FAIL=0」不代表通過 —— 它代表什麼都沒驗。")
    print("另有 replay10.py:拿真帳本回放 10 天,預期紅字只有 08-27(單獨跑)")
    return 1 if (total_f or broken) else 0


if __name__ == "__main__":
    raise SystemExit(main())
