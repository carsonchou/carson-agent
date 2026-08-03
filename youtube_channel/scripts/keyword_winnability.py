#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keyword_winnability.py — 量「這檔股票的搜尋關鍵字,我們**排得上去嗎**」。

## 這支解決什麼(2026-08-04 實測)
個股體檢 backlog 目前依「近40日平均成交值」由大到小排(stock_checkup_backlog_gen)。
但實測 Analytics 近28天的搜尋詞,帶進流量的是:
    金像電 112觀看/338分鐘、聯茂 102/187、奇鋐 59/107、頎邦 ~90/180、緯穎、力積電…
**台積電、聯發科、鴻海一次都沒出現**——而它們正是成交值第 1、3、14 名,也就是
backlog 最前面那幾檔。

直接去 YouTube 搜(search.list, regionCode=TW)驗原因:
    「金像電」→ **我們第 1 名**(壓過 57東森財經、非凡電視)
    「頎邦  」→ 我們第 25 名
    「台積電」→ 沒進前 25(前三:寶傑點兵/台視新聞/三立財經)
    「聯發科」→ 沒進前 25(前三:TVBS財經/57東森/三立財經)

結論:**權值股的關鍵字被電視台新聞剪輯佔滿,我們排不上;中型股幾乎沒人做專片,
我們就是第一名。** 一支排第 1 的片 28 天帶 338 分鐘;排不上的帶 0。
決定價值的不是「這檔多大」,是「**需求 ÷ 競爭**」。

而全頻道只有長片的觀看分鐘算進 YPP 的 4000 小時門檻,搜尋又是唯一在成長的來源
→ 「我們能不能在這個關鍵字排第一」直接決定 YPP 進度。

## 怎麼算「可攻佔分數」
對每檔股票搜它的**名稱**(觀眾就是這樣打的,見上面的搜尋詞),看前 N 名長什麼樣:
  +  前10名裡「專門講這檔的片」越少 → 越好攻(沒人做 = 空地)
  +  前10名被大型媒體/新聞台佔據越多 → 越難攻(那是他們的主場)
  +  已經有我們的片在前10 → 這檔已攻下,不必重做
分數越高越該優先做。**不對「有多少人搜」下猜測**——那個數字我們拿不到,
只用拿得到的:誰在上面、他們是誰。

## 配額
search.list 每次 100 單位。實測本頻道日配額 >=18,000(見 memory yt-quota-budget-2026-07),
上架一支約 2,050。預設一次只探 40 檔 = 4,000 單位,且**結果永久快取**,同一檔不重複探。

用法:
  python scripts/keyword_winnability.py --probe 40      # 探 40 檔未探過的 backlog 候選
  python scripts/keyword_winnability.py --report        # 只看已探過的結果排行
  python scripts/keyword_winnability.py --validate      # 拿已知結果驗算分數對不對
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
CACHE = STUDIO / "keyword_winnability.json"
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TOP_N = 10          # 只看前 10 名——第 11 名以後幾乎沒有點擊
QUOTA_PER_SEARCH = 100

# 大型媒體/新聞台:它們佔住的關鍵字是主場,我們不去硬碰。
# (判斷用頻道名關鍵字,不用訂閱數——訂閱數要另外打 channels.list,又是一輪配額。)
_BIG_MEDIA = ("東森", "非凡", "TVBS", "三立", "台視", "中視", "華視", "民視", "年代",
              "壹電視", "鏡新聞", "公視", "新聞", "News", "NEWS", "工商", "經濟日報",
              "財訊", "天下", "商周", "Yahoo", "moneydj", "鉅亨")


def _svc():
    """只讀建服務。**絕不回寫 token**——upload_youtube 的 SCOPES 與這份 token 不同,
    走它的 helper 會 invalid_scope → 觸發瀏覽器重新授權 → 覆蓋產線憑證(踩過一次)。"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(d):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def score(items, name: str, code: str, mine: str) -> dict:
    """把搜尋結果算成可攻佔分數(0~100,越高越該做)。"""
    top = items[:TOP_N]
    ours = next((i for i, it in enumerate(top, 1)
                 if it["snippet"]["channelId"] == mine), None)
    dedicated = 0      # 前10名裡「標題就在講這一檔」的片數 = 已經有人做專片
    bigmedia = 0
    for it in top:
        t = it["snippet"]["title"]
        ch = it["snippet"]["channelTitle"]
        if name in t or (code and code in t):
            dedicated += 1
        if any(b in ch for b in _BIG_MEDIA):
            bigmedia += 1
    # 空地越多分越高;大型媒體佔越多扣越兇(那是他們的主場,硬碰沒意義)
    s = 100 - dedicated * 9 - bigmedia * 6
    return {"name": name, "code": code, "ours_rank": ours,
            "dedicated": dedicated, "bigmedia": bigmedia,
            "n_results": len(items), "score": max(0, min(100, s)),
            "top3": [it["snippet"]["channelTitle"] for it in top[:3]]}


def probe(codes_names, limit: int):
    cache = _load()
    svc = _svc()
    mine = svc.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    todo = [(c, n) for c, n in codes_names if c not in cache][:limit]
    if not todo:
        print("沒有未探過的候選(全在快取裡)。")
        return cache
    print("本次探 %d 檔,預估耗用配額 %d 單位" % (len(todo), len(todo) * QUOTA_PER_SEARCH))
    for i, (code, name) in enumerate(todo, 1):
        try:
            r = svc.search().list(part="snippet", q=name, type="video", maxResults=25,
                                  regionCode="TW", relevanceLanguage="zh-Hant").execute()
            row = score(r.get("items", []), name, code, mine)
        except Exception as exc:  # noqa: BLE001
            print("  [%d/%d] %-6s ❌ %s" % (i, len(todo), name, str(exc)[:70]), file=sys.stderr)
            continue
        cache[code] = row
        print("  [%d/%d] %-7s 分數 %3d  已有專片 %d  大媒體 %d  我們排 %s"
              % (i, len(todo), name, row["score"], row["dedicated"], row["bigmedia"],
                 row["ours_rank"] or "-"))
        if i % 10 == 0:
            _save(cache)
        time.sleep(0.2)
    _save(cache)
    return cache


def _backlog_candidates():
    """回傳 backlog 裡「還沒做過」的 (code, name),維持原本順序。"""
    import json as _j
    p = STUDIO / "stock_checkup_backlog.json"
    if not p.exists():
        for alt in STUDIO.glob("*backlog*.json"):
            p = alt
            break
    try:
        d = _j.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    rows = d if isinstance(d, list) else (d.get("rows") or d.get("backlog") or [])
    done = set()
    try:
        facts = _j.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))
        done = set((facts.get("by_code") or {}).keys())
    except Exception:  # noqa: BLE001
        pass
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        c = str(r.get("code") or "")
        n = str(r.get("name") or "").replace("*", "")
        if c and n and c not in done:
            out.append((c, n))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0, help="探測 N 檔未探過的 backlog 候選")
    ap.add_argument("--report", action="store_true", help="印已探過的排行")
    ap.add_argument("--validate", action="store_true", help="用已知結果驗算分數")
    args = ap.parse_args()

    if args.validate:
        # 拿 Analytics 已證實「有搜尋流量」與「零搜尋流量」的股票對照,看分數分不分得開
        known_good = {"2368": "金像電", "6213": "聯茂", "3017": "奇鋐", "6669": "緯穎"}
        known_bad = {"2330": "台積電", "2454": "聯發科", "2317": "鴻海"}
        cache = probe(list(known_good.items()) + list(known_bad.items()), 99)
        g = [cache[c]["score"] for c in known_good if c in cache]
        b = [cache[c]["score"] for c in known_bad if c in cache]
        print()
        print("實際有搜尋流量的 %d 檔 平均分 %.1f" % (len(g), sum(g) / max(1, len(g))))
        print("實際零搜尋流量的 %d 檔 平均分 %.1f" % (len(b), sum(b) / max(1, len(b))))
        print("→ %s" % ("✅ 分數分得開,可用來排序"
                        if g and b and sum(g) / len(g) > sum(b) / len(b) + 8
                        else "❌ 分不開,別拿這個分數排序(要換指標)"))
        return 0

    if args.probe:
        cand = _backlog_candidates()
        print("backlog 未做過的候選 %d 檔" % len(cand))
        probe(cand, args.probe)

    cache = _load()
    if args.report or args.probe:
        rows = sorted(cache.values(), key=lambda r: -r["score"])
        print()
        print("=== 可攻佔排行(分數高=空地多、該優先做) ===")
        print("%-7s %-6s %-6s %-6s %-6s %s" % ("個股", "分數", "專片", "大媒體", "我們排", "前3名"))
        for r in rows[:25]:
            print("%-7s %-6d %-6d %-6d %-6s %s"
                  % (r["name"][:7], r["score"], r["dedicated"], r["bigmedia"],
                     r["ours_rank"] or "-", " / ".join(x[:10] for x in r["top3"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
