#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""field_miner.py — 全欄位系統性挖礦（一階掃描）。

## 為什麼需要這支（2026-08-27）
`brain_auto.py` 的候選是**手寫模板**，跑了 350 條只用到 15 個資料欄位。
而平台對這個帳號開放 **4,367 個欄位**（14 個資料集）—— 覆蓋率 **0.34%**。

手寫再多模板都不叫挖因子。真正該做的是：
**拿已經實測有效的模板，套遍每一個欄位。**

實測基準（`brain_auto` 跑出來的）：
    group_rank(ts_rank(winsorize(ts_backfill(est_eps/close, 120), std=4), 126), subindustry)
    → Sharpe 2.25 / Fitness 1.34 / Turnover 24.1%  ← 已提交
**所以模板是對的，缺的是欄位廣度。**

## 一階 / 二階
- **一階（本檔）**：一模板 × 全欄位。目的是**找出哪些欄位本身有訊號**，
  不求最佳化。跑完會得到一張「欄位 → sharpe/fitness」的地圖。
- **二階**：只對一階有訊號的欄位做參數與運算子變化。
  ⚠️ 二階做出來的是**孿生 alpha**（self-corr 0.9+，交不出去）。
  一階找到的**獨立分子**才是能提交的資源 —— 所以一階永遠優先。

## ⚠️ 兩個排序事故（2026-08-29 修正）—— 都是「拿代理指標排序，沒檢查硬約束」

### 事故一：VECTOR 欄位燒掉 1,233 次模擬，命中 0
原本按 `alphaCount` 由低到高排（冷門優先，理由是 SelfCorrelation 越低分越高）。
`news12` 正好是全平台最冷門的資料集 → 掃描器一開工就一頭撞進去，連撞 1,173 次，
**每一次都是同一個錯誤**：

    Operator divide / ts_backfill does not support event inputs

根因：欄位有兩種 `type`，而 `ALL_FIELDS.json` 當初**沒存**：
  · `MATRIX` —— 一股一值，算術運算子直接吃
  · `VECTOR` —— 一股一串事件，**必須先 vec_avg 收斂**才能做算術
`news12` 800/875 是 VECTOR。全平台共 **1,387 個 VECTOR 欄位**，
在舊模板下 100% 打不到 —— 而它們正是 alphaCount 最低的一批。
→ 修法不是跳過，是**給 VECTOR 一套自己的模板**（見 VEC_FORMS），把 1,387 個欄位解鎖。

### 事故二：命中率最高的資料集被排到隊尾
實測各資料集命中率差 **4 倍以上**：
    fundamental2   掃 402  命中 114  28.4%   ← 最高產
    analyst4       掃 607  命中  40   6.6%
而 `fundamental6`（同家族、574 個 MATRIX 欄位）只掃了 10 個，
因為它 alphaCount 高，被「冷門優先」推到最後面。

→ 排序改成 **產出率優先、擁擠度其次**。產出率直接從帳本即時算，
  沒掃過的資料集用 `(命中+1)/(已掃+4)` 當先驗（≈0.25，介於最好與次好之間）：
  已證明高產的先掃、沒資料的次之、已證明低產的最後。**會隨資料自動修正。**

## 用法
    python field_miner.py --plan          # 只列掃描順序,不打 API
    python field_miner.py --run 200       # 掃 200 條
    python field_miner.py --run 20 --vector   # 只掃 VECTOR（新模板驗證用）
    python field_miner.py --yield         # 只看各資料集實測命中率
"""
from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B  # noqa: E402

FIELDS_FILE = ROOT / "ALL_FIELDS.json"
TYPES_FILE = ROOT / "FIELD_TYPES.json"

# 一階模板：實測 Sharpe 2.25 的那個形狀。{X} 填「已經是 matrix 的運算式」。
# winsorize+ts_backfill 是官方對 weight test / 稀疏資料的指定解法；
# group_rank(..., subindustry) 讓訊號在產業內部排序，壓 CONCENTRATED_WEIGHT 與
# LOW_SUB_UNIVERSE_SHARPE（那是我卡最久的兩關）。
TEMPLATE = "group_rank(ts_rank(winsorize(ts_backfill({X}, 120), std=4), 126), subindustry)"

# ── MATRIX 欄位的三種讀法 ──
# 依據：**所有雙門檻達標的 alpha 都是比率**（est_eps/close、operating_income/equity）。
# 比率把規模除掉，正好解掉官方點名的 sub-universe 殺手（size 乘數）。
FORMS = {
    "raw":     "{F}",
    "per_px":  "{F}/close",     # 除以股價 → 殖利率型（est_eps/close 就是這型）
    "per_cap": "{F}/cap",       # 除以市值 → 規模中性
}

# ── VECTOR 欄位：先收斂成 matrix，才能套同一套比率邏輯 ──
# 這個帳號只開放兩個 vec 運算子（OPERATOR_SIGS.txt 實查）：vec_avg(x) / vec_sum(x)。
# 用 avg 不用 sum：sum 會被「該股當期有幾則事件」放大 —— 那是覆蓋度不是訊號，
# 且會直接把 CONCENTRATED_WEIGHT 推爆（事件多的大型股吃掉全部權重）。
VEC_FORMS = {
    "v_raw":     "vec_avg({F})",
    "v_per_px":  "vec_avg({F})/close",
    "v_per_cap": "vec_avg({F})/cap",
}

SETTINGS = dict(B.BASE)
SETTINGS.update(decay=0, truncation=0.1, nanHandling="ON", universe="TOP3000")

# 覆蓋率太低的欄位不值得掃：資料缺太多會直接掛 CONCENTRATED_WEIGHT
MIN_COVERAGE = 0.30


def load_types() -> dict:
    """{field_id: 'MATRIX'|'VECTOR'}。抓不到就回空 dict（退回舊行為，不要當掉）。"""
    if not TYPES_FILE.exists():
        print("⚠️ 沒有 FIELD_TYPES.json —— 先跑 fetch_field_types.py，"
              "否則會重蹈 VECTOR 燒 1,233 次的覆轍", file=sys.stderr)
        return {}
    raw = json.loads(io.open(TYPES_FILE, encoding="utf-8").read())
    out = {}
    for _ds, m in raw.items():
        for k, v in m.items():
            if k != "_complete":
                out[k] = v
    return out


# 「這個模板餵這種型別的資料根本跑不動」的錯誤字樣。
# 這類失敗量的是**模板寫錯**，不是資料沒訊號 —— 不可以算進命中率的分母。
STRUCTURAL_ERR = ("does not support event inputs", "Incompatible unit")


def _structural(r: dict) -> bool:
    e = r.get("error") or ""
    return any(k in e for k in STRUCTURAL_ERR)


def dataset_yield(led: dict) -> dict:
    """從帳本即時算各資料集命中率。回傳 {dataset: 後驗命中率}。

    `(命中+1)/(有效已掃+4)` —— 沒掃過的資料集得到 0.25，
    排在已證明高產的之後、已證明低產的之前。掃越多越接近真值。

    ⚠️ **結構性錯誤不進分母**（2026-08-29）。
    否則會出現這種自我實現的死結：`news12` 用舊模板掃了 1,053 次全滅，
    產出率被算成 0.001 → 永久排到隊尾。但那 1,053 次失敗量的是
    「舊模板不吃 VECTOR」這個**已經修好的 bug**，不是「news12 沒訊號」。
    拿一個不再成立的理由把 800 個全平台最冷門的欄位打入冷宮，
    正是 memory `yt-quality-score-not-predictive` 記的同一種病：
    **用內部指標排序前，先確認那個指標量的是你以為的東西。**
    """
    tot, hit = defaultdict(int), defaultdict(int)
    for r in led.values():
        lab = str(r.get("label", ""))
        if not lab.startswith("F1|"):
            continue
        parts = lab.split("|")
        if len(parts) < 2:
            continue
        if _structural(r):
            continue
        ds = parts[1]
        tot[ds] += 1
        if r.get("ok") and (r.get("result") or {}).get("evaluable_pass"):
            hit[ds] += 1
    return {ds: (hit[ds] + 1) / (tot[ds] + 4) for ds in set(tot) | set(hit)}


def load_fields(led=None):
    """回傳 [(dataset, field, coverage, alphaCount, type)]，依「產出率優先」排序。"""
    raw = json.loads(io.open(FIELDS_FILE, encoding="utf-8").read())
    types = load_types()
    yld = dataset_yield(led if led is not None else B.load_ledger())
    PRIOR = 0.25                      # 沒掃過的資料集
    out = []
    for ds, rows in raw.items():
        for r in rows:
            fid = r[0]
            cov = r[1] if len(r) > 1 else None
            ac = r[2] if len(r) > 2 else None
            if not fid:
                continue
            if cov is not None and cov < MIN_COVERAGE:
                continue
            out.append((ds, fid, cov or 0, ac if ac is not None else 10 ** 9,
                        types.get(fid, "MATRIX")))
    # 同資料集內：冷門的先、覆蓋率高的先
    out.sort(key=lambda x: (x[3], -x[2]))

    # 🔴 2026-09-01：**不要**全域照產出率排序。
    # 那樣整個隊伍前段會是同一個資料集（實測：前 800 條全是 fundamental2），
    # 而 fundamental2 已經產出 1,154 條「通過」——**可提交的是 0 條**，全是孿生體。
    # 產出率量的是「過不過閘門」，我們要的是「交不交得出去」，兩者在飽和的
    # 資料集上完全脫鉤。今天實測：跨資料集兩兩 PnL 相關 10 組只有 1 組 ≥0.7，
    # **多樣性才是可提交量的來源**。同一個錯誤在 brain_daily_pick 挑片那邊
    # 也犯了一次（高分榜被 fundamental2 塞滿），這裡是它的上游。
    #
    # 改成資料集之間輪流（round-robin），產出率只決定**輪內順序**，
    # 不再決定「誰先掃完整個資料集」。已證明沒訊號的（掃過 ≥300 條、
    # 產出率 <0.02）排到最後，但不排除 —— news12 的教訓是低產出率可能
    # 量的是我自己的 bug，不是資料集本身（見 dataset_yield 的註解）。
    groups = defaultdict(list)
    for x in out:
        groups[x[0]].append(x)
    live, dead = [], []
    for ds in groups:
        (dead if yld.get(ds, PRIOR) < 0.02 else live).append(ds)
    live.sort(key=lambda d: -yld.get(d, PRIOR))
    dead.sort(key=lambda d: -yld.get(d, PRIOR))
    mixed = []
    for order in (live, dead):
        for i in range(max((len(groups[d]) for d in order), default=0)):
            for d in order:
                if i < len(groups[d]):
                    mixed.append(groups[d][i])
    return mixed


def forms_for(ftype: str) -> dict:
    """欄位型別 → 該用哪組模板。**不認得的型別回空 dict（跳過），不要猜。**

    🔴 2026-08-29 這裡踩了兩次同型錯誤，第二次才改成白名單：
      1. 第一次：只有一組模板，VECTOR 欄位全滅（1,233 次模擬）
      2. 第二次：改成「VECTOR 用 vec 模板、其他一律當 MATRIX」——
         結果 `GROUP` 型別（分類欄位，例如 `pv13_1l_scibr` 是 sector 分群）
         被當成 MATRIX 丟進算術運算子，開場連撞 14 次 `Incompatible unit`。

    平台實際有 **5 種** type，不是 2 種：
        MATRIX 2,828 · VECTOR 1,387 · GROUP 142 · SYMBOL 4 · UNIVERSE 6
    `pv13` 的 165 個欄位裡有 **135 個是 GROUP** —— 所以一掃 pv13 就整片失敗。

    「其他一律當 X」是黑名單思維：每出現一種沒想到的型別就再燒一輪模擬才發現。
    改成白名單 —— 只有明確知道怎麼處理的型別才產生候選，其餘直接跳過。
    """
    if ftype == "VECTOR":
        return VEC_FORMS
    if ftype == "MATRIX":
        return FORMS
    return {}                      # GROUP / SYMBOL / UNIVERSE：算術運算子吃不下


def cmd_yield():
    led = B.load_ledger()
    yld = dataset_yield(led)
    tot, hit = defaultdict(int), defaultdict(int)
    for r in led.values():
        lab = str(r.get("label", ""))
        if lab.startswith("F1|") and len(lab.split("|")) > 1:
            ds = lab.split("|")[1]
            tot[ds] += 1
            if r.get("ok") and (r.get("result") or {}).get("evaluable_pass"):
                hit[ds] += 1
    print(f"{'dataset':<16}{'已掃':>7}{'命中':>7}{'實測':>9}{'排序用':>9}")
    print("-" * 50)
    for ds in sorted(yld, key=lambda d: -yld[d]):
        raw_rate = hit[ds] / tot[ds] if tot[ds] else 0
        print(f"{ds:<16}{tot[ds]:>7}{hit[ds]:>7}{raw_rate:>8.1%}{yld[ds]:>9.3f}")


def cmd_plan(n=40):
    fs = load_fields()
    nv = sum(1 for x in fs if x[4] == "VECTOR")
    print(f"可掃欄位 {len(fs)} 個（MATRIX {len(fs)-nv} / VECTOR {nv}，"
          f"已濾掉 coverage < {MIN_COVERAGE:.0%}）\n")
    print(f"{'dataset':<15}{'field':<40}{'type':<8}{'cov':>7}{'已建alpha':>10}")
    print("-" * 82)
    for ds, f, cov, ac, ty in fs[:n]:
        print(f"{ds:<15}{f[:38]:<40}{ty:<8}{cov:>7.1%}{ac:>10,}")
    print(f"\n… 另外 {max(0, len(fs)-n)} 個")


def cmd_run(n, only_type=None, only_ds=None):
    """掃描順序：**同一個欄位的三種形式排在一起**，不是掃完 raw 才掃 per_px。

    這樣才能對每個欄位一次得到完整判斷（原始值沒訊號但比率有，是很常見的），
    而不是等全部欄位的 raw 都跑完（約 3 天）才開始測比率。
    """
    led = B.load_ledger()
    fs = load_fields(led)
    todo = []
    for ds, f, cov, ac, ty in fs:
        if only_type and ty != only_type:
            continue
        if only_ds and ds not in only_ds:
            continue
        for form, pat in forms_for(ty).items():
            expr = TEMPLATE.format(X=pat.format(F=f))
            if B._key(expr, SETTINGS) in led:
                continue
            todo.append((f"F1|{ds}|{f}|{form}", expr, dict(SETTINGS)))
        if len(todo) >= n:
            break
    if not todo:
        print("全部欄位都掃過了。")
        return
    nv = sum(1 for t in todo if t[0].rsplit("|", 1)[-1].startswith("v_"))
    print(f"一階掃描：{len(todo)} 條（MATRIX {len(todo)-nv} / VECTOR {nv}），"
          f"產出率優先排序，2 worker 併發")
    print(f"  首條：{todo[0][0]}")
    print(f"        {todo[0][1]}")
    B.candidates = lambda: todo          # noqa: E731  一次性覆寫
    B.cmd_run(len(todo))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    if "--yield" in a:
        cmd_yield()
    elif "--plan" in a:
        cmd_plan()
    elif "--run" in a:
        i = a.index("--run")
        ot = "VECTOR" if "--vector" in a else ("MATRIX" if "--matrix" in a else None)
        # --only ds1,ds2 —— 強制只掃指定資料集。
        # 為什麼需要:預設排序是「產出率優先」,而產出率是從帳本算的,
        # 沒掃過的資料集只拿到 0.25 先驗,永遠排在已證明高產的 fundamental2 後面。
        # 但 2026-08-29 發現真正缺的不是「更多有訊號的欄位」而是**不相關的資料領域**,
        # 而選擇權/風險模型/社群這三個領域是 0 次模擬 —— 要能手動插隊。
        ods = None
        if "--only" in a:
            j = a.index("--only")
            if len(a) > j + 1:
                ods = set(a[j + 1].split(","))
        cmd_run(int(a[i + 1]) if len(a) > i + 1 else 100, only_type=ot, only_ds=ods)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
