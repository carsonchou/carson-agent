#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runway.py — 還剩幾條**真的交得出去**的 alpha？也就是還有幾天跑道。

## 為什麼需要這支（2026-08-29）
帳本說「153 個獨立分子」，但那是**模擬有通過**的數量，不是**交得出去**的數量。
兩者差很多，而我一直拿前者在跟 Carson 報進度。

真正的閘門是 `SELF_CORRELATION < 0.7`，而它是**遞減資源**：
每提交一條，池子就變大一點，剩下的候選就更難不撞。實測軌跡：

    08-27 第 1 條   self-corr ≈ 0（池子空的）
    08-29 第 1 條   0.5242
    08-29 第 2 條   0.6665   ← 門檻 0.7

而且**不只要對已提交的不撞，同一天的兩條彼此也不能撞**
（08-29 原本挑的兩條彼此 0.90，差點白丟一個名額）。
所以這不是「逐條比對」，是**最大獨立集**問題。

## 方法：直接算日 PnL 相關，而不是靠分子名稱猜
分子名稱不可靠 —— `unrecognized_tax_benefits_affecting_tax_rate` 與
`unrecognized_tax_benefit_increase_current_period` 是**不同字串、同一個會計科目**，
實測相關 0.8999。字串比對看不出來。

**這個替身值先驗過**（2026-08-29，n=2）：拿同一套算法算候選對已提交的最大相關，
跟 BRAIN 自己回報的 SELF_CORRELATION 比 —— 誤差 ≤0.01：

    xAjl5o9N   我算 0.5332   BRAIN 0.5242   差 0.009
    Jj73bqOn   我算 0.5958   BRAIN 0.5933   差 0.003

→ 可以用來估算，**但灰帶區間內不能當判準**（誤差蓋過差距），
  灰帶的定義就是下面的常數：`THRESHOLD ± GREY` = **[0.68, 0.72)**
  （實際分類：`< 0.68` 收下、0.68 到 0.72 當測不準、`>= 0.72` 拒；
   浮點上下界是 0.6799999999999999 ⇒ **0.68 本身落在灰帶**），
  那個區間一律回報「要平台實測才知道」。
  🔴 2026-09-09：這裡曾寫「0.69~0.71」，**與程式碼不一致**，由 pv13 那輪抓到。
  不是文書問題：`ZY7MpbJY` 的 0.7173 在兩組邊界下分類不同（拒 vs 測不準），
  而這個錯誤已經經由派工單傳染過一次。**改這段時要連常數一起改。**
  （同病：memory `detector-failure-shapes-2026-09` ⑥：宣稱寫在註解裡，下一個人拿它當規格。）
  這是 memory
  yt-search-capture-engine-2026-08 的教訓：拿替身值分析前先驗替身等不等於真值。

## 貪婪最大獨立集
從 fitness 最高的開始，逐條檢查它對「已提交 + 已選入」的最大相關：
< 門檻就收下，否則丟掉。貪婪不保證最優，但方向保守（實際跑道 ≥ 這個估計），
而且順序照 fitness 排 = 先拿好的，符合實際提交策略。

## 用法
    python runway.py --top 60      # 只評估 fitness 前 60 的候選（預設）
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

THRESHOLD = 0.7
GREY = 0.02          # 門檻上下這個範圍內視為「測不準」
CACHE = ROOT / "pnl_cache.json"

# 🔴 corr() 要求 n >= 100,而 fetch_pnl 收 `len(recs) >= 100` 只產出 len-1 個差分
#    —— 剛好 100 筆的 alpha 會讓 corr **恆回 None**。序列長度必須用同一把尺量,
#    否則「量不了」會被當成「不相關」(舊行為)或「最大相關」(新行為),兩種都錯。
MIN_OBS = 100

# 🔴 每條 alpha 抓 PnL 的**牆鐘**上限(秒)。次數上限擋不住時間成本,
#    因為每次要等多久是對方給的(`Retry-After`)——
#    `brain_auto.py` 的 `poll_check` 為 `/check` 寫過同一句結論。
#    實測:空 records 重試 6 次 × `Retry-After>=60`(被夾在 60)= **360 秒/條**,
#    runway 73 條 ⇒ 7.3 小時;而 `brain_daily_pick`(cron 12:20、15:00 結算,
#    預算 2.6 小時)共用 `fetch_pnl`,19 條 ⇒ 1.9 小時,吃掉大半預算。
#    這個成本是「空 records 要重試」這個修法**新增的**,所以由它自己付上限。
#
# ⚠️ 這個值**未經量測**。repo 內沒有 PnL recordset 的耗時錨(找過 brain_auto
#    與 docs);最近的鄰居是同族非同步端點 `/check` 的 `CHECK_DEADLINE = 180`
#    與同家族 `fetch_yearly` 的隱含預算 ~80 秒。90 是「/check 的一半」,暫定值。
#    穩態下不會咬到(pnl_cache 已有全部序列,走快取零連線),只有**新 alpha**
#    會撞;撞到是 rc=2 大聲中止不是靜默,所以先不要假設平台壞了,調大即可。
#
# ⚠️ 這個 90 只涵蓋 **sleep 那半邊**:deadline 檢查點在 GET **之前**,
#    所以真正的上界是 `90 + 一次 timeout=90` ≈ **180 秒/條**。
#    (`brain_auto.py` 對 `/check` 是把 timeout 那半邊一起算進去的。)
FETCH_DEADLINE = 90.0


# 分子的實作只有 `brain_auto.numerator` 一份(2026-09-08 收斂,原本四份)。
# 舊版只認 `ts_backfill(`,認不出的共用一個 `?` 桶 —— 那個桶幾乎只砍平台側。
numerator = B.numerator


def load_cache() -> dict:
    """回快取 dict。**簽章不動**(brain_daily_pick.py:66,106 靠它)。

    🔴 原本「檔案不存在」與「檔案壞掉」都靜默回 `{}`。方向是安全的(頂多重抓),
       但壞掉這件事沒有任何人會知道,而重抓要花配額。兩者現在分得出來。
    """
    if not CACHE.exists():
        return {}
    try:
        d = json.loads(io.open(CACHE, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {CACHE.name} 讀不得({e})—— 當成空快取,會重抓全部 PnL。",
              file=sys.stderr)
        return {}
    if not isinstance(d, dict):
        print(f"[warn] {CACHE.name} 不是 dict(型別 {type(d).__name__})—— 當成空快取。",
              file=sys.stderr)
        return {}
    return d


def save_cache(cache) -> None:
    """tmp → replace。

    🔴 原本是 `io.open(CACHE, "w").write(json.dumps(cache))` —— `io.open(...,"w")`
       是接收者,**先求值先截斷**,`json.dumps` 之後才跑。中途拋例外就留下一個
       0 bytes 的 pnl_cache.json,而那對下游是「合法但空」的快取(零錯誤訊號),
       重建成本是把全部 PnL 重抓一遍。同 memory write-truncates-before-it-fails。
       (brain_daily_pick 那兩處寫成 `CACHE.write_text(json.dumps(cache))`,
       引數先求值,所以**沒有「先截斷再序列化」這個問題**。但它仍不是原子寫 ——
       中途被砍或磁碟滿一樣會留半截檔。**不要把這句讀成「那個檔的寫入是安全的」。**)
    """
    try:
        blob = json.dumps(cache)          # 先序列化,成功了才碰檔案
    except Exception as e:  # noqa: BLE001
        print(f"[warn] PnL 快取序列化失敗({e}),這一輪不寫檔。", file=sys.stderr)
        return
    tmp = CACHE.with_suffix(CACHE.suffix + ".tmp")
    try:
        io.open(tmp, "w", encoding="utf-8").write(blob)
        os.replace(tmp, CACHE)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] PnL 快取寫入失敗({e})。", file=sys.stderr)


def _clean_series(v):
    """快取條目驗證。壞掉回 None。

    🔴 第一版只檢查**前 5 個元素** ⇒ `[1.0]*5 + [None]*495` 原樣回傳,
       `corr()` 隨即丟未捕捉的 TypeError。而 `isinstance(True, int)` 是 True,
       所以 `[True]*500` 也照收。兩者都由獨立驗證員實測抓到。
       n≈500、alpha≈70,全驗的成本可以忽略,不值得為它留一個型別漏洞。
    """
    if not isinstance(v, list) or len(v) < MIN_OBS:
        return None
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
    return v


def _variance(a):
    n = len(a)
    m = sum(a) / n
    return sum((x - m) ** 2 for x in a)


def usable(series):
    """這條序列**本身**能不能拿去算相關度:長度夠、而且整條的變異不為 0。

    ⚠️ **這不是 `corr()` 回 None 的補集。** 第一版的 docstring 這樣宣稱過,
       獨立驗證員做出反例把它推翻:`usable()` 量的是**整條**序列的變異,
       而 `corr()` 會先把兩邊截成**最後 n 筆**再算變異。所以
       「整條有變異、但最後 100 天完全沒動」的序列 `usable=True` 而 `corr` 回 None。
       兩者量的是**不同窗口**,不可能同進同退。

       ⇒ `corr` 回 None 仍然會發生,而且**那是資料條件不是 bug**。
         main() 因此把它記成「比較視窗內零變異」並把該候選歸入「沒量到」,
         不是印一句「這是 bug」把讀的人導向錯的方向(第一版就是這樣寫的)。

    留著這支的理由:它在**源頭**擋掉整條都不能用的序列,
    讓 `corr` 回 None 的情形從「常態」縮到「窗口退化」這一種。
    """
    return (isinstance(series, list) and len(series) >= MIN_OBS
            and _variance(series) > 0)


def fetch_pnl_ex(s, aid, cache, deadline=None):
    """回 `(diffs, reason)`。`diffs is None` ⟺ `reason` 是非空字串。

    🔴 2026-09-05:原本這裡有 **5 條路徑回同一個 `None`** ——
       重試用完 / 非 2xx / 回傳不是 JSON / 資料筆數不足 / 快取值壞掉。
       只有「筆數不足」是真實資料條件,其餘都是「沒量到」,而呼叫端 `if p:`
       把兩者折成同一件事。

       後果實測(獨立驗證員,stub、不連網):已提交的池子裡讓一條回
       401/403/429/500/502/空body/非JSON/非dict/records非list 共 9 種,
       候選對池子的最大相關 **0.9988 級的真相關被算成 0.0078**,
       分類 **rejected → accepted**。單一次 5xx 就把「和已提交的幾乎一模一樣」
       翻成「不相關,收下」。而 self-correlation 是這條線唯一真正稀缺的資源。

    🔴 第二版補:**`recordsets` 是非同步端點** —— 回 200 但 `records` 可能還沒
       算好(`brain_auto.py` 對 `/check` 有同樣註記)。第一版只對**空 text** 重試,
       沒對**空 records** 重試,於是把「還沒算好」讀成「這條 alpha 沒有 PnL」,
       再被我自己新發明的「資料不足」類別歸成真實資料條件 ——
       **用一條新路徑重造了同一個 bug**,而且輸出還主動宣稱「不影響判斷」。
    """
    v = _clean_series(cache.get(aid))
    if v is not None:
        return v, ""
    cache.pop(aid, None)          # 壞掉或太短就丟掉重抓,不要靜默沿用
    if deadline is None:
        deadline = FETCH_DEADLINE
    t0 = time.monotonic()
    r = None
    last = "未知"                  # 🔴 三條耗盡路徑原本共用同一句 reason
    for attempt in range(6):
        # 🔴 用 `>=` 不是 `>`:下面的 sleep 夾成「剩餘時間」,elapsed 會**漸近逼近
        #    deadline 但不超過**,`>` 因此可能永遠不成立 —— deadline 等於沒生效,
        #    而外表完全正常(照樣從次數用完那條出去,只是訊息講錯原因)。
        #    這個坑 09-05 在 brain_auto.poll_check 上真的踩過一次。
        if time.monotonic() - t0 >= deadline:
            # 🔴 帶上「試了幾次」與「伺服器要求等多久」:這個 deadline 是暫定值,
            #    而**第一次真的撞到就是唯一一次免費的量測機會**。只寫「超過 90 秒」
            #    的話,下一個人知道不夠卻不知道該調到多少。
            return None, ("超過 %g 秒仍拿不到(試了 %d 次;最後一次:%s;"
                          "伺服器最後要求等 %s 秒)"
                          % (deadline, attempt, last,
                             (getattr(r, "headers", None) or {}).get("Retry-After", "未給")))
        r = s.get(f"{B.API}/alphas/{aid}/recordsets/pnl", timeout=90)
        if r.status_code == 429:
            last = "429 限流"
            time.sleep(min(40, 3 * 2 ** attempt,
                           max(0.0, deadline - (time.monotonic() - t0)))); continue
        if r.status_code == 401:
            last = "401 未認證(已重取 cookie 重試)"
            s.cookies.update(B.auth().cookies); continue
        if not r.ok:
            return None, "HTTP %s: %s" % (r.status_code, (r.text or "")[:60])
        if not (r.text or "").strip():
            last = "回應 body 空白"
            time.sleep(min(B._retry_after(r, 3),
                           max(0.0, deadline - (time.monotonic() - t0)))); continue
        try:
            j = r.json()
        except Exception as e:  # noqa: BLE001
            return None, "回傳不是 JSON: %s (%s)" % ((r.text or "")[:60], e)
        if not isinstance(j, dict):
            return None, "回傳不是 dict(型別 %s)" % type(j).__name__
        recs = j.get("records")
        if recs is None or (isinstance(recs, list) and not recs):
            # 非同步端點還沒算好 ⇒ 要等,不是「這條沒有 PnL」。
            last = "回 200 但 records 仍是空的(非同步端點尚未算好)"
            time.sleep(min(B._retry_after(r, 3),
                           max(0.0, deadline - (time.monotonic() - t0)))); continue
        if not isinstance(recs, list):
            return None, "records 不是 list(型別 %s)" % type(recs).__name__
        break
    else:
        return None, "重試 6 次仍拿不到(最後一次:%s)" % last
    try:
        vals = [row[1] for row in recs]                  # [date, cumulative_pnl]
        diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    except Exception as e:  # noqa: BLE001
        return None, "records 形狀不對: %s" % e
    if not diffs:
        # 🔴 0 個觀測**不是**「這條 alpha 太年輕」。已提交(ACTIVE)的 alpha 一定有
        #    回測期間的 PnL;拿到 0 列代表沒量到,不可以歸成真實資料條件。
        return None, "沒量到:records 只有 %d 列,算不出任何觀測" % len(recs)
    if len(diffs) < MIN_OBS:
        return None, "資料不足(只有 %d 個觀測,需要 %d)" % (len(diffs), MIN_OBS)
    if _variance(diffs) <= 0:
        # 零變異 = 相關度在數學上沒有定義。放著會讓 corr 回 None,
        # 而那個 None 若被當成「不相關」就是 fail-open。在源頭擋掉。
        return None, "PnL 完全沒有變動(零變異),相關度沒有定義"
    cache[aid] = diffs
    return diffs, ""


def fetch_pnl(s, aid, cache):
    """回日 PnL 差分序列,拿不到回 None。

    ⚠️ **簽章保持原樣**:唯一的外部呼叫端 `brain_daily_pick.py`(cron 每天 12:20)
       在三處用 `d is None` / `if d` 判斷。改成二元組會讓 tuple 恆為 truthy,
       相關度全部歸零、**全部 accepted** —— 比原本的缺陷嚴重得多。
       (那正是 09-05 上一批修 poll_check 時真的踩到的迴歸。)
       要原因的呼叫端請直接用 `fetch_pnl_ex`。
    """
    return fetch_pnl_ex(s, aid, cache)[0]


def corr(a, b):
    """Pearson 相關。**算不出來回 None**(簽章不動,brain_daily_pick 靠它)。

    ⚠️ 回 `None` 的意思是「沒量到」,**不是「不相關」**。呼叫端把它當成 0
       就是 fail-open。本檔 `main()` 現在當成最大相關處理,見那邊的註解。
    """
    n = min(len(a), len(b))
    if n < MIN_OBS:
        return None
    a, b = a[-n:], b[-n:]
    ma = sum(a) / n; mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (va ** 0.5 * vb ** 0.5)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    top = 60
    if "--top" in sys.argv:
        i = sys.argv.index("--top")
        if len(sys.argv) > i + 1:
            top = int(sys.argv[i + 1])

    s = B.auth()
    cache = load_cache()

    # 已提交的（池子）
    # 🔴 2026-09-05:原本這裡內嵌六道守衛,而 pick_next 有另一份 —— 兩份對
    #    `{"id": 7}` 與重複 id 的判定相反。合併進 brain_auto.active_alpha_ids,
    #    並改用權威的 `count` 而不是「剛好回滿 100 筆」這個代理訊號
    #    (`{"count":250,"results":[50 筆]}` 會讓代理訊號靜默放行一份偏小的清單)。
    active_set, why_active = B.active_alpha_ids(s)
    if active_set is None:
        print(f"✗ 取不到已提交清單:{why_active}")
        print("  池子是所有判斷的基準，拿不到就不能算 —— 中止。")
        print("  (空池子和『問不到』在下游長得一樣:前者讓每個候選最大相關都是 0。)")
        return 2
    active = sorted(active_set)
    if not active:
        # 🔴 **不中止**:平台誠實回報零提交時,「候選全部安全」就是正確答案
        #    (開站第一天)。但這個結果**沒有判別力**,而它長得跟
        #    「池子很大、候選真的都不撞」一模一樣 —— 讀的人要分得出來。
        print("⚠️ 已提交 0 條 —— 池子是空的，以下每個候選的最大相關都會是 0，"
              "**這個結果沒有判別力**（不是「都不撞」，是沒有東西可以撞）。")
    print(f"已提交 {len(active)} 條，抓 PnL…")

    # 🔴 單一規則:**任何無法納入相關度計算的池成員,都讓池子不完整。**
    #    第一版把「資料不足」另立成一類、排除掉並印「（真實資料條件，不影響判斷）」
    #    —— 那句話是假的。我們就是無法判斷候選跟它撞不撞,而候選對它的真相關
    #    可能是 ~1.0(獨立驗證員實測:0 觀測那條讓 accepted 誤收)。
    #    理由仍然要分得出來(沒量到 / 資料不足 / 零變異),但**處置只有一種**。
    pool, pool_bad = [], []
    for aid in active:
        p, why = fetch_pnl_ex(s, aid, cache)
        if p is None or not usable(p):
            pool_bad.append((aid, why or "序列不可用於相關度計算"))
            continue
        pool.append((aid, p))
    save_cache(cache)
    print(f"  取得 {len(pool)}/{len(active)} 條的 PnL")

    # 原本這裡只印「已提交 N」與「取得 M」兩個數字,**沒有任何斷言在比對它們**
    # —— 訊息在畫面上,不在判斷裡。
    if pool_bad:
        # 🔴 分兩段:重跑會好 vs 重跑不會好。--allow-incomplete-pool 是為
        #    **暫時性失敗**設計的逃生門;套在**永久性資料條件**上會退化成
        #    「每次都要帶旗標」,那句「偏樂觀、不可直接提交」就變成常態雜訊而失效。
        transient = [(a, w) for a, w in pool_bad
                     if not (w.startswith("資料不足") or "零變異" in w)]
        permanent = [(a, w) for a, w in pool_bad if (a, w) not in transient]
        print(f"\n✗ 已提交的池子不完整：{len(active)} 條裡有 {len(pool_bad)} 條"
              f"無法納入相關度計算。")
        if transient:
            print("  【重跑會好】沒量到:")
            for aid, why in transient:
                print(f"    {aid}  {why}")
        if permanent:
            print("  【重跑不會好】這是這條 alpha 的永久狀態:")
            for aid, why in permanent:
                print(f"    {aid}  {why}")
            print("    → 這一格比較我們永遠量不到。要嘛接受偏誤，")
            print("      要嘛把「把它排除出池子」這個決定寫下來，不要每次都帶旗標。")
        if "--allow-incomplete-pool" not in sys.argv:
            print("\n  池子少一條 = 候選對它的相關度**量不到** = 會把該擋的收下。")
            print("  「資料不足」也算在內：它是真實資料條件，但一樣代表我們")
            print("  判斷不了候選跟它撞不撞 —— 排除它不等於它不影響結果。")
            print("  稍後重跑，或明知偏誤時加 --allow-incomplete-pool。")
            return 2
        print("\n  ⚠️ --allow-incomplete-pool：以下結果**偏向樂觀**"
              "（相關度被低估），不可以直接拿去提交。")

    # ── 候選池:帳本 ∪ 平台快照,每個分子取 fitness 最高 ──
    # 🔴 2026-09-08:這裡原本自己寫了一份「帳本 → 每分子取最好 → 扣掉已提交」,
    #    是同一條規則的**第三份實作**,而且**池子只有帳本** ⇒ 平台上跑完、
    #    checks 零 FAIL、帳本卻記成失敗的那一群(對帳實據 213 條)結構上看不到,
    #    跑道因此系統性偏短。改成呼叫 pick_next 的共用純函式。
    # 📌 順帶修掉「別名」造成的重複:平台對同一個欄位收兩個別名,帳本兩列、
    #    平台同一個 alpha_id ⇒ 舊寫法會產生兩條候選(實測 674 條裡重複 154 條、
    #    `--top 60` 內重複 8 條 = 評估名額被自己吃掉)。`build_pool()` 以
    #    alpha_id 為鍵,結構上不可能再出現同 id 兩條。
    import pick_next as P  # noqa: PLC0415  函式內 import,避免模組層互相牽動
    import reconcile as RC  # noqa: PLC0415
    led = B.load_ledger()
    plat, snap_meta, snap_why = RC.load_snapshot()
    if plat is None:
        # fail-closed。退回帳本-only 會讓跑道**偏短而且不自知** —— 那正是這次修掉的病。
        # 與 `--allow-incomplete-pool` 是兩件事:那道守的是「已提交池少一條」,
        # 這道守的是「候選池少一半」,不要互相代用。
        print(f"\n✗ 平台快照拿不到:{snap_why}")
        print("  候選池要「帳本 ∪ 平台」才完整,只用帳本會讓跑道系統性偏短。")
        print("  先跑:python reconcile.py --snapshot（約 10 分鐘，唯讀）")
        return 2
    cand, pool_st = P.build_pool(led, plat, set(active))
    picks, _by, _dn = P.dedup_by_numerator(cand, led, plat, set(active))
    _famcut = P.excluded_by_done_nums(_by, _dn)
    if _famcut:
        # 這一刀不出現在下面任何一張表上（它在清單成形之前就砍了）。
        print(f"  另有 {len(_famcut)} 條因『分子已交過』整族排除"
              f"（最高 fitness {(_famcut[0].get('fitness') or 0):.2f}）——"
              f"它們不會出現在下面任何一張表上。")
    cands = sorted(picks, key=lambda c: -(c.get("fitness") or 0))[:top]
    print(f"候選池:帳本 ∪ 平台快照 {snap_meta['count']} 條"
          f"（{snap_meta['fetched_at']}，{snap_meta['age_h']:.1f}h 前）"
          f" → 合格未提交 {pool_st['qualified_excl_done']}"
          f"（平台獨有 {pool_st['cand_by_src']['platform']}）")
    print(f"候選 {len(cands)} 條（每個分子取 fitness 最高、扣掉已提交），逐條抓 PnL…\n")

    accepted, grey, rejected = [], [], []
    unassessed = []                # 候選自己沒量到 —— 不可以靜默消失
    window_blind = 0               # corr 回 None 的次數 —— 資料條件,不是 bug
    chosen = list(pool)            # 已提交 + 已選入,都算進池子
    for c in cands:
        aid = c["alpha_id"]
        p, why = fetch_pnl_ex(s, aid, cache)
        if p is None or not usable(p):
            # 舊行為是 `if not p: continue` —— 方向安全(不會被推薦),但它讓
            # accepted+grey+rejected 的總和**悄悄小於候選數**,而「跑道 N 天」
            # 正是從 accepted 算出來的。少掉的那些要講出來。
            unassessed.append((aid, numerator(c["expr"]), why or "序列不可用"))
            continue
        mx, who, blind = 0.0, None, None
        for oid, op in chosen:
            v = corr(p, op)
            if v is None:
                blind = oid
                break
            if abs(v) > mx:
                mx, who = abs(v), oid
        if blind is not None:
            # 🔴 `corr` 回 None = **這一格比較量不到**,不是「不相關」(舊行為直接
            #    跳過 ⇒ mx 偏低 ⇒ 誤收),也不是 bug(第一版的告警這樣寫,方向錯)。
            #    usable() 量整條變異、corr() 量最後 n 筆的變異,兩者本來就會分歧。
            #    量不到就不給它一個分類 —— 歸「沒量到」,理由指名是哪一條。
            window_blind += 1
            unassessed.append((aid, numerator(c["expr"]),
                               "與 %s 的比較視窗內零變異，相關度沒有定義" % blind))
            continue
        row =(mx, numerator(c["expr"]), aid, c.get("fitness"), who)
        if mx < THRESHOLD - GREY:
            accepted.append(row); chosen.append((aid, p))
        elif mx < THRESHOLD + GREY:
            grey.append(row)
        else:
            rejected.append(row)
        save_cache(cache)
    # 🔴 迴圈內的 save_cache 只在**分類成功**那條路徑上;走 unassessed /
    #    window-blind 的 `continue` 不會存,而那些候選的 PnL 已經抓下來了。
    #    最後幾條若都沒量到,那幾次抓取就白花。收尾再存一次。
    save_cache(cache)

    print(f"{'分子':<44}{'id':<11}{'fit':>6}{'最大相關':>10}  撞到誰")
    print("-" * 88)
    for mx, n, aid, fi, who in accepted:
        print(f"{n[:42]:<44}{aid:<11}{(fi or 0):>6.2f}{mx:>10.4f}  {who}")
    if grey:
        print(f"\n【測不準區 {THRESHOLD-GREY:.2f}~{THRESHOLD+GREY:.2f}】我的方法誤差 ±0.01，"
              f"這些要平台實測才知道：")
        for mx, n, aid, fi, who in grey:
            print(f"{n[:42]:<44}{aid:<11}{(fi or 0):>6.2f}{mx:>10.4f}  {who}")

    if unassessed:
        print(f"\n【沒量到，未列入任何一類】{len(unassessed)} 條 —— "
              f"這些**不是**「確定撞」，是沒問到：")
        for aid, n, why in unassessed[:12]:
            print(f"{n[:42]:<44}{aid:<11}  {why}")
        if len(unassessed) > 12:
            print(f"    …另外 {len(unassessed) - 12} 條")

    print(f"\n{'='*88}")
    print(f"安全可交 {len(accepted)} 條 | 測不準 {len(grey)} 條 | "
          f"確定撞 {len(rejected)} 條 | 沒量到 {len(unassessed)} 條")
    # 🔴 對帳:四類相加必須等於候選數。對不上代表有一整類在中途消失了,
    #    而「跑道 N 天」是從 accepted 算的 —— 分母悄悄變小不會有任何錯誤訊號。
    tot = len(accepted) + len(grey) + len(rejected) + len(unassessed)
    # ⚠️ **這是給未來改動用的絆索,不是現在會叫的檢查。** 目前每個 cands 項目
    #    都必然落進四類之一,所以它結構上不可能觸發 —— 但正因如此,下一個看到
    #    「永遠 False 的分支」的人很可能把它當死碼清掉。它的價值在下一次改動:
    #    有人新增一條 `continue` 而忘記歸類時,這裡會叫。**不會叫 ≠ 沒價值。**
    if tot != len(cands):
        print(f"⚠️ 對帳不符：四類合計 {tot} ≠ 候選 {len(cands)}，"
              f"上面的數字有一類沒被算進來，不要引用。")
    if window_blind:
        print(f"⚠️ 有 {window_blind} 條候選因為「比較視窗內零變異」量不到相關度，"
              f"已歸入『沒量到』(不是確定撞)。usable() 量整條變異、corr() 量最後 n 筆，"
              f"兩者本來就會分歧 —— **這是資料條件,不是 bug**。")
    days = len(accepted) // 2
    print(f"→ 一天 2 條，跑道約 **{days} 天**"
          f"（樂觀情境含測不準：{(len(accepted)+len(grey))//2} 天）")
    measured = len(accepted) + len(grey) + len(rejected)
    if len(unassessed) > measured:
        # 🔴 「0 天」會被讀成「候選全撞了」,而這裡的 0 天是「大部分根本沒量到」。
        #    這行是唯一會被單獨引用的數字,所以差別要寫在它旁邊,不是只寫在上面。
        #
        # 🔴 判準是「沒量到的 > **全部量到的**」,不是「> accepted」。
        #    第一版寫成 `> len(accepted)`,而 accepted=0 時任何一條沒量到都成立
        #    —— 「0 安全 / 48 確定撞」正是這條線的常態(`hybrid_miner.py:6`)⇒
        #    這個 ⚠️ 會幾乎每次真跑都出現、退化成常駐雜訊,等到真正該叫的那次
        #    (大部分沒量到)就沒人看了。**告警的價值等於它沉默的時候比較多。**
        print(f"   ⚠️ 沒量到的（{len(unassessed)}）比量到的（{measured}）還多"
              f" —— 這個天數是**下界中的下界**，先把沒量到的弄清楚再引用它。")
    print("注意：貪婪解，實際跑道 ≥ 這個估計；且每交一條門檻就更緊，要持續重算。")
    if pool_bad:
        print("⚠️ 本次池子不完整(--allow-incomplete-pool)，以上偏樂觀，不可直接拿去提交。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
