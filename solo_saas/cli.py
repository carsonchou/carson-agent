# -*- coding: utf-8 -*-
"""numerus — 財經文字的同段可驗算檢查。

用法:
    python cli.py <檔案或目錄> [--ext .voice.txt] [--gate]

預設**只報告不擋**。--gate 才讓 CONTRADICTED 變成 exit 1。
🔴 BARE 永遠不影響 exit code,理由見 README「為什麼 BARE 不能當閘門」。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from numerus.check import BARE, CONSISTENT, CONTRADICTED, check_text


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def iter_files(target, ext):
    if os.path.isfile(target):
        yield target
        return
    for root, _, files in os.walk(target):
        for f in sorted(files):
            if f.endswith(ext):
                yield os.path.join(root, f)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = argv[1]
    ext = argv[argv.index("--ext") + 1] if "--ext" in argv else ".txt"
    gate = "--gate" in argv
    quiet = "--quiet" in argv

    tally = {CONTRADICTED: 0, BARE: 0, CONSISTENT: 0}
    total = flagged = 0
    for path in iter_files(target, ext):
        total += 1
        fs = check_text(read(path))
        if not fs:
            continue
        for f in fs:
            tally[f.verdict] += 1
        hits = [f for f in fs if f.verdict != CONSISTENT]
        if not hits:
            continue
        flagged += 1
        if quiet and not any(f.verdict == CONTRADICTED for f in hits):
            continue
        print("\n== %s" % os.path.basename(path))
        for f in hits:
            print("  [%s] %s" % (f.verdict, f.claim.raw))
            if f.verdict == CONTRADICTED:
                best = min(f.candidates, key=lambda kv: abs(kv[1] - f.claim.amount))
                print("      同段算得出來的最接近值:%s = %s 元"
                      % (best[0], format(best[1], ",.0f")))
                print("      稿子寫的是:%s 元" % format(f.claim.amount, ",.0f"))
            elif f.implied_principal:
                print("      反解:這句要成立,本金得是 %s 元"
                      % format(f.implied_principal, ",.0f"))
            print("      原句:%s" % f.claim.segment[:70])

    print("\n---- 掃過 %d 個檔,%d 個有標記 ----" % (total, flagged))
    print("CONTRADICTED=%d  BARE=%d  CONSISTENT=%d"
          % (tally[CONTRADICTED], tally[BARE], tally[CONSISTENT]))
    return 1 if (gate and tally[CONTRADICTED]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
