#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""universe_sweep.py — 把已經找到的好分子，換小 universe 重跑一次。

## 為什麼（2026-08-29）
官方 Challenge 的 Quality Factor 看四項：
    Universe（**越小越好**）· SelfCorrelation（越低越好）· Fitness（越高越好）· Delay（D1>D0）

而 `field_miner.py` 的 SETTINGS 把 universe 寫死 `TOP3000` —— 這是**四項裡最大的那一格**。
實測對照（已提交的 7 條）：

    08-27  2 條  fitness 均 1.195  全 TOP3000            → 剛好 2000.0（上限）
    08-28  3 條  fitness 均 1.313  TOP3000 + TOP1000×2   → 剛好 2000.0（上限）
    08-29  2 條  fitness 均 1.545  全 TOP3000            → 待結算

兩天都精準吃滿 2,000，所以目前還沒有痛。但 **SelfCorrelation 這一項只會一天比一天糟**
（第一天池子是空的 ≈ 0，08-29 已經是 0.524 / 0.667，門檻 0.7）。
等它把分數拉下來的時候再想辦法就來不及了 —— 現在就要在別的維度先把餘裕做出來。

Universe 是四項裡**唯一不用重新探索就能改善**的：分子已經找到了，換個設定重跑就好。

## 為什麼不是全部重跑
換小 universe 不是免費的：
- 股票池變小 → 分散度下降 → `CONCENTRATED_WEIGHT` 更容易掛
- `LOW_SUB_UNIVERSE_SHARPE` 的門檻是相對公式，池子小了門檻跟著動
- Sharpe 本身可能掉（訊號在小型股上比較強是常見的）
所以這支是**重跑 + 逐條驗**，不是無腦換設定。跑完照樣要看 evaluable_pass。

## 只挑已經證明有訊號的分子
一階掃描的命中率約 24%，代表四條裡有三條是廢的。拿全部欄位重跑等於再燒一次那 76%。
這支只拿**已經雙門檻達標**的分子（每個分子取 fitness 最高那條的運算式），
把算力全花在確定有礦的地方。

## 用法
    python universe_sweep.py --plan          # 只列要跑什麼
    python universe_sweep.py --run 200
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

# 由大到小。TOP200 以下先不碰 —— 池子太小時 CONCENTRATED_WEIGHT 幾乎必掛，
# 而且 sub-universe 的相對門檻會變得很難看。等 TOP1000/500 有實測結果再決定要不要往下探。
UNIVERSES = ("TOP1000", "TOP500")


# 分子的實作只有 `brain_auto.numerator` 一份(2026-09-08 收斂,原本四份)。
# 舊版只認 `ts_backfill(`,認不出的共用一個 `?` 桶 —— 那個桶幾乎只砍平台側。
numerator = B.numerator


def base_settings() -> dict:
    """跟 field_miner 完全一樣的設定，只有 universe 會被換掉。

    刻意共用而不是自己另寫一份：兩邊 drift 的話，重跑出來的東西
    就不能跟原本那條比較了（那是 memory yt-duplicate-impl-gate-bypass 的同型坑，
    同一件事有兩份實作，改了其中一份沒人發現）。
    """
    import field_miner as FM
    return dict(FM.SETTINGS)


def winners(led: dict):
    """每個獨立分子取 fitness 最高的那條運算式。"""
    best = {}
    for r in led.values():
        if not (r.get("ok") and (r.get("result") or {}).get("evaluable_pass")):
            continue
        n = numerator(r["expr"])
        f = r["result"].get("fitness") or 0
        if n not in best or f > (best[n]["result"].get("fitness") or 0):
            best[n] = r
    return sorted(best.values(), key=lambda r: -(r["result"].get("fitness") or 0))


def build(led):
    base = base_settings()
    todo = []
    for r in winners(led):
        n = numerator(r["expr"])
        for uni in UNIVERSES:
            st = dict(base); st["universe"] = uni
            if B._key(r["expr"], st) in led:
                continue
            todo.append((f"UNI|{uni}|{n}", r["expr"], st))
    return todo


def cmd_plan(n=25):
    led = B.load_ledger()
    w = winners(led)
    todo = build(led)
    print(f"已達標的獨立分子 {len(w)} 種 × universe {len(UNIVERSES)} 種 "
          f"= 待跑 {len(todo)} 條（已扣掉跑過的）\n")
    print(f"{'分子':<46}{'原TOP3000 fitness':>20}")
    print("-" * 68)
    for r in w[:n]:
        print(f"{numerator(r['expr'])[:44]:<46}{(r['result'].get('fitness') or 0):>20.2f}")


def cmd_run(n):
    led = B.load_ledger()
    todo = build(led)[:n]
    if not todo:
        print("都跑過了。")
        return
    print(f"universe 重跑：{len(todo)} 條（{'/'.join(UNIVERSES)}），2 worker 併發")
    print(f"  首條：{todo[0][0]}")
    B.candidates = lambda: todo      # noqa: E731
    B.cmd_run(len(todo))


def cmd_report():
    """比較同一個分子在不同 universe 下的表現 —— 這才是這支的產出。"""
    led = B.load_ledger()
    rows = {}
    for r in led.values():
        if not r.get("ok"):
            continue
        res = r.get("result") or {}
        lab = str(r.get("label", ""))
        n = numerator(r["expr"])
        # 用「掃描各欄位找 TOP* 標記」而不是寫死位置(2026-08-29 踩過):
        # `U|` 這個前綴**之前的實驗已經用掉了**,而且格式不同(`U|esteps|TOP500`,
        # 第二格是名字不是 universe)。寫死 split("|")[1] 會把 "esteps" 當 universe 讀,
        # 報表整個錯位而且不會報錯。改成認內容不認位置,新舊格式都吃得下。
        parts = lab.split("|")
        unis = [x for x in parts if x.startswith("TOP")]
        if unis:
            uni = unis[0]
        elif lab.startswith("F1|"):
            uni = "TOP3000"          # field_miner 的 SETTINGS 寫死 TOP3000
        else:
            continue
        cur = rows.setdefault(n, {})
        old = cur.get(uni)
        if old is None or (res.get("fitness") or 0) > (old.get("fitness") or 0):
            cur[uni] = {"fitness": res.get("fitness"), "sharpe": res.get("sharpe"),
                        "pass": res.get("evaluable_pass"), "id": r.get("alpha_id")}
    have = {n: v for n, v in rows.items() if len(v) > 1}
    if not have:
        print("還沒有可比較的資料（universe 重跑還沒跑）。")
        return
    print(f"{'分子':<40}{'TOP3000':>18}{'TOP1000':>18}{'TOP500':>18}")
    print("-" * 96)
    def cell(d):
        if not d:
            return "-"
        return f"{(d['fitness'] or 0):.2f}{'' if d['pass'] else ' ✗'}"
    for n, v in sorted(have.items(), key=lambda kv: -((kv[1].get('TOP1000') or {}).get('fitness') or 0)):
        print(f"{n[:38]:<40}{cell(v.get('TOP3000')):>18}"
              f"{cell(v.get('TOP1000')):>18}{cell(v.get('TOP500')):>18}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    if "--plan" in a:
        cmd_plan()
    elif "--report" in a:
        cmd_report()
    elif "--run" in a:
        i = a.index("--run")
        cmd_run(int(a[i + 1]) if len(a) > i + 1 else 100)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
