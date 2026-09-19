# -*- coding: utf-8 -*-
"""產線那道期間閘門:08-20 版 vs 現行版,跑同一批語料。

🔴 為什麼要兩版都跑,不能只跑現行版:
   總督導給的外部基線「81% 犯期間偷換」是 **2026-08-20** 量的,
   而 `_long_mixed_period` 在 **08-30**(commit aacc154d)被改寫放寬過。
   拿現行版去跑舊語料再跟 81% 比,量到的是**判準變了**,不是行為變了
   (memory `gate-blind-while-target-evolves` / `criteria-anchored-to-mutable-property`)。

08-20 那版直接從 git blob `530275cb` 取出來(不留副本檔,指紋就是 commit 本身),
該版函式自足、只 import `re`,可以獨立 exec。

自我驗證:mtime ≤ 2026-08-20 的個股體檢稿跑 08-20 版,命中數必須是 **77**
(= fix_period_disclaimer.py docstring 記的那個 77/95)。對不上就是重建錯了,直接 fail。
"""
import datetime as dt
import io
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(REPO, "youtube_channel", "output")
BLOB = "530275cb:youtube_channel/scripts/produce_batch.py"
CUTOFF = dt.date(2026, 8, 20)
EXPECT_HITS_AT_CUTOFF = 77


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def load_old_predicate():
    """從 git blob 切出 08-20 版的 _long_mixed_period,不落任何副本檔。"""
    src = subprocess.check_output(["git", "show", BLOB], cwd=REPO).decode("utf-8")
    lines = src.split("\n")
    start = next(i for i, l in enumerate(lines)
                 if l.startswith("def _long_mixed_period"))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].startswith("def "))
    ns = {}
    exec(compile("\n".join(lines[start:end]), "pb_0820", "exec"), ns)
    return ns["_long_mixed_period"], end - start


def main():
    old, nlines = load_old_predicate()
    sys.path.insert(0, os.path.join(REPO, "youtube_channel", "scripts"))
    import produce_batch as pb

    rows = []
    for root, _d, files in os.walk(CORPUS):
        for f in sorted(files):
            if not f.endswith(".voice.txt") or "個股體檢" not in f:
                continue
            p = os.path.join(root, f)
            t = read(p)
            slug = f[:-len(".voice.txt")]
            rows.append({
                "rel": os.path.relpath(p, CORPUS),
                "d": dt.date.fromtimestamp(os.path.getmtime(p)),
                "old": bool(old(t, slug=slug)),
                "new": bool(pb._long_mixed_period(t, slug=slug)),
            })
    print("08-20 版函式 %d 行(取自 git blob %s)" % (nlines, BLOB))
    print("個股體檢家族 %d 支\n" % len(rows))

    print("== 重建驗證:用他們當時的母體跑 08-20 版 ==")
    for name, sub in (
            ("mtime <= 08-20 全部", [r for r in rows if r["d"] <= CUTOFF]),
            ("mtime <= 08-20 只算正本",
             [r for r in rows if r["d"] <= CUTOFF and os.path.dirname(r["rel"]) == ""])):
        h = sum(r["old"] for r in sub)
        print("  %-24s n=%3d 命中=%3d  %.1f%%"
              % (name, len(sub), h, 100.0 * h / len(sub) if sub else 0))
    hits = sum(r["old"] for r in rows if r["d"] <= CUTOFF)
    assert hits == EXPECT_HITS_AT_CUTOFF, (
        "重建的 08-20 判準命中 %d,不是 docstring 記的 %d ⇒ 重建錯了,下面的表不能用"
        % (hits, EXPECT_HITS_AT_CUTOFF))
    print("  ✓ 命中數 %d = fix_period_disclaimer.py docstring 的 77/95\n" % hits)

    print("== 兩版判準的按月命中率(同一批稿)==")
    print("| 月份 | 個股體檢稿數 | 08-20判準 | 率 | 現行判準 | 率 |")
    print("|------|-------------:|----------:|---:|---------:|---:|")
    for m in sorted({r["d"].strftime("%Y-%m") for r in rows}):
        sub = [r for r in rows if r["d"].strftime("%Y-%m") == m]
        o, n = sum(r["old"] for r in sub), sum(r["new"] for r in sub)
        print("| %s | %d | %d | %.1f%% | %d | %.1f%% |"
              % (m, len(sub), o, 100.0 * o / len(sub), n, 100.0 * n / len(sub)))

    # 主頻道線 ab741661 的 49.3% 分母是「08-20 後累計、且已發布」。
    # 我沒有發布狀態可以切,只能把「時間軸」這一個軸換成累計,讓督導看到
    # 光換一個軸就會移動多少 —— 這是「兩個比率不可對照」的量化依據,不是對照本身。
    print("\n== 把時間軸換成累計之後(仍含未發布,發布狀態無法切)==")
    for name, sub in (
            ("2026-09 單月(文件裡的 44.8%)",
             [r for r in rows if r["d"].strftime("%Y-%m") == "2026-09"]),
            ("mtime > 08-20 累計(含副本)", [r for r in rows if r["d"] > CUTOFF]),
            ("mtime > 08-20 累計、只算正本",
             [r for r in rows if r["d"] > CUTOFF and os.path.dirname(r["rel"]) == ""])):
        h = sum(r["old"] for r in sub)
        print("  %-28s n=%3d 命中=%3d  %.1f%%"
              % (name, len(sub), h, 100.0 * h / len(sub) if sub else 0))
    print("  ⇒ 換一個軸就移動數個百分點;發布狀態那個軸沒有資料 ⇒ 和 49.3% 不可對照。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
