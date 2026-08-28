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


def poll_check(s, aid, tries=40):
    """Check Submission 是非同步的：回 200 但 body 可能是空的，要輪詢。"""
    for _ in range(tries):
        r = s.get(f"{B.API}/alphas/{aid}/check", timeout=60)
        if r.text.strip():
            try:
                return r.json()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(float(r.headers.get("Retry-After") or 5))
    return None


def show(data):
    checks = (data.get("is") or {}).get("checks") or []
    bad, pend = [], []
    for c in checks:
        res = c.get("result")
        mark = {"PASS": "OK  ", "FAIL": "FAIL", "PENDING": "PEND"}.get(res, str(res))
        v, l = c.get("value"), c.get("limit")
        extra = f"   值={v} 限={l}" if v is not None else ""
        print(f"   [{mark}] {c.get('name')}{extra}")
        if res == "FAIL":
            bad.append(c.get("name"))
        elif res == "PENDING":
            pend.append(c.get("name"))
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
    data = poll_check(s, aid)
    if not data:
        print("✗ 檢查逾時，稍後再試")
        return 1
    bad, pend = show(data)
    if bad:
        print(f"\n✗ 有 {len(bad)} 項未通過：{', '.join(bad)} —— 不提交")
        return 1
    if pend:
        print(f"\n⚠️ 仍有未評估項目：{', '.join(pend)}")

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
