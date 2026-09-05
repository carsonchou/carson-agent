#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_score_watch.py — BRAIN 積分盯哨：分數一動就 Telegram 通知 Carson。

## 為什麼
平台**一天只結算一次**（ET 03:00 = 台北 15:00），而 Carson 一直在問「現在幾分」。
與其他反覆手動查，不如刷新後自動量一次、有變動才推播。

## 時區（實測，別再算錯）
· 計分日分界 = ET 00:00 = **台北中午 12:00**（台北的一天橫跨平台兩個計分日）
· 結算刷新   = ET 03:00 = **台北 15:00**
→ 本檔排在台北 15:15，刷新後 15 分鐘。

## 只讀不寫
只呼叫 GET，不模擬也不提交，不佔用那 2 個併發槽。

## 判準
與 `score_history.jsonl` 的前一筆比對：score / level / 已提交數 任一有變才推播。
沒變就靜默結束（不要拿沒事吵人）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

BRAIN = (Path(__file__).resolve().parent.parent.parent
         / "quant-service" / "brain_alpha")
sys.path.insert(0, str(BRAIN))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import brain_auto as B

    hist_path = BRAIN / "score_history.jsonl"
    prev = None
    if hist_path.exists():
        for line in io.open(hist_path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    prev = json.loads(line)
                except Exception:  # noqa: BLE001
                    pass

    s = B.auth()
    cur = B.track_score(s)          # 這一步會自己 append 一筆快照

    def score_of(rec):
        c = (rec or {}).get("competitions") or [{}]
        return (c[0] or {}).get("score"), (c[0] or {}).get("rank")

    pc = (prev or {}).get("consultant_http")
    cc = cur.get("consultant_http")
    ps, pr = score_of(prev)
    cs, cr = score_of(cur)
    changed = (cs != ps) or (cur.get("level") != (prev or {}).get("level")) \
        or (cur.get("submitted_total") != (prev or {}).get("submitted_total")) \
        or (cc != pc)

    print(f"score {ps} → {cs} | rank {pr} → {cr} | "
          f"level {(prev or {}).get('level')} → {cur.get('level')} | "
          f"consultant {pc} → {cc}")

    if not changed:
        print("無變動，不推播。")
        return 0

    delta = ""
    try:
        if ps is not None and cs is not None:
            delta = f"（+{cs - ps:,.0f}）"
    except Exception:  # noqa: BLE001
        pass
    # 🔴 rank 在 Challenge 榜消失後是 None，而 f"{None:,}" 會丟 TypeError。
    #    舊版寫死 {pr:,}：只要榜不在的時候有任何欄位變動，
    #    推播會炸在組字串這一行，一則都發不出去。
    #    而它壞得很安靜：changed 一直是 False，那行從來沒被執行到。
    def _n(v):
        return f"{v:,}" if isinstance(v, (int, float)) else str(v)

    consultant_line = f"顧問端點 {pc} → {cc}"
    if cc == 200 and pc != 200:
        consultant_line += "  ← 🎉 onboarding 完成，顧問權限已開"
    body = (f"分數 {_n(ps)} → {_n(cs)} {delta}\n"
            f"排名 {_n(pr)} → {_n(cr)}\n"
            f"等級 {(prev or {}).get('level')} → {cur.get('level')}\n"
            f"已提交 {cur.get('submitted_records')}\n"
            f"{consultant_line}\n\n"
            f"門檻：Bronze>1,000　Silver>5,000　Gold>10,000（Gold=顧問資格）\n"
            f"每日上限 2,000 分。")
    title = "🎉 BRAIN 顧問權限已開" if (cc == 200 and pc != 200) else "📊 BRAIN 分數更新"
    ok = B.notify(title, body)
    print(f"已推播（送出={ok}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
