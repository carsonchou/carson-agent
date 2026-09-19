#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建 STUDIO/short_to_long.json：把每支「已發布 Short」對到最相關的「已發布長片」，
供 daily_publish._long_link_for 做 Short→長片精準連看(現無此檔→所有 Short 只軟導頻道首頁)。

做法:用 slug 的 bigram 題材相似度(Jaccard)挑最像的長片——比脆弱的 funnel parent 對應穩,
且 funnel 切出來的 Short 本就與母長片高度同題材,自然會被對到母片。門檻以下(找不到夠像的)就不寫,
該 Short 於發布時 fallback 回頻道首頁(既有行為)。任何缺檔/例外→產空檔或保留現狀,絕不崩。

排程:每日發布前跑(cron 06:50),確保 12:30 上架時 _long_link_for 拿得到對應長片。

2026-07-10 連看覆蓋率補強(YT終極強化任務):THRESH 從 0.15 降到 0.10——實測抽驗全部候選片,
0.10~0.15 這段新增的 24 筆對應(見 docs/REPORTS/2026-07-10_連看與QA.md)逐筆人工核對過,全部同題材
(0050/ETF、BTC/網格、回測87勝率系列彼此之間),無亂配案例,只是既有 0.15 門檻漏接的合理配對，
故調降為新預設(只增加覆蓋率、不影響任何既有 >=0.15 的對應，因為门槛调低只会放行更多候选，
不会改变每支 short 的 argmax 结果)。
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
THRESH = 0.10                                     # bigram Jaccard 最低相似度,以下不對應
                                                   # (2026-07-10 前為 0.15；降到 0.10 後人工抽驗
                                                   # 0.10~0.15 這段新增配對皆同題材、無亂配，見上方註記)

# 「回測陷阱」礦脈系列——量化方法論陷阱關鍵詞，供 build_short_to_short.py 的同系列比對沿用
# (放在這支而非 build_short_to_short.py，維持「同一套判斷邏輯只寫一份」慣例，
# 兩支腳本本來就已經互相 import _bigrams/_jaccard)。
VEIN_CONCEPTS = {
    "walk_forward": ["walk-forward", "walkforward"],
    "oos": ["樣本外"],
    "overfit": ["過擬合"],
    "lookahead": ["前視偏差"],
    "survivorship": ["倖存者偏差", "生存者偏差", "存活者偏差"],
    "sharpe": ["夏普"],
    "ci": ["信賴區間"],
    "slippage": ["滑點", "隱形殺手"],
}


def _vein_concepts(slug: str) -> set:
    """slug 命中哪些「回測陷阱」礦脈概念關鍵詞(可能命中 0~多個)。純子字串比對(不靠 bigram
    模糊分數)，因為 bigram 分數在「回測87勝率是假的...」這類共用套話 hook 下常被無關但套話
    重疊度高的片搶走(例：「前視偏差」候選片 bigram 最高分反而是完全不同概念的「Python實測
    拆穿三招陷阱」)，關鍵詞精準比對才抓得到真正同概念的片。"""
    s = (slug or "").lower()
    out = set()
    for concept, kws in VEIN_CONCEPTS.items():
        for kw in kws:
            if kw.lower() in s:
                out.add(concept)
                break
    return out

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
    # 短片鍵集=已發布 Short + 「已渲染待上架」Short(output 有 voice.txt 但還沒進 ledger)。
    # 只收已發布會與 _long_link_for(在 Short 即將上架、尚未進 ledger 當下查詢)鍵集互斥→連結永遠 fallback 首頁。
    shorts = [k for k in ledger if k.startswith("S_") and ledger.get(k)]
    _seen = set(shorts)
    for _f in (ROOT / "output").glob("S_*.voice.txt"):
        _slug = _f.name[:-len(".voice.txt")]
        if _slug.endswith("_ytcta") or _slug in _seen:
            continue
        _seen.add(_slug)
        shorts.append(_slug)
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
