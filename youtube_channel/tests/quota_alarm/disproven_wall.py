#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""被反證的牆不算牆(2026-09-20)。不碰真帳本:把 qm._load 換成假帳本。

失敗形狀:09-15 在 9,856 被拒一次,之後每天成功花 20,681 無拒絕——舊邏輯仍取 09-15
當最近的牆,effective_limit 卡在 20,681(預留額度讓花費永遠超不過它),每天少發 2~3 支。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import quota_meter as qm  # noqa: E402


def W(sp):   # 撞牆日(每日總量拒絕)
    return {"spent": sp, "rejected_calls": 1, "rejected_daily_calls": 1, "rejected_daily_units": 400}


def S(sp):   # 無拒絕日
    return {"spent": sp}


def eff(days):
    orig = qm._load
    qm._load = lambda: {"days": days}
    try:
        return qm.effective_limit()
    finally:
        qm._load = orig


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)


# ① 真實形狀:09-15 的假牆被 09-17 的 20,681 反證 → 回到全期實測 26,282
real = {"2026-08-31": W(26001), "2026-09-10": S(26282), "2026-09-15": W(9856),
        "2026-09-16": S(19034), "2026-09-17": S(20681), "2026-09-18": S(20658)}
check("假牆被反證後上限回到 26282(舊邏輯=20681)", eff(real) == 26282)
check("_scan 不再把 09-15 當 ceil_day", qm._scan(real)[3] != "2026-09-15")

# ② 真降額:之後的日子都花不超過新牆 → 仍跟著降
down = {"2026-09-10": S(26282), "2026-09-15": W(15000), "2026-09-16": S(14800), "2026-09-17": S(15000)}
check("真降額仍降到 15000", eff(down) == 15000)

# ③ 真牆沒被反證 → 仍是牆
wall = {"2026-08-31": W(26001), "2026-09-01": S(25000), "2026-09-02": S(26001)}
check("未被反證的牆仍是 ceil", qm._scan(wall)[1] == 26001 and eff(wall) == 26001)

# ④ unreliable 日不能拿來反證
unrel = {"2026-09-15": W(15000), "2026-09-16": {"spent": 30000, "unreliable": True}}
check("unreliable 日不反證牆", eff(unrel) == 15000)

# ⑤ 多道牆:最近的被反證、較舊的沒有 → 退回較舊那道
multi = {"2026-09-01": W(24000), "2026-09-05": S(23000), "2026-09-15": W(9856), "2026-09-17": S(20000)}
check("退回未被反證的較舊牆 24000", eff(multi) == 24000)
