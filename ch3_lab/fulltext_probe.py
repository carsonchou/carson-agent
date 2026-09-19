#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fulltext_probe.py — 驗證「全文取數」能不能把題庫從 7 集擴到 24 集。

## 為什麼先驗這個
摘要掃描:50 題只有 7 題的摘要有硬數字,但 24 題全文開放。
全文能可靠取數 → 跑道 24 集;不行 → 只有 7 集。這是第二個承重假設。

## 為什麼用 Unpaywall 而不是 OpenAlex
OpenAlex 在本 session 已被我打到限流(429,退避重試也救不回)。
Unpaywall 是不同服務、專做「這個 DOI 的開放全文在哪」,而 DOI 我已經有快取。

## 判準(不是抓到數字就算過)
USABLE 要同時有:效果量 + 樣本數 + 信賴區間。半套做不出一集,而編造是紅線。
"""
import io
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
UA = "carson-agent/1.0 (mailto:moneycometomywallet@gmail.com)"
EMAIL = "moneycometomywallet@gmail.com"

TARGETS = ["Power posing", "Growth mindset", "Facial feedback",
           "Stereotype threat", "Grit", "Bilingual advantage",
           "Mozart effect", "Choice overload"]

RE_D = re.compile(r"\b(?:Cohen'?s\s*)?[dgr]\s*=\s*(-?\d?\.\d+)")
RE_N = re.compile(r"\bN\s*=\s*([\d,]{2,})|\b([\d,]{3,})\s+participants\b")
RE_CI = re.compile(r"95%\s*(?:CI|confidence interval)[^\d\-\[]{0,14}\[?\s*"
                   r"(-?\d?\.\d+)\s*[,;]\s*(-?\d?\.\d+)")


def fetch(url, timeout=45, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(6 * (i + 1))
                continue
            raise
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def pdf_text(raw):
    try:
        import fitz
        with fitz.open(stream=raw, filetype="pdf") as doc:
            return "\n".join(p.get_text() for p in doc)
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in rd.pages)
    except Exception as e:
        return f"__PARSE_FAIL__ {e}"


def probe(name, doi):
    out = {"claim": name, "doi": doi}
    d = doi.replace("https://doi.org/", "")
    try:
        j = json.loads(fetch(
            f"https://api.unpaywall.org/v2/{urllib.parse.quote(d)}?email={EMAIL}",
            timeout=30).decode("utf-8", "replace"))
    except Exception as e:
        out["status"] = "LOOKUP_FAIL"
        out["err"] = str(e)[:60]
        return out
    loc = j.get("best_oa_location") or {}
    pdf_url = loc.get("url_for_pdf") or loc.get("url")
    out.update(title=(j.get("title") or "")[:66], year=j.get("year"),
               is_oa=j.get("is_oa"))
    if not pdf_url:
        out["status"] = "NO_PDF"
        return out
    try:
        raw = fetch(pdf_url)
    except Exception as e:
        out["status"] = "FETCH_FAIL"
        out["err"] = str(e)[:60]
        return out
    if not raw[:5].startswith(b"%PDF"):
        out["status"] = "NOT_PDF"
        return out
    txt = pdf_text(raw)
    if txt.startswith("__PARSE_FAIL__"):
        out["status"] = "PARSE_FAIL"
        return out
    ds = [float(x) for x in RE_D.findall(txt)]
    ns = [a or b for a, b in RE_N.findall(txt)]
    cis = RE_CI.findall(txt)
    out.update(chars=len(txt), n_effect=len(ds), n_sample=len(ns), n_ci=len(cis),
               sample_effects=ds[:6], sample_Ns=ns[:4],
               sample_CIs=[f"[{a}, {b}]" for a, b in cis[:3]])
    out["status"] = "USABLE" if (ds and ns and cis) else "PARTIAL"
    return out


def main():
    bank = json.loads((ROOT / "facts" / "bank_scan.json").read_text(encoding="utf-8"))
    doi_of = {b["claim"]: b["doi"] for b in bank if b.get("doi")}
    rows = []
    for name in TARGETS:
        doi = doi_of.get(name)
        if not doi:
            print(f"  {name:<22}NO_DOI")
            continue
        r = probe(name, doi)
        rows.append(r)
        st = r["status"]
        line = f"  {name:<22}{st:<12}"
        if st in ("USABLE", "PARTIAL"):
            print(line + f"全文 {r['chars']:>6} 字  效果量 {r['n_effect']:>3}  "
                         f"樣本數 {r['n_sample']:>3}  CI {r['n_ci']:>3}")
            if r["sample_effects"]:
                print(f"{'':<24}效果量 {r['sample_effects']}")
            if r["sample_CIs"]:
                print(f"{'':<24}CI     {r['sample_CIs']}")
        else:
            print(line + str(r.get("err", "")))
        time.sleep(1.5)
    usable = sum(1 for r in rows if r["status"] == "USABLE")
    part = sum(1 for r in rows if r["status"] == "PARTIAL")
    print(f"\n{len(rows)} 篇 → 可用 {usable} / 半套 {part} / 取不到 "
          f"{len(rows) - usable - part}")
    (ROOT / "facts" / "fulltext_probe.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if rows:
        rate = usable / len(rows)
        print(f"外推:24 篇全文開放 × {rate:.0%} ≈ {round(24 * rate)} 集可做"
              f"(加上摘要即可用的 7 集)")


if __name__ == "__main__":
    main()
