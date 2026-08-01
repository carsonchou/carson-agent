#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_demand_sort.py — 用【真實 YouTube 搜尋需求】重排個股體檢的 backlog 順序。

## 為什麼要這支(2026-08-01 實測依據)
近 28 天流量結構:**只有搜尋在漲(+95%)**,Shorts 推薦流 -54%、其他來源全在漲。
而搜尋詞的組成(前 25 名 = 搜尋流量的 34%):

    個股名/代號  459 觀看  **64%**   ← 金像電90、聯茂88、奇鋐51、群創23、力積電28…
    幣圈         175        24%
    觀念類        64         9%
    ETF           20         3%

也就是說:**搜尋流量的主體是「有人打某一檔股票的名字」**,而個股體檢正是接這個需求的系列。

最大的單一叢集是頎邦(6147):`6147`28 + `頎邦 6147`26 + `6147颀邦`24 + `頎邦科技`19
+ `頎邦`16 + **`頎邦檢調`9** = 122 觀看。最後那個詞洩漏了機制——**是新聞事件把人推去搜**,
然後撞到我們的影片。這種需求有時效性,錯過就沒了。

## 現行排序的不足
backlog 由 stock_checkup_backlog_gen 依「近期日均成交值(Volume×Close)」排序,
那是**市值/重要性的靜態代理**,是合理的預設。但它回答不了「**現在誰在被搜**」——
成交值大的權值股(台積電、聯發科)未必是 YouTube 上被搜的那幾檔,而搜尋是我們唯一在成長
的入口。

## 這支做什麼(刻意做得很小)
**不改既有排序邏輯**,只把「Analytics 量到有人搜、但 backlog 還沒做」的檔**提到最前面**,
其餘順序原封不動。等於「搜尋需求」只是一個加權,不是取代成交值排序。
可逆:重跑 stock_checkup_backlog_gen 即回到純成交值排序;本支也會先備份原檔。

用法:
  python scripts/checkup_demand_sort.py            # 只分析、印出會怎麼排(不寫檔)
  python scripts/checkup_demand_sort.py --apply    # 真的重排 backlog
  python scripts/checkup_demand_sort.py --days 28  # 改用不同的 Analytics 視窗
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
BACKLOG = STUDIO / "stock_checkup_backlog.json"
TW = timezone(timedelta(hours=8))


def _search_terms(days: int):
    """回 [(詞, 觀看)]。錨在**最後有資料那天**(Analytics 延遲 2~4 天),不錨 today。"""
    import yt_analytics
    ya = yt_analytics._service()
    if ya is None:
        print("[warn] Analytics 取不到(需 token_analytics.json),無法取得搜尋需求", file=sys.stderr)
        return []
    today = datetime.now(TW).date()
    probe = ya.reports().query(ids="channel==MINE",
                               startDate=str(today - timedelta(days=10)),
                               endDate=str(today), dimensions="day",
                               metrics="views", sort="day").execute().get("rows", [])
    if not probe:
        return []
    last = date.fromisoformat(probe[-1][0])
    start = last - timedelta(days=days - 1)
    # ⚠️ 兩個 API 限制,都是實際撞到才知道的,寫下來免得下次再踩:
    #   ①`dimensions=video` **不能**和 insightTrafficSourceType 篩選並用(回 400 not supported),
    #     所以拿不到「每支片的搜尋觀看」;insightTrafficSourceDetail(搜尋詞)才是可行路徑。
    #   ②insightTrafficSourceDetail 的 **maxResults 上限是 25**,設 200 會回
    #     HTTP 500 FIELD_UNKNOWN_VALUE(錯誤訊息長得像伺服器錯誤,其實是參數超限,很容易誤判)。
    rows = ya.reports().query(ids="channel==MINE", startDate=str(start),
                              endDate=str(last),
                              dimensions="insightTrafficSourceDetail",
                              metrics="views",
                              filters="insightTrafficSourceType==YT_SEARCH",
                              sort="-views", maxResults=25).execute().get("rows", [])
    print("[搜尋需求] 視窗 %s ~ %s,取得 %d 個搜尋詞(API 上限 25,只涵蓋熱門詞)"
          % (start, last, len(rows)))
    return [(k, v) for k, v in rows]


def _match(terms, items):
    """把搜尋詞對應到 backlog 的股票。回 {code: 需求分數}。

    比對規則刻意保守,只認**明確**的兩種:
      ①搜尋詞裡出現 4~6 位數字且等於股票代號(如「6147」「頎邦 6147」)
      ②搜尋詞包含股票名稱(去掉名稱裡的 * 等雜訊),且名稱至少 2 個字
    不做模糊比對——寧可漏,也不要把「比特幣」硬塞給某檔股票。
    """
    by_code = {i["code"]: i for i in items if i.get("code")}
    by_name = {}
    for i in items:
        nm = re.sub(r"[*＊\s]", "", str(i.get("name") or ""))
        if len(nm) >= 2:
            by_name.setdefault(nm, i)
    score: dict[str, float] = {}
    hits: dict[str, list] = {}
    for term, views in terms:
        t = str(term)
        matched = None
        for m in re.findall(r"\d{4,6}", t):
            if m in by_code:
                matched = by_code[m]["code"]
                break
        if matched is None:
            tt = re.sub(r"[*＊\s]", "", t)
            for nm, it in by_name.items():
                if nm in tt:
                    matched = it["code"]
                    break
        if matched:
            score[matched] = score.get(matched, 0) + views
            hits.setdefault(matched, []).append((t, views))
    return score, hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的重排 backlog(預設只分析)")
    ap.add_argument("--days", type=int, default=28, help="Analytics 視窗天數")
    args = ap.parse_args()

    if not BACKLOG.exists():
        print("[fatal] 找不到 %s" % BACKLOG, file=sys.stderr)
        return 2
    d = json.loads(BACKLOG.read_text(encoding="utf-8"))
    items = d.get("items") or []
    if not items:
        print("[fatal] backlog 空的", file=sys.stderr)
        return 2

    terms = _search_terms(args.days)
    if not terms:
        print("[skip] 沒有搜尋詞資料,不動 backlog(維持既有成交值排序)。")
        return 0

    score, hits = _match(terms, items)
    todo_codes = {i["code"] for i in items if not i.get("done")}
    hot = {c: s for c, s in score.items() if c in todo_codes}
    done_hot = {c: s for c, s in score.items() if c not in todo_codes}

    print()
    print("有人搜、而且**還沒做**的股票:%d 檔" % len(hot))
    name = {i["code"]: i.get("name") for i in items}
    for c, s in sorted(hot.items(), key=lambda x: -x[1]):
        ts = "、".join("%s(%d)" % (t, v) for t, v in sorted(hits[c], key=lambda x: -x[1])[:3])
        print("  %-6s %-8s 需求分 %4d   搜尋詞:%s" % (c, name.get(c, ""), s, ts))
    if done_hot:
        print()
        print("有人搜但**已經做過**的(代表這條線有效,不必重做):%d 檔 — %s"
              % (len(done_hot),
                 "、".join("%s%s" % (name.get(c, ""), c) for c in list(done_hot)[:8])))

    if not hot:
        print()
        print("[skip] 被搜的股票都已經做過了 → 現行排序沒有需要調整的地方。")
        return 0

    # 重排:hot(依需求分大到小)提到最前,其餘原順序不動
    order = sorted(hot.items(), key=lambda x: -x[1])
    hot_codes = [c for c, _ in order]
    front = [i for c in hot_codes for i in items if i.get("code") == c]
    rest = [i for i in items if i.get("code") not in set(hot_codes)]
    new_items = front + rest

    print()
    print("重排後最前面 %d 檔(需求驅動):" % len(front))
    for i in front[:10]:
        print("   %-6s %s" % (i["code"], i.get("name")))

    if not args.apply:
        print()
        print("[dry-run] 未寫檔。要真的重排:--apply")
        return 0

    bak = BACKLOG.with_suffix(".json.bak-demand")
    shutil.copy2(BACKLOG, bak)
    d["items"] = new_items
    d["demand_sorted_at"] = datetime.now(TW).strftime("%Y-%m-%d %H:%M")
    d["demand_note"] = ("依 YouTube Analytics 實測搜尋需求把被搜過但未做的股票提前;"
                        "其餘維持 stock_checkup_backlog_gen 的成交值排序。"
                        "重跑 backlog_gen 即回到純成交值排序。")
    BACKLOG.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print("[ok] 已重排。原檔備份:%s" % bak.name)
    try:
        from ops import log_ops
        log_ops("個股體檢", "需求排序:%d 檔被搜過的股票提前(搜尋是唯一成長來源)" % len(front))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
