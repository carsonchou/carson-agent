#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_delay0.py — 跑一批 delay=0 的一階掃描（2026-09-03 換軸實驗）。

## 為什麼需要這個殼
`field_miner.py` **自己不搶鎖** —— 鎖是 `brain_alpha_cron.py` 搶的，
它再用 runpy 在同一程序裡跑 field_miner。所以直接
`python field_miner.py --run N` 不會被鎖擋，卻會跟 `0 */2 * * *` 的 cron
互搶帳號層級的兩個併發位（brain_auto.py:801「開兩個挖礦程序不會變快，
只會互相 429」）。這個殼補上那道鎖。

只掃 MATRIX：delay=0 的 2,121 個欄位裡 GROUP 35 / SYMBOL 2 / UNIVERSE 6，
餵進算術模板是結構性失敗（brain_auto 的 STRUCTURAL_ERR），掃它們只會燒額度。
VECTOR 778 個有自己的 VEC_FORMS 模板，留待下一批。

## 用法
    python -u run_delay0.py 120
前提：沒有別的挖礦程序在跑（brain_auto.claim_lock 會擋）。
"""
import sys

sys.path.insert(0, ".")
import brain_auto as B          # noqa: E402
import field_miner as F         # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
if not B.claim_lock():
    raise SystemExit("有別的挖礦程序在跑 —— 不疊上去（併發上限 2 是帳號層級）")
F.use_delay(0)
print(f"delay={F.SETTINGS['delay']}  欄位來源={F.FIELDS_FILE.name}  只掃 MATRIX  n={N}", flush=True)
F.cmd_run(N, only_type="MATRIX")
