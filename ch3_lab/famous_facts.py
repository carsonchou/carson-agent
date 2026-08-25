#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""famous_facts.py — 把名案(power posing、意志力耗損…)的數字從論文摘要抓下來。

## 為什麼名案要走另一條路
FReD 是「一篇原始研究 對 一篇重複研究」的配對表,名案不在裡面——它們對應的是
**綜合分析或多實驗室聯合重複**。那反而是更硬的敘事:不是「另一組人也做了一次」,
而是「K 個實驗室、總共 N 個人一起測」。

## 溯源是這支的重點
每個抓到的數字都連同**它出自摘要的哪一句**一起存。沒有這個,我沒辦法在寫稿前
一個一個驗;而這個頻道唯一的資產就是數字沒有一個是編的。
抓不到就標 MISSING,由我補讀原文——**不猜、不推估、不留空位給模板填**。

## 資料來源
OpenAlex(abstract_inverted_index 可還原摘要)。之前打到限流過,所以這裡只跑
7~26 個 DOI 並且每次間隔 1.5 秒,失敗退避重試。
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "facts" / "famous"
EMAIL = "moneycometomywallet@gmail.com"
UA = f"carson-agent/1.0 (mailto:{EMAIL})"

RE_N = re.compile(r"\b(?:N|n)\s*=\s*([\d,]{2,})|\b([\d,]{3,})\s+(?:participants|subjects|people)\b")
RE_ES = re.compile(r"\b(?:Cohen'?s\s*)?([dgr])\s*=\s*(-?\d*\.\d+)")
RE_CI = re.compile(r"95\s*%?\s*(?:CI|confidence interval)[^\d\-\[\(]{0,16}[\[\(]?\s*"
                   r"(-?\d*\.\d+)\s*[,;to]{1,2}\s*(-?\d*\.\d+)")
RE_K = re.compile(r"\b(\d{1,3})\s+(?:studies|samples|experiments|labs|laboratories|sites)\b")


def fetch(url, tries=4, timeout=45):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(8 * (i + 1))
                continue
            raise
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))


def abstract_of(work):
    """OpenAlex 存的是倒排索引,要還原成文字。"""
    inv = work.get("abstract_inverted_index")
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def harvest(claim, doi):
    """抓一篇。每個數字都附上出處句子。"""
    d = doi.replace("https://doi.org/", "")
    url = (f"https://api.openalex.org/works/doi:{urllib.parse.quote(d)}"
           f"?mailto={EMAIL}")
    try:
        w = json.loads(fetch(url).decode("utf-8", "replace"))
    except Exception as e:
        return {"claim": claim, "doi": doi, "status": "FETCH_FAIL", "err": str(e)[:80]}

    abst = abstract_of(w)
    rec = {"claim": claim, "doi": doi,
           "title": (w.get("title") or "")[:160],
           "year": w.get("publication_year"),
           "journal": ((w.get("primary_location") or {}).get("source") or {}).get(
               "display_name", "")[:80],
           "cited_by": w.get("cited_by_count"),
           "abstract_chars": len(abst),
           "found": {"n": [], "effect": [], "ci": [], "k": []}}
    if not abst:
        rec["status"] = "NO_ABSTRACT"
        return rec

    for s in sentences(abst):
        for m in RE_N.finditer(s):
            rec["found"]["n"].append({"value": (m.group(1) or m.group(2)), "src": s[:220]})
        for m in RE_ES.finditer(s):
            rec["found"]["effect"].append({"kind": m.group(1), "value": m.group(2),
                                           "src": s[:220]})
        for m in RE_CI.finditer(s):
            rec["found"]["ci"].append({"lo": m.group(1), "hi": m.group(2), "src": s[:220]})
        for m in RE_K.finditer(s):
            rec["found"]["k"].append({"value": m.group(1), "src": s[:220]})

    f = rec["found"]
    rec["status"] = "USABLE" if (f["n"] and f["effect"]) else "PARTIAL"
    rec["abstract"] = abst
    return rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bank = json.loads((ROOT / "facts" / "bank_scan.json").read_text(encoding="utf-8"))
    want = [b for b in bank if b["verdict"] in ("STRONG", "PARTIAL") and b.get("doi")]
    want.sort(key=lambda b: (b["verdict"] != "STRONG", -b["cited_by"]))
    print(f"要抓 {len(want)} 篇(STRONG 優先,再按被引用數)\n")

    rows = []
    for b in want:
        rec = harvest(b["claim"], b["doi"])
        rows.append(rec)
        f = rec.get("found", {})
        print(f"  {b['claim']:<34}{rec['status']:<12}"
              f"N×{len(f.get('n', []))} 效果×{len(f.get('effect', []))} "
              f"CI×{len(f.get('ci', []))} k×{len(f.get('k', []))}")
        slug = re.sub(r"[^a-z0-9]+", "_", b["claim"].lower()).strip("_")
        (OUT / f"{slug}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1.5)

    ok = sum(1 for r in rows if r["status"] == "USABLE")
    print(f"\n可用 {ok} / {len(rows)}(可用 = 摘要裡同時有樣本數與效果量)")
    print(f"檔案寫在 {OUT}")
    print("⚠️  下一步是**我逐篇讀 src 句子確認數字的意思**再寫稿——"
          "正則抓得到不等於抓對了。")


if __name__ == "__main__":
    main()
