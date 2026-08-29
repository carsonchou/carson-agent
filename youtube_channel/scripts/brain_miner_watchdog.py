#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_miner_watchdog.py — 挖礦程序沒在跑就重新拉起來。

## 為什麼（2026-08-28）
事故：二階那批跑完就結束，而 cron 每 2 小時才接手 —— 中間有最長 2 小時的**空窗**，
而且**我不會知道**（背景程序安靜地死掉不會有任何訊號）。
Carson 問「趕快挖啊」時抓到的就是這個空窗。

排程每 20 分鐘檢查一次：沒有挖礦程序 → 立刻拉起來。
比起把 cron 頻率調高，這樣更省（有在跑就什麼都不做）也更準（真的死了才補）。

## 判準
用 WMIC 查 command line 含 `field_miner` / `second_order` / `brain_auto` 的 python 程序。
`tasklist` 看不到參數，所以一定要用 WMIC/CIM —— 這是 memory `studio-black-window-popups-fix`
記過的同型坑（殺程序要查對名稱否則漏 pythonw）。

## 只補不搶
如果已經有在跑就直接結束，不會開第二個 —— 平台併發上限是 2 且是**帳號層級**，
開兩個程序只會互相 429 卡死（2026-08-27 實測過）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BRAIN = (Path(__file__).resolve().parent.parent.parent
         / "quant-service" / "brain_alpha")
# ⚠️ 新增挖礦階段時**這裡一定要跟著加**（2026-08-29 差點漏掉 universe_sweep）：
# 守門認不出來就會判定「沒在跑」→ 再拉一個起來 → 兩個程序互搶那 2 個併發槽。
# 同一份名單在 brain_auto._pid_alive_miner 也有一份（鎖的活性判斷用），要一起改。
PATTERN = ("field_miner", "second_order", "brain_auto", "universe_sweep")


def miner_running() -> bool:
    """WMIC 查 command line。tasklist 看不到參數，會誤判成沒在跑。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name like '%python%'", "get", "commandline"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception as e:  # noqa: BLE001
        print(f"[watchdog] 查程序失敗：{e}", file=sys.stderr)
        return True          # fail-safe：查不到就當作有在跑，不要盲目重啟
    return any(p in out for p in PATTERN)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if miner_running():
        print("[watchdog] 挖礦程序在跑，不動作。")
        return 0
    # 沿用 cron wrapper 的階段判斷（一階優先找獨立 base），不要自己另定一套
    wrapper = Path(__file__).resolve().parent / "brain_alpha_cron.py"
    print("[watchdog] 沒有挖礦程序 → 重新拉起")
    subprocess.Popen([sys.executable, str(wrapper), "--run", "400"],
                     cwd=str(BRAIN),
                     stdout=open(BRAIN / "watchdog_restart.log", "a", encoding="utf-8"),
                     stderr=subprocess.STDOUT)
    print("[watchdog] 已啟動")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
