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
import time
from collections import Counter, defaultdict
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
        B.notify = lambda t, b: (print(f"[dry] 不推播：{t}"), "dry")[1]
    # 🔴 上面那個 stub 回 True,而 track_score 的哨兵會把「推成功」寫進**正式檔**
    #    的單向閂裡 ⇒ 一則都沒發卻永久標記已通知。改用顯式開關,不要靠換掉 notify。

    s = B.auth()

    # 今天（ET）已經交過就不要再吵 —— 每日上限 2,000，交滿了第三條拿不到分
    snap = B.track_score(s, src="daily_pick", sentinel=not dry)
    today = et_today()
    done_today = dict(snap.get("submitted_records") or []).get(today, 0)
    if done_today >= N_PICK and not force:
        print(f"ET {today} 已交 {done_today} 條，達標，不推播。")
        return 0

    done, why_done = P.submitted_ids_ex(s)
    if done is None:
        # 🔴 這裡和 pick_next.main() 用法完全相同(cand 排除已提交 +
        #    done_nums 排除已交分子),所以空集合在**這條 cron 路徑上也是**
        #    fail-open ⇒ 會挑出已經交過的、並推播叫人去交。
        #    (我先前寫的規格說「這支保持預設,空集合是安全方向」——
        #     那是只看了 :68 的 _prefilter 就推廣,錯的。)
        B.notify("🔴 BRAIN 挑片中止:取不到已提交清單",
                 f"ET {today} {why_done}\n\n"
                 f"**這不是「一條都還沒交」,是沒問到。** 照舊跑會把已經交過的\n"
                 f"重新挑出來、而且分子去重會整個失效。請確認 token 後重跑。")
        print(f"取不到已提交清單:{why_done} —— 中止(不是沒有候選,是沒問到)。")
        return 2
    # 🔴 2026-09-08:候選池 = **帳本 ∪ 平台快照**,不是只有帳本。
    #    帳本看不到的 alpha 這支永遠選不到 —— 2026-09-05 對帳查出 199 條
    #    「平台有、帳本沒有」,其中 4 條 checks 零 FAIL(最高 Sharpe 2.35,
    #    對照已提交最高 2.40)。組池與去重的實作**只有 pick_next 一份**:
    #    這支原本自己抄了一份,於是修好 pick_next 不會修到這條每天 12:20 真的
    #    在做決定的路徑(memory: 做決策的那個系統看的是哪一本帳)。
    import reconcile as R2
    plat, meta, why_snap = R2.load_snapshot()
    if plat is None and "--no-refresh" not in sys.argv:
        # 🔴 快照過期就**自己重抓**,不要靠另一個排程去餵它。
        #    分成兩個排程的話會多一種失效形態:快照那支默默壞掉,這支每天照常
        #    中止,而「中止」的訊息會說快照拿不到 —— 沒有人會知道是排程掉了。
        #    列舉唯讀、約 10 分鐘;本支排 12:20(ET 00:20),抓完仍遠早於 15:00 結算。
        print(f"平台快照{why_snap} —— 現抓一份（唯讀，約 10 分鐘）…")
        try:
            # `totals` 一定要傳:少了它 `expected_total` 是 None,而 `load_snapshot()`
            # 會（正確地）判這份快照無法確認完不完整 ⇒ 剛抓好的快照當場被自己退回。
            totals: dict = {}
            R2.save_snapshot(R2.fetch_platform(s, verbose=False, totals=totals),
                             expected=totals.get("expected"))
            plat, meta, why_snap = R2.load_snapshot()
        except Exception as e:  # noqa: BLE001
            why_snap = f"重抓失敗：{type(e).__name__} {e}"
            plat = None
    if plat is None:
        # fail-closed。**不可以退回只用帳本** —— 那正是這次要修掉的盲區,
        # 而它退化時不會產生任何錯誤訊號(候選表照樣印得出來)。
        B.notify("🔴 BRAIN 挑片中止:平台快照拿不到",
                 f"ET {today} {why_snap}\n\n"
                 f"候選池要「帳本 ∪ 平台」才完整。只用帳本會漏掉平台上跑完、\n"
                 f"checks 零 FAIL、但帳本記成失敗的那一群(對帳實據 199 條/4 條合格)。\n"
                 f"→ 跑 `python reconcile.py --snapshot`(約 10 分鐘,唯讀)後重跑本支。")
        print(f"平台快照拿不到:{why_snap} —— 中止(不退回帳本-only)。")
        return 2
    led = B.load_ledger()
    cand, pool_st = P.build_pool(led, plat, done)
    # 每個分子只留最好的一條：同分子必然高度相關（實測 0.97），多測是浪費額度。
    # 換分母沒用（close 與 cap 本身高度相關），只有**換分子**才真的降相關（0.62）。
    picks, by, done_nums = P.dedup_by_numerator(cand, led, plat, done)
    print(f"候選池:帳本 ∪ 平台快照 {meta['count']} 條（{meta['fetched_at']}，"
          f"{meta['age_h']:.1f}h 前）→ 合格未提交 {pool_st['qualified_excl_done']} "
          f"（平台獨有 {pool_st['cand_by_src']['platform']}）| 未交分子 {len(picks)} 種")
    # 🔴 2026-09-01：不能單純照 fitness 取前 N。
    # 實測：1,220 條通過裡 fundamental2 一家佔 **1,154 條**（94.6%），
    # 高分榜單被同一家的孿生體塞滿 —— 今天照舊排序取前 6 條，
    # 六條全是 fundamental2、全部 self-corr 0.77~0.90 被平台擋下，
    # 而同一時間 analyst4 / pv13 / option9 有 4 條互不相關的躺在庫存裡沒被看到。
    #
    # 另一個實測（同日）：跨資料集兩兩 PnL 相關 10 組只有 1 組 ≥0.7，
    # 而同資料集內部幾乎全撞。→ **資料集是相關性的主軸**，排序要先跨家分配。
    # （我一開始以為是「模板決定相關」，量完被自己推翻：跨資料集 0.0~0.53。）
    # 🔴 粗排只用兩邊都有的欄位（fitness/sharpe）。**不可以用 last_year_sharpe**:
    #    它只有帳本側有(1,352/1,359),平台獨有的候選一條都沒有,拿缺值當 -9 或 0
    #    排序等於把整個平台側沉到底再截掉 —— 池子改對了還是選不到。
    picks.sort(key=P.prerank_key)
    # 跨資料集 round-robin。實作只有 `pick_next.spread_by_family` 一份 ——
    # 這段原本內嵌在這裡,於是沒有任何測試碰得到它,而漏帶 `label` 那個 bug
    # (平台側整群塌成一家)就出在這幾行(獨立驗證員 2026-09-08 指出)。
    spread, order = P.spread_by_family(picks, N_CHECK * 3)
    print(f"  分家 {len(order)} 家 → spread {len(spread)} 條"
          f"（各家 {[len(v) for v in order]}）")
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
    skipped = []          # (aid, 原因) —— 「沒問到」和「問到了不合格」必須分得出來
    for r in picks:
        aid = r["alpha_id"]
        # 🔴 2026-09-05:poll_check 改回 (data, reason) 二元組。這個呼叫端當時
        #    漏改,實測**成功與失敗路徑都** AttributeError(tuple 恆為 truthy,
        #    `if not d` 不觸發、`d.get` 不存在)—— 會打死每天 12:20 的排程,
        #    連它自己「沒有候選」的推播警訊都發不出來。由獨立驗證員抓到。
        _t0 = time.monotonic()
        d, why = P.poll_check(s, aid)
        _elapsed = round(time.monotonic() - _t0, 1)
        if d is None:
            print(f"  {aid} 沒拿到 check 結果：{why}，跳過")
            # 🔴 認證死掉的話後面每條都會同樣死,而**全部跳過之後的推播原本寫的是
            #    「獨立分子快用完了」** —— 歸因完全相反,且訊息裡「跑了 0 條 check」
            #    這個矛盾沒有人會去讀。認證問題要自己講自己的名字。
            if why.startswith("HTTP 401") or why.startswith("HTTP 403"):
                B.notify("🔴 BRAIN 挑片中止：認證失效",
                         f"ET {today} {why}\n\n"
                         f"**這不是庫存問題** —— 一條 check 都沒跑成。\n"
                         f"請更新 token 後重跑 brain_daily_pick。")
                print("認證失效,中止本輪(不是沒有候選,是沒問到)。")
                return 2
            skipped.append((aid, why))
            continue
        if why:
            print(f"  {aid} ⚠️ {why}")
        ck = P.checks_of(d)
        if ck is None:
            B.log_check_body(aid, d, "沒有可判讀的 checks", elapsed=_elapsed)
            print(f"  {aid} 回 200 但沒有可判讀的 checks（不是全過），跳過")
            skipped.append((aid, "沒有可判讀的 checks"))
            continue
        sc = ck.get("SELF_CORRELATION", ("?", None))[1]
        # 唯一規則(brain_auto.non_pass):非 PASS 一律不合格 —— PENDING(沒評估完)
        # 與未知狀態都不是通過。
        bad = B.non_pass(ck)
        # 🔴 只留 key 的話,「全是 PENDING」和「全是真 FAIL」推出的告警會一字不差
        #    —— 而這兩者的下一步完全相反(再等一下 vs 挖新資料集)。
        #    分辨用的資訊(result)手邊就有,不要在這一行丟掉。
        bad_res = B.results_of(ck, bad)
        if bad:
            # 排程路徑也要落檔。原本只有手動跑的 submit_alpha 會落,而真正每天
            # 撞到 PENDING 的是這支 —— 不落檔的話那個未知永遠不會變成資料。
            B.log_check_body(aid, d, "非 PASS: " + ",".join(
                "%s=%s" % (k, bad_res.get(k)) for k in bad), elapsed=_elapsed)
        y = (r.get("year_quality") or {}).get("last_year_sharpe")
        rows.append(dict(sc=sc if sc is not None else 9, num=P.numerator(r["expr"]),
                         aid=aid, sh=r.get("sharpe"),
                         fit=r.get("fitness"), ly=y, bad=bad, rec=r,
                         bad_res=bad_res, elapsed=_elapsed))
        print(f"  {P.numerator(r['expr'])[:30]:<32} {aid}  self_corr={sc}  "
              f"{'非PASS:' + ','.join(bad) if bad else 'OK'}")

    # 🔴 逐年表要在這裡補抓:平台獨有的候選不在帳本裡 ⇒ **一條都沒有** year_quality,
    #    而下面的排序把缺值當 0 用。不補的話「沒量到」會被當成「最後一年 0.00」,
    #    一整群平台側候選會因為一個從沒量過的數字被排到最後(同族缺陷:PAUSED.md C 項)。
    n_filled = P.fill_year_quality(s, [x["rec"] for x in rows if x["ly"] is None])
    for x in rows:
        x["ly"] = (x["rec"].get("year_quality") or {}).get("last_year_sharpe")
    if n_filled:
        print(f"  補抓逐年統計 {n_filled} 條")
    still_unknown = [x["aid"] for x in rows if x["ly"] is None and not x["bad"]]
    if still_unknown:
        # 補不到就講出來。**不可以讓它靜靜地以 0 參加排序** —— 那是把「沒量到」
        # 說成一個量到的數,而讀的人看不出差別。
        print(f"  ⚠️ 逐年表拿不到 {len(still_unknown)} 條，排序上等同 0："
              + ",".join(still_unknown))

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
    # 🔴 `ly` 未知的**不混進主排序**:拿 0 當它等於把「沒量到」說成「近年很差」,
    #    而平台側候選 year_quality 覆蓋率是 0/6(靠上面現場補抓)。未知的排在
    #    已知的後面並保留在名單裡 —— `pick_next.main()` 同一件事同一個處置,
    #    兩支不可以不一致(不一致本身就會讓下一個人以為其中一支是對的)。
    ok.sort(key=lambda x: (x["ly"] is None, -((x["fit"] or 0) + (x["ly"] or 0) * 0.5)))

    if not ok and not near:
        # 🔴 原本無論什麼原因都推同一句「獨立分子快用完了」。實測三種完全不同的
        #    原因(全 PENDING / 全真 FAIL / 認證死)推同一則同一句歸因,而 401 那則
        #    寫「跑了 0 條 check」卻仍歸因庫存耗盡。歸因錯的告警比沒有告警更糟,
        #    因為它會把讀的人導去挖新資料集,而真正要做的是換 token 或再等一下。
        if not rows:
            detail = ("一條 check 都沒有跑成（%d 條全部跳過）。\n"
                      "**這不是庫存問題。** 原因：\n  · %s"
                      % (len(skipped), "\n  · ".join("%s：%s" % x for x in skipped[:6])))
        else:
            n_bad = sum(1 for x in rows if x["bad"])
            tally = Counter(v for x in rows for v in (x.get("bad_res") or {}).values())
            n_pend = tally.get("PENDING", 0)
            n_fail = tally.get("FAIL", 0)
            n_other = sum(v for k, v in tally.items() if k not in ("PENDING", "FAIL"))
            slow = max([x.get("elapsed") or 0 for x in rows] or [0])
            # not n_other 不可以省:PENDING+WARNING 若判成「純 PENDING」,會叫人
            # 去放寬 deadline,而放寬對 WARNING 無效 —— 把未知狀態講成已知狀態,
            # 正是這批在修的那類病。
            if n_pend and not n_fail and not n_other:
                head = ("**原因是 PENDING,不是候選不好。** %d 項仍在評估中,"
                        "代表輪詢沒等到平台算完(最慢一條 %.0f 秒,deadline %.0f 秒)。\n"
                        "→ 放寬 BRAIN_CHECK_DEADLINE 再跑一次,不要去挖新資料集。"
                        % (n_pend, slow, B.CHECK_DEADLINE))
            elif n_fail and not n_pend:
                head = ("**%d 項是平台判定的真 FAIL。** 這一種才代表候選本身不行 ——"
                        "「獨立分子快用完了、需要挖新資料集」在這一種情況下成立。" % n_fail)
            else:
                head = ("非 PASS 的組成:PENDING %d、FAIL %d、其他 %d"
                        "(最慢一條 %.0f 秒,deadline %.0f 秒)。\n"
                        "→ 混合情況,先看 check_bodies.jsonl 再決定要不要挖新資料集。"
                        % (n_pend, n_fail, n_other, slow, B.CHECK_DEADLINE))
            detail = ("跑了 %d 條 check：%d 條有非 PASS 項目、%d 條 self-corr ≥ %s。\n%s"
                      % (len(rows), n_bad, len(rows) - n_bad, SAFE, head))
        B.notify("⚠️ BRAIN 今天沒有安全的候選", f"ET {today} {detail}")
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
        # 「最後一年」要有「沒有」的出口:`or 0` 會把拿不到的逐年表印成 0.00,
        # 而真的量到 0.00 是「近年撐不住、別交」—— 兩者在訊息上必須分得出來。
        def _n(v, fmt="%.2f", miss="未知"):
            """四個數字都要有「沒有」的出口(PAUSED.md 下一棒 C)。

            `or 0` 會把「沒量到」印成 `0.00`,而真的量到 0.00 的意思相反
            （Sharpe 0 = 別交)。**兩者在訊息上必須分得出來**,
            而 cron 又不能因為一個 None 就格式化例外(那會整天無聲)。
            `sc` 的 9 是「拿不到 self-corr」的哨兵值,不是一個相關度。
            """
            return miss if v is None else fmt % v
        lines.append(f"   Sharpe {_n(x['sh'])} · fitness {_n(x['fit'])} · "
                     f"self-corr {_n(None if x['sc'] == 9 else x['sc'], '%.3f', '未知（沒量到）')}"
                     f" · 最後一年 {_n(x['ly'], '%.2f', '未知（逐年表拿不到）')}")
        if (x["rec"] or {}).get("src") == "platform":
            lines.append("   ⚠️ 這條只在平台上、帳本沒有（帳本把它記成了失敗）")
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
