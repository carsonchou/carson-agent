#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_daily_pick.py — 每天自動挑好今天該交哪兩條，直接 Telegram 給 Carson。

## 為什麼（2026-08-29）
Carson 的指示是：「把這東西全部自動化，我不想管，我只負責按提交，
你要在我需要授權的時候通知我。」

搜尋已經全自動（field_miner + watchdog + cron），但**挑選**還卡在我手動跑
`pick_next.py --check` 再把 id 貼給他。那等於整條線每天要等我開一次 session
——而我不是排程的一部分。這支把最後一哩補起來。

**提交本身仍然由 Carson 按。** 那是 CLAUDE.md 的「對外發布」紅線：
alpha 進 WorldQuant 的池子會綁他的真實身分（CT30034），且官方條款寫明
偵測到 gaming 會終止帳號。搜尋自動化、提交人工，這條線不動。

## 時區（實測，別再算錯）
· 計分日分界 = ET 00:00 = **台北中午 12:00**
· 結算刷新   = ET 03:00 = **台北 15:00**
→ 本檔排在台北 **12:20**：ET 新的一天剛開始 20 分鐘，
  這時候交的才會算進今天，而且離 15:00 結算還有足足 2.6 小時緩衝。
  （排 15:15 的 brain_score_watch 量的是**昨天**的結果，兩支不衝突。）

## 為什麼要花模擬額度跑 check
self-correlation 是**平台實測值**，離線算不出來。而它是遞減資源
（交越多、後面越難不相關；08-28 第二條已經 0.6168，門檻 0.7）。
挑錯的成本 = 提交被擋 + 浪費當天名額，遠高於多跑幾次 check。
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRAIN = (Path(__file__).resolve().parent.parent.parent
         / "quant-service" / "brain_alpha")
sys.path.insert(0, str(BRAIN))

ALPHA_URL = "https://platform.worldquantbrain.com/alpha/{}"
SAFE = 0.60          # self-corr 低於這個視為安全（官方門檻 0.7，留 0.1 緩衝）
N_CHECK = 6          # 跑實測 check 的候選數
N_PICK = 2           # 建議提交數（一天 2 條的推理見 submit_alpha.py）


def et_today() -> str:
    """平台計分日（ET）。台北中午 12:00 前算前一天。"""
    return (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%d")


def _prefilter(s, picks, n_want, drop_at=0.68):
    """離線 PnL 相關預篩：與**已提交池**明顯撞的先剔掉，別浪費平台 check。

    平台的 /check 是遞減資源（也佔模擬額度），而 self-correlation 的定義就是
    「對已提交池的最大相關」—— 那個我自己算得出來（誤差 ≤0.01）。
    只有灰區才需要平台裁決。

    取不到 PnL 的**保留**（讓平台判），不是丟掉：
    這支的作用是省額度，不是當守門員。守門在後面 `ok` 那一關。
    """
    import pick_next as P
    import runway as R
    cache = R.load_cache()
    try:
        sub = [d for d in (R.fetch_pnl(s, a, cache) for a in P.submitted_ids(s)) if d]
        kept = []
        for r in picks:
            d = R.fetch_pnl(s, r.get("alpha_id"), cache)
            if d is None:
                kept.append(r); continue
            w = max((abs(R.corr(d, e) or 1) for e in sub), default=0.0)
            if w >= drop_at:
                print(f"  [預篩] {P.numerator(r['expr'])[:30]:<32} 離線相關 {w:.3f} ≥ {drop_at}，不送 check")
                continue
            kept.append(r)
    finally:
        try:
            R.CACHE.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    # 全被篩掉時退回原本清單：預篩是為了省額度，
    # 不該讓它變成「今天什麼都不交」的原因（那 2,000 分拿不回來）。
    return (kept or picks)[:n_want]


def _decorrelate(s, ok, n_want):
    """從 ok 依序挑 n_want 條，**彼此之間**也要不相關。

    🔴 為什麼（2026-08-31 事故）：那天挑出的兩條對「已提交的全部」self-corr
    分別是 0.51 / 0.48（都很安全），但**彼此**實測 0.8999 —— 兩條一起交，
    第二條會被平台的 SELF_CORRELATION 擋下，白白浪費當天一個名額。

    原本的去重是比**分子字串**：不同字串就當成不同因子。而
    `unrecognized_tax_benefits_affecting_tax_rate` 和
    `unrecognized_tax_benefit_increase_current_period` 是兩個字串、
    同一個會計概念 —— 字串比不出相關性，PnL 可以。

    平台的 self-corr 只告訴你「對已提交的池子」相關多少，
    **問不到兩條未提交的之間**。所以這裡自己用日 PnL 差分算 Pearson
    （對照平台回報值校準過，誤差 ≤0.01）。
    """
    import runway as R
    cache = R.load_cache()
    chosen, series = [], []
    try:
        for x in ok:
            if len(chosen) >= n_want:
                break
            d = R.fetch_pnl(s, x["aid"], cache)
            if d is None:                       # 取不到 PnL → 不賭，跳過
                print(f"  {x['aid']} 取不到 PnL，跳過（不敢賭它跟誰撞）")
                continue
            worst = max((abs(R.corr(d, e) or 1) for e in series), default=0.0)
            if worst >= SAFE:
                print(f"  {x['num'][:30]:<32} 與已選的相關 {worst:.3f} ≥ {SAFE}，剔除")
                continue
            x["pair"] = worst
            chosen.append(x); series.append(d)
    finally:
        try:
            R.CACHE.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    # 一條都選不出來時退回最高分那條：**單獨一條不可能跟自己撞**，
    # 而「今天不交」的成本是那 2,000 分永遠拿不回來。
    return chosen or ok[:1]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import brain_auto as B
    import pick_next as P

    # --force 跳過「今天交過了」的守門、--dry 不真的推播。
    # 兩個都是為了**能在非 12:20 的時間驗完整條路**：
    # 只驗早退路徑等於什麼都沒驗（memory verification-that-cannot-fail）。
    force = "--force" in sys.argv
    dry = "--dry" in sys.argv
    if dry:
        B.notify = lambda t, b: (print(f"[dry] 不推播：{t}"), True)[1]

    s = B.auth()

    # 今天（ET）已經交過就不要再吵 —— 每日上限 2,000，交滿了第三條拿不到分
    snap = B.track_score(s)
    today = et_today()
    done_today = dict(snap.get("submitted_records") or []).get(today, 0)
    if done_today >= N_PICK and not force:
        print(f"ET {today} 已交 {done_today} 條，達標，不推播。")
        return 0

    done = P.submitted_ids(s)
    led = B.load_ledger()
    cand = [r for r in led.values()
            if r.get("ok") and (r.get("result") or {}).get("evaluable_pass")
            and r.get("alpha_id") not in done]

    # 每個分子只留最好的一條：同分子必然高度相關（實測 0.97），多測是浪費額度。
    # 換分母沒用（close 與 cap 本身高度相關），只有**換分子**才真的降相關（0.62）。
    by = defaultdict(list)
    for r in cand:
        by[P.numerator(r["expr"])].append(r)
    done_nums = {P.numerator(r["expr"]) for r in led.values() if r.get("alpha_id") in done}
    picks = []
    for num, v in by.items():
        if num in done_nums:
            continue
        v.sort(key=lambda r: -(r["result"].get("fitness") or 0))
        picks.append(v[0])
    # 🔴 2026-09-01：不能單純照 fitness 取前 N。
    # 實測：1,220 條通過裡 fundamental2 一家佔 **1,154 條**（94.6%），
    # 高分榜單被同一家的孿生體塞滿 —— 今天照舊排序取前 6 條，
    # 六條全是 fundamental2、全部 self-corr 0.77~0.90 被平台擋下，
    # 而同一時間 analyst4 / pv13 / option9 有 4 條互不相關的躺在庫存裡沒被看到。
    #
    # 另一個實測（同日）：跨資料集兩兩 PnL 相關 10 組只有 1 組 ≥0.7，
    # 而同資料集內部幾乎全撞。→ **資料集是相關性的主軸**，排序要先跨家分配。
    # （我一開始以為是「模板決定相關」，量完被自己推翻：跨資料集 0.0~0.53。）
    picks.sort(key=lambda r: -(r["result"].get("fitness") or 0))
    by_ds = defaultdict(list)
    for r in picks:
        by_ds[(r.get("label") or "||").split("|")[1]].append(r)
    # 各家依「該家最佳 fitness」排序，然後一輪一條輪流拿（round-robin）。
    order = sorted(by_ds.values(), key=lambda v: -(v[0]["result"].get("fitness") or 0))
    spread = []
    for i in range(max(len(v) for v in order)):
        for v in order:
            if i < len(v):
                spread.append(v[i])
        if len(spread) >= N_CHECK * 3:     # 給預篩留挑的空間（篩掉的多半是同一家）
            break
    # ── 先用離線 PnL 相關篩掉「一定會被擋」的，再花平台額度做實測 check ──
    # 實測對照：離線算的 Pearson 與平台回報的 SELF_CORRELATION 誤差 ≤0.01。
    # 今天 6 條 check 有 5 條回 FAIL —— 那 5 條離線就算得出來，等於白花 5 次額度。
    # 灰區（0.68~0.72）留給平台判，那是我的方法測不準的範圍。
    picks = _prefilter(s, spread, N_CHECK)

    if not picks:
        B.notify("⚠️ BRAIN 沒有可交的候選",
                 f"ET {today} 還沒交，但庫存裡找不到未提交的獨立分子。\n"
                 f"挖礦程序可能停了 —— 查 brain_miner_watchdog。")
        print("沒有候選，已推播警訊。")
        return 0

    rows = []
    for r in picks:
        aid = r["alpha_id"]
        d = P.poll_check(s, aid)
        if not d:
            print(f"  {aid} check 逾時，跳過")
            continue
        ck = {c["name"]: (c.get("result"), c.get("value"))
              for c in ((d.get("is") or {}).get("checks") or [])}
        sc = ck.get("SELF_CORRELATION", ("?", None))[1]
        bad = [k for k, v in ck.items() if v[0] == "FAIL"]
        y = (r.get("year_quality") or {}).get("last_year_sharpe")
        rows.append(dict(sc=sc if sc is not None else 9, num=P.numerator(r["expr"]),
                         aid=aid, sh=r["result"].get("sharpe"),
                         fit=r["result"].get("fitness"), ly=y, bad=bad))
        print(f"  {P.numerator(r['expr'])[:30]:<32} {aid}  self_corr={sc}  "
              f"{'FAIL:' + ','.join(bad) if bad else 'OK'}")

    ok = [x for x in rows if not x["bad"] and x["sc"] < SAFE]
    # SAFE=0.60 是**離線估計**時代留的緩衝（我的方法誤差 ±0.01，但池子會隨提交變動）。
    # 走到這裡的 sc 已經是**平台自己量的**，門檻就是 0.7 —— 對這種值再扣 0.1 太保守：
    # 今天 0.6851 那條就是這樣被丟掉的，而丟掉一個名額 = 1,000 分永遠拿不回來。
    # 折衷：0.60 以下優先，名額沒填滿才用 0.60~0.69 補。真正的風險（先交的那條
    # 會把池子墊高、讓後交的超過 0.7）由 _decorrelate 把兩條之間壓在 0.60 以下擋住。
    near = [x for x in rows if not x["bad"] and SAFE <= x["sc"] < 0.69]
    # self-corr 當篩選、不當排序：實測全在 0.42~0.52，遠低於門檻，
    # 拿 0.06 的差距去換掉 fitness 0.4 的差不划算。排序用官方 Quality Factor
    # 真正在意的：fitness，加上「近年還撐不撐得住」（分數每週依樣本外更新）。
    ok.sort(key=lambda x: -((x["fit"] or 0) + (x["ly"] or 0) * 0.5))

    if not ok and not near:
        B.notify("⚠️ BRAIN 今天沒有安全的候選",
                 f"ET {today} 跑了 {len(rows)} 條 check，沒有一條同時通過"
                 f"（無 FAIL + self-corr < {SAFE}）。\n"
                 f"獨立分子快用完了，一階掃描需要挖到新的資料集。")
        print("沒有安全候選，已推播。")
        return 0

    # max(0, ...)：done_today > N_PICK 時 N_PICK-done_today 是**負數**，
    # 而 ok[:-1] 不是空清單、是「除了最後一個以外全部」—— 會安靜地推出一堆
    # 不該交的候選。正式路徑有上面的守門碰不到，但負索引切片是會給錯答案
    # 而不報錯的寫法，不留。
    # --want N 覆蓋當日要挑幾條。存在的理由是**驗證**：正式路徑下
    # n_want 由「今天交了幾條」決定，補位那條分支在已交滿的日子測不到
    # （只驗早退路徑等於沒驗，memory verification-that-cannot-fail）。
    n_want = max(0, N_PICK - done_today) or 1
    if "--want" in sys.argv:
        n_want = int(sys.argv[sys.argv.index("--want") + 1])
    take = _decorrelate(s, ok, n_want)
    if len(take) < n_want and near:
        near.sort(key=lambda x: x["sc"])
        extra = _decorrelate(s, take + near, n_want)
        if len(extra) > len(take):
            print(f"  名額沒填滿，從 0.60~0.69 補了 {len(extra) - len(take)} 條")
            take = extra
    lines = [f"ET {today}（台北今天）可以交了。已交 {done_today} 條。", ""]
    for i, x in enumerate(take, 1):
        lines.append(f"{i}. {x['num'][:40]}")
        # 全部套 `or 0`：這支跑在 cron 裡,一個 None 格式化例外 = 當天沒通知
        # 且**完全無聲**。那正是 memory verification-that-cannot-fail 記的病。
        lines.append(f"   Sharpe {(x['sh'] or 0):.2f} · fitness {(x['fit'] or 0):.2f} · "
                     f"self-corr {(x['sc'] or 0):.3f} · 最後一年 {(x['ly'] or 0):.2f}")
        # 兩條之間的相關也要看得見：平台只查得到「對已提交池」，查不到彼此。
        if x.get("pair"):
            lines.append(f"   與上一條的相關 {x['pair']:.3f}（門檻 {SAFE}）")
        lines.append(f"   {ALPHA_URL.format(x['aid'])}")
        lines.append("")
    lines.append("進頁面按 Submit。全綠才會過；被擋的話回報我，")
    lines.append("多半是 self-correlation（那代表這個分子跟已交的撞了）。")
    body = "\n".join(lines)
    sent = B.notify("🧮 BRAIN 今天要交的 alpha", body)
    print(body)
    print(f"\n已推播（送出={sent}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
