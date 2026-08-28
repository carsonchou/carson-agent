#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plain.py — 白話主張的**唯一**讀取點。

## 為什麼是一個模組而不是各自寫一份
縮圖(`make_thumbs`)和 Short 開場(`make_short`)現在講同一句話 ——
那是刻意的:觀眾在 feed 看到的第一個畫面,和點進去看到的第一個畫面,
必須是同一句,否則等於換了一支片。

而「同一句」如果由兩份程式各自去查 JSON,遲早會漂開。這條線上同型的錯
已經犯過八次(最近一次是 `chapter_times` 有兩份實作,驗證印的時間戳跟
實際寫進去的不一樣,而它整個存在的意義就是確認寫進去的是什麼)。所以
查表只有這裡一份。

## fail-closed
查不到就回 None,呼叫端不產那支。退回論文語言等於白做這次改版,而且
那種退化是**靜默的** —— 圖產得出來、片渲得出來,只是沒人看得懂。
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
PATH = ROOT / "facts" / "plain_claims.json"


def _load():
    if not PATH.exists():
        return {}
    return json.loads(PATH.read_text(encoding="utf-8"))


def get(*keys):
    """依序試多個鍵,回 {"lines": [l1, l2], "spoken": str} 或 None。

    鍵有三種寫法在流通:`publish_meta` 的 `dir`(eps/ep013)、
    `make_short` 的 `key`(ep013)、以及名案的 slug(ego_depletion)。
    這裡一次把三種都試掉,呼叫端不必知道自己手上是哪一種。
    """
    d = _load()
    for k in keys:
        if not k:
            continue
        for cand in (k, f"eps/{k}", f"eps_famous/{k}"):
            v = d.get(cand)
            if isinstance(v, dict) and v.get("lines") and v.get("spoken"):
                return v
    return None


def lines(*keys):
    v = get(*keys)
    return v["lines"] if v else None


def spoken(*keys):
    v = get(*keys)
    return v["spoken"] if v else None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = _load()
    n = 0
    for k, v in d.items():
        if k.startswith("_"):
            continue
        n += 1
        assert isinstance(v, dict), k
        assert len(v["lines"]) == 2, k
        assert v["spoken"].endswith("?"), k       # 開場是問句,不是斷言
        assert not any(ch.isdigit() for ch in " ".join(v["lines"])), k
        long = max(len(x) for x in v["lines"])
        flag = "  ⚠ 偏長" if long > 26 else ""
        print(f"{k:34s} {v['lines'][0]} / {v['lines'][1]}{flag}")
        print(f"{'':34s} 唸:{v['spoken']}")
    print(f"\n{n} 支,全部有 lines + spoken")
