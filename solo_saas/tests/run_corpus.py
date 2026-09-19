# -*- coding: utf-8 -*-
"""跑語料。陽性抓不到 或 陰性被誤殺 → exit 1。"""
import io, json, os, sys

try:   # cp950 主控台會把繁中輸出印成亂碼 —— 讀不懂的測試報告等於沒有報告
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from numerus.check import CONTRADICTED, check_text, worst

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(HERE, "corpus.json"), encoding="utf-8"))

fails = []
for c in data["cases"]:
    fs = check_text(c["text"])
    got = worst(fs) if fs else "NO_CLAIM"
    exp = c["expect"]
    ok = (got != CONTRADICTED) if exp == "NOT_CONTRADICTED" else (got == exp)
    # 選用:針對**單一條宣稱**的判決。worst() 是整段的總結論,一句話裡只要
    # 有另一條合理地判成 BARE,總結論就被拉下去 —— 那會讓「我要驗的那一條
    # 對得上」這件事講不出口。expect_claims 讓語料可以指名道姓。
    detail = []
    for raw, want in c.get("expect_claims", {}).items():
        hit = [f for f in fs if raw in f.claim.raw]
        got1 = hit[0].verdict if hit else "NO_CLAIM"
        if got1 != want:
            ok = False
            detail.append("%s 期望 %s 得到 %s" % (raw, want, got1))
    print(("  ok  " if ok else "  FAIL") + "  %-22s expect=%-16s got=%s" % (c["id"], exp, got))
    for f in fs:
        extra = ""
        if f.verdict == CONTRADICTED:
            best = min(f.candidates, key=lambda kv: abs(kv[1] - f.claim.amount))
            extra = "  最接近的算法:%s = %s" % (best[0], format(best[1], ",.0f"))
        elif f.implied_principal:
            extra = "  反解本金 = %s 元" % format(f.implied_principal, ",.0f")
        print("        - %-8s %-10s%s" % (f.verdict, f.claim.raw, extra))
    for d in detail:
        print("        ! " + d)
    if not ok:
        fails.append(c["id"])

print("\n%d/%d 通過" % (len(data["cases"]) - len(fails), len(data["cases"])))
if fails:
    print("失敗:" + ", ".join(fails))
sys.exit(1 if fails else 0)
