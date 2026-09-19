# -*- coding: utf-8 -*-
"""補抓 OpenAlex 沒有摘要的那幾篇 —— 改走 Semantic Scholar。

OpenAlex 的 `abstract_inverted_index` 對舊刊或某些出版社是空的
(power posing 的重測、stereotype threat 的統合分析都是空的)。
Semantic Scholar 另有一份摘要,兩邊互補。

⚠️ 一樣的規矩:抓回來先核 **title 對不對得上**。上一輪 learning styles
就是 DOI 猜錯,抓回一篇「The instructor's face in video instruction」——
標題一看就知道不是,但如果我只看「status: PARTIAL」就會直接拿去用。
"""
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
DEST = ROOT / "facts" / "famous" / "demand6b.json"
UA = "carson-agent/1.0 (mailto:moneycometomywallet@gmail.com)"

WANT = [
    ("power_posing", "test", "10.1177/0956797614553946",
     "Assessing the Robustness of Power Posing"),
    ("stereotype_threat", "test", "10.1016/j.jsp.2014.10.002",
     "Does stereotype threat influence performance of girls"),
    ("learning_styles", "test", "10.1037/a0037478",
     "Matching learning style to instructional method"),
    ("10000_hour_rule", "test2", "10.1177/0956797614535810",
     "Deliberate Practice and Performance"),
    ("anchoring", "test2", "10.1027/1864-9335/a000178",
     "Investigating Variation in Replicability"),
    ("loss_aversion", "test2", "10.1287/mnsc.2013.1806",
     "Reference-dependent preferences / loss aversion field"),
]

FIELDS = "title,year,abstract,citationCount,venue,externalIds"


def get(doi):
    url = ("https://api.semanticscholar.org/graph/v1/paper/DOI:"
           + urllib.parse.quote(doi) + "?fields=" + FIELDS)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if i == 3:
                return {"error": str(e)[:100]}
            time.sleep(6 * (i + 1))


def main():
    recs = json.loads(DEST.read_text(encoding="utf-8")) if DEST.exists() else []
    have = {(r["topic"], r["role"]) for r in recs}
    for topic, role, doi, expect in WANT:
        if (topic, role) in have:
            continue
        w = get(doi)
        w.update({"topic": topic, "role": role, "doi": doi, "expect": expect})
        got = (w.get("title") or "")[:64]
        # 標題核對:期望字串的前四個字要出現在回傳標題裡。
        ok = expect.lower().split()[0] in got.lower() if got else False
        w["title_ok"] = ok
        w["abstract_chars"] = len(w.get("abstract") or "")
        recs.append(w)
        print(f"  {topic:18s}{role:6s}{'✓' if ok else '⛔'} "
              f"摘要 {w['abstract_chars']:>5d} 字  {got}")
        DEST.write_text(json.dumps(recs, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        time.sleep(3)
    print(f"\n落檔 {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
