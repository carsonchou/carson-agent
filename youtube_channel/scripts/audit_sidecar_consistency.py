#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_sidecar_consistency.py — 用 sidecar 當比對來源**之前**必跑的一致性檢查。

**為什麼在還沒有任何 sidecar 的時候就先寫這支**
基建線落檔的銳角 A(`8f7e67d9`):`produce_batch._fact_record_key(topic)` 在 topic 沒有 `id` 時
退回 `"title:" + title[:160]`,而 **`fact_key` 不參與計算** ⇒ 兩個無 id 同標題的 topic 會**撞鍵**,
空 topic 全落在同一個鍵上,撞號時**後寫蓋先寫**。
⇒ **一支片的 sidecar 可能記到另一支片的 fact_keys。**

🔴 **那比「沒有 sidecar」更糟:沒有會被發現,記錯的會被當憑據用。**

基建線判斷「目前結構上不會發生」(record→pop 在同一次 `call_claude` 內連續、平行跑是不同
process 不共用模組層 dict),主頻道線**同意且不去改它**。本支不是修法,是**在拿它當證據之前
先驗一次**的絆線 —— 因為判斷「結構上不會」和「實際沒發生」是兩件事,而這條一旦發生是靜默的。

⚠️ **本支寫於 `output/` 一份 sidecar 都還沒有的時候(實測 0 份)。**
那是刻意的:檢查要在資料出現**之前**就位,否則第一批 sidecar 會被無檢查地拿去用。

用法:
  python scripts/audit_sidecar_consistency.py            # 掃 output/*.facts.json
  python scripts/audit_sidecar_consistency.py --selftest # 合成陽性/陰性對照
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

VERDICT_OK = "ok"                  # slug 代號與 fact_keys 代號一致
VERDICT_MISMATCH = "mismatch"      # 🔴 對不上 —— 可能是銳角 A,**擱置不判定**
VERDICT_UNKNOWN = "unknown"        # 認不出代號(Shorts/ETF/大盤),本檢查不適用
VERDICT_EMPTY = "empty"            # fact_keys 為空


def codes_in(text: str, known: set) -> set:
    """text 裡出現、且真的是事實庫代號的那些四位數。"""
    return {c for c in re.findall(r"(\d{4})", text or "") if c in known}


def codes_of_keys(fact_keys, known: set) -> set:
    """fact_keys 各段裡的代號。用**任一段**比對(不可用 endswith ——
    `checkup_crash__2303__crisis2008` 的結尾是 `__crisis2008`,那個坑已經踩過一次,見 5237734c)。"""
    out = set()
    for k in fact_keys or []:
        for seg in str(k).split("__"):
            if seg in known:
                out.add(seg)
    return out


def check_one(rec: dict, known: set) -> dict:
    slug = str(rec.get("slug") or "")
    fks = rec.get("fact_keys") or []
    sc = codes_in(slug, known)
    kc = codes_of_keys(fks, known)
    if not fks:
        v = VERDICT_EMPTY
    elif not sc or not kc:
        v = VERDICT_UNKNOWN
    elif sc & kc:
        v = VERDICT_OK
    else:
        v = VERDICT_MISMATCH
    return {"slug": slug[:60], "slug_codes": sorted(sc), "key_codes": sorted(kc),
            "n_keys": len(fks), "selection": rec.get("selection"), "verdict": v}


def _known_codes() -> set:
    try:
        res = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    except Exception:  # noqa: BLE001
        return set()
    return {seg for k in res for seg in k.split("__") if re.fullmatch(r"\d{4}", seg)}


def selftest() -> int:
    known = {"1785", "8210"}
    cases = [
        ("陰性·一致", {"slug": "L_個股體檢光洋科1785…", "fact_keys": ["checkup_long_horizon__1785",
                                                            "checkup_crash__1785__crisis2008"]}, VERDICT_OK),
        ("🔴陽性·記到別支片", {"slug": "L_個股體檢光洋科1785…",
                        "fact_keys": ["checkup_long_horizon__8210"]}, VERDICT_MISMATCH),
        ("不適用·Shorts 認不出代號", {"slug": "S_0050定投vs網格",
                              "fact_keys": ["dca_vs_allin__0050"]}, VERDICT_UNKNOWN),
        ("空記錄", {"slug": "L_個股體檢光洋科1785…", "fact_keys": []}, VERDICT_EMPTY),
    ]
    bad = 0
    for name, rec, want in cases:
        got = check_one(rec, known)["verdict"]
        ok = got == want
        bad += (not ok)
        print(f"  {'✅' if ok else '🔴'} {name}:期望 {want} 得到 {got}")
    print("[selftest] " + ("全部通過" if not bad else f"🔴 {bad} 項不符"))
    return 0 if not bad else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    known = _known_codes()
    files = sorted(OUT.glob("*.facts.json"))
    print(f"[sidecar] output/ 底下 sidecar {len(files)} 份;事實庫已知代號 {len(known)} 個")
    if not files:
        print("[sidecar] **0 份可檢查** —— 這不是『全部一致』,是**還沒有資料**。"
              "cb52ae03 只對它之後產的片寫 sidecar,既有庫存永遠不會有。")
        return 0
    from collections import Counter
    cnt = Counter()
    rows = []
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            cnt["parse_error"] += 1
            print(f"  ⚠️ 讀不起來 {f.name}:{exc}", file=sys.stderr)
            continue
        r = check_one(rec, known)
        cnt[r["verdict"]] += 1
        if r["verdict"] == VERDICT_MISMATCH:
            rows.append(r)
    for k, v in cnt.most_common():
        print(f"  {k:10s} {v}")
    if rows:
        print(f"\n🔴 **{len(rows)} 份對不上 —— 那些片先擱置不要判定**(可能是銳角 A):", file=sys.stderr)
        for r in rows[:10]:
            print(f"    {r['slug']}｜slug 代號 {r['slug_codes']}｜fact_keys 代號 {r['key_codes']}",
                  file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
