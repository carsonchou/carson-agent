#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_demand_external.py — 用**外部**搜尋需求排序個股體檢的製作順序。

## 為什麼要「外部」(既有的 checkup_demand_sort 有結構性盲點)
既有那支讀的是 YouTube Analytics 的 `insightTrafficSourceDetail`——**我們自己頻道**的
搜尋詞。那份清單只包含「搜了之後找到我們」的詞。沒做過的股票,人家搜了也找不到我們,
那個詞**永遠不會出現在我們的 Analytics 裡**。

所以它每次回報的「有人搜、但還沒做的股票:0 檔」不是好消息,是**結構上必然**——
它在用「已經被我們覆蓋的需求」推論「還沒被覆蓋的需求」,那是循環的。
(而且 insightTrafficSourceDetail 的 maxResults 上限是 25,視窗本來就只有熱門詞。)

## 這支的訊號
YouTube 搜尋建議(autocomplete)。公開端點、免費、**不吃 Data API 配額**,而且反映的
正是「人們實際打什麼」——不需要我們已經有片才看得到。實測分得很開:

    台積電 14 / 聯發科 14 / 中華電 14   (高人氣,建議數飽和在上限)
    雷科    9 / 嘉澤    8 / 波若威  7   (中等)
    蜜望實  3 / 堡達    1               (極冷門)
    同一詞連查兩次結果一致 → 訊號穩定

**只數投資意圖的建議**,不數總數:「雷科 股票」「嘉澤3533」算,
「嘉澤 演員」「中華電信招考」不算(那是同名的別的東西,對我們是雜訊)。
代號本身出現在建議裡(如「雷科 6207」)加重權——那證明有人在搜這支**股票**而不是同名的人事物。

## 為什麼這件事值錢
發布名額是稀缺的:實測 3 支/天(節奏實驗證明比 7 支/天更好),其中長片約 2.5 支。
而全市場 1925 檔、已發布覆蓋只有 **103 檔(5.4%)**、已算出事實但還沒發片的有 **479 檔**。
把那 479 檔照真實需求排序,和照現行的「成交值代理」排序,長期差距是好幾倍的搜尋佔位效益。
(memory yt-search-capture-engine:時數 ≈ 佔位數 × 搜尋量 × 150 秒。)

## ⛔ 2026-08-30 驗證結果:**這個分數不能拿來排序,--apply 不要用**
套用之前先做了「這個分數預不預測得了真實觀看」的驗證(memory yt-quality-score-not-predictive:
品質分 vs 觀看相關 -0.084,當排名器完全無效——同一型錯誤不要犯第二次)。
拿 35 支**已發布**、片齡 >=7 天的體檢片回頭算需求分,和真實觀看做相關:

    r(需求分, 每天觀看)    = **-0.205**   ← 負的:需求分越高,觀看反而越少
    對照 r(片齡, 每天觀看) = -0.502       ← 片齡才是真正的驅動因子
    分層:需求分 1~3 → 每天 17.7 觀看 / 3~5 → 24.9 / 5~7 → 14.1 / **7~9 → 6.7**

也就是說:**外部搜尋需求高的股票,我們的片反而拿不到觀看。**
合理的解釋是**競爭**:高需求股(聯電/華通/旺宏)財經頻道早就做爛了,小頻道排不上去;
冷門股(希華/頎邦)我們是唯一的搜尋結果,整個長尾都吃下來。
但 n=35、r=-0.205 也不足以反過來宣稱「越冷門越好」——真正該量的是**需求 ÷ 競爭**,
而競爭度要靠 search.list(100 units/次,今天配額不夠)或爬搜尋結果頁
(**違反 ToS,不做**,見 memory yt-scraper-tos-removal-2026-07)。

保留這支是因為:①探測與快取的機制是好的,量到競爭度之後可以直接接上
②`covered_codes()` 的滑動視窗解法(slug 去了標點,台積電2330 20年 → 233020,
用 \\d{4} 邊界會全部抓不到)其他地方也用得上。
**在量出競爭度、並重驗相關性之前,--apply 一律不要用。**

## 用法
  python scripts/checkup_demand_external.py --limit 60          # 只探前 60 檔,印排名
  python scripts/checkup_demand_external.py --limit 479 --apply # ⛔ 見上方,現在不要用
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
BACKLOG = STUDIO / "stock_checkup_backlog.json"
FACTS = STUDIO / "stock_checkup_facts.json"
LEDGER = STUDIO / "uploaded_ledger.json"
CACHE = STUDIO / "demand_external_cache.json"
CACHE_DAYS = 21          # 搜尋需求不會天天變;快取省得反覆打人家端點

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# 投資意圖詞:建議裡含這些才算數(排掉同名的演員/招考/歌曲等雜訊)
INTENT = ("股票", "股價", "配息", "除權", "除息", "財報", "法說", "目標價", "值得買",
          "填息", "殖利率", "營收", "個股", "分析", "存股", "多少錢", "漲", "跌", "投資")


def suggest(q: str):
    url = ("https://suggestqueries-clients6.youtube.com/complete/search?client=youtube"
           "&hl=zh-TW&gl=TW&ds=yt&q=" + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    i, j = raw.find("("), raw.rfind(")")
    if i < 0 or j < 0:
        return []
    return [x[0] for x in json.loads(raw[i + 1:j])[1]]


def score(name: str, code: str):
    """回 (分數, 命中的建議詞)。分數 = 投資意圖建議數 + 代號出現的加權。"""
    try:
        sug = suggest(name)
    except Exception:  # noqa: BLE001
        return None, []
    hits = [s for s in sug if any(k in s for k in INTENT)]
    # 代號出現在建議裡 = 有人在搜這支「股票」而不是同名的別的東西,加重
    code_hit = [s for s in sug if code in s.replace(" ", "")]
    sc = len(hits) + 2 * len(code_hit)
    return sc, (hits + code_hit)[:5]


def covered_codes():
    """已經發布過體檢片的代號。slug 去了標點,代號常跟後面的數字黏在一起
    (台積電2330 20年 → 233020),所以用滑動視窗比對,不能用 \\d{4} 邊界。"""
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8"))
        bl = json.loads(BACKLOG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    uni = {str(i.get("code")) for i in bl.get("items", [])}
    out = set()
    for slug in led:
        if "個股體檢" not in slug:
            continue
        for m in re.finditer(r"\d{4,}", slug):
            d = m.group(0)
            for i in range(len(d) - 3):
                if d[i:i + 4] in uni:
                    out.add(d[i:i + 4])
                    break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--apply", action="store_true", help="把排序寫回 backlog(產線隔天就照新順序做)")
    ap.add_argument("--delay", type=float, default=0.45, help="每次查詢間隔秒數(對人家端點客氣點)")
    args = ap.parse_args()

    bl = json.loads(BACKLOG.read_text(encoding="utf-8"))
    items = bl.get("items", [])
    names = {str(i.get("code")): str(i.get("name") or "") for i in items}
    facts = json.loads(FACTS.read_text(encoding="utf-8")).get("by_code", {})
    done = covered_codes()

    # 候選:已算出事實、還沒發片(這批最便宜——FinMind 額度與運算早就付過了)
    cand = [c for c in facts if c not in done and names.get(c)]
    print(f"全市場 {len(items)} 檔｜已發布覆蓋 {len(done)} 檔({len(done)/max(len(items),1)*100:.1f}%)"
          f"｜已算事實未發片 {len(cand)} 檔")
    print(f"本次探測前 {min(args.limit, len(cand))} 檔(照現行 backlog 順序取)\n")

    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    except Exception:  # noqa: BLE001
        cache = {}
    now = time.time()

    rows, probed = [], 0
    for code in cand[:args.limit]:
        nm = names[code]
        c = cache.get(code)
        if c and (now - c.get("ts", 0)) < CACHE_DAYS * 86400:
            rows.append((c["score"], code, nm, c.get("hits", [])))
            continue
        sc, hits = score(nm, code)
        probed += 1
        if sc is None:
            print(f"  [warn] {code} {nm} 查詢失敗,略過")
            continue
        cache[code] = {"score": sc, "hits": hits, "ts": now, "name": nm}
        rows.append((sc, code, nm, hits))
        time.sleep(args.delay)

    try:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    rows.sort(reverse=True)
    print(f"(本次實際查詢 {probed} 檔,其餘走 {CACHE_DAYS} 天快取)\n")
    print(f"{'排名':>4} {'代號':>6} {'名稱':<10} {'需求分':>5}  建議詞")
    print("-" * 88)
    for i, (sc, code, nm, hits) in enumerate(rows[:30], 1):
        print(f"{i:>4} {code:>6} {nm[:9]:<10} {sc:>5}  {' / '.join(hits)[:52]}")
    if len(rows) > 30:
        zero = sum(1 for r in rows if r[0] == 0)
        print(f"\n… 其餘 {len(rows)-30} 檔;其中需求分 0 的有 {zero} 檔"
              f"(沒有任何投資意圖的搜尋建議 = 做了也沒人搜)")

    if not args.apply:
        print("\n[dry-run] 未改動 backlog。")
        return 0
    # ⛔ 2026-08-30:實測 r(需求分, 每天觀看) = -0.205(n=35 已發布片),**方向是反的**。
    # 拿沒驗過、而且驗出來是負相關的分數去重排產線順序,就是重蹈品質分那次的覆轍。
    # 要解除這道鎖:先量出競爭度、重算相關性、確認是正的,再把這段拿掉。
    print("\n⛔ 拒絕套用:這個需求分**經實測不能預測觀看**(r=-0.205,方向還是反的)。")
    print("   詳見本檔開頭的驗證段落。要用它排序,得先量出競爭度並重驗相關性。")
    print("   (刻意做成硬擋而不是警告——警告會被下一個人忽略。)")
    return 2

    # 寫回 backlog:把探測過的候選照需求分提前,其餘維持原順序(穩定排序,不打亂沒探過的)
    order = {code: -sc for sc, code, _n, _h in rows}
    probed_set = set(order)
    head = [it for it in items if str(it.get("code")) in probed_set]
    tail = [it for it in items if str(it.get("code")) not in probed_set]
    head.sort(key=lambda it: order.get(str(it.get("code")), 0))
    bl["items"] = head + tail
    bl["demand_sorted_at"] = time.strftime("%Y-%m-%d %H:%M")
    bl["demand_sorted_n"] = len(head)
    bak = BACKLOG.with_suffix(".json.bak_demand")
    if not bak.exists():
        bak.write_text(BACKLOG.read_text(encoding="utf-8"), encoding="utf-8")
    BACKLOG.write_text(json.dumps(bl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 已把 {len(head)} 檔照外部需求排到 backlog 最前面(備份 {bak.name})。")
    try:
        from ops import log_ops
        log_ops("需求排序", f"外部搜尋建議排序 {len(head)} 檔;首位 {rows[0][2]}{rows[0][1]}(分{rows[0][0]})")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
