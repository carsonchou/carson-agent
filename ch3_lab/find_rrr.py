#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_rrr.py — 找「登記重複報告 / 多實驗室重測」來擴充名案線的跑道。

## 為什麼走這條路
全文路徑實測收穫很低:8 篇只解開 1 篇(4 篇 403 或非 PDF)。
而 Registered Replication Report、Many Labs、Multilab 這類論文**摘要本身**
就寫著「k 個實驗室、總 N、效果量、信賴區間」——那正是名案線需要的形狀,
不必碰全文。而且它們幾乎都是開放取用、方法事先登記,是最硬的證據型別。

## 判準(跟 famous_facts.py 一致:寧可漏,不可錯)
只收摘要裡**同時**找得到 效果量 + 樣本數 的;k 值有就記、沒有不猜。
抓到之後仍然要我逐句讀 quote 才會進事實庫——正則抓得到不等於抓對了。

用法:
  python find_rrr.py            # 只列出,不寫入
  python find_rrr.py --json out.json
"""
import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
EMAIL = "moneycometomywallet@gmail.com"
UA = f"carson-agent/1.0 (mailto:{EMAIL})"

QUERIES = ["Registered Replication Report", "Many Labs replication",
           "multilab preregistered replication", "large-scale replication psychology"]

RE_ES = re.compile(r"\b(?:Cohen'?s\s*)?([dgr])\s*=\s*(-?\d*\.\d+)")
RE_N = re.compile(r"\bN\s*=\s*([\d,]{3,})|\b([\d,]{3,})\s+participants\b")
RE_CI = re.compile(r"95\s*%?\s*(?:CI|confidence interval)[^\d\-\[\(]{0,16}[\[\(]?\s*"
                   r"(-?\d*\.\d+)\s*[,;]\s*(-?\d*\.\d+)")
RE_K = re.compile(r"\b(?:k\s*=\s*)?(\d{1,3})\s+(?:labs|laboratories|sites|samples|"
                  r"studies|experiments|replications)\b", re.I)


def fetch(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:                        # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def abstract_of(w):
    inv = w.get("abstract_inverted_index")
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()

    seen, hits = set(), []
    for q in QUERIES:
        url = ("https://api.openalex.org/works?"
               + urllib.parse.urlencode({
                   "search": q, "per-page": 50, "mailto": EMAIL,
                   "filter": "publication_year:>2010,has_abstract:true"}))
        try:
            items = fetch(url)["results"]
        except Exception as e:                   # noqa: BLE001
            print(f"  查詢「{q}」失敗:{str(e)[:60]}")
            continue
        for w in items:
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            if not doi or doi in seen:
                continue
            seen.add(doi)
            ab = abstract_of(w)
            if len(ab) < 200:
                continue
            es = RE_ES.findall(ab)
            ns = [x or y for x, y in RE_N.findall(ab)]
            if not (es and ns):
                continue
            hits.append({
                "title": (w.get("title") or "")[:130],
                "year": w.get("publication_year"),
                "doi": doi,
                "cited_by": w.get("cited_by_count"),
                "journal": ((w.get("primary_location") or {}).get("source") or {})
                           .get("display_name", "")[:50],
                "effects": [f"{k}={v}" for k, v in es[:5]],
                "samples": ns[:4],
                "cis": [f"[{x}, {y}]" for x, y in RE_CI.findall(ab)[:3]],
                "k": [m for m in RE_K.findall(ab)[:4]],
                "abstract": ab,
            })
        time.sleep(1.5)

    hits.sort(key=lambda h: -(h["cited_by"] or 0))
    print(f"找到 {len(hits)} 篇摘要同時有效果量與樣本數的重測論文\n")
    for h in hits[:25]:
        print(f"  {h['year']}  引用 {h['cited_by']:>5}  {h['title'][:78]}")
        print(f"        {h['journal'][:44]}")
        print(f"        效果量 {h['effects']}  N {h['samples']}  "
              f"CI {h['cis']}  k {h['k']}")
    if a.json:
        pathlib.Path(a.json).write_text(
            json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已寫 {a.json}")
    print("\n⚠️ 這只是候選。要進事實庫必須我逐句讀 abstract 確認每個數字的意思——"
          "正則抓得到不等於抓對了(先前踩過:抓到的 N 是對照組人數不是總數)。")


if __name__ == "__main__":
    main()
