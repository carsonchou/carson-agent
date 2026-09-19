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
            if _valid(v):
                return v
    return None


def _valid(v):
    """這一筆合不合格。**產線走這條**,不是只有手動跑 `python plain.py` 才驗。

    舊版的檢查全在 `__main__` 底下 —— 那等於沒有檢查:產線 import 進來
    永遠不會執行到。實測 3 行也照樣放行,而 `make_thumbs` 只畫 [0][1],
    第三行會被靜默吃掉。「宣告了沒接上」在這條線上已經犯過四次。
    """
    if not isinstance(v, dict):
        return False
    lines, spoken = v.get("lines"), v.get("spoken")
    if not isinstance(lines, list) or len(lines) != 2:
        return False
    if not all(isinstance(x, str) and x.strip() for x in lines):
        return False
    if not isinstance(spoken, str) or not spoken.strip().endswith("?"):
        return False
    # 數字一律由事實庫填,手寫句裡不該有。有數字就是有人手寫了一個
    # 沒經過溯源守門的值。
    if any(ch.isdigit() for ch in " ".join(lines) + spoken):
        return False
    return True


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
        assert _valid(v), k          # 同一個判準,不寫第二份
        long = max(len(x) for x in v["lines"])
        flag = "  ⚠ 偏長" if long > 26 else ""
        print(f"{k:34s} {v['lines'][0]} / {v['lines'][1]}{flag}")
        print(f"{'':34s} 唸:{v['spoken']}")
    print(f"\n{n} 支,全部有 lines + spoken")
