#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tw_universe_facts.py — 【全台股全市場事實引擎】旗艦破圈片的數據軍火。

背景（2026-07-14 任務）：頻道一天量產 18 支模板短片，沒有一支是「別人抄不了」的
重磅。Carson 手上有別人沒有的武器：tw_universe_backtest.py 的全市場 universe
（twstock 上市+上櫃全股票）+ tw_data.py 的資料層方法論 + tw_facts_engine.py 的
含息還原/資料清洗（_sanitize_series）方法論。本引擎把三者接起來，算「全市場級」
的數據：

  1. 全台股（現存上市+上櫃）每一檔跑「月定期定額 10 年」→ 報酬分佈
     （中位數/最慘/最猛/幾成贏 0050）——「選股 vs 買大盤」的全樣本答案。
  2. 「飆股的下場」：每年報酬前 10 名的股票，追蹤之後 3 年的報酬分佈
     ——「追飆股後來怎樣」的全樣本答案。

誠信鐵則（同 tw_facts_engine）：
  - 用 auto_adjust=True 含息還原價（不是 tw_data.py 的原始價快取，那份是
    auto_adjust=False，給動能回測用的，不能拿來算總報酬/定期定額）。
  - 沿用 tw_facts_engine._sanitize_series 同一套「單日 ±50% 異常跳空只留最後一段
    乾淨資料」清洗邏輯（yfinance 分割/單位淨值重編未回溯的假跳空會做出假崩盤）。
  - 倖存者偏差要「明講」，不能偷偷剔除：
      (a) universe 本身＝twstock.codes 現存上市+上櫃代碼，不含已下市股票——
          這本身就是倖存者偏差第一層，任何「N 檔」的敘述都要註記。
      (b) universe 內資料不足 10 年（多半是近年才上市）的股票，DCA 分佈計算會
          排除，計入 coverage 統計、不偷偷藏起來。
      (c) 「飆股後來怎樣」的追蹤：若某檔飆股在 fwd 窗口內已下市/資料中斷，計入
          n_forward_missing，不悄悄跳過不提。

兩階段設計（讓長時間網路抓取跟本地運算分離，可中斷續跑）：
  --fetch  ：把 universe 的含息還原收盤價抓到本地快取 twdata/cache_adj/
             （已有快取檔的直接跳過 = 天然可續跑；用 --sample N 先驗證）
  --compute：只讀本地快取（不連網），算兩大類事實，寫
             youtube_channel/STUDIO/tw_universe_facts.json

用法：
  python scripts/tw_universe_facts.py --fetch --sample 50      # 小樣本抓取驗證
  python scripts/tw_universe_facts.py --compute --sample 50    # 小樣本算
  python scripts/tw_universe_facts.py --fetch --all            # 全市場抓取（可中斷續跑）
  python scripts/tw_universe_facts.py --compute --all          # 全市場運算 + 寫 JSON

驗證：python -m py_compile scripts/tw_universe_facts.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
REPO_ROOT = ROOT.parent                                  # D:\carson-agent
STUDIO = ROOT / "STUDIO"
sys.path.insert(0, str(REPO_ROOT))
import tw_data  # noqa: E402  （沿用 get_universe()；不沿用它的 load_ohlcv 快取，那份是 auto_adjust=False)

CACHE_DIR = REPO_ROOT / "twdata" / "cache_adj"           # 含息還原收盤價快取（本引擎專用，跟 tw_data 原始快取分開）
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = STUDIO / "tw_universe_facts.json"
FETCH_LOG_CSV = REPO_ROOT / "twdata" / "universe_facts_fetch_log.csv"

DISCLAIMER = "歷史回測，非未來保證；不構成投資建議、不喊單、不報明牌。"
SOURCE_NOTE = ("Yahoo Finance（yfinance, auto_adjust=True 含息還原收盤價）；"
               "已套用 _sanitize_series 清洗（砍除單日 ±50% 以上疑似分割/單位淨值重編"
               "未回溯調整的假跳空，只保留最後一次異常後的連續乾淨資料）；"
               "universe＝twstock 現存上市+上櫃股票代碼（不含已下市股票，見 coverage 揭露）")

BENCH_CODE = "0050"
BENCH_TICKER = "0050.TW"

MIN_YEARS_DCA = 10.0
FWD_YEARS = 3
ELIGIBLE_MIN_STOCKS = 200   # 該年至少要有這麼多檔「有效年報酬」樣本，才拿來選 Top10（樣本太小的年份不具全市場代表性）

# ── 資料清洗：跟 tw_facts_engine._sanitize_series 完全同一套邏輯（見該檔案註解）──
_ANOMALY_RATIO_HI = 1.5
_ANOMALY_RATIO_LO = 1.0 / 1.5


def sanitize_series(s):
    if s is None or len(s) < 5:
        return s
    ratio = s / s.shift(1)
    bad = ratio[(ratio > _ANOMALY_RATIO_HI) | (ratio < _ANOMALY_RATIO_LO)]
    if len(bad) == 0:
        return s
    last_bad_date = bad.index.max()
    cleaned = s[s.index > last_bad_date]
    if len(cleaned) < 60:
        return cleaned
    return cleaned


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.replace('.', '_')}.csv"


def load_cached_series(ticker: str):
    """只讀本地快取，不連網。回傳原始（未 sanitize）Series 或 None。"""
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        s = df["Close"].dropna()
        if len(s) < 60:
            return None
        return s
    except Exception:
        return None


def download_adj_series(ticker: str, sleep: float = 0.4, max_retries: int = 1):
    """打 yfinance 抓含息還原收盤價，成功則存快取（存「原始未清洗」資料，清洗邏輯
    留到 compute 階段做，方便日後迭代清洗規則不必重抓）。回傳 Series 或 None。"""
    import yfinance as yf
    df = None
    for attempt in range(max_retries + 1):
        try:
            raw = yf.download(ticker, period="max", auto_adjust=True,
                               progress=False, threads=False)
            if raw is not None and len(raw) > 0:
                df = raw
                break
        except Exception:
            df = None
        if attempt < max_retries:
            time.sleep(sleep * (attempt + 1))
    if df is None or len(df) == 0:
        return None
    col = df["Close"]
    if hasattr(col, "columns"):
        col = col.iloc[:, 0]
    s = col.dropna()
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if len(s) < 60:
        return None
    try:
        s.to_frame("Close").to_csv(_cache_path(ticker))
    except Exception:
        pass
    return s


def years_span(s):
    return (s.index[-1] - s.index[0]).days / 365.25


def slice_trailing(s, years):
    cutoff = s.index[-1] - _dt.timedelta(days=int(years * 365.25))
    return s[s.index >= cutoff]


# ── 事實類型 1：定期定額 N 年總報酬（單一標的，供全市場分佈用）─────────────────
def dca_total_return(s, years=MIN_YEARS_DCA):
    """回傳 dict(total_return/start/end/months) 或 None（資料不足 N 年）。"""
    if s is None:
        return None
    sub = slice_trailing(s, years)
    if len(sub) < 60:
        return None
    span = years_span(sub)
    if span < years * 0.95:      # 要求接近完整 N 年（容許 5% 假日/停牌落差）
        return None
    monthly = sub.resample("MS").first().dropna()
    if len(monthly) < years * 12 * 0.9:
        return None
    shares, invested = 0.0, 0.0
    for px in monthly:
        px = float(px)
        if px <= 0:
            continue
        shares += 1.0 / px
        invested += 1.0
    if invested <= 0:
        return None
    final_val = shares * float(sub.iloc[-1])
    tr = final_val / invested - 1.0
    return {"total_return": tr, "start": str(sub.index[0].date()),
            "end": str(sub.index[-1].date()), "months": int(len(monthly))}


# ── 事實類型 2：年度收盤（供「飆股下場」用）───────────────────────────────────
def annual_closes(s):
    """回傳 {year(int): close(float)}，每年取該年最後一個交易日收盤。"""
    y = s.resample("YE").last().dropna()
    out = {}
    for idx, v in y.items():
        out[int(idx.year)] = float(v)
    return out


def pct(x, digits=1):
    if x is None:
        return "—"
    try:
        return f"{x * 100:.{digits}f}%"
    except Exception:
        return "—"


# ── Phase A：抓取（可中斷續跑；已有快取檔的直接跳過）──────────────────────────
def fetch_phase(targets, refresh: bool, sleep: float):
    print("=" * 70)
    print(f"[fetch] 本次目標 {len(targets)} 檔（含息還原收盤價，auto_adjust=True）")
    print(f"[fetch] 快取目錄: {CACHE_DIR}")
    print("=" * 70)
    n_ok = n_fail = n_skip_cached = 0
    t0 = time.time()
    log_rows = []

    # 基準 0050 是 ETF，tw_data.get_universe() 只列「股票」type 不含它，
    # universe/targets 裡永遠不會出現 0050 —— 這裡強制單獨確保基準已快取，
    # 否則 compute_phase 對比 0050 的所有事實都會失敗。
    if refresh or not _cache_path(BENCH_TICKER).exists():
        print(f"[fetch] 基準 {BENCH_TICKER}（不在 universe 內，單獨確保快取）...")
        bs = download_adj_series(BENCH_TICKER, sleep=sleep)
        if bs is None:
            print(f"[fetch] ⚠ 基準 {BENCH_TICKER} 抓取失敗！後續 compute 會中止，請重試 --fetch")
        else:
            print(f"[fetch] 基準 {BENCH_TICKER} OK {len(bs)} 筆 {bs.index[0].date()}~{bs.index[-1].date()}")
        time.sleep(sleep)
    for k, (code, ticker, market, name) in enumerate(targets, 1):
        p = _cache_path(ticker)
        if not refresh and p.exists():
            n_skip_cached += 1
            continue
        s = download_adj_series(ticker, sleep=sleep)
        if s is None:
            n_fail += 1
            print(f"[{k}/{len(targets)}] {code} {ticker} 抓取失敗（略過，計入 n_fail）")
            log_rows.append({"code": code, "ticker": ticker, "status": "fail"})
        else:
            n_ok += 1
            print(f"[{k}/{len(targets)}] {code} {ticker} OK {len(s)} 筆 "
                  f"{s.index[0].date()}~{s.index[-1].date()}")
            log_rows.append({"code": code, "ticker": ticker, "status": "ok",
                             "bars": len(s), "start": str(s.index[0].date()),
                             "end": str(s.index[-1].date())})
        time.sleep(sleep)
        if (n_ok + n_fail) % 50 == 0 and log_rows:
            pd.DataFrame(log_rows).to_csv(FETCH_LOG_CSV, index=False, mode="a",
                                          header=not FETCH_LOG_CSV.exists())
            log_rows = []
    if log_rows:
        pd.DataFrame(log_rows).to_csv(FETCH_LOG_CSV, index=False, mode="a",
                                      header=not FETCH_LOG_CSV.exists())
    dt_ = time.time() - t0
    print("-" * 70)
    print(f"[fetch] 完成：新抓成功 {n_ok}、失敗 {n_fail}、已有快取跳過 {n_skip_cached}，"
          f"耗時 {dt_:.0f}s")
    n_cached_total = sum(1 for (_, tk, _, _) in targets if _cache_path(tk).exists())
    print(f"[fetch] 目前本次 targets 中共 {n_cached_total}/{len(targets)} 檔已有快取可供 --compute 使用")


# ── Phase B：運算（只讀本地快取，不連網）──────────────────────────────────────
def compute_phase(universe, min_years_dca=MIN_YEARS_DCA, fwd_years=FWD_YEARS,
                   eligible_min_stocks=ELIGIBLE_MIN_STOCKS):
    as_of = _dt.date.today().isoformat()
    n_universe = len(universe)
    n_no_cache = 0
    n_sanitize_dropped = 0
    n_have_clean = 0
    n_dca_ok = 0
    n_dca_too_short = 0

    dca_rows = []                 # 全市場 DCA 10 年分佈
    per_stock_yearly = {}         # code -> {"y": {year:close}, "name":..., "market":...}

    for code, ticker, market, name in universe:
        raw = load_cached_series(ticker)
        if raw is None:
            n_no_cache += 1
            continue
        s = sanitize_series(raw)
        if s is None or len(s) < 60:
            n_sanitize_dropped += 1
            continue
        n_have_clean += 1

        r = dca_total_return(s, min_years_dca)
        if r is None:
            n_dca_too_short += 1
        else:
            n_dca_ok += 1
            dca_rows.append({"code": code, "name": name, "market": market, **r})

        y = annual_closes(s)
        if len(y) >= 3:
            first_year = min(y.keys())
            per_stock_yearly[code] = {"y": y, "name": name, "market": market,
                                       "first_year": first_year}

    print("=" * 70)
    print(f"[compute] universe={n_universe}  無快取={n_no_cache}  "
          f"清洗後太短剔除={n_sanitize_dropped}  乾淨可用={n_have_clean}")
    print(f"[compute] DCA{min_years_dca:.0f}年 可算={n_dca_ok}  資料不足10年剔除={n_dca_too_short}")

    # ── 基準：0050 ──────────────────────────────────────────────────────────
    bench_raw = load_cached_series(BENCH_TICKER)
    if bench_raw is None:
        print(f"[compute] ⚠ 基準 {BENCH_TICKER} 無快取，無法做對比類事實，中止")
        return None
    bench_s = sanitize_series(bench_raw)
    bench_dca = dca_total_return(bench_s, min_years_dca)
    bench_y = annual_closes(bench_s)
    if bench_dca is None:
        print("[compute] ⚠ 0050 DCA 10年計算失敗，中止")
        return None

    facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": {}}
    results = facts["results"]

    def add(key, method, symbol_desc, desc, keywords, payload, source=SOURCE_NOTE):
        if not payload:
            return
        entry = {
            "key": key,
            "claim": payload.get("summary", desc),
            "desc": desc,
            "summary": payload.get("summary", desc),
            "keywords": keywords,
            "method": method,
            "symbol": symbol_desc,
            "period": f"{payload.get('start', '?')}~{payload.get('end', '?')}",
            "source": source,
            "computed_at": as_of,
            "disclaimer": DISCLAIMER,
            "data": payload,
        }
        results[key] = entry

    # ═══ 事實類型 1：全市場 DCA 10 年報酬分佈 vs 0050 ═══════════════════════
    if dca_rows:
        trs = np.array([r["total_return"] for r in dca_rows], dtype=float)
        n = len(trs)
        bench_tr = bench_dca["total_return"]
        n_beat_bench = int((trs > bench_tr).sum())
        n_loss = int((trs <= 0).sum())
        n_profit = int((trs > 0).sum())
        ranked = sorted(dca_rows, key=lambda r: r["total_return"])
        worst = ranked[0]
        best = ranked[-1]
        bins = [(-1.01, -0.5), (-0.5, -0.2), (-0.2, 0.0), (0.0, 0.2),
                (0.2, 0.5), (0.5, 1.0), (1.0, 1e9)]
        bin_labels = ["< -50%", "-50~-20%", "-20~0%", "0~20%", "20~50%", "50~100%", "> 100%"]
        dist = []
        for (lo, hi), lab in zip(bins, bin_labels):
            cnt = int(((trs > lo) & (trs <= hi)).sum())
            dist.append({"range": lab, "count": cnt, "pct": round(cnt / n * 100, 1)})

        payload = {
            "n_universe": n_universe,
            "n_computed": n,
            "n_beat_bench_0050": n_beat_bench,
            "pct_beat_bench_0050": round(n_beat_bench / n * 100, 1),
            "pct_lose_bench_0050": round((n - n_beat_bench) / n * 100, 1),
            "n_profitable": n_profit,
            "pct_profitable": round(n_profit / n * 100, 1),
            "n_loss": n_loss,
            "pct_loss": round(n_loss / n * 100, 1),
            "median_total_return": round(float(np.median(trs)), 4),
            "mean_total_return": round(float(np.mean(trs)), 4),
            "worst": {"code": worst["code"], "name": worst["name"],
                      "total_return": round(worst["total_return"], 4)},
            "best": {"code": best["code"], "name": best["name"],
                     "total_return": round(best["total_return"], 4)},
            "bench_0050_total_return": round(bench_tr, 4),
            "distribution": dist,
            "start": min(r["start"] for r in dca_rows),
            "end": max(r["end"] for r in dca_rows),
            "coverage_note": (f"universe {n_universe} 檔（twstock 現存上市+上櫃，不含已下市股票"
                               f"＝倖存者偏差第一層）；無本地快取 {n_no_cache} 檔、"
                               f"資料清洗後太短剔除 {n_sanitize_dropped} 檔、"
                               f"資料不足10年剔除 {n_dca_too_short} 檔；"
                               f"實際完成月定期定額10年計算 {n} 檔（覆蓋率 "
                               f"{n / n_universe * 100:.1f}%）。"),
            "summary": (f"全市場現存 {n_universe} 檔股票中，實際算出「月定期定額10年報酬」的有 {n} 檔"
                        f"（其餘因資料不足10年/清洗剔除/無快取而排除，覆蓋率 {n / n_universe * 100:.1f}%）。"
                        f"這 {n} 檔裡，只有 {pct(n_beat_bench / n)} 的股票10年定期定額報酬贏過0050"
                        f"（0050同期定期定額報酬 {pct(bench_tr)}）；中位數報酬 {pct(float(np.median(trs)))}，"
                        f"平均 {pct(float(np.mean(trs)))}；有 {pct(n_loss / n)} 的股票10年後定期定額還是賠錢；"
                        f"最慘的是 {worst['name']}（{worst['code']}） {pct(worst['total_return'])}，"
                        f"最猛的是 {best['name']}（{best['code']}）{pct(best['total_return'])}。"),
        }
        add("universe_dca_10y_distribution",
            "全市場（現存上市+上櫃）逐檔跑月定期定額10年（每月扣款1單位，含息還原價），"
            "彙整報酬分佈並與0050同法定期定額對比",
            f"全市場 {n} 檔 vs 0050（{BENCH_CODE}）",
            "全台股定期定額10年，報酬輸贏0050的全樣本分佈",
            ["定期定額", "全市場", "0050", "分佈", "選股 vs 大盤", "倖存者偏差"],
            payload)

    # ═══ 事實類型 2：飆股的下場（每年前10名之後3年報酬）═══════════════════════
    # 只納入「yr本身已是完整年」且「yr+fwd_years也已是完整年」的年度：今年(進行中)
    # 或 forward窗口還沒走完的年度，不是「下市/資料中斷」，是「未來還沒發生」，
    # 兩者意義不同不能混在同一個 n_forward_missing 裡，用年份上限直接排除掉。
    last_complete_year = _dt.date.today().year - 1
    all_years = sorted({yr for v in per_stock_yearly.values() for yr in v["y"].keys()
                        if yr <= last_complete_year and yr + fwd_years <= last_complete_year})
    year_top10 = {}
    n_years_eligible = 0
    for yr in all_years:
        rets = []
        for code, v in per_stock_yearly.items():
            y = v["y"]
            first_year = v["first_year"]
            # 排除用第一個(可能是IPO當年、非完整年)資料當基準年，避免假報酬
            if (yr - 1) in y and yr in y and (yr - 1) > first_year:
                rets.append((code, y[yr] / y[yr - 1] - 1.0))
        if len(rets) < eligible_min_stocks:
            continue
        n_years_eligible += 1
        ranked = sorted(rets, key=lambda x: x[1], reverse=True)
        top10 = ranked[:10]
        rows = []
        n_missing = 0
        for code, ret in top10:
            v = per_stock_yearly[code]
            y = v["y"]
            if (yr + fwd_years) in y:
                fwd = y[yr + fwd_years] / y[yr] - 1.0
            else:
                fwd = None
                n_missing += 1
            rows.append({"code": code, "name": v["name"], "year_return": round(ret, 4),
                         "fwd3y_return": None if fwd is None else round(fwd, 4)})
        # 同期大盤(0050) 3年後報酬供對照
        bench_fwd = None
        if yr in bench_y and (yr + fwd_years) in bench_y:
            bench_fwd = bench_y[yr + fwd_years] / bench_y[yr] - 1.0
        year_top10[yr] = {"n_sample": len(rets), "top10": rows,
                          "n_forward_missing": n_missing, "bench_fwd_return": bench_fwd}

    if year_top10:
        all_fwd = [r["fwd3y_return"] for v in year_top10.values() for r in v["top10"]
                   if r["fwd3y_return"] is not None]
        n_total_picks = sum(len(v["top10"]) for v in year_top10.values())
        n_missing_total = sum(v["n_forward_missing"] for v in year_top10.values())
        arr = np.array(all_fwd, dtype=float)
        n_fwd = len(arr)
        n_fwd_neg = int((arr < 0).sum())
        bench_fwds = [v["bench_fwd_return"] for v in year_top10.values()
                      if v["bench_fwd_return"] is not None]
        bench_fwd_median = float(np.median(bench_fwds)) if bench_fwds else None
        yrs_covered = sorted(year_top10.keys())

        payload = {
            "years_covered": yrs_covered,
            "n_years_eligible": n_years_eligible,
            "eligible_min_stocks_per_year": eligible_min_stocks,
            "n_total_picks": n_total_picks,
            "n_forward_computed": n_fwd,
            "n_forward_missing_delisted_or_gap": n_missing_total,
            "pct_forward_missing": round(n_missing_total / n_total_picks * 100, 1) if n_total_picks else None,
            "median_fwd3y_return": round(float(np.median(arr)), 4) if n_fwd else None,
            "mean_fwd3y_return": round(float(np.mean(arr)), 4) if n_fwd else None,
            "pct_negative_fwd3y": round(n_fwd_neg / n_fwd * 100, 1) if n_fwd else None,
            "worst_fwd3y": round(float(arr.min()), 4) if n_fwd else None,
            "best_fwd3y": round(float(arr.max()), 4) if n_fwd else None,
            "bench_0050_median_fwd3y_return": round(bench_fwd_median, 4) if bench_fwd_median is not None else None,
            "by_year": year_top10,
            "start": f"{yrs_covered[0]}" if yrs_covered else None,
            "end": f"{yrs_covered[-1]}" if yrs_covered else None,
            "coverage_note": ("universe 僅含現存上市+上櫃股票（不含已下市），故本統計結構性排除了"
                               "「飆漲後下市/下櫃/資料中斷」的個股（真實情況只會更慘，這是倖存者偏差"
                               "第二層）；n_forward_missing_delisted_or_gap 是「入選Top10但3年後在"
                               "現存universe中查無資料」的次數（可能真的下市，也可能資料中斷，"
                               "本引擎無法細分兩者，一併揭露）。"),
            "summary": (f"{yrs_covered[0]}~{yrs_covered[-1]} 共 {n_years_eligible} 個年度、每年報酬前10名"
                        f"（該年至少 {eligible_min_stocks} 檔樣本才採計），共 {n_total_picks} 檔次入選，"
                        f"其中 {n_fwd} 檔次能算出「之後3年」報酬：中位數 {pct(float(np.median(arr))) if n_fwd else '—'}，"
                        f"有 {pct(n_fwd_neg / n_fwd) if n_fwd else '—'} 之後3年是虧損收場；"
                        f"同期0050中位數3年報酬 {pct(bench_fwd_median) if bench_fwd_median is not None else '—'}；"
                        f"另有 {n_missing_total} 檔次（{pct(n_missing_total / n_total_picks) if n_total_picks else '—'}）"
                        f"3年後在現存universe查無資料（疑似下市/下櫃，因倖存者偏差未列入報酬統計，"
                        f"真實下場可能更差）。"),
        }
        add("universe_chase_top10_forward3y",
            "全市場逐年報酬排名，取每年前10名，追蹤該股之後3年報酬（含息還原價年收盤對年收盤）",
            f"全市場每年Top10 → 後續{fwd_years}年（{yrs_covered[0]}~{yrs_covered[-1]}）",
            "追高飆股的人，後來怎麼了（全樣本）",
            ["飆股", "追高", "Top10", "動能", "全市場", "倖存者偏差"],
            payload)

    n_facts = len(results)
    print(f"[compute] 共產出 {n_facts} 組全市場事實")
    return facts


def build_symbol_list(args, universe):
    by_code = {u[0]: u for u in universe}
    if args.symbols:
        codes = [s.strip() for s in args.symbols.split(",") if s.strip()]
        return [by_code[c] for c in codes if c in by_code]
    if args.sample:
        # 確保 0050（基準）永遠在樣本內
        pri = [by_code[c] for c in (BENCH_CODE,) if c in by_code]
        rest = [u for u in universe if u[0] != BENCH_CODE]
        return (pri + rest)[: args.sample]
    return universe


def main():
    ap = argparse.ArgumentParser(description="全台股全市場事實引擎")
    ap.add_argument("--fetch", action="store_true", help="抓取階段（連網，可中斷續跑）")
    ap.add_argument("--compute", action="store_true", help="運算階段（只讀本地快取，不連網）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, metavar="N", help="只處理 N 檔（驗證用）")
    g.add_argument("--symbols", type=str, help="逗號分隔代碼")
    g.add_argument("--all", action="store_true", help="全市場")
    ap.add_argument("--refresh", action="store_true", help="fetch: 忽略本地快取重抓")
    ap.add_argument("--sleep", type=float, default=0.4, help="fetch: 下載間隔秒")
    ap.add_argument("--dry", action="store_true", help="compute: 只印不寫檔")
    ap.add_argument("--eligible-min", type=int, default=ELIGIBLE_MIN_STOCKS,
                    help="compute: 事實2每年最少樣本數才採計Top10（驗證小樣本時可調低）")
    ap.add_argument("--min-years-dca", type=float, default=MIN_YEARS_DCA,
                    help="compute: 事實1定期定額年數門檻")
    args = ap.parse_args()

    if not (args.fetch or args.compute):
        print("請指定 --fetch 和/或 --compute")
        return 1
    if not (args.sample or args.symbols or args.all):
        args.sample = 50
        print("未指定範圍，預設 --sample 50")

    universe = tw_data.get_universe()
    print(f"[main] universe（twstock 現存上市+上櫃股票）: {len(universe)} 檔")
    targets = build_symbol_list(args, universe)
    print(f"[main] 本次目標: {len(targets)} 檔")

    if args.fetch:
        fetch_phase(targets, refresh=args.refresh, sleep=args.sleep)

    if args.compute:
        facts = compute_phase(targets if (args.sample or args.symbols) else universe,
                               min_years_dca=args.min_years_dca,
                               eligible_min_stocks=args.eligible_min)
        if facts is None:
            return 1
        if args.dry:
            print("[compute] --dry：不寫檔")
            print(json.dumps(facts, ensure_ascii=False, indent=2)[:4000])
            return 0
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[compute] 已寫入 {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
