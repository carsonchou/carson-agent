#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_no_duplicate_rules.py — 「同一條規則只能有一份實作」變成**會產生輸出的檢查**。

## 為什麼(2026-09-08)
這條規則在這個 repo 裡寫在**註解**裡至少三處,而它今天被違反了四次:
`numerator()` 有四份(`pick_next` / `runway` / `hybrid_miner` / `universe_sweep`),
其中三份帶著舊正則。註解攔不住,因為**違反它時不會產生任何輸出**
(memory `verification-that-cannot-fail` 第零種)。

⚠️ 這支檢查**只擋得住未來長出第五份**,對「兩份行為不一致」無能為力 ——
名字相同只是最容易抓的那一種。真正的重複可以叫別的名字(2026-09-05 的
`submitted_ids` 事故就是兩份不同名的實作)。**不要把它當成收斂完成的證明。**

## 陽性對照用的是**真實歷史**,不是合成 fixture
`git show <收斂前的 commit>:<檔案>` 拿出當時真的有四份的那個狀態,
斷言這支檢查**會叫**。合成 fixture 只能證明「它對我編的東西會叫」。

    python test_no_duplicate_rules.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent

# 規則名 → 應該只出現在哪個檔(定義處)。掃的是 `def <name>(`。
RULES = {
    "numerator": "brain_auto.py",
    "family_key": "brain_auto.py",
    "build_pool": "pick_next.py",
    "dedup_by_numerator": "pick_next.py",
    "spread_by_family": "pick_next.py",
    "fetch_platform": "reconcile.py",
    "load_snapshot": "reconcile.py",
}
# 掃描範圍:BRAIN 這條線的產線檔。備份檔(.bak-*)與測試不算。
SCAN_DIRS = [ROOT, REPO / "youtube_channel" / "scripts"]

FAILS: list[str] = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def _py_files(dirs):
    out = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.py")):
            if ".bak" in f.name or f.name.startswith("test_"):
                continue
            out.append(f)
    return out


def find_defs(texts: dict[str, str]) -> dict[str, list[str]]:
    """`{規則名: [檔名, …]}`。`texts` 是 {檔名: 原始碼},這樣同一套判定
    可以套在**工作樹**和**歷史版本**上 —— 陽性對照才用得到同一份程式碼。"""
    hits: dict[str, list[str]] = {k: [] for k in RULES}
    for fname, src in texts.items():
        for rule in RULES:
            if re.search(r"^def %s\(" % re.escape(rule), src, re.M):
                hits[rule].append(fname)
    return hits


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    print("── 1. 工作樹:每條規則只有一份定義 ──")
    texts = {f.name: f.read_text(encoding="utf-8", errors="replace")
             for f in _py_files(SCAN_DIRS)}
    print(f"  掃了 {len(texts)} 個檔")
    hits = find_defs(texts)
    for rule, where in RULES.items():
        got = hits[rule]
        check(f"`{rule}` 只定義在 {where}", got == [where], f"實際 {got}")

    print("\n── 2. 陽性對照:拿收斂**之前**的真實版本餵同一套判定,它必須叫 ──")
    # `78b57b55` 是收斂評估的 commit,那時 numerator 還有四份。
    before = "78b57b55"
    old_texts, missing = {}, []
    for rel in ("quant-service/brain_alpha/pick_next.py",
                "quant-service/brain_alpha/runway.py",
                "quant-service/brain_alpha/hybrid_miner.py",
                "quant-service/brain_alpha/universe_sweep.py",
                "quant-service/brain_alpha/brain_auto.py"):
        r = subprocess.run(["git", "show", f"{before}:{rel}"], cwd=REPO,
                           capture_output=True)
        if r.returncode != 0:
            missing.append(rel)
            continue
        old_texts[Path(rel).name] = r.stdout.decode("utf-8", "replace")
    if missing:
        # 拿不到歷史版本時**不可以**默默跳過 —— 那樣這一節就變成「不會叫的檢查」。
        check(f"取得 {before} 的歷史版本", False, f"拿不到:{missing}")
    else:
        old_hits = find_defs(old_texts)
        check(f"{before} 當時 `numerator` 有多份（⇒ 這支檢查真的會叫）",
              len(old_hits["numerator"]) >= 4, f"當時 {old_hits['numerator']}")
        check(f"{before} 當時 `family_key` 不在 brain_auto",
              "brain_auto.py" not in old_hits["family_key"],
              f"當時 {old_hits['family_key']}")

    print("\n── 3. 這支檢查抓不到的（寫下來，免得被當成收斂完成的證明）──")
    print("  · 兩份**不同名**的實作（2026-09-05 的 submitted_ids 事故就是這種）")
    print("  · 同一個名字下**行為不一致**的兩份")
    print("  · 內嵌在函式裡、沒有 `def` 的重複邏輯（本批的 round-robin 原本就是）")

    print("\n" + ("✅ 全過" if not FAILS else f"❌ {len(FAILS)} 格失敗：{FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
