# -*- coding: utf-8 -*-
"""量:一個「無憑據的百分比」現在會不會被 fact_source_guard 擋下來。

儀器 = 產線那一把:daily_publish.py:588 → fsg.check_slug(s, fsg.fact_pool())
       → check_slug 內部只是 unsourced_claims(slug_text(slug), pool)。
       本探針直接呼叫 unsourced_claims(text, fact_pool()),**跳過 check_slug** 是刻意的:
       check_slug 掛了 _observe_hook 會寫檔(_obs_write),探針不可以動正式機檔案。
       跳過它不改變判定 —— check_slug 對 out 一個字都不動(fact_source_guard.py:1107-1113)。

判定語意:unsourced_claims 回空 list = 這段文字**過關**(可發布);回非空 = 被擋。
"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\carson-agent\youtube_channel")
sys.path.insert(0, str(ROOT / "scripts"))
import fact_source_guard as fsg  # noqa: E402

# ── 隔離斷言:確認載到的是主頻道那份,不是 yt_ch2 那份 ──
assert Path(fsg.__file__).resolve() == (ROOT / "scripts" / "fact_source_guard.py").resolve(), fsg.__file__
assert fsg.STUDIO.resolve() == (ROOT / "STUDIO").resolve(), fsg.STUDIO
print("[隔離] fact_source_guard.__file__ =", fsg.__file__)
print("[隔離] fsg.STUDIO =", fsg.STUDIO)

# ── 寫入證據:探針跑前後,STUDIO 下 json 的 mtime 不可以變 ──
def studio_fingerprint():
    out = {}
    for p in sorted((ROOT / "STUDIO").glob("*.json")):
        try:
            out[p.name] = (p.stat().st_mtime_ns, p.stat().st_size)
        except OSError:
            pass
    return out

fp_before = studio_fingerprint()

POOL = fsg.fact_pool()
TP = fsg.typed_fact_pool()
print("[池] 全域 fact_pool =", len(POOL), "個數字")
print("[池] typed pool:", {k: len(v) for k, v in sorted(TP.items())})


def blocked(text):
    """True = 被擋(有查無來源的數字)。"""
    return bool(fsg.unsourced_claims(text, POOL))


def hits(text):
    return fsg.unsourced_claims(text, POOL)


# ══════════════════════════════════════════════════════════════════
# 陽性對照 A:2026-07-13 那次真實捏造事故的原句(不是合成 fixture)
# ══════════════════════════════════════════════════════════════════
print("\n=== A. 真實案例陽性對照(07-13 捏造事故原句)===")
REAL_CASES = [
    "根據臺股十年資料,毛利率成長選股的勝率只有百分之三十一。",
    "回測顯示,毛利率成長選股的勝率只有百分之三十一。",
    "百分之六十七的個股在財報前三個月就反映完畢,報酬幾乎被吃光。",
    "實測發現百分之四十七的訂單失效,獲利直接歸零。",
    "回測顯示,當沖客的勝率只有百分之八十,其實七成被手續費吃掉。",
]
for t in REAL_CASES:
    h = hits(t)
    print(("  擋 " if h else "  放行"), t[:44], "|", [(c["value"], c["raw"]) for c in h][:3])

# ══════════════════════════════════════════════════════════════════
# B. 百分比值域全掃:0.1~100.0 每 0.1 一格 = 1000 個值
#    問的是「整個百分比值域裡,有多少比例是這道閘門會放行的」。
#    若接近 100%,則「捏造的百分比」與「真的百分比」在這道閘門上不可區分。
# ══════════════════════════════════════════════════════════════════
TEMPLATES = {
    "T1 一般績效句(勝率)": "根據臺股十年資料,這個策略的勝率是{v}%。",
    "T2 假掛名(回測顯示)": "回測顯示,這個策略的年化報酬率是{v}%。",
    "T3 一般績效句(總報酬)": "這檔股票二十年的總報酬是{v}%,遠遠贏過大盤。",
    "T4 比較結果句": "這個策略的報酬比大盤高出{v}%。",
}

print("\n=== B. 百分比值域全掃(0.1~100.0,step 0.1,n=1000)===")
vals_100 = [round(i * 0.1, 1) for i in range(1, 1001)]
B_pass = {}
for name, tpl in TEMPLATES.items():
    n_pass = 0
    passed_round10 = []
    for v in vals_100:
        vs = ("%g" % v)
        if not blocked(tpl.format(v=vs)):
            n_pass += 1
            if v % 10 == 0:
                passed_round10.append(v)
    B_pass[name] = n_pass
    print("  %-24s 放行 %4d/1000 = %5.1f%%   整十數放行: %s"
          % (name, n_pass, n_pass / 10.0, passed_round10))

# ══════════════════════════════════════════════════════════════════
# C. 大值域掃(101~2000,step 1)——個股體檢常見的長期總報酬量級
# ══════════════════════════════════════════════════════════════════
print("\n=== C. 大百分比值域掃(101~2000,step 1,n=1900)===")
vals_big = list(range(101, 2001))
for name, tpl in list(TEMPLATES.items())[:3]:
    n_pass = sum(1 for v in vals_big if not blocked(tpl.format(v=v)))
    print("  %-24s 放行 %4d/1900 = %5.1f%%" % (name, n_pass, n_pass * 100.0 / len(vals_big)))

# ══════════════════════════════════════════════════════════════════
# D. 陰性/陽性對照:金額型(交接檔說「金額型擋 98%」)
#    金額只在假掛名句被抽取,所以用假掛名句餵。
# ══════════════════════════════════════════════════════════════════
print("\n=== D. 金額型對照(假掛名句,1~500 萬,step 1,n=500)===")
AMT_TPL = "回測顯示,一年就少賺{v}萬,獲利全被手續費吃掉。"
amt_vals = list(range(1, 501))
n_amt_pass = sum(1 for v in amt_vals if not blocked(AMT_TPL.format(v=v)))
print("  放行 %d/500 = %.1f%%  ⇒ 擋 %.1f%%" %
      (n_amt_pass, n_amt_pass / 5.0, 100 - n_amt_pass / 5.0))

# ══════════════════════════════════════════════════════════════════
# E. 儀器自身的陽性對照:這個 harness 到底報不報得出「擋」?
#    用一個結構上一定擋的輸入(空池)驗證判定函式會翻面。
# ══════════════════════════════════════════════════════════════════
print("\n=== E. 儀器陽性對照(空池 → 同一句必須變成「擋」)===")
probe = TEMPLATES["T1 一般績效句(勝率)"].format(v="37.3")
print("  全域池:", "擋" if blocked(probe) else "放行")
print("  空池  :", "擋" if fsg.unsourced_claims(probe, set()) else "放行")

# ══════════════════════════════════════════════════════════════════
# F. _sourced_unit 這個述詞本身(總督導指名的那個函式)
# ══════════════════════════════════════════════════════════════════
print("\n=== F. 述詞層 _sourced_unit(raw='%',pct 單位)===")
for strict in (False, True):
    n = sum(1 for v in vals_100 if fsg._sourced_unit(v, "%g%%" % v, POOL, strict))
    print("  strict=%-5s 判定「有憑據」 %4d/1000 = %5.1f%%" % (strict, n, n / 10.0))

# ── 寫入證據回讀 ──
fp_after = studio_fingerprint()
changed = [k for k in set(fp_before) | set(fp_after) if fp_before.get(k) != fp_after.get(k)]
print("\n[寫入證據] STUDIO/*.json 於探針前後有變動的檔案:", changed or "無(0 個)")
