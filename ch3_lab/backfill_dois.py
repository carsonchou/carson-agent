#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_dois.py — 把佇列裡缺的 DOI 從 Crossref 補回來。

## 為什麼要做這個,而不是把閘門調鬆
`publish_meta.py` 對 DOI 是 fail-closed:湊不出兩個可查證的 DOI 就不准
進對外清單。實測有 4/19 集會被刷掉(DOI 欄是 `nan` 或 FReD 的內部鍵值
如 `wiebe_2004`)。

「讓更多東西通過」的改動在這條產線上是紅旗。正解是**去把真的 DOI 找回來**,
不是放寬 `is_doi()`。找不到就讓它被擋掉——少發一集,好過掛一個查不到的引用。

## 比對規則(寧可漏,不可錯)
Crossref 用標題搜尋會回一堆相近的東西。只在下列條件**全部**成立才採用:
- 標題正規化後的相似度 ≥ 0.90(去標點、小寫、壓空白)
- 年份差距 ≤ 1(出版年與線上年常差一年)
掛錯 DOI 比沒有 DOI 更糟——沒有 DOI 只是少一集,掛錯是指著別人的論文
說「這是我的數字來源」。

用法:
  python backfill_dois.py            # 只查,不寫
  python backfill_dois.py --apply
"""
import argparse
import difflib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
QUEUE = ROOT / "facts" / "episode_queue.csv"
EMAIL = "moneycometomywallet@gmail.com"
UA = f"carson-agent/1.0 (mailto:{EMAIL})"
SIM_MIN, YEAR_SLACK = 0.90, 1


def is_doi(v):
    v = str(v or "").strip().lower()
    return v.startswith("10.") or "doi.org/10." in v


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()


def lookup(title, year):
    """用標題問 Crossref。回 (doi, 對到的標題, 相似度) 或 None。"""
    q = urllib.parse.urlencode({"query.bibliographic": title[:200], "rows": 5,
                                "mailto": EMAIL})
    url = f"https://api.crossref.org/works?{q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            items = json.loads(r.read().decode("utf-8", "replace"))["message"]["items"]
    except Exception as e:                       # noqa: BLE001
        return None, f"查詢失敗 {str(e)[:50]}"
    want = norm(title)
    best = None
    for it in items:
        cand = (it.get("title") or [""])[0]
        sim = difflib.SequenceMatcher(None, want, norm(cand)).ratio()
        yr = None
        for k in ("published-print", "published-online", "issued"):
            if it.get(k, {}).get("date-parts", [[None]])[0][0]:
                yr = it[k]["date-parts"][0][0]
                break
        if best is None or sim > best[2]:
            best = (it.get("DOI"), cand, sim, yr)
    if not best or best[2] < SIM_MIN:
        return None, (f"最接近的只有 {best[2]:.2f} 相似度" if best else "無結果")
    if year and best[3] and abs(int(year) - int(best[3])) > YEAR_SLACK:
        return None, f"年份不符(來源 {year} vs Crossref {best[3]})"
    return best, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    q = pd.read_csv(QUEUE, low_memory=False)
    jobs = []
    for i, r in q.iterrows():
        for side, dcol, tcol, ycol in (("原始", "doi_o", "title_o", "year_o"),
                                       ("重複", "doi_r", "title_r", "year_r")):
            if not is_doi(r.get(dcol)):
                jobs.append((i, side, dcol, str(r.get(tcol) or ""),
                             r.get(ycol), str(r.get(dcol))))
    print(f"要補 {len(jobs)} 筆\n")

    fixed = 0
    for i, side, dcol, title, year, cur in jobs:
        if not title.strip():
            print(f"  ep{i:03d} {side}:來源連標題都沒有,無從查起")
            continue
        hit, why = lookup(title, year)
        if not hit:
            print(f"  ep{i:03d} {side}:找不到可信對應({why})")
            print(f"           標題「{title[:70]}」")
        else:
            doi, matched, sim, yr = hit
            print(f"  ep{i:03d} {side}:{doi}  相似度 {sim:.2f}  年 {yr}")
            print(f"           來源「{title[:66]}」")
            print(f"           對到「{matched[:66]}」")
            if a.apply:
                q.at[i, dcol] = doi
            fixed += 1
        time.sleep(1.2)

    print(f"\n可補 {fixed}/{len(jobs)} 筆")
    if a.apply and fixed:
        q.to_csv(QUEUE, index=False, encoding="utf-8")
        print(f"已寫回 {QUEUE.name}")
    elif not a.apply:
        print("(未寫入,加 --apply 才會寫)")
    print("補不到的那幾集會被 publish_meta 的 fail-closed 擋下來——這是對的,"
          "不要為了湊數去放寬 is_doi()。")


if __name__ == "__main__":
    main()
