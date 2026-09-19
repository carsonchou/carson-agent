#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""稽核:個股體檢片講的數字,對不對得上**那一檔自己**的事實。

## 為什麼需要這支(2026-08-31 實測)

fact_source_guard 用的是**全域**事實池:全部已體檢個股的所有數字攤平在一起,
目前 38,231 個。實測這個池在報酬率區間已經**實質連續**:
    pct 子池 0~200 區間有 20,704 個值,相鄰間距中位 0.0032
    而嚴容差是 max(0.25, 值×0.5%) >= 0.25 = 間距的 78 倍
→ 任何百分比都找得到鄰居。隨手編的 1234.5% / 777.7% / 88.8% / 42.195%,
   守門**全部**說「有憑據」;隨機 400 個百分比通過率 100%。

它 2026-07 建立時事實庫只有 5 組,擋得住;現在 504 檔 × 13 組把池子填成連續,
它就開始為任何數字背書。**規則在素材變多之後靜默反轉** —— 與同日抓到的
「防重複規則變成事實使用天花板」同一個形狀。

實際後果(39 支未發布個股體檢,拿**該檔自己的**事實當池):
    信昌電6173  旁白「單筆All in 總報酬 794.7%」  事實 1194.7%   差 400 個百分點
    光洋科1785  旁白「一路抱到現在 228.9%」       事實 264.2%
    大同2371    旁白「0050 報酬率 237.5%」        對照標的數字對不上
    東聯1710    旁白「0050 僅報酬 21.2%」         同上(0050 是觀眾最會查的)
    十銓4967    旁白「台積電報酬42.5%、回撤-48.1%」這支片手上沒有台積電的事實
全域池對這些**全部放行**。

## 為什麼這支不擋人

memory yt-period-swap-integrity:我 08-28 在這一區「修一修」讓產線停了兩天,
17 支被殺沒一支是真的。所以這支**只報告不阻擋**,先累積幾天觀察偽陽性長什麼樣,
確認穩定之後再由 Carson 決定要不要接成 daily_publish 的閘門。

## 已知的偽陽性形態(池子已經吃掉的)

·**百分位補數**:事實「第 62 百分位」→ 旁白「38% 的時間比現在高」(100−62,正確換算)
·**整數修辭**:五成/八成/一半/兩倍 → 50/80/100 這類整數
還會殘留的:名次換算(「11 檔中第 5 名 = 前 45%」)、舉例性數字
(「即使長期報酬高達百分之兩百」是假設不是宣稱)。這些要靠人看,所以本支只報告。

用法:`python scripts/audit_per_stock_facts.py [--published] [--json 路徑]`
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"

# 整數修辭:「跌了五成」「八成腰斬」「翻了一倍」——這些不是引用事實,是講話方式。
_ROUND_RHETORIC = {0.0, 10.0, 20.0, 25.0, 30.0, 40.0, 50.0,
                   60.0, 70.0, 75.0, 80.0, 90.0, 100.0, 200.0}


def _load():
    facts = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    bl = json.loads((STUDIO / "stock_checkup_backlog.json").read_text(encoding="utf-8"))
    rows = bl if isinstance(bl, list) else bl.get("items", [])
    uni = {str(r["code"]): r.get("name", "") for r in rows
           if isinstance(r, dict) and r.get("code")}
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    return facts, uni, led


def code_of(slug: str, facts: dict, uni: dict):
    """從 slug 認出股票代號。滑動視窗取 4 位數,再用**股名前兩字**交叉確認 ——
    slug 裡的數字不只有代號(年數/報酬率都在),只比對數字會認錯。"""
    body = slug[2:]
    for chunk in re.sub(r"\D", " ", body).split():
        for i in range(max(len(chunk) - 3, 0) + 1):
            c = chunk[i:i + 4]
            if len(c) != 4 or c not in uni:
                continue
            if not any(k.endswith("__" + c) for k in facts):
                continue
            nm = re.sub(r"[*\-]|KY|ky", "", uni[c])
            if nm and nm[:2] and nm[:2] in body:
                return c
    return None


def pool_for(code: str, facts: dict) -> set:
    """這一檔自己的事實數字池。

    收三種:①事實原文裡出現的所有數字 ②百分位補數(100−x,「第62百分位」→「38%比現在高」)
    ③整數修辭(五成/八成/一半)。刻意**不收**其他個股的數字 —— 那正是全域池的病根。"""
    s = set()
    for k, v in facts.items():
        if not (k.endswith("__" + code) or f"__{code}__" in k):
            continue
        for x in re.findall(r"-?\d+\.?\d*", str(v.get("summary", ""))):
            try:
                fv = abs(float(x))
            except ValueError:
                continue
            s.add(fv)
            if 0 < fv <= 100:
                s.add(round(100 - fv, 4))
    return s | _ROUND_RHETORIC


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--published", action="store_true", help="改掃已發布的片")
    ap.add_argument("--json", default="", help="把結果寫成 JSON")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import fact_source_guard as fsg
    facts, uni, led = _load()
    ledset = set(led)
    slugs = [os.path.basename(p)[:-4]
             for p in glob.glob(str(ROOT / "output" / "L_個股體檢*.mp4"))]
    slugs = [s for s in slugs if (s in ledset) == args.published]

    hits, n = [], 0
    for s in sorted(slugs):
        c = code_of(s, facts, uni)
        if not c:
            continue
        n += 1
        bad = fsg.check_slug(s, pool_for(c, facts))
        if bad:
            hits.append({"slug": s, "code": c, "name": uni.get(c, ""),
                         "videoId": led.get(s, ""),
                         "values": sorted({b["value"] for b in bad}),
                         "clause": str(bad[0].get("clause", ""))[:200]})

    scope = "已發布" if args.published else "未發布"
    print(f"個股體檢({scope}) {n} 支,數字對不上自己事實的:{len(hits)} 支\n")
    for h in hits:
        print(f"  {h['name']}{h['code']}  {h['values'][:5]}"
              + (f"  https://youtu.be/{h['videoId']}" if h["videoId"] else ""))
        print(f"     「{h['clause'][:96]}」")
    if args.json:
        Path(args.json).write_text(json.dumps(hits, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n已寫入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
