#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_funnel_shorts.py — 誠信稽核:切片 Shorts 的旁白數字是否溯源得到來源長片。

## 為什麼(2026-08-17 事故)
B41_vS97LO8「反直覺!聯鈞定期定額反而虧更多…報酬負37%」已對外播出 479 次才被抓到:
來源長片明寫「定期定額總報酬 656.4%、回撤降到 -38.3%,顯示定期定額**降低風險**」,
切片把回撤誤當報酬、還把結論整個反轉。當時的閘門只認阿拉伯數字,而旁白一律中文唸法。

閘門已修,但**已經發布的切片片沒人回頭查**。這支就是回頭查的工具:
對每支切片 Shorts,拿它的旁白數字(阿拉伯+中文唸法)去比對**它自己的來源長片**,
列出查無來源的數字。fail-open 報告用,不自動下架(下架是對外動作,要人看過再決定)。

## 判準
- 只查「有 parent 來源長片」的切片片(題庫 source=funnel 且帶 parent)
- 數字兩邊都正規化(阿拉伯 + 中文唸法),同 shorts_funnel._drop_untraceable 的口徑
- 容差:完全相符才算命中(口播四捨五入的情況會被列出來,由人判讀)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"


def _pool(text: str) -> set:
    """文字裡所有數字的正規化池(阿拉伯原文 + 中文唸法轉換)。"""
    t = re.sub(r"[,，]", "", text)
    pool = set(re.findall(r"\d+(?:\.\d+)?", t))
    try:
        from fact_source_guard import _cn_num_to_float as c2f
        cns = re.findall(r"百分之([零一二三四五六七八九十百千點]+)", t)
        cns += re.findall(r"([零一二三四五六七八九十百千點]{2,})[倍年萬]", t)
        for c in cns:
            v = c2f(c)
            if v is not None:
                pool.add("%g" % v)
    except Exception:  # noqa: BLE001
        pass
    return pool


def _claims(text: str) -> list:
    """旁白裡的績效類數字(帶單位者),回正規化字串清單。"""
    t = re.sub(r"[,，]", "", text)
    out = list(re.findall(r"\d+(?:\.\d+)?(?=\s*[%％倍年萬])", t))
    try:
        from fact_source_guard import _cn_num_to_float as c2f
        cns = re.findall(r"百分之([零一二三四五六七八九十百千點]+)", t)
        cns += re.findall(r"([零一二三四五六七八九十百千點]{2,})[倍年萬]", t)
        for c in cns:
            v = c2f(c)
            if v is not None:
                out.append("%g" % v)
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    bank = json.loads((STUDIO / "topic_bank.json").read_text(encoding="utf-8"))
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    # 題目 → parent(來源長片 slug)
    parents = {}
    for t in bank:
        if t.get("source") == "funnel" and t.get("parent"):
            key = re.sub(r"[^一-鿿0-9A-Za-z]", "", str(t.get("title", "")))[:12]
            if key:
                parents[key] = t["parent"]
    rows = []
    for slug, vid in led.items():
        if not slug.startswith("S_"):
            continue
        vt = OUT / f"{slug}.voice.txt"
        if not vt.exists():
            continue
        skey = re.sub(r"[^一-鿿0-9A-Za-z]", "", slug[2:])[:12]
        par = next((p for k, p in parents.items() if k[:8] and k[:8] in skey), None)
        if not par:
            continue
        pmd = OUT / f"{par}.md"
        if not pmd.exists():
            continue
        src = _pool(pmd.read_text(encoding="utf-8"))
        say = _claims(vt.read_text(encoding="utf-8"))
        bad = sorted({n for n in say if n not in src})
        rows.append((slug, vid, par, bad))
    print(f"可稽核的切片 Shorts:{len(rows)} 支\n")
    flagged = [r for r in rows if r[3]]
    for slug, vid, par, bad in rows:
        mark = "🔴" if bad else "✅"
        print(f"{mark} {slug[:40]}  ({vid})")
        if bad:
            print(f"     查無來源:{bad}")
            print(f"     來源長片:{par[:44]}")
    print(f"\n有問題 {len(flagged)} / {len(rows)} 支")
    if flagged:
        print("⚠️ 下架與否請人判讀(口播四捨五入也會被列出),不自動處理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
