#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tw_stock_data.py — 【台股真回測數據引擎】讓台股影片用真數字、不是 LLM 嘴砲。

抓台股歷史（0050/006208/0056/00878/00929/^TWII 大盤，及少數權值如 2330），
算「真回測」寫進 STUDIO/tw_stock_facts.json，供 produce_batch 寫台股腳本時注入實證數字。

算三類對比（有數據就算，算不出的略過/標 null）：
  ①一次 All in vs 定期定額（近 10/20 年 總報酬%、年化%、最大回撤%）
  ②大盤長抱 vs 簡單擇時（跌破年線/200 日均線出場）
  ③高股息（0056/00878）vs 市值型（0050）近 N 年報酬對比

★誠信鐵則（最高優先）：twstock/yfinance 缺、抓不到、算不出 → 該項略過或標 null，
  **絕不編造精確數字**。整支包 try，失敗寫空/保留舊檔不崩。每筆帶 as_of + 「歷史回測，非未來保證」註記。

用法：
  python scripts/tw_stock_data.py          # 跑全部並寫檔
  python scripts/tw_stock_data.py --dry     # 只印不寫
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "STUDIO" / "tw_stock_facts.json"

DISCLAIMER = "歷史回測，非未來保證；不構成投資建議、不喊單、不報明牌。"

# 標的（皆為上市 TWSE ETF/指數/權值股，yfinance 抓得到；上櫃另議故不放）
TW_MARKET = "^TWII"        # 加權指數（大盤）
ETF_MKTCAP = "0050.TW"     # 市值型
ETF_MKTCAP2 = "006208.TW"  # 市值型（富邦台50）
ETF_HIDIV = "0056.TW"      # 高股息
ETF_HIDIV2 = "00878.TW"    # 高股息（國泰永續高股息）
BLUECHIP = "2330.TW"       # 護國神山（權值代表，僅供分析非喊單）


def _has_pkgs():
    """回傳 (yfinance, pandas) 模組或 (None, None)。缺套件優雅回 None。"""
    try:
        import pandas as pd  # noqa: F401
        import yfinance as yf  # noqa: F401
        return yf, pd
    except Exception:  # noqa: BLE001
        return None, None


def _fetch_close(yf, pd, ticker, years):
    """抓 ticker 近 years 年『還原（含息）收盤』日線 Series；抓不到回 None。"""
    try:
        end = _dt.date.today()
        start = end - _dt.timedelta(days=int(years * 366) + 10)
        df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                         auto_adjust=True, progress=False, threads=False)
        if df is None or len(df) == 0:
            return None
        col = df["Close"]
        # 多層欄位（yfinance 新版可能回 MultiIndex）取單一 ticker 欄
        if hasattr(col, "columns"):
            col = col.iloc[:, 0]
        s = col.dropna()
        if len(s) < 60:  # 資料太少不可信，略過
            return None
        return s
    except Exception:  # noqa: BLE001
        return None


def _cagr(start_val, end_val, years):
    try:
        if start_val <= 0 or end_val <= 0 or years <= 0:
            return None
        return (float(end_val) / float(start_val)) ** (1.0 / years) - 1.0
    except Exception:  # noqa: BLE001
        return None


def _max_drawdown(series):
    """最大回撤（峰到谷最大跌幅，回負值 %）。series 為 pandas Series 或 list。"""
    try:
        peak = None
        mdd = 0.0
        for v in list(series):
            v = float(v)
            if peak is None or v > peak:
                peak = v
            if peak and peak > 0:
                dd = (v - peak) / peak
                if dd < mdd:
                    mdd = dd
        return mdd
    except Exception:  # noqa: BLE001
        return None


def _pct(x, digits=1):
    """把小數轉成百分數字串（0.53 → '53.0%'）；None → '—'。"""
    if x is None:
        return "—"
    try:
        return f"{x * 100:.{digits}f}%"
    except Exception:  # noqa: BLE001
        return "—"


def _allin_vs_dca(pd, close, years):
    """一次 All in vs 每月定期定額。回 dict（total_return/cagr/mdd 各兩組）或 None。"""
    try:
        s = close.copy()
        if len(s) < 60:
            return None
        y0 = s.iloc[0]
        y1 = s.iloc[-1]
        span = (s.index[-1] - s.index[0]).days / 365.25
        if span <= 0:
            return None
        # All in：期初一次投入
        allin_tr = float(y1) / float(y0) - 1.0
        allin_cagr = _cagr(y0, y1, span)
        allin_mdd = _max_drawdown(s)
        # 定期定額：每月第一個交易日投 1 單位金額，累積股數
        monthly = s.resample("MS").first().dropna()
        if len(monthly) < 6:
            return None
        shares = 0.0
        invested = 0.0
        equity = []  # 每月市值曲線（供回撤）
        for px in monthly:
            px = float(px)
            if px <= 0:
                continue
            shares += 1.0 / px  # 每月固定金額 1，買到 1/px 股
            invested += 1.0
            equity.append(shares * px)
        if invested <= 0 or not equity:
            return None
        final_val = shares * float(monthly.iloc[-1])
        dca_tr = final_val / invested - 1.0
        dca_cagr = _cagr(1.0, final_val / invested, span)  # 以倍數近似年化
        dca_mdd = _max_drawdown(equity)
        summary = (
            f"一次All in總報酬 {_pct(allin_tr)}（年化 {_pct(allin_cagr)}、最慘賠 {_pct(allin_mdd)}）；"
            f"每月定期定額總報酬 {_pct(dca_tr)}（年化 {_pct(dca_cagr)}、最慘賠 {_pct(dca_mdd)}）")
        return {
            "allin": {"total_return": allin_tr, "cagr": allin_cagr, "max_drawdown": allin_mdd},
            "dca": {"total_return": dca_tr, "cagr": dca_cagr, "max_drawdown": dca_mdd},
            "years": round(span, 1),
            "summary": summary,
        }
    except Exception:  # noqa: BLE001
        return None


def _buyhold_vs_timing(pd, close):
    """大盤長抱 vs 簡單擇時（收盤跌破 200 日均線出場、站回進場）。回 dict 或 None。"""
    try:
        s = close.copy()
        if len(s) < 250:
            return None
        ma = s.rolling(200).mean()
        span = (s.index[-1] - s.index[0]).days / 365.25
        if span <= 0:
            return None
        # 長抱
        bh_cagr = _cagr(s.iloc[0], s.iloc[-1], span)
        bh_mdd = _max_drawdown(s)
        # 擇時：在市時吃當日報酬，出場時報酬 0（不做空、不計成本簡化，僅示意擇時代價）
        rets = s.pct_change().fillna(0.0)
        in_mkt = (s.shift(1) > ma.shift(1)).fillna(False)  # 昨收站上年線 → 今日在市（避前視）
        equity = [1.0]
        for i in range(1, len(s)):
            r = float(rets.iloc[i]) if bool(in_mkt.iloc[i]) else 0.0
            equity.append(equity[-1] * (1.0 + r))
        timing_end = equity[-1]
        timing_cagr = _cagr(1.0, timing_end, span)
        timing_mdd = _max_drawdown(equity)
        summary = (
            f"大盤長抱不動年化 {_pct(bh_cagr)}（最慘賠 {_pct(bh_mdd)}）；"
            f"跌破年線就跑的簡單擇時年化 {_pct(timing_cagr)}（最慘賠 {_pct(timing_mdd)}）")
        return {
            "buy_hold": {"cagr": bh_cagr, "max_drawdown": bh_mdd},
            "timing_200ma": {"cagr": timing_cagr, "max_drawdown": timing_mdd},
            "years": round(span, 1),
            "summary": summary,
        }
    except Exception:  # noqa: BLE001
        return None


def _hidiv_vs_mktcap(pd, hidiv_close, mktcap_close, hidiv_name, mktcap_name):
    """高股息 vs 市值型 近 N 年總報酬（含息還原）對比。回 dict 或 None。"""
    try:
        if hidiv_close is None or mktcap_close is None:
            return None
        # 對齊共同起點（取兩者都有資料的起始日）
        common_start = max(hidiv_close.index[0], mktcap_close.index[0])
        h = hidiv_close[hidiv_close.index >= common_start]
        m = mktcap_close[mktcap_close.index >= common_start]
        if len(h) < 60 or len(m) < 60:
            return None
        span = (h.index[-1] - common_start).days / 365.25
        if span <= 0:
            return None
        h_tr = float(h.iloc[-1]) / float(h.iloc[0]) - 1.0
        m_tr = float(m.iloc[-1]) / float(m.iloc[0]) - 1.0
        h_cagr = _cagr(h.iloc[0], h.iloc[-1], span)
        m_cagr = _cagr(m.iloc[0], m.iloc[-1], span)
        summary = (
            f"近 {round(span, 1)} 年含息還原：高股息 {hidiv_name} 總報酬 {_pct(h_tr)}（年化 {_pct(h_cagr)}）"
            f" vs 市值型 {mktcap_name} 總報酬 {_pct(m_tr)}（年化 {_pct(m_cagr)}）")
        return {
            "hidiv": {"ticker": hidiv_name, "total_return": h_tr, "cagr": h_cagr},
            "mktcap": {"ticker": mktcap_name, "total_return": m_tr, "cagr": m_cagr},
            "years": round(span, 1),
            "summary": summary,
        }
    except Exception:  # noqa: BLE001
        return None


def build_facts():
    """算全部回測，回 facts dict。任何一項失敗只略過該項，不影響其他項。"""
    yf, pd = _has_pkgs()
    as_of = _dt.date.today().isoformat()
    facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": {}}
    if yf is None:
        facts["note"] = "yfinance/pandas 未安裝，未算任何真回測（不編造數字）。"
        return facts, False

    results = facts["results"]

    # 抓資料（各自 try，抓不到就 None）
    twii_20 = _fetch_close(yf, pd, TW_MARKET, 20)
    twii_10 = _fetch_close(yf, pd, TW_MARKET, 10)
    e0050_20 = _fetch_close(yf, pd, ETF_MKTCAP, 20)
    e0050_10 = _fetch_close(yf, pd, ETF_MKTCAP, 10)
    e0056 = _fetch_close(yf, pd, ETF_HIDIV, 10)
    e00878 = _fetch_close(yf, pd, ETF_HIDIV2, 10)

    # ① All in vs 定投（0050 近10年、大盤近20年）
    if e0050_10 is not None:
        r = _allin_vs_dca(pd, e0050_10, 10)
        if r:
            results["allin_vs_dca_0050_10y"] = {
                "desc": "0050 近10年 一次All in vs 每月定期定額",
                "summary": r["summary"], "keywords": ["定投", "定期定額", "All in", "0050", "微笑曲線"],
                "data": r,
            }
    if twii_20 is not None:
        r = _allin_vs_dca(pd, twii_20, 20)
        if r:
            results["allin_vs_dca_twii_20y"] = {
                "desc": "加權大盤 近20年 一次All in vs 每月定期定額",
                "summary": r["summary"], "keywords": ["定投", "定期定額", "All in", "大盤", "加權"],
                "data": r,
            }

    # ② 大盤長抱 vs 簡單擇時（跌破年線出場）
    twii_for_timing = twii_20 if twii_20 is not None else twii_10
    if twii_for_timing is not None:
        r = _buyhold_vs_timing(pd, twii_for_timing)
        if r:
            results["buyhold_vs_timing_twii"] = {
                "desc": "大盤 長抱不動 vs 跌破年線就跑的簡單擇時",
                "summary": r["summary"], "keywords": ["大盤", "擇時", "長抱", "年線", "加權"],
                "data": r,
            }

    # ③ 高股息 vs 市值型
    mktcap_ref = e0050_10 if e0050_10 is not None else e0050_20
    if e0056 is not None and mktcap_ref is not None:
        r = _hidiv_vs_mktcap(pd, e0056, mktcap_ref, "0056", "0050")
        if r:
            results["hidiv_0056_vs_0050"] = {
                "desc": "高股息 0056 vs 市值型 0050（含息還原）",
                "summary": r["summary"], "keywords": ["高股息", "市值型", "0056", "0050", "存股", "ETF"],
                "data": r,
            }
    if e00878 is not None and mktcap_ref is not None:
        r = _hidiv_vs_mktcap(pd, e00878, mktcap_ref, "00878", "0050")
        if r:
            results["hidiv_00878_vs_0050"] = {
                "desc": "高股息 00878 vs 市值型 0050（含息還原）",
                "summary": r["summary"], "keywords": ["高股息", "市值型", "00878", "0050", "存股", "ETF"],
                "data": r,
            }

    ok = len(results) > 0
    if not ok:
        facts["note"] = "有套件但所有標的都抓不到/算不出，未寫入任何數字（不編造）。"
    return facts, ok


def main():
    ap = argparse.ArgumentParser(description="台股真回測數據引擎")
    ap.add_argument("--dry", action="store_true", help="只印不寫檔")
    args = ap.parse_args()

    try:
        facts, ok = build_facts()
    except Exception as e:  # noqa: BLE001  最外層防呆：整支失敗也不崩、不動舊檔
        print(f"[tw_stock_data] 建構失敗，保留舊檔不動：{e}")
        return 1

    n = len(facts.get("results", {}))
    print(f"[tw_stock_data] as_of={facts['as_of']} 算出 {n} 項回測")
    for k, v in facts.get("results", {}).items():
        print(f"  · [{k}] {v.get('desc', '')}")
        print(f"      {v.get('summary', '')}")
    if facts.get("note"):
        print(f"  ! {facts['note']}")

    if args.dry:
        print("[tw_stock_data] --dry：不寫檔")
        return 0

    # 防呆：算不出任何數字時，不要用空檔覆蓋既有真數據（保留舊檔）
    if n == 0 and OUT_FILE.exists():
        print("[tw_stock_data] 本次 0 項，保留既有 tw_stock_facts.json 不覆蓋")
        return 0
    try:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[tw_stock_data] 已寫入 {OUT_FILE}")
    except Exception as e:  # noqa: BLE001
        print(f"[tw_stock_data] 寫檔失敗（不崩）：{e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
