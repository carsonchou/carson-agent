#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""submit_alpha.py — 提交一條 alpha 到 WorldQuant BRAIN。

## 為什麼是獨立一支、要 Carson 本人跑
提交是**不可逆的對外動作**：alpha 會進 WorldQuant 的池子並綁 Carson 的真實身分
（CT30034 / CHOU TING-RUI）。搜尋可以全自動，這一步不行 —— 這也是 CLAUDE.md
「對外發布」紅線的定義。Claude Code 的分類器同樣會擋下自動提交，那擋得對。

## 使用前提
提交前必須先 Check Submission 全綠（含 SELF_CORRELATION）。
`brain_auto.py --report` 或 `successful_alphas.md` 會列出候選。

## 用法
    python submit_alpha.py --check 0mwrA8p8      # 只檢查,不提交
    python submit_alpha.py --submit 0mwrA8p8     # 檢查通過才提交

## ⚠️ 節奏：一天 2 條（2026-08-27 定案，附推理過程）

**結論：一天 2 條。不是 1 條，也不是 3 條。**

### 為什麼不是 1 條（我一開始建議錯了）
原本的理由是「一條值 1,500~2,000，一天送 2 條會浪費分數」。
那個推理假設了**alpha 是稀缺的**——但實際上 alpha 不稀缺（搜尋器持續產出，
當時手上就有 7 條），**天數才稀缺**（每日上限 2,000 + 官方要求跨 5 天以上）。

重算：
    一條值 2,000 → 1條/天 5天  ｜ 2條/天 5天（打平）
    一條值 1,500 → 1條/天 7天  ｜ 2條/天 5天（2條勝）
    一條值 1,000 → 1條/天 10天 ｜ 2條/天 5天（2條勝）
**2 條從不比較慢，三分之二情境更快。** 溢出的分數不花錢，浪費的天數換不回來。

### 為什麼不是 3 條
每日上限硬是 2,000。**只有當一條值不到 667 分時第三條才有意義**，
而那低於所有估計的下緣 → 第三條拿不到額外的分。
兩個實際代價：(a) 庫存撐不到 5 天會斷貨；(b) 官方條款寫明偵測到 gaming
會終止帳號 —— 一天 2 條像研究，一天 5 條像刷分。**承擔風險卻沒有回報。**

### 還沒確定的事（要量，不要猜）
「一條實際值幾分」目前**沒有實測值**，1,500~2,000 是社群轉述。
`brain_auto.py` 的 `track_score()` 每批會記一筆快照到 `score_history.jsonl`。
**每天動手前先比對前一天的增量**，用自己帳號的斜率決定節奏，不要照猜的排程跑。

已提交紀錄：2026-08-27 交 2 條（`0mwrA8p8` Sharpe 2.25、`bljOoR6K` Sharpe 1.70）。

## 挑哪一條交：看逐年，不要只看總分
`brain_auto.py` 的 `year_quality()` 會算 `recent2_min_sharpe` / `last_year_sharpe`。
**總分高不代表近年撐得住**——2026-08-27 實例：
    esteps|zs63n   總 Sharpe 1.82 但最後一年只剩 **0.38**
    opinc_eq       總 Sharpe 1.70 而最後一年 **1.33**（唯一站在門檻上）
差點就照總分把最弱的排在前面。顧問報酬看的是 alpha 在**未來真實市場**的表現，
不是歷史回測平均 → **優先交近年還撐得住的**。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402


# 輪詢與判讀已合併進 brain_auto(見那邊的 poll_check / check_verdict)。
poll_check = B.poll_check


def show(data):
    """印出每一項檢查。**走 `B.parse_checks`,不自己重讀 body。**

    🔴 2026-09-05 第三輪:原本這裡自己做 `(data.get("is") or {}).get("checks")`
       然後 `c.get("result")`。`checks` 裡混進一個非 dict 的項目(例如平台/代理層
       塞進來的字串)就 `AttributeError` 崩掉 —— 是 fail-closed(不會 POST),
       但它是「一份實作」宣稱之外**殘留的第二個 body 讀取器**,
       而這整批修的就是「同一件事有好幾份實作」。
    """
    ck = B.parse_checks(data) or {}
    bad, pend = [], []
    for name, c in ck.items():
        res = c.get("result")
        mark = {"PASS": "OK  ", "FAIL": "FAIL", "PENDING": "PEND"}.get(res, str(res))
        v, l = c.get("value"), c.get("limit")
        extra = f"   值={v} 限={l}" if v is not None else ""
        print(f"   [{mark}] {name}{extra}")
        if res == "FAIL":
            bad.append(name)
        elif res == "PENDING":
            pend.append(name)
    return bad, pend


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    mode = "--submit" if "--submit" in a else "--check"
    ids = [x for x in a if not x.startswith("--")]
    if not ids:
        print(__doc__)
        return 1
    aid = ids[0]

    s = B.auth()
    print(f"Check Submission：{aid}（非同步，可能要等一會）")
    # tries=40 / wait=5 是這支原本的值;改成 B.poll_check 別名時要明寫,
    # 否則會靜默套用 brain_auto 的預設 35/4(獨立驗證員抓到的沒宣告行為改變)。
    _t0 = time.monotonic()
    data, why = poll_check(s, aid, tries=40, default_wait=5)
    _elapsed = round(time.monotonic() - _t0, 1)
    if data is None:
        print(f"✗ 沒拿到檢查結果：{why} —— 不提交")
        return 3
    if why:
        # 拿到 body 但沒等完。下面 check_verdict 會因為 PENDING 擋下,
        # 但擋下的**理由**要說對:是我們沒等完,不是平台判它不合格。
        print(f"⚠️ {why}")
    ok, why2, ck = B.check_verdict(data)
    if ck is not None:
        show(data)
    if not ok:
        B.log_check_body(aid, data, why2, elapsed=_elapsed)
        print(f"\n✗ {why2} —— 不提交")
        # 1 = 平台判定不合格(要改式子);3 = 沒觀測到/沒評估完(要再等或找人看)。
        # 兩者的下一步不同,所以 exit code 也要分得出來。
        return 1 if "未通過" in why2 else 3
    if mode != "--submit":
        print("\n（--check 模式，未提交。要提交請加 --submit）")
        return 0

    print("\n全綠，送出提交…")
    r = s.post(f"{B.API}/alphas/{aid}/submit", timeout=60)
    print(f"POST /submit -> HTTP {r.status_code}  {(r.text or '')[:200]}")

    # 🔴 社群實測教訓：**HTTP 201 不等於提交成功**。self-correlation 沒過會靜默留在
    #    UNSUBMITTED。必須回讀 status 確認 —— 與本專案 memory 記過的
    #    「API 回 200 但靜默不改」是同型坑。
    for _ in range(30):
        time.sleep(5)
        g = s.get(f"{B.API}/alphas/{aid}", timeout=30)
        if not g.ok:
            continue
        st = g.json().get("status")
        print(f"   回讀 status = {st}")
        if st and st != "UNSUBMITTED":
            print(f"\n{'✅ 提交成功' if st == 'ACTIVE' else '狀態：' + str(st)}")
            return 0
    print("\n⚠️ status 仍是 UNSUBMITTED —— 提交可能未生效，到平台頁面確認")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
