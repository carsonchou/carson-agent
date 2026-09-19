# -*- coding: utf-8 -*-
"""同稿自相矛盾掃描 —— **只報告,不阻斷,不搬檔**。

用法:
    python selfcontra_cli.py <檔案或目錄> [--ext .voice.txt] [--json 輸出.json]
                             [--tol 1.0] [--since YYYY-MM-DD]

🔴 這支**沒有 --gate**,而且刻意不做。
   memory `yt-period-swap-integrity`:我上次在這個區域「修一修」,產線停了兩天;
   memory `gate-verification-population`:動會擋產出的閘門前要先量三個母體。
   升級成閘門的條件寫在 GATE_UPGRADE_CRITERIA.md,目前一條都不成立。

exit code:
    永遠 0。看到非 0 就是**這支自己壞了**,不是產線的問題,不要為它停任何東西。
    它到底跑了沒 → 看輸出的 scanned 數字(全語料 ≈900),**是 0 才叫壞了**;
    別拿 flagged 空不空判斷,空有兩種讀法。
"""

import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from numerus.selfcontra import (TOL, find_contradictions,   # noqa: E402
                                foreign_tokens_from_filename)


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
    for root, _dirs, files in os.walk(target):
        for f in sorted(files):
            if f.endswith(ext):
                yield os.path.join(root, f)


def arg(argv, flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    target = argv[1]
    ext = arg(argv, "--ext", ".voice.txt")
    tol = float(arg(argv, "--tol", TOL))
    since = arg(argv, "--since")
    since_ts = None
    if since:
        since_ts = dt.datetime.strptime(since, "%Y-%m-%d").timestamp()

    scanned = in_domain = 0
    rows = []
    for path in iter_files(target, ext):
        if since_ts and os.path.getmtime(path) < since_ts:
            continue
        scanned += 1
        fname = os.path.basename(path)
        cs = find_contradictions(read(path), tol=tol,
                                 foreign_tokens=foreign_tokens_from_filename(fname))
        if not cs:
            continue
        rows.append({
            "path": path,
            "mtime": dt.date.fromtimestamp(os.path.getmtime(path)).isoformat(),
            "worst_pp": round(cs[0].spread, 2),
            "groups": [{
                "metric": c.metric,
                "strategy": c.strategy,
                "spread_pp": round(c.spread, 2),
                # 🔴 trigger = **這次指控的理由**(造成 spread 的那兩筆),
                #    和 readings(全部讀數)分開落檔。2026-09-10 總督導查出
                #    ALL-IN0050 那支「判決對、理由錯」,而當時的輸出裡
                #    看不出它是憑哪一對叫的 —— 只驗判決量出來的精確率
                #    不代表你以為的東西(memory
                #    `verification-claims-in-commit-messages`)。
                "trigger": {
                    "low": {"value": c.low.value, "sentence": c.low.sentence[:200]},
                    "high": {"value": c.high.value, "sentence": c.high.sentence[:200]},
                },
                "readings": [{"value": r.value, "vague": r.vague,
                              "sentence": r.sentence[:200]} for r in c.readings],
            } for c in cs],
        })

    rows.sort(key=lambda r: -r["worst_pp"])
    for r in rows:
        print("\n== %.1f pp  [%s]  %s" % (r["worst_pp"], r["mtime"], r["path"]))
        for g in r["groups"]:
            print("  [%s/%s] %.1f pp" % (g["metric"], g["strategy"], g["spread_pp"]))
            trig = g["trigger"]
            # 🔴 先印「憑哪一對叫的」。人要能只讀這兩行就判理由成不成立,
            #    不必自己從 readings 裡回推 min/max。
            for tag, rd in (("憑↓", trig["low"]), ("憑↑", trig["high"])):
                print("   %s %7.2f%%  %s" % (tag, rd["value"], rd["sentence"][:104]))
            seen = {(round(trig["low"]["value"], 2), trig["low"]["sentence"][:40]),
                    (round(trig["high"]["value"], 2), trig["high"]["sentence"][:40])}
            for rd in g["readings"]:
                k = (round(rd["value"], 2), rd["sentence"][:40])
                if k in seen:
                    continue
                seen.add(k)
                print("   其他 %7.2f%%%s %s"
                      % (rd["value"], "~" if rd["vague"] else " ", rd["sentence"][:104]))

    print("\n---- scanned=%d flagged=%d tol=%.1fpp ----" % (scanned, len(rows), tol))
    out = arg(argv, "--json")
    if out:
        payload = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
                   "scanned": scanned, "flagged": len(rows),
                   "tol_pp": tol, "rows": rows}
        tmp = out + ".tmp"
        # 🔴 tmp → 讀回 → replace(memory `write-truncates-before-it-fails`:
        #    open(p,"w") 先截斷後寫入,中途拋例外就剩 0 bytes,而空檔對下游是
        #    合法的「零筆」,零訊號)
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        with io.open(tmp, encoding="utf-8") as fh:
            back = json.load(fh)
        assert back["scanned"] == scanned and len(back["rows"]) == len(rows)
        os.replace(tmp, out)
        print("寫入 %s (scanned=%d)" % (out, scanned))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv))
