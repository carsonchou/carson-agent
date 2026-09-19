#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hidiv_showdown_facts.py — 第三旗艦數據軍火：高股息 ETF 全家族 vs 市值型全面對決。

背景（2026-07-15 任務）：「高股息還香嗎／主動式 vs 市值型」是 2025-26 台股賽道最大熱議
流量題（00940/00939/00919/00878 申購熱潮後的全民辯論），競品情報顯示所有頭部頻道都在
講感覺，沒有任何頻道用系統性回測正面對決。tw_facts_engine.py 已把主要高股息 ETF
（0056/00713/00878/00915/00918/00919/00929）算進 hidiv_vs_mktcap 系列事實（含息還原、
共同起點、CAGR/MDD），但受 MIN_YEARS=3.0 誠信硬地板限制，00934/00936/00939/00940
（2023 下半年後才上市，資料不足 3 年）在那條產線裡被排除；而且缺本任務明確要求的
兩類新視角：①配息再投入 vs 領息花掉的差距 ②配息率 vs 總報酬散佈。

本腳本做四件事（沿用 tw_facts_engine.py / tw_universe_facts.py 同一套方法論：
auto_adjust=True 含息還原、_sanitize_series 假跳空清洗、fetch/compute 兩階段分離）：
  1. 家族總表（leaderboard）：直接復用 tw_facts_engine 已算出的 hidiv_vs_mktcap
     對決（不重算），彙整成「近N年含息總報酬」排名 vs 0050／006208。
  2. 00939/00940 申購熱潮專案：資料不足 3 年不代表不能揭露——用「自上市至今」
     實際天數（誠實標註，不套 3 年門檻）對比同期 0050，回答「搶購的人現在賺還賠」。
  3. 配息再投入 vs 領息花掉：用 auto_adjust=True（含息還原＝視同配息全部再投入）
     對比 auto_adjust=False（原始股價＝視同配息全部領出花掉，只留資本利得）兩條
     序列的總報酬缺口，量化「左手領息、右手是不是真的變薄」。
  4. 配息率 vs 總報酬散佈：用 yfinance dividends 算「近12個月殖利率」，對比自
     上市至今總報酬，誠實列表＋簡單相關係數，不代入因果語氣。

誠信鐵則（同 tw_facts_engine/tw_universe_facts）：
  - _sanitize_series 清洗假跳空；含息還原一律 auto_adjust=True。
  - 抓不到／資料太短（<60 個交易日）的標的明確跳過，計入 coverage，不編造。
  - 上市不足 3 年的仍計入（申購熱潮題本來就是要看「還沒滿 3 年」的這批），但一律
    在 period/desc 裡如實標註實際年數，不偽稱「長期回測」。
  - 領息 vs 再投入的兩條序列，起訖日以「兩者資料重疊區間」對齊，避免起點不同造成假差距。

用法：
  python scripts/hidiv_showdown_facts.py --fetch      # 抓原始股價(auto_adjust=False)+配息，連網、可續跑
  python scripts/hidiv_showdown_facts.py --compute    # 只讀本地快取 + tw_facts_computed.json（不連網），
                                                          算 4 組事實，寫入 STUDIO/tw_universe_facts.json
  python scripts/hidiv_showdown_facts.py --fetch --compute --dry   # 一次做完，--dry 只印不寫

驗證：python -m py_compile scripts/hidiv_showdown_facts.py
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tw_facts_engine as tfe  # noqa: E402  復用 SYMBOLS/fetch_series(含息還原)/cagr/max_drawdown/pct/清洗邏輯

STUDIO = ROOT / "STUDIO"
OUT_FILE = STUDIO / "tw_universe_facts.json"            # 任務指定：寫進這份全市場事實庫
TW_FACTS_COMPUTED = STUDIO / "tw_facts_computed.json"    # 復用 tw_facts_engine 已算好的 hidiv_vs_mktcap 對決

RAW_CACHE_DIR = STUDIO / "tw_facts_cache_raw"             # 原始股價(auto_adjust=False)快取，獨立於含息還原快取
DIV_CACHE_DIR = STUDIO / "tw_facts_cache_div"              # 配息快取
RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DIV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_MAX_AGE_H = 20

DISCLAIMER = "歷史回測，非未來保證；不構成投資建議、不喊單、不報明牌。"
SOURCE_NOTE = ("Yahoo Finance（yfinance）；含息還原序列 auto_adjust=True，領息對照序列"
               "auto_adjust=False（原始收盤價，已扣除股利但不重新投入）；配息數字為 yfinance "
               "股利事件序列；含息還原/原始股價皆已套用與 tw_facts_engine 同一套 "
               "_sanitize_series 清洗（砍除單日 ±50% 以上疑似分割/單位淨值重編未回溯調整的假跳空）。")

HIDIV_CODES = ["0056", "00713", "00878", "00915", "00918", "00919",
               "00929", "00934", "00936", "00939", "00940"]
MKTCAP_CODES = ["0050", "006208"]
ALL_CODES = HIDIV_CODES + MKTCAP_CODES

pct = tfe.pct
cagr = tfe.cagr
max_drawdown = tfe.max_drawdown
years_span = tfe.years_span


# ── Phase A 資料層：原始股價(auto_adjust=False) + 配息 ────────────────────────
def _raw_cache_path(code: str) -> Path:
    return RAW_CACHE_DIR / f"{code}.csv"


def _div_cache_path(code: str) -> Path:
    return DIV_CACHE_DIR / f"{code}.csv"


def _load_raw_cache(code: str):
    p = _raw_cache_path(code)
    if not p.exists():
        return None
    try:
        age_h = (time.time() - p.stat().st_mtime) / 3600.0
        if age_h > CACHE_MAX_AGE_H:
            return None
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        s = df["Close"].dropna()
        return s if len(s) >= 60 else None
    except Exception:
        return None


def _load_div_cache(code: str):
    p = _div_cache_path(code)
    if not p.exists():
        return None
    try:
        age_h = (time.time() - p.stat().st_mtime) / 3600.0
        if age_h > CACHE_MAX_AGE_H:
            return None
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        return df["Dividend"].dropna()
    except Exception:
        return None


def fetch_raw_and_div(code: str, refresh: bool = False):
    """回傳 (raw_close_series 或 None, dividends_series 或 None)。原始股價=auto_adjust=False
    （已套清洗），配息=yf.Ticker(ticker).dividends（原始頻率，未清洗，配息事件本身無假跳空問題）。"""
    ticker = tfe.SYMBOLS[code]["ticker"]
    raw = None if refresh else _load_raw_cache(code)
    div = None if refresh else _load_div_cache(code)
    if raw is None:
        try:
            import yfinance as yf
            df = yf.download(ticker, period="max", auto_adjust=False, progress=False, threads=False)
            if df is not None and len(df) > 0:
                col = df["Close"]
                if hasattr(col, "columns"):
                    col = col.iloc[:, 0]
                s = col.dropna()
                s.index = pd.to_datetime(s.index)
                s = s[~s.index.duplicated(keep="last")].sort_index()
                s = tfe._sanitize_series(s)
                if s is not None and len(s) >= 60:
                    raw = s
                    s.to_frame("Close").to_csv(_raw_cache_path(code))
        except Exception as exc:  # noqa: BLE001
            print(f"[hidiv_showdown] {code} 原始股價抓取失敗（略過）：{exc}")
    if div is None:
        try:
            import yfinance as yf
            d = yf.Ticker(ticker).dividends
            if d is not None and len(d) > 0:
                d = d.copy()
                d.index = pd.to_datetime(d.index).tz_localize(None)
                d.to_frame("Dividend").to_csv(_div_cache_path(code))
                div = d
        except Exception as exc:  # noqa: BLE001
            print(f"[hidiv_showdown] {code} 配息抓取失敗（略過）：{exc}")
    return raw, div


def fetch_phase(codes, refresh: bool, sleep: float):
    print("=" * 70)
    print(f"[fetch] 高股息家族對決：原始股價(auto_adjust=False)+配息，共 {len(codes)} 檔")
    print("=" * 70)
    for i, code in enumerate(codes, 1):
        # 含息還原序列復用 tw_facts_engine 自己的快取（20h 內免重抓）
        adj = tfe.fetch_series(code, refresh=refresh)
        raw, div = fetch_raw_and_div(code, refresh=refresh)
        print(f"[{i}/{len(codes)}] {code}: 含息還原={'OK ' + str(len(adj)) + '筆' if adj is not None else '失敗'}"
              f"  原始股價={'OK ' + str(len(raw)) + '筆' if raw is not None else '失敗'}"
              f"  配息={'OK ' + str(len(div)) + '筆' if div is not None else '失敗'}")
        time.sleep(sleep)


# ── 事實 1：家族總表（leaderboard，復用 tw_facts_engine 已算好的 hidiv_vs_mktcap） ──
def build_leaderboard():
    if not TW_FACTS_COMPUTED.exists():
        print("[compute] ⚠ tw_facts_computed.json 不存在，先跑 tw_facts_engine.py")
        return None
    d = json.loads(TW_FACTS_COMPUTED.read_text(encoding="utf-8"))
    results = d.get("results", {})
    rows = []
    for key, item in results.items():
        if not key.startswith("hidiv_vs_mktcap__") or not key.endswith("_vs_0050"):
            continue
        code = key.split("__", 1)[1].split("_vs_")[0]
        data = item.get("data") or {}
        h = data.get("hidiv") or {}
        m = data.get("mktcap") or {}
        if not h or not m:
            continue
        name = tfe.SYMBOLS.get(code, {}).get("name", code)
        rows.append({
            "code": code, "name": name,
            "years": data.get("years"), "start": data.get("start"), "end": data.get("end"),
            "hidiv_total_return": round(h.get("total_return", 0.0), 4),
            "hidiv_cagr": round(h.get("cagr", 0.0), 4) if h.get("cagr") is not None else None,
            "hidiv_max_drawdown": round(h.get("max_drawdown", 0.0), 4) if h.get("max_drawdown") is not None else None,
            "bench_0050_total_return": round(m.get("total_return", 0.0), 4),
            "bench_0050_cagr": round(m.get("cagr", 0.0), 4) if m.get("cagr") is not None else None,
            "gap_vs_0050": round(m.get("total_return", 0.0) - h.get("total_return", 0.0), 4),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: -r["hidiv_total_return"])
    n = len(rows)
    n_lose = sum(1 for r in rows if r["gap_vs_0050"] > 0)
    best = rows[0]
    worst = rows[-1]
    excluded = [c for c in HIDIV_CODES if c not in {r["code"] for r in rows}]
    lines = [f"{r['name']}({r['code']}) 自{r['start']}起（{r['years']}年）含息還原總報酬 "
              f"{pct(r['hidiv_total_return'])}（同期0050 {pct(r['bench_0050_total_return'])}，"
              f"落後 {pct(r['gap_vs_0050'])}）" for r in rows]
    payload = {
        "n_family": n,
        "n_lose_to_0050": n_lose,
        "pct_lose_to_0050": round(n_lose / n * 100, 1),
        "best": {"code": best["code"], "name": best["name"], "total_return": best["hidiv_total_return"]},
        "worst": {"code": worst["code"], "name": worst["name"], "total_return": worst["hidiv_total_return"]},
        "rows": rows,
        "excluded_insufficient_data": excluded,
        "start": min(r["start"] for r in rows), "end": max(r["end"] for r in rows),
        "coverage_note": (f"納入 {n} 檔高股息ETF（各自對比0050，用兩者資料重疊期間，公平比較；"
                           f"起訖年數逐檔不同已如實標註）；{', '.join(excluded) if excluded else '無'} "
                           f"因上市未滿3年（tw_facts_engine誠信門檻）未列入本總表，另見「申購熱潮」事實。"),
        "summary": (f"{n} 檔高股息ETF vs 0050（各自用自己資料涵蓋的重疊期間比較，非統一起點）："
                    f"{n_lose}/{n}（{pct(n_lose/n)}）同期總報酬輸給0050；表現最好的是{best['name']}"
                    f"({best['code']}) {pct(best['hidiv_total_return'])}，最差的是{worst['name']}"
                    f"({worst['code']}) {pct(worst['hidiv_total_return'])}。逐檔明細："
                    + "；".join(lines)),
    }
    return payload


# ── 事實 2：00939/00940 申購熱潮專案（自上市至今，不套3年門檻，如實標註年數） ──
def _pair_since_listing(hidiv_s, mktcap_s):
    if hidiv_s is None or mktcap_s is None:
        return None
    common_start = max(hidiv_s.index[0], mktcap_s.index[0])
    h = hidiv_s[hidiv_s.index >= common_start]
    m = mktcap_s[mktcap_s.index >= common_start]
    if len(h) < 30 or len(m) < 30:
        return None
    span = (h.index[-1] - common_start).days / 365.25
    h_tr = float(h.iloc[-1]) / float(h.iloc[0]) - 1.0
    m_tr = float(m.iloc[-1]) / float(m.iloc[0]) - 1.0
    h_cagr = cagr(h.iloc[0], h.iloc[-1], span) if span > 0 else None
    m_cagr = cagr(m.iloc[0], m.iloc[-1], span) if span > 0 else None
    return {
        "years": round(span, 2), "start": str(common_start.date()), "end": str(h.index[-1].date()),
        "hidiv_total_return": round(h_tr, 4), "hidiv_cagr": round(h_cagr, 4) if h_cagr is not None else None,
        "bench_total_return": round(m_tr, 4), "bench_cagr": round(m_cagr, 4) if m_cagr is not None else None,
        "gap": round(m_tr - h_tr, 4),
    }


def build_ipo_wave():
    rows = []
    for code in ("00939", "00940"):
        adj = tfe.fetch_series(code)
        bench = tfe.fetch_series("0050")
        if adj is None or bench is None:
            continue
        r = _pair_since_listing(adj, bench)
        if r is None:
            continue
        name = tfe.SYMBOLS[code]["name"]
        currently_up = r["hidiv_total_return"] > 0
        rows.append({"code": code, "name": name, **r,
                      "currently_profitable": currently_up})
    if not rows:
        return None
    lines = []
    for r in rows:
        lines.append(f"{r['name']}({r['code']}) 自{r['start']}上市至今（{r['years']}年）含息還原總報酬 "
                      f"{pct(r['hidiv_total_return'])}（{'賺錢' if r['currently_profitable'] else '倒賠'}），"
                      f"同期0050含息還原總報酬 {pct(r['bench_total_return'])}"
                      f"（{'落後' if r['gap']>0 else '領先'} 0050 {pct(abs(r['gap']))}）")
    payload = {
        "rows": rows,
        "start": min(r["start"] for r in rows), "end": max(r["end"] for r in rows),
        "note_short_history": ("00939/00940 上市未滿3年（本項為誠信考量特別放寬 tw_facts_engine "
                                "MIN_YEARS=3.0 門檻的獨立分析，因為『申購熱潮至今賺賠』本來就是要看"
                                "這段還沒滿3年的期間；年數已如實標註，非長期回測，僅供短期參考）。"),
        "summary": "；".join(lines) + "。" + (
            "兩檔月配息熱潮ETF目前皆" + ("賺錢" if all(r["currently_profitable"] for r in rows)
                                        else ("倒賠" if not any(r["currently_profitable"] for r in rows)
                                              else "一賺一賠")) + "，但同期0050含息還原報酬"
            + ("兩檔皆落後" if all(r["gap"] > 0 for r in rows)
               else ("兩檔皆領先" if all(r["gap"] < 0 for r in rows) else "互有領先落後"))
            + "。"
        ),
    }
    return payload


# ── 事實 3：配息再投入 vs 領息花掉的差距 ──────────────────────────────────────
def build_reinvest_vs_spend():
    rows = []
    n_no_raw = 0
    for code in ALL_CODES:
        adj = tfe.fetch_series(code)
        raw = _load_raw_cache(code)
        if adj is None or raw is None:
            n_no_raw += 1
            continue
        common_start = max(adj.index[0], raw.index[0])
        common_end = min(adj.index[-1], raw.index[-1])
        a = adj[(adj.index >= common_start) & (adj.index <= common_end)]
        r = raw[(raw.index >= common_start) & (raw.index <= common_end)]
        if len(a) < 60 or len(r) < 60:
            n_no_raw += 1
            continue
        span = (a.index[-1] - a.index[0]).days / 365.25
        reinvest_tr = float(a.iloc[-1]) / float(a.iloc[0]) - 1.0    # 含息還原＝視同配息全部再投入
        spend_tr = float(r.iloc[-1]) / float(r.iloc[0]) - 1.0        # 原始股價＝視同配息全部領出花掉，只剩資本利得
        gap = reinvest_tr - spend_tr
        name = tfe.SYMBOLS[code]["name"]
        kind = tfe.SYMBOLS[code]["kind"]
        rows.append({
            "code": code, "name": name, "kind": kind,
            "years": round(span, 1), "start": str(a.index[0].date()), "end": str(a.index[-1].date()),
            "reinvest_total_return": round(reinvest_tr, 4),
            "spend_total_return": round(spend_tr, 4),
            "reinvest_vs_spend_gap": round(gap, 4),
        })
    if not rows:
        return None
    hidiv_rows = [r for r in rows if r["kind"] == "hidiv"]
    mktcap_rows = [r for r in rows if r["kind"] == "mktcap"]
    hidiv_gap_avg = float(np.mean([r["reinvest_vs_spend_gap"] for r in hidiv_rows])) if hidiv_rows else None
    mktcap_gap_avg = float(np.mean([r["reinvest_vs_spend_gap"] for r in mktcap_rows])) if mktcap_rows else None
    rows.sort(key=lambda r: -r["reinvest_vs_spend_gap"])
    lines = [f"{r['name']}({r['code']}) {r['years']}年：再投入總報酬 {pct(r['reinvest_total_return'])} "
              f"vs 領息花掉(只留資本利得) {pct(r['spend_total_return'])}，差距 {pct(r['reinvest_vs_spend_gap'])}"
             for r in rows]
    payload = {
        "rows": rows,
        "hidiv_avg_gap": round(hidiv_gap_avg, 4) if hidiv_gap_avg is not None else None,
        "mktcap_avg_gap": round(mktcap_gap_avg, 4) if mktcap_gap_avg is not None else None,
        "n_excluded_no_raw_data": n_no_raw,
        "start": min(r["start"] for r in rows), "end": max(r["end"] for r in rows),
        "method_note": ("『再投入』＝auto_adjust=True含息還原序列（配息視同當天買回）；『領息花掉』＝"
                         "auto_adjust=False原始收盤價序列（配息已從股價扣除但不重新買回，只留資本利得）；"
                         "兩序列取重疊區間比較，起訖日一致。"),
        "summary": (f"{len(hidiv_rows)}檔高股息ETF「配息再投入」平均比「領息花掉」多賺 "
                    f"{pct(hidiv_gap_avg) if hidiv_gap_avg is not None else '—'}（複利效果）；"
                    f"{len(mktcap_rows)}檔市值型ETF同一缺口平均 "
                    f"{pct(mktcap_gap_avg) if mktcap_gap_avg is not None else '—'}"
                    f"（市值型配息少，再投入/領息花掉兩條路徑差距通常較小）。逐檔明細：" + "；".join(lines)),
    }
    return payload


# ── 事實 4：配息率 vs 總報酬散佈 ───────────────────────────────────────────────
def build_payout_scatter():
    rows = []
    for code in HIDIV_CODES:
        adj = tfe.fetch_series(code)
        raw = _load_raw_cache(code)
        div = _load_div_cache(code)
        if adj is None or raw is None or div is None or len(div) == 0:
            continue
        last_date = raw.index[-1]
        cutoff = last_date - pd.Timedelta(days=365)
        ttm_div = div[(div.index > cutoff) & (div.index <= last_date)]
        if len(ttm_div) == 0:
            continue
        last_price = float(raw.iloc[-1])
        if last_price <= 0:
            continue
        ttm_yield = float(ttm_div.sum()) / last_price
        total_return_since_listing = float(adj.iloc[-1]) / float(adj.iloc[0]) - 1.0
        span = years_span(adj)
        r_cagr = cagr(adj.iloc[0], adj.iloc[-1], span) if span > 0 else None
        name = tfe.SYMBOLS[code]["name"]
        rows.append({
            "code": code, "name": name,
            "ttm_dividend_yield": round(ttm_yield, 4),
            "n_ttm_distributions": int(len(ttm_div)),
            "total_return_since_listing": round(total_return_since_listing, 4),
            "cagr_since_listing": round(r_cagr, 4) if r_cagr is not None else None,
            "years_since_listing": round(span, 1),
        })
    if len(rows) < 3:
        return None
    yields = np.array([r["ttm_dividend_yield"] for r in rows])
    trs = np.array([r["total_return_since_listing"] for r in rows])
    corr = float(np.corrcoef(yields, trs)[0, 1]) if len(rows) >= 3 else None
    by_yield = sorted(rows, key=lambda r: -r["ttm_dividend_yield"])
    by_return = sorted(rows, key=lambda r: -r["total_return_since_listing"])
    top3_yield_codes = {r["code"] for r in by_yield[:3]}
    top3_return_codes = {r["code"] for r in by_return[:3]}
    overlap = len(top3_yield_codes & top3_return_codes)
    lines = [f"{r['name']}({r['code']})：近12個月殖利率 {pct(r['ttm_dividend_yield'])}，"
              f"自上市至今含息還原總報酬 {pct(r['total_return_since_listing'])}（{r['years_since_listing']}年）"
             for r in by_yield]
    payload = {
        "rows": rows,
        "n": len(rows),
        "correlation_yield_vs_total_return": round(corr, 3) if corr is not None else None,
        "top3_yield_codes": sorted(top3_yield_codes),
        "top3_total_return_codes": sorted(top3_return_codes),
        "overlap_top3": overlap,
        "start": None, "end": str(_dt.date.today()),
        "method_note": ("近12個月殖利率＝近365天配息事件加總／目前股價（原始股價，未還原）；"
                         "總報酬為各自上市以來含息還原總報酬，年數不同已如實標註，非同期比較。"
                         "相關係數僅描述樣本內殖利率與總報酬的線性關聯方向與強弱，不代表因果。"),
        "summary": (f"{len(rows)}檔高股息ETF「近12個月殖利率」與「自上市總報酬」相關係數 "
                    f"{corr:.2f}" if corr is not None else "" ) + (
                    f"（{'正相關但不強' if corr is not None and 0 < corr < 0.5 else '負相關' if corr is not None and corr < 0 else '正相關'}，"
                    if corr is not None else "") + (
                    f"配得多不必然賺得多）；殖利率前3高（{', '.join(sorted(top3_yield_codes))}）與總報酬前3高"
                    f"（{', '.join(sorted(top3_return_codes))}）僅重疊{overlap}檔。逐檔：" + "；".join(lines)),
    }
    return payload


# ── 組裝並寫入 STUDIO/tw_universe_facts.json ─────────────────────────────────
def compute_phase(dry: bool):
    as_of = _dt.date.today().isoformat()
    if OUT_FILE.exists():
        try:
            facts = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": {}}
    else:
        facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": {}}
    facts["as_of"] = as_of
    results = facts.setdefault("results", {})

    def add(key, method, symbol_desc, desc, keywords, payload):
        if not payload:
            print(f"[compute] ⚠ {key} 算不出來（資料不足），略過不寫入（誠信：算不出就明講）")
            return
        entry = {
            "key": key, "claim": payload.get("summary", desc), "desc": desc,
            "summary": payload.get("summary", desc), "keywords": keywords,
            "method": method, "symbol": symbol_desc,
            "period": f"{payload.get('start', '?')}~{payload.get('end', '?')}",
            "source": SOURCE_NOTE, "computed_at": as_of, "disclaimer": DISCLAIMER,
            "data": payload,
        }
        results[key] = entry
        print(f"[compute] ✓ {key}")

    add("hidiv_family_showdown",
        "彙整 tw_facts_engine.hidiv_vs_mktcap 系列（含息還原、共同起點、各自資料重疊期間）成排名總表",
        "高股息ETF家族（0056/00713/00878/00915/00918/00919/00929，資料滿3年者） vs 0050",
        "高股息ETF全家族 vs 0050 含息總報酬排名總表",
        ["高股息", "市值型", "0050", "0056", "00878", "00919", "ETF", "存股", "家族對決"],
        build_leaderboard())

    add("hidiv_00939_00940_ipo_wave_vs_0050",
        "00939/00940自上市至今(不套3年門檻，如實標註實際年數)含息還原總報酬 vs 同期0050",
        "00939（統一台灣高息動能） / 00940（元大台灣價值高息） vs 0050",
        "00939/00940申購熱潮至今：搶購的人現在賺還賠",
        ["00939", "00940", "申購熱潮", "月配息", "0050", "高股息"],
        build_ipo_wave())

    add("hidiv_reinvest_vs_spend_gap",
        "含息還原(auto_adjust=True,視同配息再投入) vs 原始股價(auto_adjust=False,視同配息領出花掉)兩序列總報酬缺口，重疊期間比較",
        f"高股息ETF家族 {len(HIDIV_CODES)}檔 + 市值型 {len(MKTCAP_CODES)}檔",
        "配息再投入 vs 領息花掉，長期下來差多少",
        ["配息", "再投入", "複利", "左手領息右手", "高股息", "市值型"],
        build_reinvest_vs_spend())

    add("hidiv_payout_vs_total_return_scatter",
        "近12個月殖利率(配息事件加總/現價) vs 自上市至今含息還原總報酬，逐檔列表+簡單相關係數",
        f"高股息ETF家族 {len(HIDIV_CODES)}檔",
        "配得多是不是賺得多：殖利率 vs 總報酬散佈",
        ["殖利率", "配息率", "高股息", "總報酬", "散佈"],
        build_payout_scatter())

    n = len(results)
    print(f"[compute] tw_universe_facts.json 目前共 {n} 組事實")
    if dry:
        print("[compute] --dry：不寫檔")
        return facts
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[compute] 已寫入 {OUT_FILE}")
    return facts


def main():
    ap = argparse.ArgumentParser(description="高股息ETF家族 vs 市值型全面對決事實引擎")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--compute", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not (args.fetch or args.compute):
        print("請指定 --fetch 和/或 --compute")
        return 1
    if args.fetch:
        fetch_phase(ALL_CODES, refresh=args.refresh, sleep=args.sleep)
    if args.compute:
        compute_phase(dry=args.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
