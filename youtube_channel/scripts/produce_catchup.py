#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""補跑今天沒產滿的長片額度。

## 為什麼(2026-08-31 實帳)

清晨網路層斷線,所有 LLM 供應商連不上:

    [08-31 05:37] 決策部門｜⚠️ 所有 LLM 供應商都失敗:gemini: HTTPSConnectionPool(...)
    [08-31 05:47] 寄生標題｜⚠️ 所有 LLM 供應商都失敗:groq: HTTPSConnectionPool(...)
    [08-31 06:07] 補產部門｜⚠️ long 連續失敗,跳過      ← 主力產線整批放棄

主力的 `06:07 --long 8` 一支都沒產就跳過,而且**沒有任何重試**。當天排程只從
12:30 那輪拿到 2 支,對上 8 支/天的發布 = 淨流失。到 09:00 網路早就好了。

現有的 stall_watchdog 補不到這個洞:它看的是「最後一次有動」的時戳,
門檻是**好幾天**;單一批次掛掉、隔天又正常,它從頭到尾不會叫。

## 為什麼不能只是再排一次 --long 8

produce_batch 的 `--long N` 是「這輪產 N 支」,不是「補到 N 支」。
好日子再跑一次就變成雙倍產量 —— 白燒題目(每支抽中即標 used)和 LLM 錢。

所以這支先**數今天實際成稿幾支**,只補差額;夠了就安靜結束。

## 兩道保險

·**不重複跑**:偵測到已經有 produce_batch 在跑就直接結束(06:07 那輪可能跑好幾小時,
  memory 記過「9.5 小時只生出 5 支」),否則兩個實例會互搶題目。
·**只補差額**:差額 <=0 就不呼叫,零成本。

用法:`python scripts/produce_catchup.py [--target 8] [--dry]`
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS = ROOT / "STUDIO" / "ops_log.txt"


def produced_today(day: str) -> int:
    """今天成稿的長片數。數 ops_log 的「已備妥待渲染」行 —— 那是產線自己寫的完成訊號,
    比數 output/*.voice.txt 的 mtime 可靠(那些檔會被後續工序改寫,實測 08-30 會多報四倍)。"""
    if not OPS.exists():
        return 0
    n = 0
    pat = re.compile(r"^\[" + re.escape(day) + r" ")
    for ln in OPS.read_text(encoding="utf-8", errors="replace").splitlines():
        if pat.match(ln) and "已備妥待渲染" in ln and "：L_" in ln:
            n += 1
    return n


def _python_cmdlines() -> str:
    """所有 python 程序的**完整命令列**。

    要命令列不要映像檔名:tasklist 只給得到 python.exe,而本機同時跑著十幾支 python
    (local_cron / brain_alpha_cron / launcher+worker 配對…),分不出是哪一支。

    WMIC 先試、PowerShell 備援:WMIC 是**已棄用元件**,微軟正在從 Windows 移除。
    只留 WMIC 的話,它哪天消失 → except 吞掉 → 這道保險靜默失效而沒人知道
    (正是本專案一再踩到的「靜默失敗」形狀)。"""
    for cmd in (
        ["wmic", "process", "where", "name like '%python%'", "get", "commandline"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\""
         " | Select-Object -ExpandProperty CommandLine"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and len(r.stdout) > 40:
                return r.stdout
        except Exception:
            continue
    return ""


def already_running(needle: str = "produce_batch.py") -> bool:
    """已經有 produce_batch 在跑?兩個實例會互搶題目(每支抽中當下就標 used)。

    查不到程序清單時回 False(fail-open):漏跑一批的代價 > 偶爾撞車的代價,
    而撞車本身還有 produce_batch 自己的庫存上限擋著。"""
    return needle in _python_cmdlines()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=8, help="今天該有幾支長片成稿")
    ap.add_argument("--dry", action="store_true", help="只算不跑")
    args = ap.parse_args()

    day = dt.datetime.now().strftime("%m-%d")
    done = produced_today(day)
    gap = args.target - done
    print(f"[catchup] {day} 今日成稿長片 {done} / 目標 {args.target} → 差額 {gap}")

    if gap <= 0:
        print("[catchup] 已達標,不補跑。")
        return 0
    if already_running():
        print("[catchup] produce_batch 正在跑,跳過(避免兩個實例互搶題目)。")
        return 0
    if args.dry:
        print(f"[catchup] --dry:本來會跑 produce_batch --long {gap}")
        return 0

    py = ROOT / ".venv" / "Scripts" / "python.exe"
    cmd = [str(py if py.exists() else sys.executable),
           str(ROOT / "scripts" / "produce_batch.py"),
           "--manual", "--format-focus", "--shorts", "0",
           "--long", str(gap), "--target", "150", "--no-render"]
    print("[catchup] 補跑:" + " ".join(cmd[1:]))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
