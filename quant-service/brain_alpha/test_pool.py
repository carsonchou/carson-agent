#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_pool.py — 候選池 = 帳本 ∪ 平台。**全部固定資料，零平台連線。**

驗收問句照 2026-09-08 的裁示寫成「**修完之後它挑不挑得到那 4 條**」，
不是「測試有沒有過」—— 後者在整段挑片邏輯都沒跑到時也會全綠。

所以每一格都配一個**陰性對照**：同一個斷言在「舊行為」（只有帳本／舊粗排鍵）
下必須失敗。沒有陰性對照的話，「4/4 都挑得到」與「這個檢查對什麼都說挑得到」
分不開（memory `yt-readback-stale-cache`）。

    python test_pool.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick_next as P  # noqa: E402

FAILS: list[str] = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ── 固定資料 ───────────────────────────────────────────────
# 形狀照 auto_ledger.jsonl 與 reconcile.fetch_platform 的實際輸出。
def _led_row(aid, num, fit, ok=True, ep=True, ly=1.5, label="RAT|ds_a|g"):
    return {
        "key": "k" + aid, "alpha_id": aid, "label": label, "ok": ok,
        "expr": f"group_rank(ts_rank(winsorize(ts_backfill({num}/close, 120), std=4), 126), subindustry)",
        "result": {"sharpe": 1.5, "fitness": fit, "failed": [] if ep else ["LOW_SHARPE"],
                   "pending": ["SELF_CORRELATION"], "evaluable_pass": ep, "all_pass": False},
        "year_quality": {"last_year_sharpe": ly} if ly is not None else None,
    }


def _plat_row(num, sharpe, fitness, fails=(), checks_n=8):
    return {"dc": "2026-09-03T05:21:00-04:00", "status": "UNSUBMITTED", "delay": 1,
            "universe": "TOP3000", "decay": 15, "nz": "SUBINDUSTRY",
            "code": f"group_rank(ts_rank(winsorize(ts_backfill({num}/close, 120), std=4), 126), subindustry)",
            "sharpe": sharpe, "fitness": fitness,
            "checks_n": checks_n, "fails": list(fails), "pending": ["SELF_CORRELATION"]}


LED = {r["key"]: r for r in [
    _led_row("SUBMITTED1", "already_num", 1.2),      # 已提交（在帳本裡）
    _led_row("LEDG_OK_1", "ledger_num_a", 1.10),
    _led_row("LEDG_OK_2", "ledger_num_b", 1.05),
    _led_row("LEDG_DUP", "ledger_num_a", 0.90),      # 同分子較差的一條 → 應被去重
    _led_row("LEDG_FAIL", "ledger_num_c", 2.00, ep=False),   # 帳本說不合格
    # 乙群的形狀：帳本記成失敗（沒有 alpha_id 的那些列本來就進不了池子），
    # 這一列代表「帳本裡有這條式子但記成失敗」，平台上卻有一條跑完的 alpha。
]}
LED["orphan_fail_row"] = {"key": "orphan_fail_row", "ok": False,
                          "expr": "…", "error": "poll 401"}

PLAT = {
    "SUBMITTED1": _plat_row("already_num", 2.40, 1.20),
    "LEDG_OK_1": _plat_row("ledger_num_a", 1.50, 1.10),
    # 🔴 主角：平台上跑完、checks 零 FAIL、帳本裡沒有 alpha_id 的那一群
    "PLAT_ONLY_A": _plat_row("plat_num_a", 2.35, 1.60),
    "PLAT_ONLY_B": _plat_row("plat_num_b", 2.18, 1.55),
    # 平台上有 FAIL → 不合格
    "PLAT_FAIL": _plat_row("plat_num_c", 3.00, 2.90, fails=["LOW_SUB_UNIVERSE_SHARPE"]),
    # 🔴 沒有 is/checks（模擬沒跑完）→ fails 也是空的，但**不可以**當成零 FAIL
    "PLAT_NOCHECK": _plat_row("plat_num_d", None, None, checks_n=None),
    # 已提交但**不在帳本裡**：它的分子必須也被排除（同分子必撞）
    "SUBMITTED2": _plat_row("plat_submitted_num", 2.0, 1.4),
}
DONE = {"SUBMITTED1", "SUBMITTED2"}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print("── 1. 候選池 = 帳本 ∪ 平台 ──")
    cand, st = P.build_pool(LED, PLAT, DONE)
    ids = {c["alpha_id"] for c in cand}
    check("平台獨有的合格品進得了池子（PLAT_ONLY_A/B）",
          {"PLAT_ONLY_A", "PLAT_ONLY_B"} <= ids, f"池子={sorted(ids)}")
    check("帳本側合格品仍在（LEDG_OK_1/2、LEDG_DUP）",
          {"LEDG_OK_1", "LEDG_OK_2", "LEDG_DUP"} <= ids)
    check("平台有 FAIL 的不進池子（PLAT_FAIL）", "PLAT_FAIL" not in ids)
    check("**沒有 checks 的不算零 FAIL**（PLAT_NOCHECK）", "PLAT_NOCHECK" not in ids)
    check("帳本判不合格且平台沒有的不進（LEDG_FAIL）", "LEDG_FAIL" not in ids)
    check("已提交的排除（SUBMITTED1/2）", not (DONE & ids))
    check("stats 分得出來源", st["cand_by_src"]["platform"] == 2, str(st["cand_by_src"]))

    print("\n── 1b. 陰性對照:只有帳本(舊行為)時,那兩條必須看不到 ──")
    cand_old, _ = P.build_pool(LED, {}, DONE)
    ids_old = {c["alpha_id"] for c in cand_old}
    check("舊行為下 PLAT_ONLY_A/B 不在池子裡（⇒ 上面那格量到的是修法，不是恆真）",
          not ({"PLAT_ONLY_A", "PLAT_ONLY_B"} & ids_old), f"舊池子={sorted(ids_old)}")

    print("\n── 2. 分子去重 ──")
    picks, by, done_nums = P.dedup_by_numerator(cand, LED, PLAT, DONE)
    pid = {c["alpha_id"] for c in picks}
    check("同分子只留 fitness 最好的（LEDG_OK_1 留、LEDG_DUP 去）",
          "LEDG_OK_1" in pid and "LEDG_DUP" not in pid)
    check("已交分子整族排除（already_num）", "already_num" in done_nums)
    check("**已交但不在帳本裡**的那條,分子也排除（plat_submitted_num）",
          "plat_submitted_num" in done_nums, f"done_nums={sorted(done_nums)}")
    check("平台獨有的兩條通過去重", {"PLAT_ONLY_A", "PLAT_ONLY_B"} <= pid, f"picks={sorted(pid)}")

    print("\n── 2b. label 要跟著進池子（brain_daily_pick 的跨資料集 round-robin 靠它）──")
    # 🔴 第一版漏了 `label`,實測後果:所有候選落進同一「家」→ 家數 1 →
    #    round-robin 退化成純 fitness 排序 → 那 4 條全被擠出 spread。
    #    **零錯誤訊號**,候選表照樣印得出來。
    fam = {(c.get("label") or "||").split("|")[1] for c in cand}
    check("帳本側候選保留 label", any(c.get("label") for c in cand))
    check("分得出 >1 家（含平台獨有的空 label 自成一家）", len(fam) > 1, str(sorted(fam)))
    check("平台獨有的候選 label 是 None（不是硬塞一個假的資料集）",
          all(c.get("label") is None for c in cand if c["src"] == "platform"))

    print("\n── 3. 粗排:缺 year_quality 的不可以被沉到底 ──")
    ranked = sorted(picks, key=P.prerank_key)
    top = [c["alpha_id"] for c in ranked[:2]]
    check("平台獨有的兩條排在最前面（fitness 1.60/1.55 vs 帳本側 1.10）",
          set(top) == {"PLAT_ONLY_A", "PLAT_ONLY_B"}, f"前二={top}")

    # 陰性對照：舊粗排鍵（last_year_sharpe，缺值 -9）會把它們沉到底。
    def old_key(c):
        return -((c.get("year_quality") or {}).get("last_year_sharpe") or -9)
    old_rank = [c["alpha_id"] for c in sorted(picks, key=old_key)]
    tail = set(old_rank[-2:])
    check("舊粗排鍵下它們落在最後兩名（⇒ 這一格量到的是修法）",
          tail == {"PLAT_ONLY_A", "PLAT_ONLY_B"}, f"舊排序={old_rank}")
    check("舊粗排鍵 + n=2 截斷後它們消失（結構性排除的第二道）",
          not ({"PLAT_ONLY_A", "PLAT_ONLY_B"} & set(old_rank[:2])))

    print("\n── 4. 缺 year_quality 不可以被填成 0 ──")
    c = {"alpha_id": "X", "year_quality": None}
    calls = []

    def fake_fetch(_s, aid):
        calls.append(aid)
        return None                     # 抓不到
    orig = P.B.fetch_yearly
    P.B.fetch_yearly = fake_fetch
    try:
        n = P.fill_year_quality(None, [c])
    finally:
        P.B.fetch_yearly = orig
    check("抓不到時回報補了 0 條", n == 0)
    check("抓不到時 year_quality 留 None,不是 0", c["year_quality"] is None,
          repr(c["year_quality"]))
    check("真的去抓了（不是靜靜跳過）", calls == ["X"], str(calls))

    print("\n" + ("✅ 全過" if not FAILS else f"❌ {len(FAILS)} 格失敗：{FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
