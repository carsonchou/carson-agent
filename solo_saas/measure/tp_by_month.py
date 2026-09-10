# -*- coding: utf-8 -*-
"""只用真陽性、按內容家族分開的按月表(第二版,標籤改用**精確路徑**)。

🔴 第一版用檔名關鍵字比對,踩到坑:同一檔股票有多支副本
   (堡達3537 有三支、廣閎科6693 兩支…),關鍵字一次命中好幾支,
   真陽性被灌成 19 支。⇒ 標籤一律綁**精確相對路徑**,而且要對帳:
   標到的支數必須正好 12 / 1 / 12,對不上就停。
   (memory `flattened-key-hides-evidence`:壓平 key 會讓證據在眼前消失。)

標籤來源:reaudit_out.txt 的排名 → findings §3 的三分類清單。
"""
import datetime as dt
import io
import os
import re
import sys

sys.path.insert(0, r"D:\carson-agent\solo_saas")
from numerus.selfcontra import (find_contradictions,  # noqa: E402
                                foreign_tokens_from_filename, readings_for)

CORPUS = r"D:\carson-agent\youtube_channel\output"
SCRATCH = os.path.dirname(os.path.abspath(__file__))

# findings §3 的三分類,用 reaudit_out.txt 的**排名**指名
RANK_A = [5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 25]
RANK_B = [24]
RANK_C = [1, 2, 3, 4, 14, 15, 16, 17, 18, 19, 22, 23]


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def load_labels():
    lab = {}
    for line in io.open(os.path.join(SCRATCH, "reaudit_out.txt"),
                        encoding="utf-8", errors="replace"):
        m = re.match(r"^\[(\d+)\]\s+[\d.]+ pp\s+(.+\.voice\.txt)\s*$", line.rstrip())
        if not m:
            continue
        n, rel = int(m.group(1)), m.group(2)
        k = "a" if n in RANK_A else "b" if n in RANK_B else "c" if n in RANK_C else None
        assert k, n
        lab[rel] = k
    assert len(lab) == 25, len(lab)
    assert sum(1 for v in lab.values() if v == "a") == 12
    assert sum(1 for v in lab.values() if v == "c") == 12
    return lab


def main():
    lab = load_labels()
    rows, seen = [], set()
    for root, _d, files in os.walk(CORPUS):
        for f in sorted(files):
            if not f.endswith(".voice.txt"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, CORPUS)
            t = read(p)
            ft = foreign_tokens_from_filename(f)
            cs = find_contradictions(t, foreign_tokens=ft)
            k = lab.get(rel)
            if k:
                seen.add(rel)
            rows.append({
                "rel": rel,
                "m": dt.date.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m"),
                "fam": "個股體檢" if "個股體檢" in f else "其他",
                "loc": ("正本" if os.path.dirname(rel) == "" else os.path.dirname(rel)),
                "dom": bool(readings_for(t, foreign_tokens=ft)),
                "flag": bool(cs),
                "k": k,
            })

    missing = set(lab) - seen
    assert not missing, missing
    flagged = [r for r in rows if r["flag"]]
    bad = [r["rel"] for r in flagged if not r["k"]]
    assert not bad, bad
    print("全部 %d / 定義域 %d / 被標記 %d / 標籤對上 %d"
          % (len(rows), sum(r["dom"] for r in rows), len(flagged), len(seen)))

    print("\n== 家族 × 分類(只看被標記的 25 支)==")
    for fam in ("個股體檢", "其他"):
        line = "  %-6s" % fam
        for k in ("a", "b", "c"):
            line += "  (%s)=%d" % (k, sum(1 for r in flagged
                                          if r["fam"] == fam and r["k"] == k))
        print(line)

    print("\n== 真陽性(a)所在目錄 ==")
    for loc in sorted({r["loc"] for r in flagged if r["k"] == "a"}):
        n = sum(1 for r in flagged if r["k"] == "a" and r["loc"] == loc)
        print("  %-12s %d" % (loc, n))

    months = sorted({r["m"] for r in rows})
    for fam in ("個股體檢", "其他"):
        print("\n== %s ==" % fam)
        print("| 月份 | 稿數 | 定義域 | 被標記 | (a)真陽性 | (a)/定義域 |")
        print("|------|-----:|-------:|-------:|----------:|-----------:|")
        for m in months:
            sub = [r for r in rows if r["m"] == m and r["fam"] == fam]
            if not sub:
                continue
            dom = sum(r["dom"] for r in sub)
            tp = sum(1 for r in sub if r["k"] == "a")
            print("| %s | %d | %d | %d | %d | %s |"
                  % (m, len(sub), dom, sum(r["flag"] for r in sub), tp,
                     ("%.1f%%" % (100.0 * tp / dom)) if dom else "—"))

    print("\n== 個股體檢:排掉 _bad_leak(已被別的閘門攔下、沒有出廠)==")
    print("| 月份 | 定義域 | (a)真陽性 | (a)/定義域 |")
    print("|------|-------:|----------:|-----------:|")
    for m in months:
        sub = [r for r in rows if r["m"] == m and r["fam"] == "個股體檢"
               and "_bad_leak" not in r["loc"]]
        dom = sum(r["dom"] for r in sub)
        tp = sum(1 for r in sub if r["k"] == "a")
        if dom:
            print("| %s | %d | %d | %.1f%% |" % (m, dom, tp, 100.0 * tp / dom))

    print("\n== 家族組成(定義域內)==")
    print("| 月份 | 定義域 | 個股體檢 | 其他 | 個股體檢佔比 |")
    print("|------|-------:|---------:|-----:|-------------:|")
    for m in months:
        sub = [r for r in rows if r["m"] == m and r["dom"]]
        if not sub:
            continue
        k = sum(1 for r in sub if r["fam"] == "個股體檢")
        print("| %s | %d | %d | %d | %.1f%% |"
              % (m, len(sub), k, len(sub) - k, 100.0 * k / len(sub)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
