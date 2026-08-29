#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runway.py — 還剩幾條**真的交得出去**的 alpha？也就是還有幾天跑道。

## 為什麼需要這支（2026-08-29）
帳本說「153 個獨立分子」，但那是**模擬有通過**的數量，不是**交得出去**的數量。
兩者差很多，而我一直拿前者在跟 Carson 報進度。

真正的閘門是 `SELF_CORRELATION < 0.7`，而它是**遞減資源**：
每提交一條，池子就變大一點，剩下的候選就更難不撞。實測軌跡：

    08-27 第 1 條   self-corr ≈ 0（池子空的）
    08-29 第 1 條   0.5242
    08-29 第 2 條   0.6665   ← 門檻 0.7

而且**不只要對已提交的不撞，同一天的兩條彼此也不能撞**
（08-29 原本挑的兩條彼此 0.90，差點白丟一個名額）。
所以這不是「逐條比對」，是**最大獨立集**問題。

## 方法：直接算日 PnL 相關，而不是靠分子名稱猜
分子名稱不可靠 —— `unrecognized_tax_benefits_affecting_tax_rate` 與
`unrecognized_tax_benefit_increase_current_period` 是**不同字串、同一個會計科目**，
實測相關 0.8999。字串比對看不出來。

**這個替身值先驗過**（2026-08-29，n=2）：拿同一套算法算候選對已提交的最大相關，
跟 BRAIN 自己回報的 SELF_CORRELATION 比 —— 誤差 ≤0.01：

    xAjl5o9N   我算 0.5332   BRAIN 0.5242   差 0.009
    Jj73bqOn   我算 0.5958   BRAIN 0.5933   差 0.003

→ 可以用來估算，**但 0.69~0.71 這個帶狀區間內不能當判準**（誤差蓋過差距），
  那個區間一律回報「要平台實測才知道」。這是 memory
  yt-search-capture-engine-2026-08 的教訓：拿替身值分析前先驗替身等不等於真值。

## 貪婪最大獨立集
從 fitness 最高的開始，逐條檢查它對「已提交 + 已選入」的最大相關：
< 門檻就收下，否則丟掉。貪婪不保證最優，但方向保守（實際跑道 ≥ 這個估計），
而且順序照 fitness 排 = 先拿好的，符合實際提交策略。

## 用法
    python runway.py --top 60      # 只評估 fitness 前 60 的候選（預設）
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

THRESHOLD = 0.7
GREY = 0.02          # 門檻上下這個範圍內視為「測不準」
CACHE = ROOT / "pnl_cache.json"


def numerator(expr: str) -> str:
    m = re.findall(r"ts_backfill\(([^,)]+)", expr or "")
    return m[0].split("/")[0].strip() if m else "?"


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(io.open(CACHE, encoding="utf-8").read())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def fetch_pnl(s, aid, cache):
    """回傳日 PnL 差分序列。快取到檔案 —— 同一條 alpha 的歷史 PnL 不會變。"""
    if aid in cache:
        return cache[aid]
    for attempt in range(6):
        r = s.get(f"{B.API}/alphas/{aid}/recordsets/pnl", timeout=90)
        if r.status_code == 429:
            time.sleep(min(40, 3 * 2 ** attempt)); continue
        if r.status_code == 401:
            s.cookies.update(B.auth().cookies); continue
        if not r.text.strip():
            time.sleep(float(r.headers.get("Retry-After") or 3)); continue
        break
    else:
        return None
    if not r.ok:
        return None
    try:
        recs = r.json().get("records") or []
    except Exception:  # noqa: BLE001
        return None
    if len(recs) < 100:
        return None
    vals = [row[1] for row in recs]                      # [date, cumulative_pnl]
    diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    cache[aid] = diffs
    return diffs


def corr(a, b):
    n = min(len(a), len(b))
    if n < 100:
        return None
    a, b = a[-n:], b[-n:]
    ma = sum(a) / n; mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (va ** 0.5 * vb ** 0.5)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    top = 60
    if "--top" in sys.argv:
        i = sys.argv.index("--top")
        if len(sys.argv) > i + 1:
            top = int(sys.argv[i + 1])

    s = B.auth()
    cache = load_cache()

    # 已提交的（池子）
    r = s.get(f"{B.API}/users/self/alphas?limit=100&status=ACTIVE", timeout=60)
    active = [a["id"] for a in (r.json().get("results") or [])]
    print(f"已提交 {len(active)} 條，抓 PnL…")
    pool = []
    for aid in active:
        p = fetch_pnl(s, aid, cache)
        if p:
            pool.append((aid, p))
    print(f"  取得 {len(pool)} 條的 PnL")

    # 候選：每個分子取 fitness 最高的
    led = B.load_ledger()
    best = {}
    for rec in led.values():
        if not (rec.get("ok") and (rec.get("result") or {}).get("evaluable_pass")):
            continue
        if not rec.get("alpha_id"):
            continue
        n = numerator(rec["expr"])
        f = rec["result"].get("fitness") or 0
        if n not in best or f > (best[n]["result"].get("fitness") or 0):
            best[n] = rec
    cands = sorted(best.values(), key=lambda x: -(x["result"].get("fitness") or 0))
    cands = [c for c in cands if c["alpha_id"] not in active][:top]
    print(f"候選 {len(cands)} 條（每個分子取 fitness 最高、扣掉已提交），逐條抓 PnL…\n")

    accepted, grey, rejected = [], [], []
    chosen = list(pool)            # 已提交 + 已選入,都算進池子
    for c in cands:
        aid = c["alpha_id"]
        p = fetch_pnl(s, aid, cache)
        if not p:
            continue
        mx, who = 0.0, None
        for oid, op in chosen:
            v = corr(p, op)
            if v is not None and abs(v) > mx:
                mx, who = abs(v), oid
        row = (mx, numerator(c["expr"]), aid, c["result"].get("fitness"), who)
        if mx < THRESHOLD - GREY:
            accepted.append(row); chosen.append((aid, p))
        elif mx < THRESHOLD + GREY:
            grey.append(row)
        else:
            rejected.append(row)
        io.open(CACHE, "w", encoding="utf-8").write(json.dumps(cache))

    print(f"{'分子':<44}{'id':<11}{'fit':>6}{'最大相關':>10}  撞到誰")
    print("-" * 88)
    for mx, n, aid, fi, who in accepted:
        print(f"{n[:42]:<44}{aid:<11}{(fi or 0):>6.2f}{mx:>10.4f}  {who}")
    if grey:
        print(f"\n【測不準區 {THRESHOLD-GREY:.2f}~{THRESHOLD+GREY:.2f}】我的方法誤差 ±0.01，"
              f"這些要平台實測才知道：")
        for mx, n, aid, fi, who in grey:
            print(f"{n[:42]:<44}{aid:<11}{(fi or 0):>6.2f}{mx:>10.4f}  {who}")

    print(f"\n{'='*88}")
    print(f"安全可交 {len(accepted)} 條 | 測不準 {len(grey)} 條 | 確定撞 {len(rejected)} 條")
    days = len(accepted) // 2
    print(f"→ 一天 2 條，跑道約 **{days} 天**"
          f"（樂觀情境含測不準：{(len(accepted)+len(grey))//2} 天）")
    print("注意：貪婪解，實際跑道 ≥ 這個估計；且每交一條門檻就更緊，要持續重算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
