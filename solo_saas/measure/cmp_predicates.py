# -*- coding: utf-8 -*-
"""把產線那道 `_long_mixed_period` 拿來跑同一批語料,和我的偵測器對照。

🔴 為什麼要跑,而不是用讀的:總督導給了一個外部基線(2026-08-20 掃 95 支個股體檢,
   77 支 81% 犯期間偷換)。要用那個 81% 當「閘門有沒有生效」的量度,
   前提是**兩個判準量的是同一件事**。用讀的只會得到我的印象,
   09-10 已經有一次「拿沒有鑑別力的東西當指紋」(33.8% 最大回撤)。所以直接跑。

   量出來:交集 **0 支** ⇒ 不可對照。

🔴 安全:只呼叫 `_long_mixed_period`(純判斷,只讀 STUDIO/stock_checkup_facts.json)。
   跑前後對 STUDIO 目錄做 mtime 快照比對,證明沒有寫到任何東西
   (memory `web-center-test-prod-misfire`:隔離邊界是被呼叫函式的整個依賴集合)。

⚠️ 快照會抓到**同時在跑的本機排程**的寫入,那不是本程序做的。已知雜訊只列一個
   (`local_cron.lock`),而且是分開印、不是靜音 —— 靜音等於把警報關掉
   (memory `verification-that-cannot-fail`)。分辨方法:跑一次「只 import 不呼叫」
   的陰性對照,那次應該 0 檔異動。
"""
import datetime as dt
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.join(REPO, "youtube_channel")
CORPUS = os.path.join(ROOT, "output")
STUDIO = os.path.join(ROOT, "STUDIO")
KNOWN_SCHEDULER_NOISE = {"local_cron.lock"}
sys.path.insert(0, os.path.join(REPO, "solo_saas"))


def snap(d):
    out = {}
    for r, _dd, ff in os.walk(d):
        for f in ff:
            p = os.path.join(r, f)
            try:
                out[p] = os.path.getmtime(p)
            except OSError:
                pass
    return out


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def main():
    before = snap(STUDIO)

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import produce_batch as pb
    from numerus.selfcontra import (find_contradictions,
                                    foreign_tokens_from_filename)

    rows = []
    for root, _d, files in os.walk(CORPUS):
        for f in sorted(files):
            if not f.endswith(".voice.txt"):
                continue
            p = os.path.join(root, f)
            t = read(p)
            slug = f[:-len(".voice.txt")]
            rows.append({
                "rel": os.path.relpath(p, CORPUS),
                "m": dt.date.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m"),
                "fam": "個股體檢" if "個股體檢" in f else "其他",
                "theirs": bool(pb._long_mixed_period(t, slug=slug)),
                "mine": bool(find_contradictions(
                    t, foreign_tokens=foreign_tokens_from_filename(f))),
            })

    after = snap(STUDIO)
    changed = [p for p in set(before) | set(after)
               if before.get(p) != after.get(p)]
    noise = [p for p in changed if os.path.basename(p) in KNOWN_SCHEDULER_NOISE]
    real = [p for p in changed if p not in noise]
    print("STUDIO 寫入檢查:%s"
          % ("乾淨(0 檔異動)" if not real else "🔴 有 %d 檔非預期異動 %s"
             % (len(real), real[:5])))
    if noise:
        print("  (另有 %d 檔已知排程雜訊:%s)"
              % (len(noise), ", ".join(sorted(os.path.basename(p) for p in noise))))

    n = len(rows)
    th = sum(r["theirs"] for r in rows)
    mi = sum(r["mine"] for r in rows)
    both = sum(1 for r in rows if r["theirs"] and r["mine"])
    print("\n全語料 %d 支:產線判準標 %d、我的標 %d、兩者都標 %d"
          % (n, th, mi, both))
    print("  我的 %d 支裡有 %d 支產線判準也標(%.0f%%)"
          % (mi, both, 100.0 * both / mi if mi else 0))
    print("  產線標的 %d 支裡只有 %d 支我也標(%.1f%%)"
          % (th, both, 100.0 * both / th if th else 0))

    print("\n== 產線判準:個股體檢家族的按月命中率(和 81% 基線同口徑)==")
    print("| 月份 | 個股體檢稿數 | 命中 | 命中率 |")
    print("|------|-------------:|-----:|-------:|")
    for m in sorted({r["m"] for r in rows}):
        sub = [r for r in rows if r["m"] == m and r["fam"] == "個股體檢"]
        if not sub:
            continue
        h = sum(r["theirs"] for r in sub)
        print("| %s | %d | %d | %.1f%% |" % (m, len(sub), h, 100.0 * h / len(sub)))

    print("\n== 同上,排掉 _bad_leak / _redo 等副本目錄(只算 output 根目錄正本)==")
    print("| 月份 | 個股體檢稿數 | 命中 | 命中率 |")
    print("|------|-------------:|-----:|-------:|")
    for m in sorted({r["m"] for r in rows}):
        sub = [r for r in rows if r["m"] == m and r["fam"] == "個股體檢"
               and os.path.dirname(r["rel"]) == ""]
        if not sub:
            continue
        h = sum(r["theirs"] for r in sub)
        print("| %s | %d | %d | %.1f%% |" % (m, len(sub), h, 100.0 * h / len(sub)))

    print("\n== 我標了、產線判準沒標的(這些是它的判準看不到的形狀)==")
    for r in rows:
        if r["mine"] and not r["theirs"]:
            print("   %s" % r["rel"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
