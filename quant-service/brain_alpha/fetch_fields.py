#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fields.py — 抓某個 delay 的全欄位清單（id / type / coverage / alphaCount）。

## 為什麼是新的一支（2026-09-03）
`fetch_field_types.py` 把 `delay=1` 寫死在 URL 裡（該檔第 49 行），而且它只補 type，
欄位清單另外躺在 `ALL_FIELDS.json`。要掃 delay=0 需要**兩份都換**。

`/data-fields` 一次就回 id / type / coverage / alphaCount 四樣，所以不需要兩支。
本檔輸出兩個檔案，schema 與既有的完全相同，讓 field_miner 可以直接換讀：
    ALL_FIELDS_D{n}.json   {ds: [[id, coverage, alphaCount], ...]}
    FIELD_TYPES_D{n}.json  {ds: {id: type, _complete: bool}}

**delay=1 時不覆寫既有檔案**（會寫成 _D1 後綴），理由同 fetch_field_types.py 的註解：
既有兩個檔案正在被跑著的 miner 讀，另存一份壞了可以直接刪。

## type 有三種，不是兩種
MATRIX（一股一值）· VECTOR（一股一串事件，要先 vec_* 收斂）· **GROUP**（分組用）。
field_miner 的 `load_types()` 對未知型別預設回 MATRIX —— GROUP 餵進算術模板
會結構性失敗。如實記錄，由呼叫端決定要不要掃。

## 用法
    python fetch_fields.py --delay 0
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

PAGE = 50


def get(s, url, tries=8):
    """429 指數退避 —— 挖礦程序同時在打同一個帳號的 API（併發上限 2）。"""
    r = None
    for a in range(tries):
        r = s.get(url, timeout=60)
        if r.status_code == 429:
            time.sleep(min(60, 4 * 2 ** a)); continue
        if r.status_code == 401:
            s.cookies.update(B.auth().cookies); continue
        return r
    return r


def datasets(s, delay):
    out, off = [], 0
    while True:
        r = get(s, f"{B.API}/data-sets?instrumentType=EQUITY&region=USA"
                   f"&delay={delay}&universe=TOP3000&limit={PAGE}&offset={off}")
        if not r.ok:
            print(f"data-sets offset={off} 問不到 HTTP {r.status_code}", file=sys.stderr)
            return out, False
        j = r.json(); out += j.get("results") or []
        if len(out) >= (j.get("count") or 0):
            return out, True
        off += PAGE; time.sleep(2)


def fields(s, ds, delay):
    got, off = [], 0
    while True:
        r = get(s, f"{B.API}/data-fields?dataset.id={ds}&instrumentType=EQUITY"
                   f"&region=USA&delay={delay}&universe=TOP3000&limit={PAGE}&offset={off}")
        if not r.ok:
            # 抓不到就標 incomplete，**不要當成「這個資料集只有這麼多欄位」**
            print(f"  {ds} offset={off} 問不到 HTTP {r.status_code} → 標為不完整", file=sys.stderr)
            return got, False
        res = r.json().get("results") or []
        got += res
        if len(res) < PAGE:
            return got, True
        off += PAGE; time.sleep(0.5)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    a = sys.argv[1:]
    delay = int(a[a.index("--delay") + 1]) if "--delay" in a else 0
    f_all = ROOT / f"ALL_FIELDS_D{delay}.json"
    f_typ = ROOT / f"FIELD_TYPES_D{delay}.json"

    s = B.auth()
    ds_rows, ds_ok = datasets(s, delay)
    print(f"delay={delay}  資料集 {len(ds_rows)} 個（清單{'完整' if ds_ok else '不完整'}）")

    all_f, all_t, incomplete = {}, {}, []
    for d in ds_rows:
        ds = d.get("id")
        rows, ok = fields(s, ds, delay)
        if not ok:
            incomplete.append(ds)
        all_f[ds] = [[x.get("id"), x.get("coverage"), x.get("alphaCount")] for x in rows if x.get("id")]
        all_t[ds] = {x["id"]: x.get("type") for x in rows if x.get("id")}
        all_t[ds]["_complete"] = ok
        c = {}
        for x in rows:
            c[x.get("type")] = c.get(x.get("type"), 0) + 1
        exp = d.get("fieldCount")
        flag = "" if exp == len(rows) else f"  ⚠️ 平台說 {exp} 個，抓到 {len(rows)} 個"
        print(f"  {ds:<16} {len(rows):>5} 欄位  {c}{flag}")
        time.sleep(1)

    io.open(f_all, "w", encoding="utf-8").write(json.dumps(all_f, ensure_ascii=False))
    io.open(f_typ, "w", encoding="utf-8").write(json.dumps(all_t, ensure_ascii=False))
    tot = sum(len(v) for v in all_f.values())
    print(f"\n寫出 {f_all.name} / {f_typ.name}  欄位總數 {tot}")
    if incomplete:
        print(f"⚠️ 不完整的資料集 {len(incomplete)} 個：{incomplete} —— **不要當成掃過了**")
    else:
        print("所有資料集皆完整")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
