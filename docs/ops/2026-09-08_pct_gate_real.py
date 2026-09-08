# -*- coding: utf-8 -*-
"""探針二:在**真實候選語料**上,把「被抽出來的百分比宣稱」和「被擋下來的」分開數。

問題:合成句量到「非比較句的百分比 100% 放行」。
     那在真實旁白上,百分比宣稱到底有多少個、其中幾個被擋?被擋的是哪一種?

唯讀。不呼叫 check_slug(它掛 _observe_hook 會寫檔)。
"""
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(ROOT / "scripts"))
import fact_source_guard as fsg  # noqa: E402

assert Path(fsg.__file__).resolve() == (ROOT / "scripts" / "fact_source_guard.py").resolve()

def fingerprint():
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted((ROOT / "STUDIO").glob("*.json"))}

fp0 = fingerprint()
POOL = fsg.fact_pool()
slugs = fsg.pending_slugs()
print("[語料] 待發候選 slug 數 =", len(slugs))

n_with_text = 0
n_blocked = 0
claim_units = Counter()      # 所有被抽出的宣稱,按單位
bad_units = Counter()        # 被判無憑據的,按單位
bad_kind = Counter()         # 被擋的原因型別(比較句 / 假掛名 / 其他)
blocked_slugs = []

for s in slugs:
    try:
        t = fsg.slug_text(s)
    except Exception:
        continue
    if not t:
        continue
    n_with_text += 1
    claims = fsg.extract_claims(t)
    for c in claims:
        claim_units[fsg._unit_of_claim(c["raw"])] += 1
    bad = fsg.unsourced_claims(t, POOL)
    if bad:
        n_blocked += 1
        blocked_slugs.append((s, bad))
    for c in bad:
        u = fsg._unit_of_claim(c["raw"])
        bad_units[u] += 1
        if c["clause"].startswith("【假掛名"):
            bad_kind[u + "/假掛名"] += 1
        elif fsg._is_comparison_result(c["clause"], c["raw"]):
            bad_kind[u + "/比較結果句"] += 1
        else:
            bad_kind[u + "/一般句"] += 1

print("[語料] 有文字的 =", n_with_text, " 被擋 =", n_blocked,
      "(%.1f%%)" % (n_blocked * 100.0 / max(n_with_text, 1)))
print("\n所有被抽出的宣稱(按單位):", dict(claim_units.most_common()))
print("被判無憑據的宣稱(按單位):", dict(bad_units.most_common()))
print("被判無憑據的宣稱(按單位/型別):", dict(bad_kind.most_common()))

pct_all = claim_units.get("pct", 0)
pct_bad = bad_units.get("pct", 0)
print("\n⇒ 百分比宣稱:共 %d 個,被擋 %d 個 = %.2f%%" %
      (pct_all, pct_bad, pct_bad * 100.0 / max(pct_all, 1)))
for u in ("amount_wan", "multiple", "count"):
    a, b = claim_units.get(u, 0), bad_units.get(u, 0)
    if a:
        print("⇒ %-11s:共 %d 個,被擋 %d 個 = %.2f%%" % (u, a, b, b * 100.0 / a))

print("\n被擋的片(前 12 支):")
for s, bad in blocked_slugs[:12]:
    c = bad[0]
    print("  - %-46s | %s %s | %s" % (s[:46], c["value"], c["raw"], c["clause"][:46]))

fp1 = fingerprint()
print("\n[寫入證據] STUDIO/*.json 變動:", [k for k in set(fp0) | set(fp1) if fp0.get(k) != fp1.get(k)] or "無(0 個)")
