#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重生自環率:連續兩稿的失敗理由是不是同一個。

用法:
    cd youtube_channel
    .venv/Scripts/python.exe tests/regen_feedback/selfloop.py            # 全部
    .venv/Scripts/python.exe tests/regen_feedback/selfloop.py --since 09-04

## 這是唯一真正的驗收指標

`produce_batch` 的重生迴圈原本**沒有回饋**:失敗原因算出來、寫進 log,然後丟掉 ——
`call_claude()` 的簽章接不住它。所以三次重生是三個位元組相同的呼叫,只差取樣隨機性。
**那不是「重生沒收斂」,是沒有迴圈。**

而 memory 記著「新稿殘餘率 23.1% ⇒ fail-closed 約 1.2%」——0.231³ = 1.23%,
**立方關係只在獨立重抽下成立**。獨立性從來沒被驗過,而整個良率預期建立在它上面。

⚠️ **不要用「良率上升」當證據**:良率單日在 0~96% 之間擺,單日變化說明不了任何事。
要看的是自環率:同一支片連續兩稿的失敗理由相同的比例。

改動落在 2026-09-03(retry_reason/retry_n),所以:
    --since 之前 = 基準(實測 57.1%,n=28)
    --since 09-04 起 = 改動後,要拿新產的稿重量
"""
import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LOG = ROOT / "STUDIO" / "ops_log.txt"
# 兩條重生路徑各自的 log 格式(這條線今天才因為「同一件事兩處只改一處」出過事,
# 所以量的時候兩條都要收)
LINE = re.compile(
    r"^\[(\d\d-\d\d) [\d:]+\] 補產·重生｜"
    r"(?:A4長片第(\d+)次重生|鎖題長片終檢第(\d+)次重生):(.+?)｜(.+)$")


def family(reason):
    """把理由歸成家族——比字面相同更嚴格地看「有沒有換一種失敗」。
    字面相同一定同家族;家族相同但字面不同(例:兩種長度訊息)仍算自環。"""
    for key in ("長度不足", "段數", "資訊密度", "期間", "矛盾", "洩漏", "碎句", "跑題"):
        if key in reason:
            return key
    return reason[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="只看這個日期(MM-DD)之後")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    runs = collections.defaultdict(list)      # 片名 → [(第幾次, 理由)]
    for ln in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(ln.strip())
        if not m:
            continue
        day, n1, n2, reason, title = m.groups()
        if a.since and day < a.since:
            continue
        runs[title.strip()].append((int(n1 or n2 or 0), reason.strip()))

    pairs, same, trans = 0, 0, collections.Counter()
    for _title, seq in runs.items():
        seq.sort()
        for (_, r1), (_, r2) in zip(seq, seq[1:]):
            pairs += 1
            f1, f2 = family(r1), family(r2)
            same += f1 == f2
            trans[(f1, f2)] += 1

    win = f"(--since {a.since})" if a.since else "(全部)"
    print(f"重生日誌 {win}:{len(runs)} 支片、連續兩稿 {pairs} 組\n")
    if not pairs:
        print("⚠️ 沒有可比的連續兩稿 —— 這**不是**「自環率 0」,是沒有資料。")
        print("   改動後要重量,需要新產的稿(每次重生 = 一次 LLM 大呼叫)。")
        return 2
    print(f"🔴 自環率(連續兩稿同一家族):{same}/{pairs} = {same / pairs * 100:.1f}%")
    print("   基準:2026-09-03 改動前實測 57.1%(n=28)\n")
    print("轉移(前一稿 → 後一稿),前 10:")
    for (f1, f2), c in trans.most_common(10):
        mark = "  ← 自環" if f1 == f2 else ""
        print(f"   {c:>3}  {f1} → {f2}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
