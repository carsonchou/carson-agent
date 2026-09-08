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

## 為什麼要能指定資料集（2026-09-08 補）
不帶 `--only` 時 round-robin 會把整批平均分給全部 9 個有 MATRIX 的資料集，
其中 `fundamental2` / `fundamental6` 各佔 1,830 / 1,026 條候選 —— 而那兩個正是
**已經飽和**的領域（delay=1 時代 fundamental2 產出 1,154 條「通過」、
可提交 **0** 條，全是孿生體）。換軸的目的是拿到**不相關**的分子，
把小批燒在飽和領域上等於白跑。

⚠️ 排序用的產出率是從**帳本**算的，而帳本不分 delay ——
所以 delay=0 的第一批會沿用 delay=1 的產出率當先驗。這是刻意的（同一個資料集
在兩個 delay 下的欄位大致同一批），但**它不是 delay=0 的實測值**，
掃過之後 `dataset_yield` 會自己修正。

## 用法
    python -u run_delay0.py 120
    python -u run_delay0.py 150 --only option8,pv1,pv13,analyst4,socialmedia12,socialmedia8
前提：沒有別的挖礦程序在跑（brain_auto.claim_lock 會擋）。
"""
import sys

sys.path.insert(0, ".")
import brain_auto as B          # noqa: E402
import field_miner as F         # noqa: E402

argv = sys.argv[1:]
N = int(argv[0]) if argv and argv[0].isdigit() else 120
ONLY = None
if "--only" in argv:
    i = argv.index("--only")
    if len(argv) > i + 1:
        ONLY = set(argv[i + 1].split(","))

if not B.claim_lock():
    raise SystemExit("有別的挖礦程序在跑 —— 不疊上去（併發上限 2 是帳號層級）")
F.use_delay(0)
print(f"delay={F.SETTINGS['delay']}  欄位來源={F.FIELDS_FILE.name}  只掃 MATRIX  n={N}"
      f"  資料集={'全部' if ONLY is None else ','.join(sorted(ONLY))}", flush=True)
try:
    F.cmd_run(N, only_type="MATRIX", only_ds=ONLY)
finally:
    B.release_lock()
