#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_score_watch.py — BRAIN 積分盯哨的排程入口。

## 為什麼
平台**一天只結算一次**（ET 03:00 = 台北 15:00），而 Carson 一直在問「現在幾分」。
與其反覆手動查，不如刷新後自動量一次、有變動才推播。

## 時區（實測，別再算錯）
· 計分日分界 = ET 00:00 = **台北中午 12:00**（台北的一天橫跨平台兩個計分日）
· 結算刷新   = ET 03:00 = **台北 15:00**
→ 本檔排在台北 15:15，刷新後 15 分鐘。

## 只讀不寫
只呼叫 GET，不模擬也不提交，不佔用那 2 個併發槽。

## 🔴 2026-09-05：判斷邏輯已下放到 `brain_auto.track_score()`，本檔只剩「呼叫」
舊版在這裡自己比對 `score_history.jsonl` 的**最後一行**再決定推不推。
獨立驗證員實測推翻：那個檔有**四路寫入者**（本檔、`brain_alpha_cron`、
`brain_miner_watchdog` 拉起的 `brain_auto`、`brain_daily_pick`），
誰先落盤誰就把變動吃掉，而吃掉的那幾支完全不會叫。
15 次真實變動裡本檔只第一個看到 **4 次**；`submitted_total` 六次**全滅**
（全被 12:00/12:20 的 daily_pick 吃掉），連 `NONE→BRONZE`、`BRONZE→SILVER`
兩次升級也漏了。漏報的形狀是「回報無變動」——**一切看起來正常**。

⇒ 偵測改放在 `track_score()` 裡（D3），所以**每個寫入者都是哨兵**，
   採樣從 3 次/天變成每次有人寫入；顧問旗標改**單向閂**（D4）。
   細節與預設值的理由寫在 `brain_auto.py` 的 `_sentinel()` 上方。

**不要在本檔重新加入比對與推播**——那會讓同一次執行推兩則。
"""
from __future__ import annotations

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

    s = B.auth()
    # 落盤 + 判斷 + 推播全在這一步裡（見 brain_auto._sentinel）
    rec = B.track_score(s, src="score_watch")

    c = (rec.get("competitions") or [{}])[0] or {}
    print(f"score {c.get('score')} | rank {c.get('rank')} | alphas {c.get('alphas')} | "
          f"level {rec.get('level')} | submitted {rec.get('submitted_total')} | "
          f"consultant {rec.get('consultant_http')}")
    print(f"推播：score/level/submitted="
          f"{'已送' if rec.get('notified') else '未觸發或送失敗'}"
          f"　顧問閂={'已扣上' if rec.get('consultant_notified') else '未扣'}")
    if rec.get("errors"):
        print(f"errors: {rec['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
