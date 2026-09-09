#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_drill_regression.py — 定期證明三支哨的留痕**還抓得到已知案例**。

## 為什麼存在(2026-09-09,承 docs/ops/2026-09-09_verify_bb7ea299.md §四)

三支哨在 `c09a2486` / `bb7ea299` 之後有了 `--selftest` 演習,而且演習與正式**共用同一個
函式**(`_push_and_trace`,不是複本)—— 但獨立驗證掃過 9 支 pythonw 排程、`crontab.txt`
與全 repo:**沒有任何東西會定期去按它**。

⇒ 引信是手動的,而手動引信等於沒有引信:memory `gate-blind-while-target-evolves`
「閘門上線後要有東西**定期證明它還抓得到已知案例**」。
那條 memory 的另一半同樣重要:**陽性對照要用真案例,不要用合成 fixture** ——
所以這支不自己造假資料,它就是去按那三支哨自己的演習模式。

## 判準:每一種演習都要有**期望**,而且期望要包含陰性
- 推播失敗類(`pushfail` / `pushraise`)⇒ log 必須同時長出「吞掉但留痕」**與**「本輪收尾」
- state 形狀類(quota 專有)⇒ 判決行必須是預期那一種
- **陰性對照**(`zero` / `summary` / `up`)⇒ **不可以**出現留痕行
  沒有陰性,「該叫的都叫了」和「這條檢查恆叫」分不開。

## 輸出
正向輸出:**每次跑都寫一行** `docs/ops/watch-drill-regression.log`,全過也寫
—— 「沒有輸出」因此永遠是異常(和三支哨自己同一個設計)。
exit code:0 = 全過;1 = 有演習沒達到期望(這代表**留痕壞了**,不是產線壞了)。

## 用法
    python scripts\\watch_drill_regression.py          # 跑全部
    python scripts\\watch_drill_regression.py --list   # 只列出會跑什麼,不執行

⚠️ 這支**不碰正式資料**:三支哨的 `--selftest` 各自用自己的沙箱/selftest state 檔,
且演習路徑上真的 `notify.push` 根本沒有被 import。本檔只讀它們的 log 尾巴。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "docs" / "ops" / "watch-drill-regression.log"

SEEDING = REPO / "scripts" / "seeding_watch.py"
NARRATION = REPO / "scripts" / "narration_compliance_watch.py"
QUOTA = REPO / "scripts" / "quota_ceiling_watch.py"

WATCH_LOGS = {
    SEEDING: REPO / "docs" / "ops" / "seeding-watch.log",
    NARRATION: REPO / "docs" / "ops" / "narration-compliance-watch.log",
    QUOTA: REPO / "docs" / "ops" / "quota-ceiling-watch.log",
}

# (腳本, 演習模式, 期望)。期望是一組 (必須出現的片語, 必須不出現的片語)。
TRACE = "吞掉但留痕"
EPILOGUE = "本輪收尾"
CASES = [
    # ── 陽性:推播兩條失敗路徑,留痕必須出現 ──────────────────────────
    (SEEDING,   "pushfail",  [TRACE, EPILOGUE], []),
    (SEEDING,   "pushraise", [TRACE, EPILOGUE], []),
    (NARRATION, "pushfail",  [TRACE, EPILOGUE], []),
    (NARRATION, "pushraise", [TRACE, EPILOGUE], []),
    (QUOTA,     "pushfail",  [TRACE, EPILOGUE], []),
    (QUOTA,     "pushraise", [TRACE, EPILOGUE], []),
    # ── 陽性:quota 的 state 形狀(輸入是真檔案,不是注入的變數)────────
    (QUOTA,     "keyless",   ["基準被迫重建"], []),
    (QUOTA,     "nullval",   ["基準被迫重建"], []),
    (QUOTA,     "broken",    ["基準被迫重建", TRACE], []),
    # ── 🔴 陰性對照:該安靜的時候必須安靜 ─────────────────────────────
    (QUOTA,     "first",     ["基準建立"], [TRACE, EPILOGUE]),
    (SEEDING,   "zero",      [], [TRACE, EPILOGUE]),
    (NARRATION, "summary",   [], [TRACE, EPILOGUE]),
]


def say(text: str) -> None:
    """pythonw 下 stdout 是 None,print 是靜默 no-op —— 所以 log 才是主通道。"""
    try:
        print(text)
    except Exception:  # noqa: BLE001
        pass


def record(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    say(line)


def run_case(script: Path, mode: str, must: list[str], must_not: list[str]) -> tuple[bool, str]:
    wlog = WATCH_LOGS[script]
    before = wlog.stat().st_size if wlog.exists() else 0
    try:
        subprocess.run([sys.executable, str(script), f"--selftest={mode}"],
                       cwd=str(REPO), capture_output=True, timeout=300)
    except Exception as e:  # noqa: BLE001
        return False, f"執行丟例外:{type(e).__name__}: {e}"
    # 只看這一輪新增的那幾行(不要把上一輪的留痕算進來)
    try:
        with wlog.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(before)
            fresh = f.read()
    except Exception as e:  # noqa: BLE001
        return False, f"讀不到 {wlog.name}:{type(e).__name__}: {e}"
    if not fresh.strip():
        return False, "這一輪 log 零新增 —— 演習根本沒寫東西(哨可能整支壞了)"
    missing = [p for p in must if p not in fresh]
    leaked = [p for p in must_not if p in fresh]
    if missing:
        return False, "缺少期望片語:" + "/".join(missing)
    if leaked:
        return False, "🔴 陰性對照被污染,不該出現卻出現了:" + "/".join(leaked)
    return True, "ok"


def main() -> int:
    now = f"{datetime.now():%Y-%m-%d %H:%M}"
    if "--list" in sys.argv:
        for s, m, must, must_not in CASES:
            say(f"{s.name} --selftest={m}  期望有={must} 期望無={must_not}")
        return 0

    fails = []
    for script, mode, must, must_not in CASES:
        ok, why = run_case(script, mode, must, must_not)
        if not ok:
            fails.append(f"{script.name}:{mode}({why})")

    n = len(CASES)
    if fails:
        record(f"[{now}] 🔴 哨留痕回歸 {n - len(fails)}/{n} 通過 —— **留痕壞了**(不是產線壞了):"
               + "；".join(fails)
               + "。修法見 docs/ops/2026-09-09_pythonw_stdio_correction.md §3.1。")
        return 1
    record(f"[{now}] ✅ 哨留痕回歸 {n}/{n} 通過"
           f"(陽性 9:兩條推播失敗路徑 × 3 支 + quota 三種 state 形狀;"
           f"陰性 3:first/zero/summary 必須安靜)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
