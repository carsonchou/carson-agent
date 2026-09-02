#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量「一支個股體檢片,把手上事實用掉幾條」——連跑一週的第 2 天起用這支,免得每天重推口徑。

## 口徑(照 2026-09-01 交接檔第一張表,不要改)

- 分母 = 該股在 `STUDIO/stock_checkup_facts.json` 有的事實**條數**(crash 一個危機算一條)
- 分子 = 旁白(`output/<slug>.voice.txt`)提到那個面向的條數
- 判準是**主題關鍵詞,不是比數字**。旁白是中文唸法(「八千一百零五點六」),
  數字比對一律失效——2026-09-01 就是在這裡先做錯一次。
- `annual_extremes` 要另判:旁白寫「在二零零八年…」而不寫「最慘一年」,
  所以除了關鍵詞,還接受**該事實裡的年份**(阿拉伯數字或中文數字)出現在旁白裡。

## 已知會低估的地方

同一句話可能同時滿足兩個面向(例:「年化 13.1%、最大回撤 -74.7%」),
本支只算「面向有沒有被講到」,不算講得深不深。所以這個數字是**覆蓋率不是品質**。

用法:
  python scripts/measure_fact_utilization.py                 # 今天產出的長片
  python scripts/measure_fact_utilization.py --date 09-01    # 指定日(檔案 mtime)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO, OUT = ROOT / "STUDIO", ROOT / "output"

# 每個事實家族「被講到」的主題詞。刻意寬鬆:寧可高估覆蓋也不要因為換句話說就判沒講,
# 因為本支要回答的是「事實有沒有進到片子裡」,不是「有沒有逐字照抄」。
KW = {
    "checkup_long_horizon":      ("年化", "總報酬", "最大回撤", "卡瑪"),
    "checkup_annual_extremes":   ("最慘", "最強", "最好的一年", "最差", "年度"),
    "checkup_three_way":         ("定期定額", "單筆", "All in", "一次全押", "一次買", "分批"),
    "checkup_underwater":        ("套牢", "創高", "新高", "等了", "水面下"),
    "checkup_halvings":          ("腰斬", "跌一半", "砍half"),
    "checkup_crash":             ("海嘯", "金融危機", "新冠", "疫情", "熊市", "崩盤"),
    "checkup_revenue_trend":     ("營收",),
    "checkup_eps_trend":         ("EPS", "每股盈餘", "每股純益"),
    "checkup_gross_margin":      ("毛利",),
    "checkup_dividend_history":  ("配息", "股利", "殖利率", "股息"),
    "checkup_valuation_position":("本益比", "百分位", "估值", "評價", "PE"),
    "checkup_industry_rank":     ("排第", "名次", "同業", "同產業", "產業裡", "檔裡", "檔中"),
    "checkup_industry_summary":  ("產業", "族群"),
}
_CN = str.maketrans("0123456789", "零一二三四五六七八九")


def hit(family: str, summary: str, text: str) -> bool:
    if any(w in text for w in KW.get(family, ())):
        return True
    if family == "checkup_annual_extremes":
        # 旁白只唸年份不唸「最慘」——年份(1998 / 一九九八)出現就算講到
        for y in re.findall(r"(19|20)\d{2}", summary):
            pass
        for y in set(re.findall(r"\b((?:19|20)\d{2})\b", summary)):
            if y in text or y.translate(_CN) in text:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="MM-DD,預設今天")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import audit_per_stock_facts as ap_
    facts, uni, _led = ap_._load()

    day = a.date or dt.date.today().strftime("%m-%d")
    lo = dt.datetime.strptime(f"{dt.date.today().year}-{day}", "%Y-%m-%d")
    hi = lo + dt.timedelta(days=1)
    files = [p for p in OUT.glob("L_*.voice.txt")
             if lo <= dt.datetime.fromtimestamp(p.stat().st_mtime) < hi]

    rates, skipped = [], []
    print(f"量測窗口 {day} 00:00~24:00(檔案 mtime);當日長片旁白 {len(files)} 支\n")
    for p in sorted(files):
        slug = p.name[:-len(".voice.txt")]
        code = ap_.code_of(slug, facts, uni)
        if not code:
            skipped.append(slug)
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        own = {k: v for k, v in facts.items()
               if k.endswith("__" + code) or f"__{code}__" in k}
        used = [k for k, v in own.items()
                if hit(k.split("__")[0], str(v.get("summary", "")), text)]
        r = len(used) / len(own) if own else 0.0
        rates.append(r)
        miss = sorted(k.split("__")[0].replace("checkup_", "") for k in own if k not in used)
        print(f"  {uni.get(code,''):<6}{code}  {len(used):>2}/{len(own):<3}{r*100:5.0f}%"
              f"   漏:{','.join(miss) if miss else '—'}")

    if rates:
        print(f"\n事實使用率中位 {statistics.median(rates)*100:.0f}%"
              f"(n={len(rates)} 支;分母=各股自己的事實條數,中位 "
              f"{statistics.median([len([1 for k in facts if k.endswith('__'+ap_.code_of(s, facts, uni)) or f'__{ap_.code_of(s, facts, uni)}__' in k]) for s in [p.name[:-len('.voice.txt')] for p in sorted(files)] if ap_.code_of(s, facts, uni)]):.0f} 條)")
    if skipped:
        print(f"\n不計入(認不出個股代號,非單一個股題):{len(skipped)} 支")
        for s in skipped:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
