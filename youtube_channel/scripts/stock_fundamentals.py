#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock_fundamentals.py —【個股體檢·基本面引擎】補「營收/EPS/毛利/股利/估值位置」給
stock_checkup_facts.py 用（2026-07-15 任務，Carson 拍板：「單獨介紹一隻股票，講基本面」）。

背景：stock_checkup_facts.py 已經有「持有體驗」（20年報酬/套牢/腰斬）這套價格面事實，
但一支介紹個股的片，觀眾要聽的是「這公司到底在幹嘛、賺不賺錢、配不配息」——這些是
**基本面**，價格走勢引擎算不出來，要另一個資料源。

資料源（先驗證再全量，見 3 檔實測）：
  首選 FinMind 免費台股 API(REST，不裝 finmind 套件也能打)：
    - TaiwanStockMonthRevenue      → 月營收，聚合成年營收/YoY
    - TaiwanStockFinancialStatements → 各項財報科目(EPS/Revenue/GrossProfit季度值)
    - TaiwanStockDividend          → 股利發放史(現金股利+股票股利，逐次配息事件)
    - TaiwanStockPER               → 逐日本益比/股價淨值比/殖利率，算「目前 vs 自己歷史區間」
    - TaiwanStockInfo              → 產業別 + 最新公司簡稱(全市場一次抓，做代號→名稱/產業對照表)
  免費層 rate limit 約 300-600 req/hr；本模組：
    - 磁碟快取 twdata/fundamentals_cache/{code}_{dataset}.json，新鮮度依資料集特性分級
      (月營收/財報/股利 30 天，PER 序列 20 小時，TaiwanStockInfo 全市場表 7 天)。
    - 單一資料集失敗重試 3 次(退避 1s/2s/4s)，重試完仍失敗回 None，呼叫端靜默略過該項
      (寫進 skipped，不編造)。
    - 呼叫端(stock_checkup_daily.py)每天只處理 1-2 檔，天然不會暴衝。

誠信鐵則(同 stock_checkup_facts.py，這裡再次強調)：
  - 每組基本面事實都是 FinMind 原始回傳數字聚合算出來的，不假手 LLM 生數字。
  - 估值位置只講「目前 PER 落在近10年歷史的第幾百分位」，絕不判斷貴/便宜、不給目標價、
    不建議買賣——「介紹≠推薦」是本系列生死線。
  - 產業描述(profile)直接取用 FinMind TaiwanStockInfo 的 industry_category 官方分類欄位，
    不用 LLM 自由生成、不含任何數字宣稱。
  - 資料不足(上市 < MIN_YEARS_FUND 或財報/營收查無資料) → 該項略過，寫進 skipped 明確揭露。

用法(獨立測試用；正式串接見 stock_checkup_facts.py 的 build_fundamentals_facts 呼叫)：
  python scripts/stock_fundamentals.py --code 2330                # 印算出的基本面事實
  python scripts/stock_fundamentals.py --code 2330 --refresh      # 忽略快取重抓
  python scripts/stock_fundamentals.py --probe 2330 2317 2454     # 3 檔實測：印 FinMind 原始欄位

驗證：python -m py_compile scripts/stock_fundamentals.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import fundamentals_yf as _yf   # FinMind 掛掉時的備援來源(見該模組說明)
except Exception as _exc:  # noqa: BLE001
    _yf = None
    print(f"[stock_fundamentals] 載入 fundamentals_yf 備援失敗，只剩 FinMind：{_exc}", file=sys.stderr)

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
REPO_ROOT = ROOT.parent                                  # D:\carson-agent
CACHE_DIR = REPO_ROOT / "twdata" / "fundamentals_cache"   # Carson 拍板路徑(獨立於 data_hunter 的 twdata/fundamentals/)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()  # 選配；免費層無 token 約 300 req/hr，有 token 約 600 req/hr

DISCLAIMER = "公開財報/股利/估值歷史數據；不構成投資建議，不喊單、不報明牌、不給目標價。"
SOURCE_NOTE = "FinMind 免費台股 API(api.finmindtrade.com/api/v4/data，公開財報/月營收/股利/估值原始數據)"

FINMIND_TIMEOUT = 10        # 單次請求逾時(秒)。主機死掉時 30 秒×3重試×5組 會把排程拖垮
_FM_TRIP = 2                # 同一次執行連續失敗這麼多次就熔斷,之後直接走 yfinance 備援
_FM_FAILS = 0               # 累計失敗數(process 內)

MIN_YEARS_FUND = 3          # 少於 3 個完整年度營收/EPS 資料不產出(上市未滿3年的新股)
MIN_PER_ROWS = 250          # PER 歷史序列至少要有這麼多筆(約1年交易日)才算百分位有意義

# 🔴 財報資料集(TaiwanStockFinancialStatements)所有呼叫端必須共用同一個抓取窗口——
# 快取 key 只有 {code}_{dataset} 不含起始日，兩個呼叫端用不同窗口會互相洗掉對方的快取
# (2026-07-15 實測抓到：calc_gross_margin 用3年窗寫入快取 → 下次 calc_eps_trend 讀到只剩
# 3年資料 → 完整年度<3 → 2330 的 EPS 整項被誤判「資料不足」略過)。統一抓最長需求(11年)，
# 短窗口的計算函式(毛利率只要近8季)自己切尾端。
FIN_STMT_FETCH_YEARS = 11

# 各資料集快取新鮮度(小時)：月營收/財報/股利每季更新一次，抓太勤只是浪費 rate limit；
# PER 是逐日資料，20 小時貼齊 stock_checkup_facts.py 價格快取的新鮮度慣例。
_TTL_H = {
    "TaiwanStockMonthRevenue": 24 * 30,
    "TaiwanStockFinancialStatements": 24 * 30,
    "TaiwanStockDividend": 24 * 30,
    "TaiwanStockPER": 20,
    "TaiwanStockInfo": 24 * 7,
}


# ── 資料層：FinMind REST + 磁碟快取 + 重試退避 ──────────────────────────────
def _cache_path(code, dataset):
    safe_code = code or "_ALL_"
    return CACHE_DIR / f"{safe_code}_{dataset}.json"


def _load_cache(code, dataset, allow_stale=False):
    """allow_stale=True 時忽略 TTL 直接回舊快取。

    給「內容幾乎不會變、但沒有它就整支垮掉」的資料用(目前只有 TaiwanStockInfo 全市場
    對照表:公司正式名稱與產業分類)。FinMind 掛掉後這張表過期就變成 None，個股體檢的
    公司名整個退化成代號(標題變「個股體檢6223」)、產業分類空白。**過期的正確名稱**
    遠好過**沒有名稱**,所以主來源抓不到時退回舊快取,而不是兩手空空。"""
    p = _cache_path(code, dataset)
    if not p.exists():
        return None
    try:
        if not allow_stale:
            ttl_h = _TTL_H.get(dataset, 24)
            age_h = (time.time() - p.stat().st_mtime) / 3600.0
            if age_h > ttl_h:
                return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _save_cache(code, dataset, rows):
    try:
        _cache_path(code, dataset).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _finmind_get(dataset, data_id=None, start_date=None, retries=3):
    """打 FinMind REST，失敗重試(退避 1s/2s/4s)；回傳 data 陣列，全部失敗回 None。"""
    import requests
    params = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    # ── 熔斷:主機不通時不要每組都重試到天荒地老 ────────────────────────────────
    # FinMind 2026-07-18 起連不上。原本每個 dataset 重試 3 次 × 30 秒 timeout，
    # 一檔 5 組 = 最壞 7.5 分鐘全花在等一台已經死掉的主機上，一天 13 檔就是近 2 小時，
    # 排程直接被拖垮。連續失敗 _FM_TRIP 次之後本 process 不再打 FinMind，直接走備援。
    global _FM_FAILS
    if _FM_FAILS >= _FM_TRIP:
        return None
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(FINMIND_URL, params=params, timeout=FINMIND_TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                if d.get("status") == 200 or d.get("msg") == "success":
                    return d.get("data") or []
                last_err = d.get("msg", f"status={d.get('status')}")
            else:
                last_err = f"http {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        if attempt < retries - 1:
            time.sleep(1.0 * (2 ** attempt))
    _FM_FAILS += 1
    print(f"[stock_fundamentals] {dataset}（{data_id}）抓取失敗（{retries} 次重試後放棄）：{last_err}")
    if _FM_FAILS == _FM_TRIP:
        print(f"[stock_fundamentals] ⚠️ FinMind 連續失敗 {_FM_TRIP} 次 → 本次執行不再嘗試，"
              f"全部改走 yfinance 備援（省下每組 3×{FINMIND_TIMEOUT}秒的空等）", file=sys.stderr)
    return None


def fetch_dataset(code, dataset, start_date=None, refresh=False):
    """快取優先；沒快取或過期才真的打 API。回傳 rows 或 None(全部失敗)。"""
    if not refresh:
        cached = _load_cache(code, dataset)
        if cached is not None:
            return cached
    rows = _finmind_get(dataset, data_id=code, start_date=start_date)
    if rows is not None:
        _save_cache(code, dataset, rows)
        time.sleep(0.8)  # 禮貌性節流，善待免費 API(避免同一輪多資料集連打)
    return rows


def fetch_stock_info_table(refresh=False):
    """全市場一次抓 TaiwanStockInfo(約 4000+ 筆歷史掛牌紀錄)，回傳 {code: {name, industry}}
    (同代號多筆取最新 date 那筆)。7 天快取(全市場一次抓，別每檔都重打)。"""
    rows = fetch_dataset(None, "TaiwanStockInfo", refresh=refresh)
    if not rows:
        # 主來源掛了就用過期快取(見 _load_cache 的 allow_stale 說明)。公司正式名稱與
        # 產業分類是靜態資料,舊表照樣正確;沒有它的話標題會退化成「個股體檢6223」。
        rows = _load_cache(None, "TaiwanStockInfo", allow_stale=True)
        if rows:
            print("[stock_fundamentals] TaiwanStockInfo 抓不到 → 使用過期快取"
                  "(公司名/產業為靜態資料,舊表仍正確)", file=sys.stderr)
    if not rows:
        return {}
    out = {}
    for row in rows:
        code = str(row.get("stock_id") or "")
        if not code:
            continue
        date = str(row.get("date") or "")
        prev = out.get(code)
        if prev is None or date >= prev.get("_date", ""):
            out[code] = {
                "name": row.get("stock_name") or code,
                "industry": row.get("industry_category") or "",
                "_date": date,
            }
    return out


# ── 事實類型 G：年營收趨勢 + YoY ─────────────────────────────────────────────
def calc_revenue_trend(code, refresh=False, years=10):
    start = (_dt.date.today() - _dt.timedelta(days=365 * (years + 1))).isoformat()
    rows = fetch_dataset(code, "TaiwanStockMonthRevenue", start_date=start, refresh=refresh)
    if not rows:
        return None
    annual = {}
    for row in rows:
        try:
            yr = int(row.get("revenue_year"))
            rev = float(row.get("revenue") or 0)
        except Exception:  # noqa: BLE001
            continue
        if rev <= 0:
            continue
        d = annual.setdefault(yr, {"months": set(), "revenue": 0.0})
        mo = row.get("revenue_month")
        if mo is not None:
            d["months"].add(int(mo))
        d["revenue"] += rev
    full_years = sorted(y for y, d in annual.items() if len(d["months"]) >= 12)
    if len(full_years) < MIN_YEARS_FUND:
        return None
    full_years = full_years[-years:]
    series = []
    prev_rev = None
    for yr in full_years:
        rev = annual[yr]["revenue"]
        yoy = (rev / prev_rev - 1.0) if prev_rev else None
        series.append({"year": yr, "revenue": round(rev, 0), "yoy": (round(yoy, 4) if yoy is not None else None)})
        prev_rev = rev
    latest = series[-1]
    yoy_txt = f"{latest['yoy']*100:+.1f}%" if latest.get("yoy") is not None else "（無前一年可比）"
    return {
        "years": len(series), "start_year": series[0]["year"], "end_year": series[-1]["year"],
        "series": series,
        "summary": (f"近{len(series)}個完整年度營收：{series[0]['year']}年約{series[0]['revenue']/1e8:.1f}億元 → "
                    f"{latest['year']}年約{latest['revenue']/1e8:.1f}億元（年增 {yoy_txt}）"),
    }


# ── 事實類型 H：年度 EPS 序列 ─────────────────────────────────────────────────
def calc_eps_trend(code, refresh=False, years=10):
    start = (_dt.date.today() - _dt.timedelta(days=365 * FIN_STMT_FETCH_YEARS)).isoformat()
    rows = fetch_dataset(code, "TaiwanStockFinancialStatements", start_date=start, refresh=refresh)
    if not rows:
        return None
    by_year = {}
    for row in rows:
        if row.get("type") != "EPS":
            continue
        date = str(row.get("date") or "")
        if len(date) < 4:
            continue
        yr = int(date[:4])
        try:
            val = float(row.get("value"))
        except Exception:  # noqa: BLE001
            continue
        by_year.setdefault(yr, []).append(val)
    full_years = sorted(y for y, vals in by_year.items() if len(vals) >= 4)
    if len(full_years) < MIN_YEARS_FUND:
        return None
    full_years = full_years[-years:]
    series = [{"year": yr, "eps": round(sum(by_year[yr][:4]), 2)} for yr in full_years]
    latest, first = series[-1], series[0]
    return {
        "years": len(series), "start_year": first["year"], "end_year": latest["year"],
        "series": series,
        "summary": (f"近{len(series)}個完整年度EPS：{first['year']}年 {first['eps']:.2f}元 → "
                    f"{latest['year']}年 {latest['eps']:.2f}元"),
    }


# ── 事實類型 I：毛利率序列(近8季) ─────────────────────────────────────────────
def calc_gross_margin(code, refresh=False, quarters=8):
    # 抓取窗口統一走 FIN_STMT_FETCH_YEARS(與 calc_eps_trend 共用同一份快取，見常數註解)；
    # 只要近8季 → 下面 rows_out[-quarters:] 自己切尾端，多抓的年份不影響結果。
    start = (_dt.date.today() - _dt.timedelta(days=365 * FIN_STMT_FETCH_YEARS)).isoformat()
    rows = fetch_dataset(code, "TaiwanStockFinancialStatements", start_date=start, refresh=refresh)
    if not rows:
        return None
    by_q = {}
    for row in rows:
        t = row.get("type")
        if t not in ("Revenue", "GrossProfit"):
            continue
        date = str(row.get("date") or "")
        try:
            val = float(row.get("value"))
        except Exception:  # noqa: BLE001
            continue
        by_q.setdefault(date, {})[t] = val
    rows_out = []
    for date in sorted(by_q.keys()):
        d = by_q[date]
        rev, gp = d.get("Revenue"), d.get("GrossProfit")
        if not rev or rev <= 0 or gp is None:
            continue
        rows_out.append({"quarter": date, "gross_margin": round(gp / rev * 100.0, 1)})
    if len(rows_out) < 4:
        return None
    rows_out = rows_out[-quarters:]
    latest = rows_out[-1]
    avg = sum(r["gross_margin"] for r in rows_out) / len(rows_out)
    return {
        "n_quarters": len(rows_out), "start": rows_out[0]["quarter"], "end": latest["quarter"],
        "series": rows_out, "latest_margin": latest["gross_margin"], "avg_margin": round(avg, 1),
        "summary": (f"近{len(rows_out)}季毛利率：最新一季({latest['quarter'][:7]}) {latest['gross_margin']:.1f}%，"
                    f"近{len(rows_out)}季平均 {avg:.1f}%"),
    }


# ── 事實類型 J：股利發放史(連續配息年數 + 近5年平均殖利率) ────────────────────
def calc_dividend_history(code, price_series=None, refresh=False, years=15):
    start = (_dt.date.today() - _dt.timedelta(days=365 * (years + 1))).isoformat()
    rows = fetch_dataset(code, "TaiwanStockDividend", start_date=start, refresh=refresh)
    if not rows:
        return None
    by_year = {}
    for row in rows:
        date = str(row.get("date") or "")
        if len(date) < 4:
            continue
        yr = int(date[:4])
        try:
            cash = float(row.get("CashEarningsDistribution") or 0)
            stock = float(row.get("StockEarningsDistribution") or 0)
        except Exception:  # noqa: BLE001
            cash, stock = 0.0, 0.0
        d = by_year.setdefault(yr, {"cash": 0.0, "stock": 0.0})
        d["cash"] += cash
        d["stock"] += stock
    if not by_year:
        return None
    this_year = _dt.date.today().year
    paid_years = sorted(y for y, d in by_year.items() if (d["cash"] + d["stock"]) > 0)
    if not paid_years:
        return {
            "n_years_data": len(by_year), "consecutive_years": 0,
            "summary": f"近{len(by_year)}年資料裡沒有配息紀錄",
            "series": [],
        }
    # 連續配息年數：從最近一個「已過完的」有配息年份往回數，中斷就停
    consec = 0
    y = max(y for y in paid_years if y < this_year) if any(y < this_year for y in paid_years) else max(paid_years)
    while y in by_year and (by_year[y]["cash"] + by_year[y]["stock"]) > 0:
        consec += 1
        y -= 1
    # 近5年平均殖利率：需要當年均價(用共用價格序列算，缺價格就只給股利金額不算殖利率)
    yields = []
    if price_series is not None and len(price_series):
        for yr in [y for y in paid_years if y >= this_year - 5 and y < this_year]:
            yr_px = price_series[(price_series.index.year == yr)]
            if len(yr_px) < 20:
                continue
            avg_px = float(yr_px.mean())
            if avg_px <= 0:
                continue
            yields.append(by_year[yr]["cash"] / avg_px)
    avg_yield = (sum(yields) / len(yields)) if yields else None
    series = [{"year": y, "cash_dividend": round(by_year[y]["cash"], 3),
               "stock_dividend": round(by_year[y]["stock"], 3)} for y in sorted(by_year.keys())]
    yld_txt = f"、近5年平均現金殖利率約 {avg_yield*100:.1f}%" if avg_yield is not None else ""
    return {
        "n_years_data": len(by_year), "consecutive_years": consec,
        "series": series, "avg_yield_5y": (round(avg_yield, 4) if avg_yield is not None else None),
        "summary": (f"資料涵蓋{len(by_year)}年，連續配息 {consec} 年"
                    f"（最近一次中斷前）{yld_txt}"),
    }


# ── 事實類型 K：估值位置(目前本益比 vs 自己10年歷史區間，只陳述位置) ──────────
def calc_valuation_position(code, refresh=False, years=10):
    start = (_dt.date.today() - _dt.timedelta(days=365 * (years + 1))).isoformat()
    rows = fetch_dataset(code, "TaiwanStockPER", start_date=start, refresh=refresh)
    if not rows or len(rows) < MIN_PER_ROWS:
        return None
    pe_rows = [(str(r.get("date")), float(r["PER"])) for r in rows
               if r.get("PER") not in (None, 0) and str(r.get("date"))]
    if len(pe_rows) < MIN_PER_ROWS:
        return None
    pe_rows.sort(key=lambda x: x[0])
    vals = sorted(v for _, v in pe_rows)
    n = len(vals)

    def _pct(p):
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return vals[idx]

    p25, p50, p75 = _pct(0.25), _pct(0.50), _pct(0.75)
    latest_date, latest_pe = pe_rows[-1]
    rank = sum(1 for v in vals if v <= latest_pe) / n
    dy_rows = [float(r["dividend_yield"]) for r in rows if r.get("dividend_yield") not in (None, 0)]
    latest_dy = dy_rows[-1] if dy_rows else None
    return {
        "years": years, "start": pe_rows[0][0], "end": latest_date,
        "latest_per": round(latest_pe, 1), "latest_date": latest_date,
        "p25": round(p25, 1), "median": round(p50, 1), "p75": round(p75, 1),
        "percentile_rank": round(rank * 100, 0),
        "latest_dividend_yield": (round(latest_dy, 2) if latest_dy is not None else None),
        "summary": (f"截至{latest_date}，本益比 {latest_pe:.1f} 倍，位於自身近{years}年歷史區間的"
                    f"第 {round(rank*100):.0f} 百分位（10年區間：P25={p25:.1f}倍／中位數={p50:.1f}倍／"
                    f"P75={p75:.1f}倍）——本片只陳述數據位置，不判斷貴或便宜、不構成買賣建議。"),
    }


# ── 主流程：組成 stock_checkup_facts.py 相容的 fact dict ─────────────────────
def build_fundamentals_facts(code, name, price_series=None, refresh=False):
    """回傳 (results dict, skipped list, profile dict)。results/skipped schema 與
    stock_checkup_facts.build_checkup() 的 add() 產出一致，可直接合併進同一份 results。"""
    as_of = _dt.date.today().isoformat()
    results, skipped = {}, []

    def add(key, method, desc, payload, source=SOURCE_NOTE):
        if not payload:
            skipped.append({"key": key, "desc": desc,
                            "reason": "FinMind 與 yfinance 兩個來源都查無資料或資料不足，本次略過未產出"})
            return
        start = payload.get("start") or payload.get("start_year") or "?"
        end = payload.get("end") or payload.get("end_year") or "?"
        results[key] = {
            "key": key, "claim": payload.get("summary", desc), "desc": desc,
            "summary": payload.get("summary", desc), "keywords": [code, name],
            "method": method, "symbol": f"{name}（{code}）", "period": f"{start}~{end}",
            "source": source, "computed_at": as_of, "disclaimer": DISCLAIMER, "data": payload,
        }

    # 每組事實:先問 FinMind，None 就改問 yfinance 備援(見 fundamentals_yf 的模組說明——
    # FinMind API 2026-07-18 起連不上，害個股體檢連續 16 天、108 檔基本面全滅且零告警)。
    # method/source 依實際來源分別標註,**不可以**讓 Yahoo 的年度數字掛 FinMind 的名。
    PLAN = [
        ("revenue_trend", f"{name} 近年營收趨勢",
         lambda: calc_revenue_trend(code, refresh=refresh),
         "TaiwanStockMonthRevenue 逐月營收依年份加總(需滿12個月才算完整年度)+年增率",
         lambda: _yf.revenue_trend(code),
         "Yahoo Finance income_stmt Total Revenue 年度營收+年增率(非逐月加總)"),
        ("eps_trend", f"{name} 近年EPS序列",
         lambda: calc_eps_trend(code, refresh=refresh),
         "TaiwanStockFinancialStatements type=EPS，四季加總為年度EPS",
         lambda: _yf.eps_trend(code),
         "Yahoo Finance income_stmt Diluted EPS 年度值(公司公告年度EPS,非四季自行加總)"),
        ("gross_margin", f"{name} 毛利率趨勢",
         lambda: calc_gross_margin(code, refresh=refresh),
         "TaiwanStockFinancialStatements GrossProfit/Revenue，近8季單季毛利率",
         lambda: _yf.gross_margin(code),
         "Yahoo Finance quarterly_income_stmt GrossProfit/TotalRevenue，近數季單季毛利率"),
        ("dividend_history", f"{name} 股利發放史",
         lambda: calc_dividend_history(code, price_series=price_series, refresh=refresh),
         "TaiwanStockDividend 逐次配息事件依年度加總，算連續配息年數+近5年平均現金殖利率(殖利率需搭配含息還原價序列)",
         lambda: _yf.dividend_history(code, price_series=price_series),
         "Yahoo Finance dividends 逐次配息依年度加總(**只有現金股利,不含股票股利**)+近5年平均現金殖利率"),
        ("valuation_position", f"{name} 估值位置(vs自身歷史區間)",
         lambda: calc_valuation_position(code, refresh=refresh),
         "TaiwanStockPER 近10年逐日本益比，算目前值在自身歷史分佈的百分位(P25/中位數/P75)——只陳述位置不判斷貴賤",
         lambda: _yf.valuation_position(code, price_series=price_series),
         "每日收盤價 ÷ **前一年度** EPS 自行推算本益比序列(Yahoo 無逐日PER;用前一年度避免前視偏誤)，算目前值在自身區間的百分位——只陳述位置不判斷貴賤"),
    ]

    print(f"[stock_fundamentals] {code}（{name}）抓基本面（FinMind，失敗則 yfinance 備援）...")
    fm_ok = yf_ok = 0
    for slug, desc, fm_fn, fm_method, yf_fn, yf_method in PLAN:
        key = f"checkup_{slug}__{code}"
        payload = method = src = None
        try:
            payload = fm_fn()
        except Exception as exc:  # noqa: BLE001
            print(f"[stock_fundamentals] {key} FinMind 例外：{exc}", file=sys.stderr)
        if payload:
            fm_ok += 1
            method, src = fm_method, SOURCE_NOTE
        elif _yf is not None:
            try:
                payload = yf_fn()
            except Exception as exc:  # noqa: BLE001
                print(f"[stock_fundamentals] {key} yfinance 例外：{exc}", file=sys.stderr)
                payload = None
            if payload:
                yf_ok += 1
                method, src = yf_method, _yf.SOURCE_NOTE
        add(key, method or fm_method, desc, payload, source=src or SOURCE_NOTE)

    # 主來源整支掛掉要**叫**。原本 FinMind 失敗和「這檔真的沒資料」寫同一句 reason，
    # 兩者長得一模一樣，所以壞了 16 天沒有任何一層發現。
    if fm_ok == 0:
        msg = (f"FinMind 五組全部取不到（{code} {name}）"
               + (f"；已由 yfinance 備援補上 {yf_ok} 組" if yf_ok else "；yfinance 備援也沒補上，這檔完全沒有基本面"))
        print(f"[stock_fundamentals] ⚠️ {msg}", file=sys.stderr)
        try:
            from ops import log_ops
            log_ops("基本面來源異常", msg)
        except Exception:  # noqa: BLE001
            pass

    info_table = fetch_stock_info_table(refresh=False)  # 全市場表快取 7 天，通常吃快取不打 API
    industry = (info_table.get(code) or {}).get("industry", "")
    profile = {"industry": industry, "source": "FinMind TaiwanStockInfo 官方產業分類(非LLM生成，不含數字)"} if industry else {}

    return results, skipped, profile


def main() -> int:
    ap = argparse.ArgumentParser(description="個股體檢·基本面引擎")
    ap.add_argument("--code", type=str, default=None)
    ap.add_argument("--name", type=str, default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--probe", nargs="+", default=None, help="3檔實測模式：印每個資料集的原始回傳(不算事實)")
    args = ap.parse_args()

    if args.probe:
        for code in args.probe:
            print("=" * 70)
            print(f"【實測】{code}")
            for ds in ("TaiwanStockMonthRevenue", "TaiwanStockFinancialStatements", "TaiwanStockDividend", "TaiwanStockPER"):
                rows = fetch_dataset(code, ds, start_date="2023-01-01", refresh=args.refresh)
                n = len(rows) if rows else 0
                print(f"  · {ds}: {n} 筆" + (f"，範例：{rows[0]}" if rows else "（查無資料）"))
        return 0

    if not args.code:
        print("[stock_fundamentals] 請給 --code 2330 或 --probe 2330 2317 2454")
        return 1

    name = args.name or args.code
    results, skipped, profile = build_fundamentals_facts(args.code, name, refresh=args.refresh)
    print("-" * 70)
    print(f"[stock_fundamentals] {args.code}（{name}）共算出 {len(results)} 組基本面事實，{len(skipped)} 組略過")
    for k, v in results.items():
        print(f"  · [{k}]\n      {v['summary']}")
    if skipped:
        print("  略過項目：")
        for sk in skipped:
            print(f"    ✗ [{sk['key']}] {sk['reason']}")
    if profile:
        print(f"  公司檔案：{profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
