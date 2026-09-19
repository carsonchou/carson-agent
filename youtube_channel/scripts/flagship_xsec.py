# -*- coding: utf-8 -*-
"""旗艦片《抱得住嗎》的**橫斷面計算層** —— 所有數字在這裡算,旁白從這裡取值。

## 為什麼分成獨立一支

`flagship_engine.py` 負責組稿(接 produce_batch 的合約),本檔只負責**算**。
分開的理由是**可以被獨立驗證**:驗證員可以只跑這一支、拿它的輸出跟自己重算的比,
不必讀組稿邏輯。2026-09-06 督導指定的驗證重點就是
「那四個數字每一個都要能追到結構化欄位」。

## 🔴 一律讀 `data.*` 結構化欄位,不准用 regex 撈 claim 句子

我 2026-09-06 第一版是用 `re.search(r"總報酬\\s*(-?[\\d,.]+)%", claim)` 撈的,
**漏掉 13 檔**(claim 句型不統一),中位數就從 559.8% 飄成 569%
—— **而且不會有任何錯誤訊號**,兩個數字都「看起來合理」。
旗艦片的假頭條比一支 2 次觀看的片裡的假數字嚴重一個量級,所以這條是硬規則。

欄位對照(來源 `STUDIO/stock_checkup_facts.json`):
| 量 | fact 類別 | `data` 欄位 |
|---|---|---|
| 含息總報酬 | `checkup_long_horizon__<code>` | `total_return`(**比率不是百分比**,0.87 = 87%) |
| 最大回撤 | 同上 | `max_drawdown`(負值比率) |
| 最長套牢 | `checkup_underwater__<code>` | `max_underwater_years` / `ongoing` |
| 對決 0050 | `checkup_three_way__<code>` | `stock_allin.total_return` vs `bench.total_return` |
"""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "STUDIO" / "stock_checkup_facts.json"

# 資料側健全下限:低於這個數就是資料壞了,不是「今天比較少」。
# fail-closed —— 旗艦片寧可不產,也不要拿半套資料講全市場。
_MIN_N = 400


def _by_prefix(results: dict, prefix: str) -> dict:
    return {k.split("__")[1]: (results[k].get("data") or {})
            for k in results if k.startswith(prefix)}


def compute(facts_path: Path | None = None) -> dict:
    """回傳旗艦片要用的全部數字。**每一個都附帶它的 n**,因為分母不同答案就不同
    —— 2026-09-06 的「30.9% vs 33.1%」就是分母差異(排不排除仍在套牢中的 93 檔)。"""
    results = json.loads((facts_path or FACTS).read_text(encoding="utf-8"))["results"]
    LH = _by_prefix(results, "checkup_long_horizon__")
    UW = _by_prefix(results, "checkup_underwater__")
    TW = _by_prefix(results, "checkup_three_way__")

    tot = {c: float(v["total_return"]) for c, v in LH.items()
           if v.get("total_return") is not None}
    dd = {c: abs(float(v["max_drawdown"])) for c, v in LH.items()
          if v.get("max_drawdown") is not None}
    uw = {c: float(v["max_underwater_years"]) for c, v in UW.items()
          if v.get("max_underwater_years") is not None}
    ongoing = {c for c, v in UW.items() if v.get("ongoing")}
    win, dca_vs_bench, dca_vs_allin, win_full10 = {}, {}, {}, {}
    for c, v in TW.items():
        a = (v.get("stock_allin") or {}).get("total_return")
        b = (v.get("bench") or {}).get("total_return")
        g = (v.get("stock_dca") or {}).get("total_return")
        if a is not None and b is not None:
            win[c] = float(a) > float(b)
            # 🔴 只有滿 10 年的那組才配得上「這十年」這句話:另外 63 檔上市較晚、
            # 窗較短(3.3~9.8 年),它們比的是 0050 在**較短窗**的報酬。
            # 獨立驗證員 2026-09-06 指出:標題若提期間,正確數字是這一組。
            if float(v.get("years") or 0) >= 9.95:
                win_full10[c] = float(a) > float(b)
        if g is not None and b is not None:
            dca_vs_bench[c] = float(g) > float(b)
        if g is not None and a is not None:
            dca_vs_allin[c] = float(g) > float(a)

    for name, d in (("long_horizon", tot), ("underwater", uw), ("three_way", win)):
        if len(d) < _MIN_N:
            raise RuntimeError(f"{name} 只有 {len(d)} 檔(下限 {_MIN_N}),"
                               f"資料不足以講「全市場」,拒絕組稿")

    def share(vals, pred):
        return round(100.0 * sum(1 for x in vals if pred(x)) / len(vals), 1)

    n_uw_settled = len([c for c in uw if c not in ongoing])
    return {
        # 分母(每一個數字都要講得出自己的 n)
        "n_return": len(tot), "n_underwater": len(uw), "n_versus": len(win),
        # 報酬
        "total_return_median_pct": round(100 * st.median(tot.values()), 1),
        "loss_share_pct": share(tot.values(), lambda x: x < 0),
        # 代價
        "maxdd_median_pct": round(100 * st.median(dd.values()), 1),
        "halved_share_pct": share(dd.values(), lambda x: x >= 0.5),
        # 套牢
        # 🔴 兩位小數:n=598 是偶數,兩個中間值是 7.1 與 7.2,取一位小數等於把平手往上進位。
        # 那是 12 個數字裡唯一一個「換個進位規則就變另一個值」的,標題不要用它。
        "uw_median_years": round(st.median(uw.values()), 2),
        "uw_ge5_share_pct": share(uw.values(), lambda x: x >= 5),
        "uw_ge10_share_pct": share(uw.values(), lambda x: x >= 10),
        "ongoing_n": len(ongoing),
        # 下限/上界:198 檔是**已觀測到**的;93 檔 ongoing 還在計時,只會讓分子變大。
        # 上界 = 若那些 ongoing 最終全部跨過 10 年。
        "uw_ge10_upper_pct": round(100.0 * (sum(1 for x in uw.values() if x >= 10)
                                            + sum(1 for c, x in uw.items()
                                                  if c in ongoing and x < 10))
                                   / len(uw), 1),
        "uw_ge10_n": sum(1 for x in uw.values() if x >= 10),
        # ongoing 之中**已經**跨過 10 年的:這是「不可以剔除 ongoing」最硬的證據 ——
        # 它們不是「還沒觀測完」,是已經確定的真陽性,剔掉就是直接刪掉這幾筆。
        "ongoing_ge10_n": sum(1 for c, x in uw.items() if c in ongoing and x >= 10),
        # 🔴 這個數字**不進旁白**,只留在這裡供稽核:它是「排除仍在套牢中的 93 檔」之後的值。
        # 排掉的正是最慘的一群 ⇒ 用它會低估痛苦。留著是為了讓人看得到兩個口徑的差。
        "_uw_ge10_excl_ongoing_pct": round(
            100.0 * sum(1 for c, x in uw.items() if c not in ongoing and x >= 10)
            / max(n_uw_settled, 1), 1),
        # 對決 0050
        "beat_n": sum(win.values()),
        "beat_share_pct": round(100.0 * sum(win.values()) / len(win), 1),
        "beat_full10_n": sum(win_full10.values()), "n_versus_full10": len(win_full10),
        "beat_full10_share_pct": round(100.0 * sum(win_full10.values())
                                       / max(len(win_full10), 1), 1),
        # 定期定額:同一批股票、同一個十年區間,只換買法
        "dca_n": len(dca_vs_allin),
        "dca_beat_allin_n": sum(dca_vs_allin.values()),
        "dca_beat_allin_share_pct": round(100.0 * sum(dca_vs_allin.values())
                                          / max(len(dca_vs_allin), 1), 1),
        "dca_beat_bench_share_pct": round(100.0 * sum(dca_vs_bench.values())
                                          / max(len(dca_vs_bench), 1), 1),
        # 分佈資料(給圖用)
        "_dd_values": sorted(round(100 * x, 1) for x in dd.values()),
        "_uw_values": sorted(round(x, 2) for x in uw.values()),
    }


def coverage() -> dict:
    """🔴 598 檔**不是**全市場。獨立驗證員 2026-09-06:全市場母體 1925 檔,
    這 598 檔是成交金額排名前段完成的 —— **檔數涵蓋三成,成交金額涵蓋九成六**。
    把它講成「全市場」或「隨便挑一檔台股」是實質失真,不是措辭問題,
    因為沒被算到的那 1327 檔正是最可能賠錢、最可能腰斬的一群。"""
    bl = json.loads((ROOT / "STUDIO" / "stock_checkup_backlog.json").read_text(encoding="utf-8"))
    rows = bl if isinstance(bl, list) else bl.get("items", [])
    uni = {str(r["code"]): r for r in rows if isinstance(r, dict) and r.get("code")}
    done = set(_by_prefix(json.loads(FACTS.read_text(encoding="utf-8"))["results"],
                          "checkup_long_horizon__"))
    # `turnover_proxy` = 近 40 筆快取交易日的平均 Volume×Close(backlog 產生器的排序依據)
    ws = {c: float(r["turnover_proxy"]) for c, r in uni.items()
          if isinstance(r.get("turnover_proxy"), (int, float))}
    tot = sum(ws.values())
    got = sum(v for c, v in ws.items() if c in done)
    return {"universe_n": len(uni), "done_n": len(done & set(uni)),
            "count_coverage_pct": round(100.0 * len(done & set(uni)) / max(len(uni), 1), 1),
            "value_coverage_pct": round(100.0 * got / tot, 1) if tot else None}


def selfcheck() -> tuple:
    """算出來的東西合不合理。**不是檢查等於某個寫死的值**(那會在資料更新時假失敗),
    是檢查它有沒有掉出物理上可能的範圍、以及各口徑之間有沒有互相矛盾。"""
    try:
        x = compute()
    except Exception as exc:  # noqa: BLE001
        return False, f"計算失敗:{exc}"
    bad = []
    if not (0 <= x["halved_share_pct"] <= 100):
        bad.append("腰斬比例超出 0~100")
    if x["uw_ge10_share_pct"] > x["uw_ge5_share_pct"]:
        bad.append("≥10 年的比例大於 ≥5 年的(單調性壞了)")
    if x["uw_ge10_share_pct"] < x["_uw_ge10_excl_ongoing_pct"]:
        bad.append("排除仍套牢中的反而更高 —— ongoing 的定義可能反了")
    if x["maxdd_median_pct"] <= 0:
        bad.append("回撤中位數應為正值(已取絕對值)")
    if x["n_return"] < _MIN_N:
        bad.append("樣本數低於下限")
    if bad:
        return False, ";".join(bad)
    return True, (f"n={x['n_return']}/{x['n_underwater']}/{x['n_versus']}、"
                  f"報酬中位 {x['total_return_median_pct']}%、"
                  f"回撤中位 {x['maxdd_median_pct']}%、"
                  f"套牢中位 {x['uw_median_years']} 年、贏 0050 {x['beat_share_pct']}%")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ok, msg = selfcheck()
    print(f"自檢:{'✅' if ok else '🔴'} {msg}")
    x = compute()
    for k, v in x.items():
        if k.startswith("_dd_") or k.startswith("_uw_v"):
            print(f"  {k}: {len(v)} 個值(min {v[0]}, max {v[-1]})")
        else:
            print(f"  {k}: {v}")
    raise SystemExit(0 if ok else 1)
