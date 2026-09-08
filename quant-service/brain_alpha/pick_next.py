#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick_next.py — 挑今天該交哪幾條：**用實測 self-correlation 排序，不是用分數**。

## 為什麼（2026-08-28）
選片標準演化了三次，每次都是被打臉才改：

1. 「挑 fitness 最高的」
   → 撞牆：`QP7vPrEr` self-corr **0.9653** 被擋。它跟同日已交的只差一個外層變換。
2. 「挑不同 base（比率）的」
   → 還是撞：`operating_income/close` vs 已交的 `operating_income/cap` → **0.9732**。
     換分母沒用，`close` 與 `cap` 本身高度相關。
3. 「挑不同**分子**的」
   → 有效：`cashflow_op/close` → **0.6168** 通過。

但第 3 條仍是**代理指標**。真正決定能不能交的是平台實測的 self-correlation，
而那個只有跑 `/check` 才知道。而且它是**遞減的資源** —— 交越多，後面越難不相關
（08-28 第二條已經 0.6168，門檻 0.7）。

→ 所以：**先花模擬額度跑 check 拿實測值，再挑最低的交。**
   挑錯的成本（提交被擋、浪費當天名額）遠高於多跑幾次 check。

## 🔴 候選池 = 帳本 ∪ 平台（2026-09-08 修）

原本候選池只有 `B.load_ledger()`。**帳本看不到的 alpha，這支程式永遠選不到**，
不管它在平台上多好 —— 而那不是假想：2026-09-05 對帳查出 199 條「平台有、帳本沒有」，
其中 **4 條 checks 零 FAIL**（最高 Sharpe 2.35，對照已提交最高 2.40）。
成因是帳本把它們記成了失敗（`poll 401` / `無有效 Location` / `status=WARNING`…），
而平台照樣把模擬跑完並建立了 alpha。**帳本裡那幾列長得就是一次正常的失敗，零錯誤訊號。**
（詳見 `docs/ledger-platform-gap-20260905.md`。）

⇒ 修法不是把那 4 條手動補進帳本 —— 那會修好那 4 條，並且把「挑片器選不到」這件事
   一起抹掉（池子滿了，以後沒人會再注意到）。改的是**池子的定義**。

平台那一半來自 `reconcile.py` 產的快照 `platform_alphas.json`。
**快照拿不到就中止**（`--ledger-only` 可覆寫，但輸出會標明涵蓋範圍）——
把「沒問到平台」靜默降級成「平台上沒別的」，就是原本那個 fail-open 換了個位置。

## 官方 Quality Factor（決定當天拿幾分）
    Universe（越小越好）· SelfCorrelation（越低越好）· Fitness（越高越好）· Delay（D1>D0）
且**跨當天所有提交者正規化** —— 所以分數不是固定的，昨天拿滿不代表今天拿滿。

## 用法
    python reconcile.py --snapshot     # 先更新平台快照（約 10 分鐘，唯讀）
    python pick_next.py --check 8      # 對前 8 個候選跑 check,依實測 self-corr 排序
    python pick_next.py --dry          # 只印候選池組成與名單，不打 /check、不需認證
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402
import reconcile as R  # noqa: E402  平台列舉與快照的唯一一份實作


# 🔴 分子與分家的實作在 `brain_auto`(唯一一份,四支共用)。這裡只留別名 ——
#    2026-09-08 之前有四份各自的 `numerator()`,其中三份帶著舊正則。
numerator = B.numerator
family_key = B.family_key


def submitted_ids_ex(s):
    """已提交的 alpha id。回 `(ids, reason)`。**判讀在 `brain_auto.active_alpha_ids`。**

    🔴 2026-09-05:原本這裡有一份、`runway.main()` 內嵌另一份,兩份行為不一致
       (對 `{"id": 7}` 與重複 id 的判定相反),而本檔下面就寫著
       「同一條規則只能有一份實作」。合併了。
    """
    return B.active_alpha_ids(s)


def submitted_ids(s):
    """已提交的 alpha id 集合。**簽章不動**(`brain_daily_pick.py:68` 靠它)。

    ⚠️ 拿不到時回**空集合**並在 stderr 警告 —— 保持原行為是為了不打壞
       `_prefilter`(那裡空集合只會少省一點額度,判斷仍由平台的 `/check` 做)。
       **但空集合會被「排除已提交」這類用法讀成「一條都還沒交」,那是 fail-open。**
       任何拿它來做排除/去重的呼叫端,一律改用 `submitted_ids_ex` 並自己擋。
    """
    ids, why = submitted_ids_ex(s)
    if ids is None:
        print("[warn] 取不到已提交清單:%s —— 當成空集合(呼叫端若拿它做排除"
              "就是 fail-open,請改用 submitted_ids_ex)" % why, file=sys.stderr)
        return set()
    return ids


# poll_check / checks_of 已合併進 brain_auto —— 這裡只留別名。
# 🔴 2026-09-05:原本這支、submit_alpha、brain_daily_pick 各有一份 /check 的
#    輪詢與判讀,三份各壞各的(而修好其中兩份的那一版,正是靠沒同步改第三份
#    造成一次 cron 全掛的迴歸)。同一條規則只能有一份實作。
poll_check = B.poll_check


def checks_of(data):
    """`{name: (result, value)}`,拿不到 checks 回 None。薄包裝,判讀在 brain_auto。"""
    ck = B.parse_checks(data)
    if ck is None:
        return None
    return {k: (c.get("result"), c.get("value")) for k, c in ck.items()}


# ────────────────────── 候選池 ──────────────────────

def build_pool(led: dict, plat: dict | None, done: set) -> tuple[list, dict]:
    """候選池 = 帳本 ∪ 平台快照，扣掉已提交的。回 `(cand, stats)`。

    **純函式，不連網** —— 這樣「那 4 條進不進得了池子」可以用固定資料證明，
    不必等一次 10 分鐘的列舉，也不會因為平台當下的狀態而變成不可重現的驗證。

    合格判準（`qualified`）的權威是**平台**，帳本只在平台沒有這條時才採信：
    帳本的 `result` 是模擬當下的快照，平台的 checks 是現在的狀態。

    🔴 `checks_n` 這個出口不可以省：平台端「**沒有 is/checks**」（模擬沒跑完、
    ERROR）與「**零 FAIL**」在 `fails == []` 上長得一模一樣。沒有這個欄位的話，
    一條根本沒評過的 alpha 會被當成合格品送進 /check —— 預設值要落在「不通過」那側。
    """
    rec: dict[str, dict] = {}
    for r in (led or {}).values():
        aid = r.get("alpha_id")
        if not aid:
            continue
        res = r.get("result") or {}
        rec[aid] = {
            "alpha_id": aid, "expr": r.get("expr"),
            # `label`（"模板|資料集|…"）是 brain_daily_pick 跨資料集 round-robin 的鍵。
            # 🔴 漏掉它的話所有候選會落進同一「家」,那個 2026-09-01 加的分散機制
            #    會靜默失效(fundamental2 的孿生體重新塞滿名單),而它不會報錯 ——
            #    實測就是這樣:家數 1、那 4 條全被擠出 spread。
            "label": r.get("label"),
            "sharpe": res.get("sharpe"), "fitness": res.get("fitness"),
            "year_quality": r.get("year_quality"),
            "ledger_pass": bool(r.get("ok") and res.get("evaluable_pass")),
            "plat": None, "src": "ledger",
        }
    for aid, p in (plat or {}).items():
        c = rec.get(aid)
        if c is None:
            c = rec[aid] = {"alpha_id": aid, "expr": None, "label": None,
                            "sharpe": None, "fitness": None, "year_quality": None,
                            "ledger_pass": None, "plat": None, "src": "platform"}
        else:
            c["src"] = "both"
        c["plat"] = p
        # 平台是現況的權威；帳本只補平台沒有的欄位（expr 在兩邊都有時以帳本為準，
        # 兩者同源，但帳本那份是我們送出去的原文）。
        if not c["expr"]:
            c["expr"] = p.get("code")
        if p.get("sharpe") is not None:
            c["sharpe"] = p.get("sharpe")
        if p.get("fitness") is not None:
            c["fitness"] = p.get("fitness")

    cand, n_excl_done, n_unqualified = [], 0, 0
    for c in rec.values():
        p = c["plat"]
        if p is not None:
            qualified = bool(p.get("checks_n")) and not p.get("fails")
        else:
            qualified = bool(c["ledger_pass"])
        if not qualified:
            n_unqualified += 1
            continue
        if c["alpha_id"] in done:
            n_excl_done += 1
            continue
        cand.append(c)
    stats = {
        "ledger_rows": len(led or {}), "platform_rows": len(plat or {}),
        "union_alpha_ids": len(rec), "qualified_excl_done": len(cand),
        "excluded_submitted": n_excl_done, "not_qualified": n_unqualified,
        "cand_by_src": {k: sum(1 for c in cand if c["src"] == k)
                        for k in ("ledger", "both", "platform")},
    }
    return cand, stats


def dedup_by_numerator(cand: list, led: dict, plat: dict | None, done: set):
    """每個分子只留最好的一條（同分子必然高度相關，多測沒意義）；
    分子已經交過的整族排除（同分子一定撞 self-correlation）。

    🔴 `done_nums` 原本只從帳本算 —— 而已提交的 alpha 若不在帳本裡，它的分子就
    不會被排除，於是可能建議一條和已交的同分子的（必撞）。這裡改成從聯集算。
    ⚠️ 認不出分子的式子回 `"?:<雜湊>"`（每條式子一個鍵），所以它們**不會**被
    去重成一條；同一條式子仍對到同一個鍵，真正的重複還是擋得住。見 `numerator()`。
    """
    exprs = {}
    for r in (led or {}).values():
        if r.get("alpha_id"):
            exprs[r["alpha_id"]] = r.get("expr")
    for aid, p in (plat or {}).items():
        exprs.setdefault(aid, p.get("code"))
    done_nums = {numerator(exprs.get(a) or "") for a in done if exprs.get(a)}

    by = defaultdict(list)
    for c in cand:
        by[numerator(c["expr"])].append(c)
    picks = []
    for num, v in by.items():
        if num in done_nums:
            continue
        v.sort(key=lambda c: -(c.get("fitness") or 0))
        picks.append(v[0])
    return picks, by, done_nums


def prerank_key(c):
    """粗排（決定誰值得花一次 /check）。

    🔴 **不可以用 `last_year_sharpe`** ——它來自 `fetch_yearly`，只有帳本側的候選
    有（實測 1,359 條合格帳本候選裡 1,352 條有），平台側**一條都沒有**。
    舊版用 `-9` 當缺值的預設再由高到低排，等於把整個平台側沉到最底、然後被
    `picks[:n]` 截掉 —— 池子改對了也還是選不到。那是同一個結構性排除的第二道。
    ⇒ 粗排只用兩邊都有的欄位；`last_year_sharpe` 留到 check 之後才用（那時再補抓）。
    """
    return -((c.get("fitness") or 0) * 1.0 + (c.get("sharpe") or 0) * 0.3)


def spread_by_family(picks, cap):
    """跨資料集 round-robin:各家依「該家最佳 fitness」排序，一輪一條輪流拿，
    取到 `cap` 條為止。回 `(spread, order)`(`order` 是各家的清單,給診斷用)。

    🔴 為什麼要是一個**函式**(2026-09-08):這段原本內嵌在 `brain_daily_pick.main()`
    裡,於是**沒有任何測試碰得到它** —— 而這批改動的第二個 bug(漏帶 `label`,
    整個平台側塌成一家)就出在這裡。當時綠燈的那 19 格測的是上游的
    `build_pool` 有沒有把 label 帶出來(**代理指標**),不是這裡的分家行為。
    獨立驗證員 2026-09-08 指出這一點,所以把它抽出來、直接測它。

    ⚠️ 這裡有一個不明顯的性質:**輪數決定「任一家最多幾條進 spread」,
    而輪數不隨家大小變**。驗證員實測(cap=18、6 家):輪數 4 ⇒ 家大小 ≤4 的全進、
    第 5 條起被切,**且上限鎖死在 4,不管那一家長到多大**。
    平台側整群共用一家時這會變成硬上限 —— 那正是 `family_key()` 要拆開它的理由。
    """
    by = defaultdict(list)
    for r in picks:
        by[family_key(r)].append(r)
    order = sorted(by.values(), key=lambda v: -(v[0].get("fitness") or 0))
    spread = []
    # `max(...)` 對空序列會 ValueError,而呼叫端的「沒有候選」守門在它之後。
    for i in range(max((len(v) for v in order), default=0)):
        for v in order:
            if i < len(v):
                spread.append(v[i])
        if len(spread) >= cap:
            break
    return spread, order


def fill_year_quality(s, rows):
    """替缺 `year_quality` 的候選補抓逐年統計。回補到幾條。

    抓不到就留 `None` —— **不可以填 0**：`最後一年 0.00` 與「沒量到」在輸出上
    要分得出來（同族缺陷見 `PAUSED.md` C 項）。
    """
    n = 0
    for c in rows:
        if c.get("year_quality"):
            continue
        yq = B.year_quality(B.fetch_yearly(s, c["alpha_id"]) or [])
        if yq:
            c["year_quality"] = yq
            n += 1
    return n


def _ly(c):
    return ((c.get("year_quality") or {}).get("last_year_sharpe"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    n = 8
    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        if len(sys.argv) > i + 1:
            n = int(sys.argv[i + 1])
    dry = "--dry" in sys.argv

    # ── 候選池的兩本帳 ──
    plat, meta, why = R.load_snapshot()
    if plat is None and "--refresh" in sys.argv:
        print(f"平台快照{why} —— 現抓一份（唯讀，約 10 分鐘）…")
        R.save_snapshot(R.fetch_platform(B.auth(), verbose=True))
        plat, meta, why = R.load_snapshot()
    if plat is None:
        if "--ledger-only" not in sys.argv:
            print(f"✗ 平台快照拿不到:{why}")
            print("  候選池只用帳本 = 這支程式 2026-09-05 查出的那個結構性盲區"
                  "（平台有、帳本沒有的合格品永遠選不到）。")
            print("  先跑:python reconcile.py --snapshot   （約 10 分鐘，唯讀）")
            print("  真的只要帳本側請明寫 --ledger-only。")
            return 2
        print(f"⚠️ --ledger-only:候選池只有帳本，平台獨有的合格品這輪看不到（{why}）")
        plat, coverage = {}, "帳本（未含平台，涵蓋範圍不完整）"
    else:
        coverage = (f"帳本 ∪ 平台快照 {meta['count']} 條"
                    f"（{meta['fetched_at']} 台北，{meta['age_h']:.1f}h 前）")

    if dry:
        done, why_done = set(), ""
        print("⚠️ --dry:不連平台，已提交清單當空集合 —— "
              "這張表**不可以拿來提交**，只用來看候選池組成。")
        s = None
    else:
        s = B.auth()
        done, why_done = submitted_ids_ex(s)
        if done is None:
            # 🔴 空集合會被下面讀成「一條都還沒交」:`cand` 不排除任何已提交的、
            #    `done_nums` 空 ⇒ 分子去重失效 ⇒ **建議重複提交**。一個名額換不回來。
            print(f"✗ 取不到已提交清單:{why_done}")
            print("  這不是「一條都還沒交」,是沒問到 —— 照舊跑會建議重複提交。中止。")
            return 2

    led = B.load_ledger()
    cand, st = build_pool(led, plat, done)
    picks_all, by, done_nums = dedup_by_numerator(cand, led, plat, done)

    print(f"候選池涵蓋範圍:{coverage}")
    print(f"  聯集 alpha {st['union_alpha_ids']}（帳本 {st['ledger_rows']} 列 / "
          f"平台 {st['platform_rows']} 條）→ 合格且未提交 {st['qualified_excl_done']}"
          f"（帳本獨有 {st['cand_by_src']['ledger']} / 兩邊都有 {st['cand_by_src']['both']}"
          f" / **平台獨有 {st['cand_by_src']['platform']}**）")
    print(f"已交分子 {len(done_nums)} 種 | 未交分子候選 {len(picks_all)} 種")

    picks_all.sort(key=prerank_key)
    picks = picks_all[:n]
    if dry:
        print(f"\n前 {len(picks)} 個候選（粗排:fitness + 0.3×sharpe）")
        print(f"{'分子':<28}{'id':<11}{'來源':<10}{'sh':>6}{'fit':>6}{'最後年':>9}")
        print("-" * 72)
        for c in picks:
            ly = _ly(c)
            print(f"{numerator(c['expr'])[:26]:<28}{c['alpha_id']:<11}{c['src']:<10}"
                  f"{(c.get('sharpe') or 0):>6.2f}{(c.get('fitness') or 0):>6.2f}"
                  f"{(f'{ly:.2f}' if ly is not None else '未抓'):>9}")
        return 0

    print(f"對前 {len(picks)} 個跑實測 check（每個約 30~60 秒）\n")
    rows = []
    for c in picks:
        aid = c["alpha_id"]
        d, why_c = poll_check(s, aid)
        if d is None:
            print(f"  {numerator(c['expr'])[:26]:<28} {aid}  ✗ {why_c}")
            # 認證死掉的話後面每一條都會同樣死。不 abort 的話這一輪會印出一整排
            # 失敗、最後給一張空的建議表 —— 而「沒有候選」和「沒問到」
            # 在那張表上長得一樣。
            if why_c.startswith("HTTP 401") or why_c.startswith("HTTP 403"):
                print("\n✗ 認證失效，中止本輪(不是沒有候選，是沒問到)。請重新取得 token。")
                return 2
            continue
        if why_c:
            print(f"  {numerator(c['expr'])[:26]:<28} {aid}  ⚠️ {why_c}")
        ck = checks_of(d)
        if ck is None:
            print(f"  {numerator(c['expr'])[:26]:<28} {aid}  ✗ 回 200 但沒有可判讀的 checks（不是全過）")
            continue
        sc = ck.get("SELF_CORRELATION", ("?", None))
        bad = B.non_pass(ck)      # 唯一規則。原本是 == "FAIL",會放行 PENDING/WARNING
        c["self_corr"] = sc[1] if sc[1] is not None else 9
        c["bad"] = bad
        rows.append(c)
        print(f"  {numerator(c['expr'])[:26]:<28} {aid}  self_corr={sc[1]}  "
              f"{'FAIL:' + ','.join(bad) if bad else 'OK'}  [{c['src']}]")

    # ── 排序邏輯（2026-08-28 修正）──
    # 原本純按 self-corr 由低到高排。但實測 8 條全在 0.42~0.52，**遠低於門檻 0.7**，
    # 彼此只差 0.06 —— 拿 0.06 的差距去換掉 Sharpe 2.03、最後一年 2.90 的候選，不划算。
    # → self-corr 當**篩選條件**（<SAFE 就算安全），不當排序依據；
    #   排序改用官方 Quality Factor 真正在意的東西：fitness、以及近年是否撐得住
    #   （官方分數每週依樣本外表現更新 → 最後一年 sharpe 決定交完之後還會不會漲）。
    SAFE = 0.60
    ok = [c for c in rows if not c["bad"]]
    n_filled = fill_year_quality(s, ok)   # 平台側候選到這裡才需要逐年表
    if n_filled:
        print(f"\n（補抓逐年統計 {n_filled} 條）")

    # 🔴 `last_year_sharpe` 抓不到的**不混進主排序**（拿 0 當它會把未知說成很差、
    #    拿高值會把未知說成很好；兩種都是把「沒量到」講成一個量到的數）。
    known = [c for c in ok if _ly(c) is not None]
    unknown = [c for c in ok if _ly(c) is None]

    def quality(c):
        return -((c.get("fitness") or 0) * 1.0 + (_ly(c) or 0) * 0.5
                 + (c.get("sharpe") or 0) * 0.3)

    safe = sorted([c for c in known if c["self_corr"] < SAFE], key=quality)
    risky = sorted([c for c in known if c["self_corr"] >= SAFE],
                   key=lambda c: c["self_corr"])

    print(f"\n建議提交順序（self-corr < {SAFE} 視為安全，之後按品質排）")
    print(f"涵蓋範圍:{coverage}")
    print(f"{'分子':<28}{'id':<11}{'selfCorr':>9}{'sh':>6}{'fit':>6}{'最後年':>8}{'來源':>10}")
    print("-" * 82)
    for c in safe + risky:
        flag = "" if c["self_corr"] < SAFE else "  ⚠️相關偏高"
        print(f"{numerator(c['expr'])[:26]:<28}{c['alpha_id']:<11}{c['self_corr']:>9.4f}"
              f"{(c.get('sharpe') or 0):>6.2f}{(c.get('fitness') or 0):>6.2f}"
              f"{_ly(c):>8.2f}{c['src']:>10}{flag}")
    for c in unknown:
        print(f"{numerator(c['expr'])[:26]:<28}{c['alpha_id']:<11}{c['self_corr']:>9.4f}"
              f"{(c.get('sharpe') or 0):>6.2f}{(c.get('fitness') or 0):>6.2f}"
              f"{'未抓到':>8}{c['src']:>10}  ← 逐年表拿不到,未列入排序")

    best = safe + risky
    if len(best) >= 2:
        print(f"\n→ 交這兩條：{best[0]['alpha_id']}（{numerator(best[0]['expr'])[:22]}）、"
              f"{best[1]['alpha_id']}（{numerator(best[1]['expr'])[:22]}）")
        print("  （一天 2 條吃滿每日 2,000 分上限；必須是**不同分子**否則會撞 self-correlation）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
