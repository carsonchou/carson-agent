#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建 STUDIO/short_to_long.json：把每支「已發布 Short」對到最相關的「已發布長片」，
供 daily_publish._long_link_for 做 Short→長片精準連看(現無此檔→所有 Short 只軟導頻道首頁)。

做法:用 slug 的 bigram 題材相似度(Jaccard)挑最像的長片——比脆弱的 funnel parent 對應穩,
且 funnel 切出來的 Short 本就與母長片高度同題材,自然會被對到母片。門檻以下(找不到夠像的)就不寫,
該 Short 於發布時 fallback 回頻道首頁(既有行為)。任何缺檔/例外→產空檔或保留現狀,絕不崩。

排程:每日發布前跑(cron 06:50),確保 12:30 上架時 _long_link_for 拿得到對應長片。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"          # {slug: videoId}
OUT_JSON = STUDIO / "short_to_long.json"          # {short_slug: long_slug}
THRESH = 0.15                                     # bigram Jaccard 最低相似度,以下不對應(0.15 濾掉泛匹配套話重疊,只留高信心同題材)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _bigrams(slug: str) -> set:
    """slug 去 L_/S_ 前綴、只留中英數,回字元 bigram 集合(題材相似度用)。"""
    s = re.sub(r"^[SL]_+", "", slug or "")
    s = re.sub(r"[^0-9A-Za-z一-鿿]+", "", s).lower()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build() -> dict:
    try:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:  # noqa: BLE001
        ledger = {}
    if not isinstance(ledger, dict):
        ledger = {}
    longs = [k for k in ledger if k.startswith("L_") and ledger.get(k)]
    shorts = [k for k in ledger if k.startswith("S_") and ledger.get(k)]
    mapping: dict = {}
    if longs and shorts:
        long_bg = {l: _bigrams(l) for l in longs}
        for s in shorts:
            sb = _bigrams(s)
            best, best_sc = None, 0.0
            for l in longs:
                sc = _jaccard(sb, long_bg[l])
                if sc > best_sc:
                    best_sc, best = sc, l
            if best and best_sc >= THRESH:
                mapping[s] = best     # 值=長片 slug;_long_link_for 會用 ledger 解析成 youtu.be
    try:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[short_to_long] 寫檔失敗(保留現狀):{exc}", file=sys.stderr)
        return mapping
    return mapping


if __name__ == "__main__":
    m = build()
    print(f"[short_to_long] 已建 {len(m)} 筆 short→long 對應 -> {OUT_JSON}")
