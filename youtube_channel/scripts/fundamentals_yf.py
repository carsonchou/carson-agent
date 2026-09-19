#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundamentals_yf.py — 個股基本面的 **yfinance 備援來源**(FinMind 死掉時頂上)。

## 為什麼需要(2026-08-03 實測)
`stock_fundamentals.py` 的五組基本面事實全部靠 FinMind
(`api.finmindtrade.com`)。實測該 host **從本機與 Anthropic 出口都連不上**
(一邊 timeout、一邊 ECONNREFUSED),而 finmindtrade.com 主站與官方文件都還活著、
endpoint 也沒改 → 是他們那台 API server 掛了,不是我們的問題,但也回不來。

災情規模(從 STUDIO/stock_checkup_facts.json 的 computed_at 逐日統計):
  2026-07-17 之前:每天 13~14 檔有基本面 ✅
  2026-07-18 起 :**連續 16 天、108 檔,基本面全滅** ❌ 且零告警

個股體檢是每日主力長片系列。等於半個月來每一支長片都在「沒有財報可講」的狀態下產出
——「基本面資料」段只剩 43 字、也沒有真資料可畫圖。Carson 說「影片做很爛」,
這是實體原因之一。

## 為什麼是 yfinance 而不是 TWSE OpenAPI
產線的**價格**序列本來就走 yfinance 且**每天都成功**(tw_facts_cache 更新到 2026-07-31),
證明這條路在這台機器是通的。TWSE/TPEx OpenAPI 在本機測試連不上(這個 session 的外連
有過濾,測不準),而 yfinance 是已驗證可用的既有相依 → 選確定能跑的那條。

## 誠信約束(這裡最容易出事,別動)
Yahoo 給的東西和 FinMind **不是同一種**,所以**絕對不可以**把 Yahoo 的年度數字塞進
FinMind 的月營收列裡冒充。差異必須寫進 summary 讓旁白照實講:
  1. 營收:Yahoo 只有**年度**(4~5 年),FinMind 是逐月加總成年度(10 年)。
  2. 股利:Yahoo 的 dividends 只有**現金股利**,沒有股票股利 → summary 不得宣稱股票股利。
  3. 估值:Yahoo 沒有逐日 PER 歷史。這裡是用**前一年度 EPS** 去除每日收盤價自行推算
     (用前一年而非當年,是因為當年 EPS 在當下還不知道,用當年會有前視偏誤)。
     期間只有 ~4 年,summary 必須寫「近N年」不得寫死 10 年。
每個 payload 都帶 `provider` 欄位,上游據此改寫 method/source,不會被誤標成 FinMind。

輸出結構與 stock_fundamentals.calc_* 逐欄位對齊,可直接餵給同一個 add()。
"""
from __future__ import annotations

import datetime as _dt
import sys
import time
import warnings
from typing import Optional

warnings.filterwarnings("ignore")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

PROVIDER = "yfinance"
SOURCE_NOTE = ("Yahoo Finance 公開財報(yfinance income_stmt / dividends)"
               "——FinMind API 停止服務期間的備援來源")

MIN_YEARS_FUND = 3     # 與 stock_fundamentals 同門檻:少於 3 個年度不產出
MIN_PER_ROWS = 250     # 推算本益比序列至少要這麼多個交易日才算百分位有意義

_TICKER_CACHE: dict = {}


def _yf():
    import yfinance as yf
    return yf


def resolve_ticker(code: str):
    """回傳 (yf.Ticker, symbol) 或 (None, None)。

    上市是 {code}.TW、上櫃是 {code}.TWO,先試上市再試上櫃(與 stock_checkup_facts.py
    的價格 fallback 同順序)。判斷「有沒有這檔」用 income_stmt 非空,而不是 .info——
    .info 對不存在的代號會回一包空殼而不是報錯,拿它當判斷會全部誤判成有資料。

    ⚠️ 每個後綴重試兩次,而且兩邊都失敗時要**印出原因**。原本寫成 `except: continue`
    靜默跳過,實測 2330 在同一支程式裡第一次呼叫失敗(yfinance 首呼叫要建 timezone 快取,
    偶發失敗)就被判成「查無此代號」,單獨再跑卻完全正常——正是「不會壞、只會少做一件事」
    的那種洞。查無代號和抓取失敗是兩件事,不可以長得一樣。"""
    if code in _TICKER_CACHE:
        return _TICKER_CACHE[code]
    yf = _yf()
    last_err = None
    # 兩個後綴為一輪,整輪重跑兩次。**不能只在丟例外時重試**——實測 process 裡的第一個
    # yfinance 呼叫(冷啟動要跟 Yahoo 握手拿 cookie/crumb)會回一張**空表格而不是報錯**,
    # 2330 因此被判成「查無此代號」,同一支程式裡排第二的 6223 卻完全正常。
    # 空表格 ≠ 沒這檔,整輪重試才擋得住。
    for rnd in range(2):
        for suffix in (".TW", ".TWO"):
            sym = f"{code}{suffix}"
            try:
                t = yf.Ticker(sym)
                inc = t.income_stmt
                if inc is not None and not inc.empty:
                    _TICKER_CACHE[code] = (t, sym)
                    return t, sym
            except Exception as exc:       # noqa: BLE001
                last_err = f"{sym}: {type(exc).__name__} {str(exc)[:60]}"
        if rnd == 0:
            time.sleep(2.0)
    print(f"[fundamentals_yf] {code} 兩個後綴、兩輪都取不到財報"
          f"（{last_err or '無例外,兩邊都回空表'}）", file=sys.stderr)
    _TICKER_CACHE[code] = (None, None)
    return None, None


def _num(v):
    """把 pandas 值轉成 float;NaN / None / 轉不動 → None(呼叫端一律要判 None)。"""
    try:
        f = float(v)
    except Exception:  # noqa: BLE001
        return None
    return None if f != f else f      # NaN 自己不等於自己


def _row_by_year(df, names):
    """從財報 DataFrame 取某一列,回 {年份: 值};names 依序試(例:優先稀釋EPS再基本EPS)。"""
    if df is None or df.empty:
        return {}
    for nm in names:
        if nm not in df.index:
            continue
        out = {}
        for col, val in df.loc[nm].items():
            v = _num(val)
            if v is None:
                continue
            try:
                out[int(str(col)[:4])] = v
            except Exception:  # noqa: BLE001
                continue
        if out:
            return out
    return {}


# ── 營收趨勢(年度) ───────────────────────────────────────────────────────────
def revenue_trend(code: str, years: int = 10) -> Optional[dict]:
    t, _sym = resolve_ticker(code)
    if t is None:
        return None
    rev = _row_by_year(t.income_stmt, ["Total Revenue", "Operating Revenue"])
    yrs = sorted(rev)[-years:]
    if len(yrs) < MIN_YEARS_FUND:
        return None
    series, prev = [], None
    for y in yrs:
        yoy = (rev[y] / prev - 1.0) if prev else None
        series.append({"year": y, "revenue": round(rev[y], 0),
                       "yoy": (round(yoy, 4) if yoy is not None else None)})
        prev = rev[y]
    latest = series[-1]
    yoy_txt = f"{latest['yoy']*100:+.1f}%" if latest.get("yoy") is not None else "（無前一年可比）"
    return {
        "provider": PROVIDER,
        "years": len(series), "start_year": series[0]["year"], "end_year": latest["year"],
        "series": series,
        "summary": (f"近{len(series)}個年度營收：{series[0]['year']}年約{series[0]['revenue']/1e8:.1f}億元 → "
                    f"{latest['year']}年約{latest['revenue']/1e8:.1f}億元（年增 {yoy_txt}）"),
    }


# ── EPS 趨勢(年度) ───────────────────────────────────────────────────────────
def eps_trend(code: str, years: int = 10) -> Optional[dict]:
    t, _sym = resolve_ticker(code)
    if t is None:
        return None
    eps = _row_by_year(t.income_stmt, ["Diluted EPS", "Basic EPS"])
    yrs = sorted(eps)[-years:]
    if len(yrs) < MIN_YEARS_FUND:
        return None
    series = [{"year": y, "eps": round(eps[y], 2)} for y in yrs]
    first, latest = series[0], series[-1]
    return {
        "provider": PROVIDER,
        "years": len(series), "start_year": first["year"], "end_year": latest["year"],
        "series": series,
        "summary": (f"近{len(series)}個年度EPS：{first['year']}年 {first['eps']:.2f}元 → "
                    f"{latest['year']}年 {latest['eps']:.2f}元"),
    }


# ── 毛利率(單季序列) ─────────────────────────────────────────────────────────
def gross_margin(code: str, quarters: int = 8) -> Optional[dict]:
    t, _sym = resolve_ticker(code)
    if t is None:
        return None
    df = None
    try:
        df = t.quarterly_income_stmt
    except Exception:  # noqa: BLE001
        df = None
    if df is None or df.empty or "Gross Profit" not in df.index or "Total Revenue" not in df.index:
        return None
    rows = []
    for col in sorted(df.columns, key=lambda c: str(c)):
        rev, gp = _num(df.loc["Total Revenue", col]), _num(df.loc["Gross Profit", col])
        if rev is None or gp is None or rev <= 0:
            continue
        rows.append({"quarter": str(col)[:10], "gross_margin": round(gp / rev * 100.0, 1)})
    if len(rows) < 4:
        return None
    rows = rows[-quarters:]
    latest = rows[-1]
    avg = sum(r["gross_margin"] for r in rows) / len(rows)
    return {
        "provider": PROVIDER,
        "n_quarters": len(rows), "start": rows[0]["quarter"], "end": latest["quarter"],
        "series": rows, "latest_margin": latest["gross_margin"], "avg_margin": round(avg, 1),
        "summary": (f"近{len(rows)}季毛利率：最新一季({latest['quarter'][:7]}) {latest['gross_margin']:.1f}%，"
                    f"近{len(rows)}季平均 {avg:.1f}%"),
    }


# ── 股利發放史(只有現金股利) ─────────────────────────────────────────────────
def dividend_history(code: str, price_series=None, years: int = 15) -> Optional[dict]:
    t, _sym = resolve_ticker(code)
    if t is None:
        return None
    try:
        div = t.dividends
    except Exception:  # noqa: BLE001
        return None
    if div is None or not len(div):
        return None
    this_year = _dt.date.today().year
    by_year: dict = {}
    for ts, val in div.items():
        v = _num(val)
        if v is None or v <= 0:
            continue
        y = int(getattr(ts, "year", str(ts)[:4]))
        if y < this_year - years:
            continue
        by_year[y] = by_year.get(y, 0.0) + v
    if not by_year:
        return None
    paid = sorted(by_year)
    # 連續配息年數:從最近一個「已過完的」有配息年份往回數,中斷即停(與 FinMind 版同演算法)
    consec = 0
    y = max([p for p in paid if p < this_year] or paid)
    while by_year.get(y, 0.0) > 0:
        consec += 1
        y -= 1
    yields = []
    if price_series is not None and len(price_series):
        for yr in [p for p in paid if this_year - 5 <= p < this_year]:
            try:
                yr_px = price_series[price_series.index.year == yr]
            except Exception:  # noqa: BLE001
                continue
            if len(yr_px) < 20:
                continue
            avg_px = float(yr_px.mean())
            if avg_px > 0:
                yields.append(by_year[yr] / avg_px)
    avg_yield = (sum(yields) / len(yields)) if yields else None
    series = [{"year": y, "cash_dividend": round(by_year[y], 3)} for y in paid]
    yld = f"、近5年平均現金殖利率約 {avg_yield*100:.1f}%" if avg_yield is not None else ""
    return {
        "provider": PROVIDER,
        "n_years_data": len(by_year), "consecutive_years": consec,
        "series": series, "avg_yield_5y": (round(avg_yield, 4) if avg_yield is not None else None),
        "cash_only": True,
        "summary": (f"資料涵蓋{len(by_year)}年，連續配息 {consec} 年（最近一次中斷前）{yld}"
                    f"；本項只計現金股利，不含股票股利"),
    }


# ── 估值位置(用前一年度 EPS 推算的本益比序列) ────────────────────────────────
def valuation_position(code: str, price_series=None, years: int = 10) -> Optional[dict]:
    """Yahoo 沒有逐日 PER 歷史,所以自行推算:每日收盤價 ÷ **前一年度** EPS。

    用前一年而不是當年,是因為當年 EPS 在當下根本還沒公布,拿它回頭算會有前視偏誤
    (算出來的歷史百分位會比真實情況好看)。代價是可用年數少一年,summary 據實寫。"""
    if price_series is None or not len(price_series):
        return None
    t, _sym = resolve_ticker(code)
    if t is None:
        return None
    eps = _row_by_year(t.income_stmt, ["Diluted EPS", "Basic EPS"])
    eps = {y: v for y, v in eps.items() if v and v > 0}   # 虧損年無本益比可言
    if len(eps) < 2:
        return None
    pe_rows = []
    for ts, px in price_series.items():
        p = _num(px)
        if p is None or p <= 0:
            continue
        y = int(getattr(ts, "year", str(ts)[:4]))
        e = eps.get(y - 1)                       # ← 前一年度 EPS
        if not e:
            continue
        pe_rows.append((str(ts)[:10], p / e))
    if len(pe_rows) < MIN_PER_ROWS:
        return None
    pe_rows.sort(key=lambda x: x[0])
    vals = sorted(v for _, v in pe_rows)
    n = len(vals)

    def _pct(p):
        return vals[min(n - 1, max(0, int(round(p * (n - 1)))))]

    p25, p50, p75 = _pct(0.25), _pct(0.50), _pct(0.75)
    latest_date, latest_pe = pe_rows[-1]
    rank = sum(1 for v in vals if v <= latest_pe) / n
    span = int(pe_rows[-1][0][:4]) - int(pe_rows[0][0][:4]) + 1

    # 歷史序列會停在「最後一個有年度EPS的隔年」——年報還沒出來的年份配不到 EPS 就被丟掉,
    # 實測旺矽因為 Yahoo 缺 2025 年度EPS，序列只到 2025-12-31，但股價有到 2026-07-31。
    # 對一支現在要發的片,只講 7 個月前的本益比太舊,所以**另外**用 TTM EPS 算一個當前值。
    # ⚠️ 只並列陳述,不併進上面的百分位計算——TTM EPS 和年度 EPS 是兩把尺,混算會得出
    # 一個不存在的排名。
    cur_pe = cur_eps = None
    try:
        ttm = _num((t.info or {}).get("trailingEps"))
        last_px = _num(list(price_series.values)[-1])
        if ttm and ttm > 0 and last_px and last_px > 0:
            cur_eps, cur_pe = round(ttm, 2), round(last_px / ttm, 1)
    except Exception:  # noqa: BLE001
        pass
    cur_txt = (f"；若改用最新四季合計EPS {cur_eps} 元對最近收盤價推算，本益比約 {cur_pe} 倍"
               f"（與上面的歷史區間演算法不同，僅供對照，不併入百分位）" if cur_pe else "")
    return {
        "provider": PROVIDER,
        "years": span, "start": pe_rows[0][0], "end": latest_date,
        "latest_per": round(latest_pe, 1), "latest_date": latest_date,
        "p25": round(p25, 1), "median": round(p50, 1), "p75": round(p75, 1),
        "percentile_rank": round(rank * 100, 0),
        "latest_dividend_yield": None,
        "current_per_ttm": cur_pe, "current_eps_ttm": cur_eps,
        "summary": (f"截至{latest_date}，本益比約 {latest_pe:.1f} 倍（以前一年度EPS推算），"
                    f"位於自身近{span}年區間的第 {round(rank*100):.0f} 百分位"
                    f"（P25={p25:.1f}倍／中位數={p50:.1f}倍／P75={p75:.1f}倍）{cur_txt}"
                    f"——本片只陳述數據位置，不判斷貴或便宜、不構成買賣建議。"),
    }


def main() -> int:
    """自測:python scripts/fundamentals_yf.py 2330 6223"""
    codes = sys.argv[1:] or ["2330", "6223"]
    for code in codes:
        t, sym = resolve_ticker(code)
        print(f"=== {code} → {sym or '查無此代號'} ===")
        if t is None:
            continue
        for nm, fn in [("營收趨勢", revenue_trend), ("EPS趨勢", eps_trend), ("毛利率", gross_margin)]:
            r = fn(code)
            print(f"  {nm:<6} {r['summary'] if r else '(無資料)'}")
        r = dividend_history(code)
        print(f"  {'股利史':<6} {r['summary'] if r else '(無資料)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
