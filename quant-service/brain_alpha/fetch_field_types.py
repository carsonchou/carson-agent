#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_field_types.py — 補抓每個欄位的 `type`，寫進 FIELD_TYPES.json。

## 為什麼（2026-08-29）
事故：一階掃描燒掉 1,233 次模擬全數失敗，錯誤訊息一模一樣：
    Operator divide / ts_backfill does not support event inputs
全部集中在 `news12`（掃 1,173 命中 0，**100% 失敗**）。

根因：`ALL_FIELDS.json` 只存了 `[id, coverage, alphaCount]`，**沒存 type**。
而 field_miner 的排序是「alphaCount 低的先掃」——news12 正好是全平台最冷門的
資料集，於是掃描器一開工就一頭撞進一個結構上跑不動的資料集，連撞 1,173 次。

`type` 有兩種：
  · MATRIX —— 一股一值，算術運算子直接吃
  · VECTOR —— 一股一串事件，**必須先用 vec_* 收斂**才能做算術

所以這支不只是止血（別再掃 VECTOR），更是解鎖：news12 的 875 個欄位是
全平台 alphaCount 最低的一批，只是需要換一個模板才拿得到。

## 為什麼要獨立一支而不是直接改 ALL_FIELDS.json
ALL_FIELDS.json 是一階掃描的輸入，正在被跑著的 miner 讀。
另存一份合併，壞了可以直接刪，不會弄髒還在跑的產線。

## 用法
    python fetch_field_types.py          # 抓全部（會自動續抓，可中斷）
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

OUT = ROOT / "FIELD_TYPES.json"
PAGE = 50


def fetch_dataset(s, ds, seen):
    """分頁抓一個資料集的所有欄位型別。429 用指數退避——挖礦程序同時在打 API。"""
    got, offset = {}, 0
    while True:
        url = (f"{B.API}/data-fields?dataset.id={ds}&instrumentType=EQUITY"
               f"&region=USA&delay=1&universe=TOP3000&limit={PAGE}&offset={offset}")
        for attempt in range(8):
            r = s.get(url, timeout=60)
            if r.status_code == 429:
                time.sleep(min(60, 4 * 2 ** attempt))
                continue
            if r.status_code == 401:          # token 過期就換一張（同 brain_auto 的教訓）
                s.cookies.update(B.auth().cookies)
                continue
            break
        if not r.ok:
            print(f"  {ds} offset={offset} HTTP {r.status_code} → 停在這裡", file=sys.stderr)
            return got, False
        res = r.json().get("results") or []
        for x in res:
            fid = x.get("id")
            if fid:
                got[fid] = x.get("type")
        if len(res) < PAGE:
            return got, True
        offset += PAGE
        time.sleep(0.5)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    all_fields = json.loads(io.open(ROOT / "ALL_FIELDS.json", encoding="utf-8").read())
    out = {}
    if OUT.exists():                          # 可中斷續抓
        out = json.loads(io.open(OUT, encoding="utf-8").read())
    s = B.auth()
    for ds in all_fields:
        if ds in out and out[ds].get("_complete"):
            print(f"{ds:<16} 已完成，跳過")
            continue
        got, complete = fetch_dataset(s, ds, out)
        got["_complete"] = complete
        out[ds] = got
        io.open(OUT, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
        n_vec = sum(1 for k, v in got.items() if v == "VECTOR")
        n_mat = sum(1 for k, v in got.items() if v == "MATRIX")
        print(f"{ds:<16} MATRIX {n_mat:>5}  VECTOR {n_vec:>5}  {'完整' if complete else '不完整'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
