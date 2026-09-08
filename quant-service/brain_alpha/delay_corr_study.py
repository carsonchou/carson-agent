#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""delay=0 vs delay=1：換軸有沒有真的降相關？（唯讀，不提交、不模擬、不挖礦）

## 這支在回答什麼
換軸到 delay=0 的**唯一理由**是降 self-correlation
（memory `brain-alpha-mining-2026-08`：只有換資料領域才降相關）。
fitness 好看不算換軸成功 —— 同族高分是這條線最常見的假進展。

## 為什麼比較組一定要同資料集
帳本裡 delay=1 的合格候選有 1,990 條，其中 **fundamental2 佔 1,164**；
而 delay=0 這批合格的 14 條**全部來自 analyst4**。
拿「delay=0 的 analyst4」比「delay=1 的全池」，量到的是**資料集組成**不是 delay
—— 那正是 `docs/ops/dispatch.md:151`「做決策的那個人看的是哪一本帳」的同型錯誤。
所以主比較是 **analyst4 delay=0 vs analyst4 delay=1**，單一變因只有 delay。
全池數字另外附，標明它答的是別的問題。

## 判準用哪個數字
`max |corr|` 對**已提交 13 條**，而不是候選彼此之間 ——
擋住提交的是「和已交的撞」，不是「候選之間撞」。兩個都算，但結論看前者。

⚠️ `runway.corr` 算不出來回 `None`，意思是**沒量到**，不是「不相關」。
本檔一律把 None 排除在分佈之外並單獨計數，**不當成 0**。

用法：
    python delay_corr_study.py             # 用預設樣本數
    python delay_corr_study.py --n1 60     # delay=1 比較組抽樣數
"""
from __future__ import annotations

import collections
import io
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B      # noqa: E402
import runway as R          # noqa: E402

SEED = 20260909             # 固定種子：抽樣可重現
DS = "analyst4"             # delay=0 合格的 14 條全部來自這裡


def load_rows():
    rows, bad = [], 0
    for line in io.open(ROOT / "auto_ledger.jsonl", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            bad += 1
    return rows, bad


def qualified(rows, delays, ds=None):
    """{alpha_id: label}。delay 欄位是 2026-09-08 才加的，舊列沒有 ⇒ None 當 delay=1。"""
    out = {}
    for r in rows:
        d = r.get("delay")
        d = 1 if d is None else d
        if d not in delays:
            continue
        lab = str(r.get("label") or "")
        if not lab.startswith("F1|"):
            continue
        if ds and lab.split("|")[1] != ds:
            continue
        if r.get("ok") and (r.get("result") or {}).get("evaluable_pass") and r.get("alpha_id"):
            out[r["alpha_id"]] = lab
    return out


def series_for(s, ids, cache):
    got, miss = {}, {}
    for aid in ids:
        v, why = R.fetch_pnl_ex(s, aid, cache)
        if v is None:
            miss[aid] = why
        else:
            got[aid] = v
    return got, miss


def maxcorr_vs(ser, cand_ids, pool_ids):
    """每條候選對 pool 的 max|corr|。回 (｛aid: max｝, 完全沒量到的 aid 清單)。"""
    out, unmeasured = {}, []
    for a in cand_ids:
        if a not in ser:
            unmeasured.append(a)
            continue
        vals = [abs(c) for b in pool_ids if b != a and b in ser
                for c in [R.corr(ser[a], ser[b])] if c is not None]
        if not vals:
            unmeasured.append(a)
        else:
            out[a] = max(vals)
    return out, unmeasured


def pairwise(ser, ids):
    ids = [a for a in ids if a in ser]
    out = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = R.corr(ser[ids[i]], ser[ids[j]])
            if c is not None:
                out.append(abs(c))
    return out


def describe(vals, name):
    if not vals:
        print("  %-34s 0 個（沒量到，不是 0 相關）" % name)
        return None
    v = sorted(vals)
    print("  %-34s n=%-4d 中位 %.3f  最大 %.3f  最小 %.3f  ≥0.7 的 %d 條"
          % (name, len(v), statistics.median(v), v[-1], v[0], sum(1 for x in v if x >= 0.7)))
    return {"n": len(v), "median": statistics.median(v), "max": v[-1],
            "min": v[0], "ge70": sum(1 for x in v if x >= 0.7)}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    n1 = 60
    if "--n1" in sys.argv:
        n1 = int(sys.argv[sys.argv.index("--n1") + 1])

    rows, bad = load_rows()
    a0 = qualified(rows, {0}, DS)
    a1_all = qualified(rows, {1}, DS)
    print("帳本 %d 列（壞行 %d）" % (len(rows), bad))
    print("%s delay=0 合格 %d 條 / delay=1 合格 %d 條（去重後的 alpha_id）"
          % (DS, len(a0), len(a1_all)))

    rnd = random.Random(SEED)
    a1 = dict(rnd.sample(sorted(a1_all.items()), min(n1, len(a1_all))))
    print("delay=1 比較組：固定種子 %d 隨機抽 %d 條（不優先挑快取內的 —— "
          "快取裡是先前挑片器看過的，挑它們會選到偏一邊的樣本）" % (SEED, len(a1)))

    s = B.auth()
    sub, why = B.active_alpha_ids(s)
    if sub is None:
        print("🔴 拿不到已提交清單（%s）—— 主判準算不了，停" % why)
        return 1
    print("已提交池 %d 條" % len(sub))

    cache = R.load_cache()
    n_cached = len(cache)
    ser, miss = series_for(s, list(a0) + list(a1) + sorted(sub), cache)
    R.save_cache(cache)
    print("PnL 序列：取到 %d / %d（快取原有 %d → 現有 %d），沒量到 %d 條"
          % (len(ser), len(a0) + len(a1) + len(sub), n_cached, len(cache), len(miss)))
    for aid, w in list(miss.items())[:5]:
        print("   沒量到 %s：%s" % (aid, w))

    print("\n=== 主判準：對已提交 13 條的 max|corr|（擋住提交的就是這個）===")
    m0, u0 = maxcorr_vs(ser, list(a0), sorted(sub))
    m1, u1 = maxcorr_vs(ser, list(a1), sorted(sub))
    r0 = describe(list(m0.values()), "%s delay=0" % DS)
    r1 = describe(list(m1.values()), "%s delay=1（抽樣）" % DS)
    print("  完全沒量到：delay=0 %d 條 / delay=1 %d 條" % (len(u0), len(u1)))

    print("\n=== 次要：候選彼此之間的 |corr| ===")
    p0 = describe(pairwise(ser, list(a0)), "%s delay=0 兩兩" % DS)
    p1 = describe(pairwise(ser, list(a1)), "%s delay=1 兩兩（抽樣）" % DS)

    print("\n=== 附錄（答的是別的問題）：delay=1 全資料集合格池 ===")
    allq1 = qualified(rows, {1})
    print("  全池 %d 條，資料集分佈 %s"
          % (len(allq1), dict(collections.Counter(v.split("|")[1] for v in allq1.values()))))
    print("  ⚠️ 不拿它跟 delay=0 比：那是資料集組成的差，不是 delay 的差。")

    print("\n=== 逐條（delay=0 的 14 條）===")
    print("  %-9s %-30s %s" % ("alpha_id", "欄位", "max|corr| vs 已提交"))
    for aid in sorted(m0, key=lambda a: -m0[a]):
        fld = a0[aid].split("|")[2]
        print("  %-9s %-30s %.3f %s" % (aid, fld[:28], m0[aid],
                                        "🔴撞" if m0[aid] >= 0.7 else ""))
    for aid in u0:
        print("  %-9s %-30s 沒量到" % (aid, a0[aid].split("|")[2][:28]))

    out = {"dataset": DS, "seed": SEED,
           "d0_ids": a0, "d1_sample_ids": a1, "submitted": sorted(sub),
           "d0_maxcorr": m0, "d1_maxcorr": m1,
           "d0_unmeasured": u0, "d1_unmeasured": u1,
           "summary": {"d0_vs_submitted": r0, "d1_vs_submitted": r1,
                       "d0_pairwise": p0, "d1_pairwise": p1}}
    p = ROOT / "docs" / "delay_corr_study_20260909.json"
    p.parent.mkdir(exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n明細 → %s" % p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
