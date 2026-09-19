#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_submit_watch.py — 「今天該交而沒交」告警。缺席才是危險的那一種。

## 為什麼要有這支（2026-09-01，事故當天寫）
08-31 是拿 Gold 的最後一天。那天 12:20 的 `brain_daily_pick` 有跑、
`brain_score_watch` 15:15/16:10/17:10 三班全部正常執行並回報「無變動」——
**因為分數確實沒變動**。整條線一路綠燈，而實際狀態是：那天一條都沒交。
直到台北 21:13 Carson 自己問「今天如何」才發現。

根因不是哪支壞了，是**監控全部在看已發生的事**：
    brain_alpha_cron      跑了幾條模擬     → 有跑就綠
    brain_miner_watchdog  挖礦程序活著沒   → 活著就綠
    brain_score_watch     分數變了沒       → 沒變 = 靜默
沒有任何一支在問「**該發生而沒發生的事**」。而每日上限 2,000 分是
**用掉就沒有的**：漏一天不是延後一天，是那 2,000 分永遠拿不回來。

→ 本檔只做一件事：ET 今天的提交數 < 目標，就吵。

## 時區（實測，別再算錯）
    計分日分界 = ET 00:00 = 台北中午 12:00
    ET 09-01 這一天  ＝  台北 09-01 12:00 → 09-02 12:00
所以「台北的今天下午」和「台北的明天早上」是**同一個 ET 計分日**，
最後補交機會在台北隔天中午 12:00 之前。排班就照這個算（見 crontab.txt）。

## fail-closed
API 掛掉 / 認證失敗 → **推播「無法確認」**，不是靜默結束。
一支「不會叫」的告警比沒有告警更糟，因為它讓人以為有人在看
（memory `verification-that-cannot-fail` 的第一種壞法）。

## 用法
    python brain_submit_watch.py            # 排程用
    python brain_submit_watch.py --dry      # 不推播，只印（測試整條路徑）
    python brain_submit_watch.py --target 2 # 覆蓋當日目標條數
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRAIN = (Path(__file__).resolve().parent.parent.parent
         / "quant-service" / "brain_alpha")
sys.path.insert(0, str(BRAIN))

ET = timezone(timedelta(hours=-4))      # EDT。11 月轉 EST 要改 -5（見下方 _et_now 註解）
TARGET = 2                              # 每日上限 2,000 分 ≈ 2 條


def _et_now() -> datetime:
    """平台計分日用的 ET 時間。

    寫死 -4（EDT）而不是用時區資料庫，是因為這支要能在沒有 tzdata 的環境跑。
    代價：**11 月第一個週日之後會差一小時**。差一小時只會讓告警早一小時響，
    不會讓它漏掉（邊界往前挪 = 更早催），所以這個誤差是安全方向的。
    到時候改成 -5 即可。
    """
    return datetime.now(timezone.utc).astimezone(ET)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import brain_auto as B

    dry = "--dry" in sys.argv
    target = TARGET
    if "--target" in sys.argv:
        target = int(sys.argv[sys.argv.index("--target") + 1])
    notify = (lambda t, b: (print(f"[dry] 不推播：{t}\n{b}"), True)[1]) if dry else B.notify

    now_et = _et_now()
    today = now_et.strftime("%Y-%m-%d")
    # 距離 ET 換日還剩多久 = 還剩多久可以補交
    eod = (now_et + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left_h = (eod - now_et).total_seconds() / 3600

    # ── 取當日提交數。任何一步失敗都要吵，不能安靜地當作「沒事」 ──
    try:
        s = B.auth()
        r = s.get(f"{B.API}/users/self/activities/submissions", timeout=30)
        if not r.ok:
            raise RuntimeError(f"submissions HTTP {r.status_code}")
        records = (r.json().get("records") or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        notify("⚠️ BRAIN 無法確認今天交了沒",
               f"查提交紀錄失敗：{exc}\n\n"
               f"ET {today}，距離換日還有 {left_h:.1f} 小時。\n"
               f"**這不代表沒交，是代表我不知道** —— 請自己開一下平台確認。")
        print(f"查詢失敗：{exc}（已推播）")
        return 1

    done = sum(int(n) for d, n in records if d == today)
    print(f"ET {today} 已交 {done}/{target}　距換日 {left_h:.1f}h")

    if done >= target:
        print("已達標，靜默結束。")
        return 0

    # ── 剩餘時間決定語氣。越接近換日越該吵，因為那 2,000 分是用掉就沒有的 ──
    if left_h <= 4:
        head, urg = "🚨 BRAIN 今天要斷了", f"只剩 {left_h:.1f} 小時就換日，過了就永遠補不回來。"
    elif left_h <= 10:
        head, urg = "⚠️ BRAIN 今天還沒交滿", f"還剩 {left_h:.1f} 小時。"
    else:
        head, urg = "🔔 BRAIN 今天還沒交", f"還有 {left_h:.1f} 小時，不急，但別忘了。"

    近 = "　".join(f"{d}:{n}" for d, n in records[-5:])
    notify(head,
           f"ET {today} 已交 **{done}/{target}** 條。{urg}\n\n"
           f"每日上限 2,000 分，**漏一天不是延後一天，是那 2,000 分永遠拿不回來**。\n\n"
           f"最近五天：{近}\n\n"
           f"候選清單是 12:20 的 brain_daily_pick 推的那則；"
           f"沒收到就叫我重跑一次挑片。")
    print(f"已推播（{head}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
