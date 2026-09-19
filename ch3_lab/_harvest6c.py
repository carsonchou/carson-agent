# -*- coding: utf-8 -*-
"""第三輪:PubMed(E-utilities)。

OpenAlex 空、Semantic Scholar 也空的那幾篇,PubMed 通常有全文摘要
—— 心理學期刊多半有 PMID。

三個來源都空的話就標 MISSING,由我自己去讀原文,**不用推估的數字補位**。
"""
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
DEST = ROOT / "facts" / "famous" / "demand6c.json"
UA = "carson-agent/1.0 (mailto:moneycometomywallet@gmail.com)"
E = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

WANT = [
    ("power_posing", "10.1177/0956797614553946", "power posing"),
    ("stereotype_threat", "10.1016/j.jsp.2014.10.002", "stereotype threat"),
    ("learning_styles", "10.1037/a0037478", "learning style"),
    ("10000_hour_rule", "10.1177/0956797614535810", "deliberate practice"),
]


def call(path, **kw):
    url = f"{E}/{path}?" + urllib.parse.urlencode(kw)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))


def main():
    recs = []
    for topic, doi, expect in WANT:
        try:
            s = call("esearch.fcgi", db="pubmed", term=f"{doi}[DOI]",
                     retmode="json")
            ids = json.loads(s)["esearchresult"]["idlist"]
        except Exception as e:
            ids = []
            print(f"  {topic:18s} 查詢失敗 {str(e)[:50]}")
        if not ids:
            recs.append({"topic": topic, "doi": doi, "status": "NO_PMID"})
            print(f"  {topic:18s} ⛔ PubMed 沒有這篇")
            time.sleep(1)
            continue
        xml = call("efetch.fcgi", db="pubmed", id=ids[0], retmode="xml")
        title = " ".join(re.findall(r"<ArticleTitle>(.*?)</ArticleTitle>",
                                    xml, re.S))
        parts = re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", xml, re.S)
        abst = re.sub(r"<[^>]+>", "", " ".join(parts))
        abst = re.sub(r"\s+", " ", abst).strip()
        title = re.sub(r"<[^>]+>", "", title).strip()
        ok = expect.split()[0].lower() in title.lower()
        recs.append({"topic": topic, "doi": doi, "pmid": ids[0],
                     "title": title, "abstract": abst,
                     "title_ok": ok, "status": "OK" if abst else "NO_ABSTRACT"})
        print(f"  {topic:18s}{'✓' if ok else '⛔'} PMID {ids[0]}  "
              f"摘要 {len(abst):>5d} 字  {title[:56]}")
        time.sleep(1)
    DEST.write_text(json.dumps(recs, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\n落檔 {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
