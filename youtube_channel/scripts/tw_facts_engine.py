#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tw_facts_engine.py — 【台股真回測事實引擎 v2】把真回測引擎接上內容產線的事實庫。

背景（2026-07 誠信整頓）：舊版 scripts/tw_stock_data.py 只算 3 類、5 組事實，
一天要生 ~20 支台股影片，事實庫遠遠不夠用 → LLM 被逼著自己編數字（查無憑據的
「毛利率選股勝率 31%」之類）。本引擎用專案既有的 tw_data.py（quant-service 同源
的台股資料層概念）+ yfinance 還原股價，批次算出**幾十組**可佐證的真回測事實，
寫回 STUDIO/tw_stock_facts.json（schema 與舊版相容：as_of/disclaimer/results），
讓 produce_batch.py 既有的 _tw_facts_context() 讀取邏輯完全不用改。

誠信鐵則（最高優先）：
  - 只算「歷史價格資料真的算得出來」的事實（定期定額/單筆、扣款日、停利、
    高股息vs市值型、槓桿ETF長抱、擇時/錯過最佳N天、崩盤期間加碼/停損）。
  - 不做個股買賣建議、不預測未來，只描述歷史。
  - 抓不到 / 資料不足(< MIN_YEARS) → 該項略過，絕不編造或用示意數字冒充真回測。
  - 每組事實都附 key/claim/summary/period(start~end)/symbol/method/source/computed_at/disclaimer。
  - 需要財報等基本面資料（毛利率、EPS、營收）的主題 → 本引擎不產出（見 --blacklist）。

用法：
  python scripts/tw_facts_engine.py            # 全算並寫入 STUDIO/tw_stock_facts.json
  python scripts/tw_facts_engine.py --dry       # 只印不寫
  python scripts/tw_facts_engine.py --refresh   # 忽略價格快取重抓
  python scripts/tw_facts_engine.py --blacklist # 印「無資料、產線不該碰」清單後結束

驗證：python -m py_compile scripts/tw_facts_engine.py
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

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
STUDIO = ROOT / "STUDIO"
# ⚠️ 寫入 tw_facts_computed.json（第三份事實庫），不是 tw_stock_facts.json：
#   後者是舊版 5 組事實 + produce_batch._tw_facts_context() 唯一讀取的檔案，不動它、
#   不動 produce_batch.py（任務紅線）。fact_source_guard.py 的 FACT_FILES 已把
#   tw_facts_computed.json 列為第三份可佐證數字池，本引擎只需把新事實寫進這裡即可
#   讓「查無來源」判斷吃到更大的數字池，不影響既有產線的注入邏輯。
OUT_FILE = STUDIO / "tw_facts_computed.json"
CACHE_DIR = STUDIO / "tw_facts_cache"                    # 還原股價快取（獨立於 quant-service 的原始快取，因為要含息還原）
CACHE_MAX_AGE_H = 20                                      # 快取超過 20 小時才重抓（省網路、避免每次跑都打 yfinance）

DISCLAIMER = "歷史回測，非未來保證；不構成投資建議、不喊單、不報明牌。"
MIN_YEARS = 3.0     # 少於 3 年的區間不產出（樣本太短不可信）
MIN_BARS = 250

# ── legacy 事實庫退役（2026-07-17 已發布誠信事故的結構性修補）─────────────────────
# 舊引擎 scripts/tw_stock_data.py 產的 STUDIO/tw_stock_facts.json（5 組）與本引擎產的
# tw_facts_computed.json（50 組）是**同一組回測的兩份快照，但回測窗口不同 → 數字互斥**：
#   · legacy `buyhold_vs_timing_twii` ：_fetch_close(^TWII, 20) → 近 20.1 年 → 長抱年化 10.2%、
#     擇時 8.9% → 結論「長抱贏」
#   · 本引擎 `buyhold_vs_timing__TWII`：period="max" → 1997-07-02 起 29 年 → 長抱 5.7%、
#     擇時 6.9% → 結論「擇時贏」
# 兩邊算術都對，但講的是同一個問題，結論相反。已發布災情：Jad4_8skToo 與 ogQukwzFn1s
# 兩支片同時在線互相打臉（詳見該次稽核報告）。
#
# 為什麼一律以本引擎（computed）為準，四個結構性理由：
#   ① legacy 是 `today - years*366` 的**滾動窗**，每天 04:00 重算 → **數字每天漂移**。
#      已發布 -jnJRZUvUzA 講 0050 十年 All-in「813%」，今天同一個 key 已變 804.5% → 對不回來。
#      本引擎 __full 系列是固定起點，可重現。
#   ② legacy 每筆**沒有** period/start/end/method/source/computed_at，寫稿端拿不到期間 → 自己編年數。
#   ③ legacy 沒有 _sanitize_series，不砍 0050 在 2014-01-02 的假跳空（ratio=0.249，見下方
#      清洗段的更正說明）與 00631L 2015-01-05（ratio=0.046）。
#   ④ **完全冗餘**：legacy 5 組主題本引擎全都有，且多 45 組。丟掉零損失。
#
# ⚠️ fail-open 設計：只有在「computed 對應版本真的存在」時才丟 legacy。萬一本引擎缺檔／該組
#    算不出來，legacy 仍會被保留使用——有真數據總比沒有好，**絕不可因為缺檔害產線停擺**。
LEGACY_FACTS_FILE = "tw_stock_facts.json"

LEGACY_SUPERSEDED_BY = {
    "allin_vs_dca_0050_10y":  "dca_vs_allin__0050__10y",
    "allin_vs_dca_twii_20y":  "dca_vs_allin__TWII__full",
    "buyhold_vs_timing_twii": "buyhold_vs_timing__TWII",
    "hidiv_0056_vs_0050":     "hidiv_vs_mktcap__0056_vs_0050",
    "hidiv_00878_vs_0050":    "hidiv_vs_mktcap__00878_vs_0050",
}


def drop_superseded_legacy(results):
    """從合併後的 {fact_key: fact} 拿掉「已被 computed 取代」的 legacy key，回傳新 dict。

    產線各讀取端（produce_batch._load_tw_facts / topics_from_facts.load_facts /
    winner_amplifier.load_facts / tw_lab_engine._load_facts）合併兩份檔時共用這一份判定，
    確保**結構上不可能**對同一件事引用到兩個互斥的答案。

    為什麼用 key 對 key 而不是比對 desc 文字：tw_lab_engine 原本的 `_dedup_sig()` 是把 desc
    正規化後比字串，但兩支引擎的 desc 措辭不同（「大盤 長抱不動 vs 跌破年線就跑的簡單擇時」
    vs「加權指數（大盤） 長抱不動 vs 簡單擇時（年線）」）→ 簽名不同 → 兩組都活下來 → 各出一集。
    文字比對本質上防不住這件事，故改用顯式 key 映射。

    fail-open：computed 對應版本不存在時**不動** legacy（見上方說明）。
    """
    if not isinstance(results, dict):
        return results
    out = dict(results)
    for legacy_key, computed_key in LEGACY_SUPERSEDED_BY.items():
        if legacy_key in out and computed_key in out:
            out.pop(legacy_key, None)
    return out

# ── 標的清單（皆 yfinance 抓得到；上市 ETF/指數/權值股，来源：Yahoo Finance）────
SYMBOLS = {
    "0050":   {"ticker": "0050.TW",  "name": "元大台灣50",     "kind": "mktcap"},
    "006208": {"ticker": "006208.TW", "name": "富邦台50",       "kind": "mktcap"},
    "0056":   {"ticker": "0056.TW",  "name": "元大高股息",      "kind": "hidiv"},
    "00878":  {"ticker": "00878.TW", "name": "國泰永續高股息",  "kind": "hidiv"},
    "00631L": {"ticker": "00631L.TW", "name": "元大台灣50正2",  "kind": "leveraged"},
    "2330":   {"ticker": "2330.TW",  "name": "台積電",          "kind": "stock"},
    "TWII":   {"ticker": "^TWII",    "name": "加權指數（大盤）", "kind": "index"},
    # 2026-07-15 高股息家族 vs 市值型全對決（第三旗艦數據軍火）新增標的：
    "00713":  {"ticker": "00713.TW", "name": "元大台灣高息低波", "kind": "hidiv"},
    "00915":  {"ticker": "00915.TW", "name": "凱基優選高股息30", "kind": "hidiv"},
    "00918":  {"ticker": "00918.TW", "name": "大華優利高填息30", "kind": "hidiv"},
    "00919":  {"ticker": "00919.TW", "name": "群益台灣精選高息", "kind": "hidiv"},
    "00929":  {"ticker": "00929.TW", "name": "復華台灣科技優息", "kind": "hidiv"},
    "00934":  {"ticker": "00934.TW", "name": "中信成長高股息",   "kind": "hidiv"},
    "00936":  {"ticker": "00936.TW", "name": "台新永續高息中小", "kind": "hidiv"},
    "00939":  {"ticker": "00939.TW", "name": "統一台灣高息動能", "kind": "hidiv"},
    "00940":  {"ticker": "00940.TW", "name": "元大台灣價值高息", "kind": "hidiv"},
}

SOURCE_NOTE = ("Yahoo Finance（yfinance，auto_adjust=True 含息還原收盤價；"
               "已過 _sanitize_series 清洗，砍除疑似分割/單位淨值重編未回溯調整的假跳空）")


# ── 資料層：抓 + 本地快取（含息還原收盤價）────────────────────────────────────
def _cache_path(code):
    return CACHE_DIR / f"{code}.csv"


def _load_cache(code):
    p = _cache_path(code)
    if not p.exists():
        return None
    try:
        age_h = (time.time() - p.stat().st_mtime) / 3600.0
        if age_h > CACHE_MAX_AGE_H:
            return None
        import pandas as pd
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        s = df["Close"].dropna()
        if len(s) < 60:
            return None
        return s
    except Exception:
        return None


def _save_cache(code, series):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        series.to_frame("Close").to_csv(_cache_path(code))
    except Exception:
        pass


# ── 資料清洗：砍掉 yfinance 未正確回溯調整的分割/單位淨值重編假跳空 ────────────
# 2026-07-13 實測發現(手動驗算時抓到)：0050 在 2014-01-02 出現單日 ratio=0.249。
# ⚠️ 2026-08-22 更正:舊註解寫「對應 0050 實際 1股拆4股分割」會被讀成「0050 在 2014 分割」,
#    那是錯的。實測 yfinance 對 0050.TW 的 splits 是 **NONE**(一筆分割紀錄都沒有),
#    而它記的配息(0.65/0.475/0.75…)與真實 0050 當年配息(約 2.60/1.90)**正好差 4 倍**
#    ——真正發生的事是:後來那次分割被回溯調整到 2014-01-02 就停住,2014 以前沒調到。
#    斷點在 2014 為真,分割不在 2014。另外要知道:yfinance 的 0050.TW 序列**本身只回溯到
#    2009-01-02**,所以就算清洗規則改好,這個資料源也給不出 2008 起算的 0050
#    (2026-08-22 回覆觀眾「大空頭」提問時就卡在這裡,只能誠實說算不出來)。
# 造成該日之前/之後的價格尺度差 4 倍；00631L 在 2015-01-05 出現單日 ratio=0.046
# （疑似單位淨值重編/分割未回溯調整，價格尺度差 ~22 倍）。這兩個假跳空若不處理，
# 會讓橫跨該日期的 total_return / max_drawdown 全部失真（例如误算出「00631L 最大
# 回撤 -96.9%」這種其實是資料斷點、不是真實崩盤的假事實）。
# 誠信鐵則：寧可少一段歷史，不可讓假的價格斷點污染回測結果 —— 偵測到單日 ±50% 以上
# 的不合理跳空，就只保留「最後一次異常跳空之後」的連續乾淨區間（真實市場中，一般
# 股票/ETF/指數單日不可能有這種量級的變動；台股個股漲跌停頂多 ±10%）。
_ANOMALY_RATIO_HI = 1.5   # 單日漲逾 50%
_ANOMALY_RATIO_LO = 1.0 / 1.5  # 單日跌逾 33.3%（對稱倒數，避免跟漲的判準不一致）


def _sanitize_series(s):
    """砍掉疑似分割/單位淨值重編未回溯調整造成的假跳空，只留最近一段連續乾淨資料。"""
    if s is None or len(s) < 5:
        return s
    ratio = s / s.shift(1)
    bad = ratio[(ratio > _ANOMALY_RATIO_HI) | (ratio < _ANOMALY_RATIO_LO)]
    if len(bad) == 0:
        return s
    last_bad_date = bad.index.max()
    cleaned = s[s.index > last_bad_date]
    if len(cleaned) < 60:
        # 砍完太短（異常點太靠近序列尾端）：清理沒有意義，讓上層 MIN_BARS/MIN_YEARS 擋掉
        return cleaned
    for dt_, r in bad.items():
        print(f"[tw_facts_engine] ⚠ 資料清洗：偵測到假跳空 {dt_.date()} ratio={r:.3f}"
              f"（疑似分割/單位淨值重編未回溯調整）→ 只保留 {last_bad_date.date()} 之後的乾淨資料")
    return cleaned


def fetch_series(code, refresh=False):
    """回傳 (code 的) 含息還原收盤價 pd.Series（index=日期）；抓不到回 None。
    先讀本地快取（<20h）省網路，沒有/過期/refresh 才打 yfinance。已套用 _sanitize_series
    砍掉假跳空（見上方說明）。"""
    if not refresh:
        cached = _load_cache(code)
        if cached is not None:
            return _sanitize_series(cached)
    info = SYMBOLS[code]
    try:
        import yfinance as yf
        df = yf.download(info["ticker"], period="max", auto_adjust=True,
                          progress=False, threads=False)
        if df is None or len(df) == 0:
            return None
        col = df["Close"]
        if hasattr(col, "columns"):
            col = col.iloc[:, 0]
        s = col.dropna()
        s.index = __import__("pandas").to_datetime(s.index)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = _sanitize_series(s)
        if s is None or len(s) < 60:
            return None
        _save_cache(code, s)
        return s
    except Exception as exc:  # noqa: BLE001
        print(f"[tw_facts_engine] {code} 抓取失敗（略過)：{exc}")
        return None


# ── 純數學小工具（不碰網路，可獨立單元驗算）──────────────────────────────────
def cagr(start_val, end_val, years):
    try:
        if start_val is None or end_val is None or start_val <= 0 or end_val <= 0 or years <= 0:
            return None
        return (float(end_val) / float(start_val)) ** (1.0 / years) - 1.0
    except Exception:
        return None


def max_drawdown(values):
    """values: 任意可迭代的權益曲線（非負）。回傳負值(如 -0.35)或 None。"""
    try:
        peak = None
        mdd = 0.0
        for v in values:
            v = float(v)
            if peak is None or v > peak:
                peak = v
            if peak and peak > 0:
                dd = (v - peak) / peak
                if dd < mdd:
                    mdd = dd
        return mdd
    except Exception:
        return None


def calmar(cagr_val, mdd_val):
    try:
        if cagr_val is None or mdd_val is None or mdd_val == 0:
            return None
        return cagr_val / abs(mdd_val)
    except Exception:
        return None


def pct(x, digits=1):
    if x is None:
        return "—"
    try:
        return f"{x * 100:.{digits}f}%"
    except Exception:
        return "—"


def years_span(s):
    return (s.index[-1] - s.index[0]).days / 365.25


def slice_trailing(s, years):
    """取序列尾端 years 年（依日曆天，不是交易日數）。"""
    if years is None:
        return s
    cutoff = s.index[-1] - _dt.timedelta(days=int(years * 365.25))
    return s[s.index >= cutoff]


# ── 事實類型 1：定期定額 vs 單筆 All-in ──────────────────────────────────────
def calc_dca_vs_allin(s):
    """回傳 dict 或 None。s: 收盤價 Series（單一標的、一段期間）。"""
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    y0, y1 = float(s.iloc[0]), float(s.iloc[-1])
    allin_tr = y1 / y0 - 1.0
    allin_cagr = cagr(y0, y1, span)
    allin_mdd = max_drawdown(s)

    monthly = s.resample("MS").first().dropna()
    if len(monthly) < 6:
        return None
    shares, invested, equity = 0.0, 0.0, []
    for px in monthly:
        px = float(px)
        if px <= 0:
            continue
        shares += 1.0 / px
        invested += 1.0
        equity.append(shares * px)
    if invested <= 0 or not equity:
        return None
    final_val = shares * float(monthly.iloc[-1])
    dca_tr = final_val / invested - 1.0
    dca_cagr = cagr(1.0, final_val / invested, span)
    dca_mdd = max_drawdown(equity)

    return {
        "allin": {"total_return": allin_tr, "cagr": allin_cagr, "max_drawdown": allin_mdd,
                  "calmar": calmar(allin_cagr, allin_mdd)},
        "dca": {"total_return": dca_tr, "cagr": dca_cagr, "max_drawdown": dca_mdd,
                "calmar": calmar(dca_cagr, dca_mdd)},
        "years": round(span, 1),
        "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "summary": (f"一次All in總報酬 {pct(allin_tr)}（年化 {pct(allin_cagr)}、"
                    f"最大回撤 {pct(allin_mdd)}、卡瑪比率 {calmar(allin_cagr, allin_mdd):.2f}）"
                    if calmar(allin_cagr, allin_mdd) is not None else
                    f"一次All in總報酬 {pct(allin_tr)}（年化 {pct(allin_cagr)}、最大回撤 {pct(allin_mdd)}）")
                   + (f"；每月定期定額總報酬 {pct(dca_tr)}（年化 {pct(dca_cagr)}、"
                      f"最大回撤 {pct(dca_mdd)}、卡瑪比率 {calmar(dca_cagr, dca_mdd):.2f}）"
                      if calmar(dca_cagr, dca_mdd) is not None else
                      f"；每月定期定額總報酬 {pct(dca_tr)}（年化 {pct(dca_cagr)}、最大回撤 {pct(dca_mdd)}）"),
    }


# ── 事實類型 2：扣款日效應（月初/月中/月底定期定額）──────────────────────────
def calc_deposit_day_effect(s):
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    import pandas as pd

    def _run(target_day):
        """每月找 >= target_day 的第一個交易日扣款；找不到(該月無)就用當月最後一個交易日。"""
        by_month = s.groupby([s.index.year, s.index.month])
        shares, invested = 0.0, 0.0
        for (_, _), grp in by_month:
            grp = grp.sort_index()
            picks = grp[grp.index.day >= target_day]
            px = float(picks.iloc[0]) if len(picks) else float(grp.iloc[-1])
            if px <= 0:
                continue
            shares += 1.0 / px
            invested += 1.0
        if invested <= 0:
            return None
        final_val = shares * float(s.iloc[-1])
        tr = final_val / invested - 1.0
        return tr

    early = _run(1)
    mid = _run(15)
    late = _run(25)
    if early is None or mid is None or late is None:
        return None
    order = sorted([("月初(1號後首個交易日)", early), ("月中(15號後首個交易日)", mid),
                     ("月底(25號後首個交易日)", late)], key=lambda x: x[1], reverse=True)
    best_label, best_val = order[0]
    worst_label, worst_val = order[-1]
    return {
        "early_day1": early, "mid_day15": mid, "late_day25": late,
        "years": round(span, 1),
        "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "summary": (f"月初扣款總報酬 {pct(early)}、月中扣款 {pct(mid)}、月底扣款 {pct(late)}；"
                    f"最佳與最差只差 {pct(best_val - worst_val)}（{best_label} 對比 {worst_label}）"),
    }


# ── 事實類型 3：停利 vs 續抱 ─────────────────────────────────────────────────
def calc_stop_profit_vs_hold(s, threshold):
    """threshold: 0.10 / 0.15 / 0.20。單筆買進、首次觸及停利點就全部出場並不再進場(持有現金到期末) vs 抱到底。"""
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    p0 = float(s.iloc[0])
    exit_date, exit_price = None, None
    for dt_, px in s.items():
        px = float(px)
        if px / p0 - 1.0 >= threshold:
            exit_date, exit_price = dt_, px
            break
    final_price = float(s.iloc[-1])
    hold_final = final_price / p0 - 1.0
    if exit_date is None:
        # 全期間都沒摸到停利點：停利策略＝抱到底，兩者相同（仍回傳，如實標註未觸發）
        stop_final = hold_final
        triggered = False
        years_to_exit = None
    else:
        stop_final = exit_price / p0 - 1.0
        triggered = True
        years_to_exit = (exit_date - s.index[0]).days / 365.25
    return {
        "threshold": threshold,
        "triggered": triggered,
        "years_to_exit": round(years_to_exit, 2) if years_to_exit is not None else None,
        "exit_date": str(exit_date.date()) if exit_date is not None else None,
        "stop_profit_final_return": stop_final,
        "hold_final_return": hold_final,
        "years": round(span, 1),
        "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "summary": (
            (f"觸及 {pct(threshold,0)} 停利點後全部出場、不再進場：最終報酬定格在 {pct(stop_final)}"
             f"（第 {years_to_exit:.1f} 年觸發，{exit_date.date()}）；"
             f"若當初抱到底不停利：最終報酬 {pct(hold_final)}"
             f"（{'停利反而少賺' if hold_final > stop_final else '停利反而少賠/多賺'} "
             f"{pct(abs(hold_final - stop_final))}）")
            if triggered else
            f"全期間 {round(span,1)} 年股價從未觸及 {pct(threshold,0)} 停利點，停利策略等同抱到底：報酬 {pct(hold_final)}"
        ),
    }


# ── 事實類型 4：高股息 vs 市值型（含息還原）──────────────────────────────────
def calc_hidiv_vs_mktcap(hidiv_s, mktcap_s, hidiv_name, mktcap_name):
    if hidiv_s is None or mktcap_s is None:
        return None
    common_start = max(hidiv_s.index[0], mktcap_s.index[0])
    h = hidiv_s[hidiv_s.index >= common_start]
    m = mktcap_s[mktcap_s.index >= common_start]
    if len(h) < MIN_BARS or len(m) < MIN_BARS:
        return None
    span = (h.index[-1] - common_start).days / 365.25
    if span < MIN_YEARS:
        return None
    h_tr = float(h.iloc[-1]) / float(h.iloc[0]) - 1.0
    m_tr = float(m.iloc[-1]) / float(m.iloc[0]) - 1.0
    h_cagr = cagr(h.iloc[0], h.iloc[-1], span)
    m_cagr = cagr(m.iloc[0], m.iloc[-1], span)
    h_mdd = max_drawdown(h)
    m_mdd = max_drawdown(m)
    return {
        "hidiv": {"ticker": hidiv_name, "total_return": h_tr, "cagr": h_cagr, "max_drawdown": h_mdd},
        "mktcap": {"ticker": mktcap_name, "total_return": m_tr, "cagr": m_cagr, "max_drawdown": m_mdd},
        "years": round(span, 1),
        "start": str(common_start.date()), "end": str(h.index[-1].date()),
        "summary": (f"近 {round(span,1)} 年含息還原：高股息 {hidiv_name} 總報酬 {pct(h_tr)}（年化 {pct(h_cagr)}、"
                    f"最大回撤 {pct(h_mdd)}） vs 市值型 {mktcap_name} 總報酬 {pct(m_tr)}"
                    f"（年化 {pct(m_cagr)}、最大回撤 {pct(m_mdd)}）"),
    }


# ── 事實類型 5：槓桿 ETF 長抱實際結果 ────────────────────────────────────────
def calc_leveraged_vs_base(lev_s, base_s, lev_name, base_name):
    if lev_s is None or base_s is None:
        return None
    common_start = max(lev_s.index[0], base_s.index[0])
    lv = lev_s[lev_s.index >= common_start]
    bs = base_s[base_s.index >= common_start]
    if len(lv) < MIN_BARS or len(bs) < MIN_BARS:
        return None
    span = (lv.index[-1] - common_start).days / 365.25
    if span < MIN_YEARS:
        return None
    lv_tr = float(lv.iloc[-1]) / float(lv.iloc[0]) - 1.0
    bs_tr = float(bs.iloc[-1]) / float(bs.iloc[0]) - 1.0
    lv_cagr = cagr(lv.iloc[0], lv.iloc[-1], span)
    bs_cagr = cagr(bs.iloc[0], bs.iloc[-1], span)
    lv_mdd = max_drawdown(lv)
    bs_mdd = max_drawdown(bs)
    theoretical_2x_tr = bs_tr * 2.0
    return {
        "leveraged": {"ticker": lev_name, "total_return": lv_tr, "cagr": lv_cagr, "max_drawdown": lv_mdd},
        "base": {"ticker": base_name, "total_return": bs_tr, "cagr": bs_cagr, "max_drawdown": bs_mdd},
        "theoretical_2x_total_return": theoretical_2x_tr,
        "decay_gap_vs_theoretical_2x": lv_tr - theoretical_2x_tr,
        "years": round(span, 1),
        "start": str(common_start.date()), "end": str(lv.index[-1].date()),
        "summary": (f"近 {round(span,1)} 年（{common_start.date()}起）長抱：槓桿 {lev_name} 實際總報酬 {pct(lv_tr)}"
                    f"（年化 {pct(lv_cagr)}、最大回撤 {pct(lv_mdd)}） vs 原型 {base_name} 總報酬 {pct(bs_tr)}"
                    f"（理論2倍應為 {pct(theoretical_2x_tr)}，實際槓桿ETF因複利耗損差了 {pct(lv_tr - theoretical_2x_tr)}）"),
    }


# ── 事實類型 6：大盤擇時 vs 傻抱 ─────────────────────────────────────────────
def calc_buyhold_vs_timing(s, ma_window=200):
    if s is None or len(s) < ma_window + 60:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    ma = s.rolling(ma_window).mean()
    bh_cagr = cagr(s.iloc[0], s.iloc[-1], span)
    bh_mdd = max_drawdown(s)
    rets = s.pct_change().fillna(0.0)
    in_mkt = (s.shift(1) > ma.shift(1)).fillna(False)
    equity = [1.0]
    n_switches = 0
    prev_state = None
    for i in range(1, len(s)):
        state = bool(in_mkt.iloc[i])
        if prev_state is not None and state != prev_state:
            n_switches += 1
        prev_state = state
        r = float(rets.iloc[i]) if state else 0.0
        equity.append(equity[-1] * (1.0 + r))
    timing_end = equity[-1]
    timing_cagr = cagr(1.0, timing_end, span)
    timing_mdd = max_drawdown(equity)
    return {
        "buy_hold": {"cagr": bh_cagr, "max_drawdown": bh_mdd},
        "timing_ma": {"window": ma_window, "cagr": timing_cagr, "max_drawdown": timing_mdd,
                      "n_switches": n_switches},
        "years": round(span, 1),
        "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "summary": (f"長抱不動年化 {pct(bh_cagr)}（最大回撤 {pct(bh_mdd)}）；"
                    f"跌破{ma_window}日均線就出場的簡單擇時年化 {pct(timing_cagr)}"
                    f"（最大回撤 {pct(timing_mdd)}，期間進出 {n_switches} 次，未計手續費/滑價）"),
    }


# ── 事實類型 7：錯過最佳 N 天 ────────────────────────────────────────────────
def calc_miss_best_days(s, n_list=(5, 10, 20)):
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    rets = s.pct_change().dropna()
    if len(rets) < 100:
        return None
    baseline_tr = float((1.0 + rets).prod() - 1.0)
    out = {"baseline_total_return": baseline_tr, "years": round(span, 1),
           "start": str(s.index[0].date()), "end": str(s.index[-1].date()), "misses": {}}
    ranked = rets.sort_values(ascending=False)
    lines = [f"全期間 {round(span,1)} 年、buy&hold 總報酬 {pct(baseline_tr)}。"]
    for n in n_list:
        best_idx = set(ranked.head(n).index)
        adj = rets.copy()
        adj.loc[list(best_idx)] = 0.0
        miss_tr = float((1.0 + adj).prod() - 1.0)
        out["misses"][str(n)] = {"total_return": miss_tr, "gap": baseline_tr - miss_tr}
        lines.append(f"錯過表現最好的 {n} 天：總報酬掉到 {pct(miss_tr)}（少賺 {pct(baseline_tr - miss_tr)}）")
    out["summary"] = " ".join(lines)
    return out


# ── 事實類型 8：崩盤期間加碼 vs 停損（真實歷史區間）──────────────────────────
CRASH_WINDOWS = {
    "covid2020": {"label": "2020新冠崩盤", "start": "2020-01-01", "end": "2020-06-30"},
    "bear2022":  {"label": "2022台股熊市", "start": "2022-01-01", "end": "2022-12-31"},
}


def calc_crash_episode(s, window_key):
    win = CRASH_WINDOWS[window_key]
    start, end = pd_ts(win["start"]), pd_ts(win["end"])
    if s is None:
        return None
    sub = s[(s.index >= start) & (s.index <= end)]
    if len(sub) < 30:
        return None
    trough_date = sub.idxmin()
    trough_price = float(sub.loc[trough_date])
    pre = sub[sub.index <= trough_date]
    if len(pre) < 2:
        return None
    peak_date = pre.idxmax()
    peak_price = float(pre.loc[peak_date])
    if peak_price <= 0 or trough_price <= 0:
        return None
    latest_date = s.index[-1]
    latest_price = float(s.iloc[-1])
    # 停損：在高點買進，跌到阱底那天全數賣出、不再進場(現金持有到現在)
    sell_at_bottom_value = trough_price / peak_price
    # 抱住：同一筆在高點買進的部位，抱到現在
    hold_now_value = latest_price / peak_price
    # 加碼／低接：在阱底那天另外買一筆，抱到現在，對比在高點買同一筆抱到現在
    buy_dip_now_value = latest_price / trough_price
    buy_peak_now_value = hold_now_value
    return {
        "window": win["label"], "window_start": win["start"], "window_end": win["end"],
        "peak_date": str(peak_date.date()), "peak_price": peak_price,
        "trough_date": str(trough_date.date()), "trough_price": trough_price,
        "latest_date": str(latest_date.date()), "latest_price": latest_price,
        "sell_at_bottom_return": sell_at_bottom_value - 1.0,
        "hold_through_return": hold_now_value - 1.0,
        "buy_the_dip_return_to_now": buy_dip_now_value - 1.0,
        "buy_at_pre_crash_peak_return_to_now": buy_peak_now_value - 1.0,
        "summary_panic_sell": (
            f"{win['label']}：若在崩跌前高點（{peak_date.date()}）買進、崩到阱底（{trough_date.date()}，"
            f"跌幅 {pct(sell_at_bottom_value - 1.0)}）恐慌全部賣出不再進場：報酬定格在 {pct(sell_at_bottom_value - 1.0)}；"
            f"若當時沒賣、抱到現在（{latest_date.date()}）：報酬 {pct(hold_now_value - 1.0)}"
            f"（多賺 {pct(hold_now_value - sell_at_bottom_value)}）"),
        "summary_buy_the_dip": (
            f"{win['label']}：在阱底（{trough_date.date()}）低接抱到現在報酬 {pct(buy_dip_now_value - 1.0)}；"
            f"同一筆錢若在崩跌前高點（{peak_date.date()}）買進抱到現在報酬 {pct(buy_peak_now_value - 1.0)}"
            f"（低接多賺 {pct(buy_dip_now_value - buy_peak_now_value)}）"),
    }


def pd_ts(x):
    import pandas as pd
    return pd.Timestamp(x)


# ── 主流程：組裝所有事實 ─────────────────────────────────────────────────────
def build_facts(refresh=False, only_symbols=None):
    as_of = _dt.date.today().isoformat()
    facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": {}}
    results = facts["results"]

    codes = list(SYMBOLS.keys()) if not only_symbols else [c for c in only_symbols if c in SYMBOLS]
    series = {}
    for code in codes:
        s = fetch_series(code, refresh=refresh)
        series[code] = s
        status = f"{len(s)} 筆 {s.index[0].date()}~{s.index[-1].date()}" if s is not None else "抓取失敗"
        print(f"[tw_facts_engine] 資料 {code}（{SYMBOLS[code]['ticker']}）: {status}")

    def add(key, method, symbol_desc, desc, keywords, payload, source=SOURCE_NOTE):
        if not payload:
            return
        entry = {
            "key": key,
            "claim": payload.get("summary", desc),   # 白話一句可佐證聲稱（schema 硬規則要求欄位）
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

    # ── 1. 定期定額 vs 單筆 All-in：每個標的算「全期間」+「近10年」(資料夠才算) ──
    dca_targets = ["0050", "006208", "0056", "00878", "2330", "TWII"]
    for code in dca_targets:
        s = series.get(code)
        if s is None:
            continue
        name = SYMBOLS[code]["name"]
        r_full = calc_dca_vs_allin(s)
        # 標籤用實際可信資料年數，別喊「全歷史」誤導成上市至今（若資料清洗砍過假跳空，
        # 可信區間會比真實上市年數短，desc/period 都要如實反映，不能報虛的年份）
        full_years_label = f"近{r_full['years']:.0f}年" if r_full else "全歷史"
        add(f"dca_vs_allin__{code}__full",
            "定期定額 vs 單筆 All-in（可信資料區間全段，月扣款1單位 vs 期初單筆）",
            f"{name}（{code}）", f"{name} {full_years_label}（可信資料區間） 一次All in vs 每月定期定額",
            ["定投", "定期定額", "All in", code, name, "微笑曲線"], r_full)
        if s is not None and years_span(s) > 11:
            s10 = slice_trailing(s, 10)
            r10 = calc_dca_vs_allin(s10)
            add(f"dca_vs_allin__{code}__10y", "定期定額 vs 單筆 All-in（近10年，月扣款1單位 vs 期初單筆）",
                f"{name}（{code}）", f"{name} 近10年 一次All in vs 每月定期定額",
                ["定投", "定期定額", "All in", code, name, "微笑曲線"], r10)

    # ── 2. 扣款日效應（0050、TWII 全歷史）──────────────────────────────────
    for code in ["0050", "TWII"]:
        s = series.get(code)
        if s is None:
            continue
        name = SYMBOLS[code]["name"]
        r = calc_deposit_day_effect(s)
        add(f"deposit_day_effect__{code}", "定期定額扣款日效應（每月1號/15號/25號後首個交易日扣款1單位，比較終值總報酬）",
            f"{name}（{code}）", f"{name} 定期定額扣款日：月初/月中/月底差多少",
            ["扣款日", "定期定額", "定投", code, name], r)

    # ── 3. 停利 vs 續抱（0050、2330，10%/15%/20%）──────────────────────────
    for code in ["0050", "2330", "006208"]:
        s = series.get(code)
        if s is None:
            continue
        name = SYMBOLS[code]["name"]
        for th in (0.10, 0.15, 0.20):
            r = calc_stop_profit_vs_hold(s, th)
            add(f"stop_profit_vs_hold__{code}__{int(th*100)}pct",
                f"停利{int(th*100)}%出場(單筆買進、首次觸及即全出、不再進場) vs 抱到底",
                f"{name}（{code}）", f"{name} 設{int(th*100)}%停利 vs 抱到底",
                ["停利", "續抱", "紀律", code, name], r)

    # ── 4. 高股息 vs 市值型（含息還原，兩兩組合）─────────────────────────────
    # 2026-07-15 擴編：高股息家族 vs 市值型全對決旗艦片，把台灣主要高股息 ETF
    # 全部納入同一套方法論（含息還原、共同起點=兩者資料重疊期間、CAGR/MDD/Calmar）。
    # 上市時間短的（00939/00940 2024上市）common_start 會自動退到「該檔自己上市日」，
    # 剛好就是「申購熱潮後至今」的公平比較，不需要另外特判。
    hidiv_codes = ["0056", "00878", "00713", "00915", "00918", "00919",
                   "00929", "00934", "00936", "00939", "00940"]
    mktcap_codes = ["0050", "006208"]
    for hc in hidiv_codes:
        for mc in mktcap_codes:
            hs, ms = series.get(hc), series.get(mc)
            if hs is None or ms is None:
                continue
            hname, mname = SYMBOLS[hc]["name"], SYMBOLS[mc]["name"]
            r = calc_hidiv_vs_mktcap(hs, ms, hc, mc)
            add(f"hidiv_vs_mktcap__{hc}_vs_{mc}", "高股息 vs 市值型（含息還原，共同起點比總報酬/年化/最大回撤）",
                f"{hname}（{hc}） vs {mname}（{mc}）", f"高股息 {hc} vs 市值型 {mc}（含息還原）",
                ["高股息", "市值型", hc, mc, "存股", "ETF"], r)

    # ── 5. 槓桿 ETF 長抱實際結果（00631L vs 0050 / 006208）───────────────────
    for base_c in ["0050", "006208"]:
        lv_s, base_s = series.get("00631L"), series.get(base_c)
        if lv_s is None or base_s is None:
            continue
        r = calc_leveraged_vs_base(lv_s, base_s, "00631L", base_c)
        add(f"leveraged_vs_base__00631L_vs_{base_c}",
            "槓桿ETF長抱 vs 原型（共同起點總報酬對比理論2倍，看複利耗損）",
            f"00631L（元大台灣50正2） vs {SYMBOLS[base_c]['name']}（{base_c}）",
            f"00631L 長抱 vs {base_c} 長抱，理論2倍打幾折",
            ["槓桿", "00631L", "正2", base_c, "複利耗損"], r)

    # ── 6. 大盤擇時 vs 傻抱（跌破200日均線）──────────────────────────────────
    for code in ["TWII", "0050"]:
        s = series.get(code)
        if s is None:
            continue
        name = SYMBOLS[code]["name"]
        r = calc_buyhold_vs_timing(s, 200)
        add(f"buyhold_vs_timing__{code}", "長抱不動 vs 跌破200日均線出場、站回進場的簡單擇時（未計手續費滑價）",
            f"{name}（{code}）", f"{name} 長抱不動 vs 簡單擇時（年線）",
            ["擇時", "長抱", "年線", code, name], r)

    # ── 7. 錯過最佳 N 天 ────────────────────────────────────────────────────
    for code in ["0050", "TWII"]:
        s = series.get(code)
        if s is None:
            continue
        s_use = slice_trailing(s, 10) if years_span(s) > 11 else s
        name = SYMBOLS[code]["name"]
        r = calc_miss_best_days(s_use, (5, 10, 20))
        add(f"miss_best_days__{code}", "buy&hold 總報酬 vs 剔除表現最好的N天(該N天報酬設為0)重算總報酬",
            f"{name}（{code}）", f"{name} 錯過表現最好的幾天，報酬差多少",
            ["擇時", "錯過最佳天數", "波動", code, name], r)

    # ── 8. 崩盤期間加碼 vs 停損（2020 新冠 / 2022 熊市）───────────────────────
    for code in ["0050", "TWII"]:
        s = series.get(code)
        if s is None:
            continue
        name = SYMBOLS[code]["name"]
        for wk in CRASH_WINDOWS:
            r = calc_crash_episode(s, wk)
            if not r:
                continue
            wlabel = CRASH_WINDOWS[wk]["label"]
            add(f"crash_panic_sell__{code}__{wk}", "崩盤前高點買進→阱底恐慌全賣不再進場(現金到現在) vs 沒賣抱到現在",
                f"{name}（{code}）", f"{wlabel}：{name} 阱底恐慌賣出 vs 抱到現在",
                ["崩盤", "停損", "恐慌", wlabel, code, name],
                {**r, "summary": r["summary_panic_sell"]})
            add(f"crash_buy_the_dip__{code}__{wk}", "阱底低接抱到現在 vs 崩盤前高點買進抱到現在",
                f"{name}（{code}）", f"{wlabel}：{name} 阱底加碼(低接) vs 高點買進，抱到現在差多少",
                ["崩盤", "加碼", "低接", wlabel, code, name],
                {**r, "summary": r["summary_buy_the_dip"]})

    return facts


# ── 「無資料、產線不該碰」主題黑名單（誠信硬規則：算不出來就明講，不編）────────
NO_DATA_BLACKLIST = [
    {"topic": "毛利率成長選股勝率", "reason": "需要各股歷年財報（毛利率）時間序列；本引擎/tw_data.py/quant-service 只有 OHLCV 股價資料，無財報基本面資料源。"},
    {"topic": "個股財報公布前後股價反應機率（如「財報前N個月就反映」）", "reason": "需要每股歷史財報公布日期 + 事件研究法；目前無財報日曆資料源。"},
    {"topic": "本益比/淨值比等估值指標選股回測", "reason": "需要歷史 EPS/BVPS 財報數據，非本引擎資料源涵蓋範圍。"},
    {"topic": "個股基本面選股(ROE/營收成長/毛利率門檻篩選)回測", "reason": "需批量財報資料庫（如公開資訊觀測站財報），本引擎僅有股價，無法計算。"},
    {"topic": "當沖/隔日沖真實勝率統計", "reason": "需要證交所逐筆成交/當沖歸戶統計資料，非公開歷史K線可推得；只能算「理論上手續費+滑價侵蝕」的機械試算，不可稱為『當沖勝率回測』。"},
    {"topic": "融資融券斷頭真實案例統計", "reason": "需要券商維持率/斷頭歷史事件資料庫，公開OHLCV無法重建。"},
    {"topic": "個股填息機率/填息天數統計", "reason": "可用 yfinance 股利資料理論上補做，但本次未實作(不在本次任務7大類清單內)；如需之後可加，目前不在 tw_stock_facts.json 內，產線不該引用。"},
    {"topic": "任何具體「勝率 X%」個股選股策略（未列於本引擎7大類方法論者）", "reason": "只要方法論未在本引擎程式碼中明確實作、可重現，一律視為未驗證，不得由 LLM 自行生成勝率數字。"},
]


def print_blacklist():
    print("=" * 70)
    print("【無資料、產線不該碰的主題黑名單】（本引擎目前算不出來，禁止 LLM 編數字頂替）")
    print("=" * 70)
    for item in NO_DATA_BLACKLIST:
        print(f"  ✗ {item['topic']}")
        print(f"      原因：{item['reason']}")


def main():
    ap = argparse.ArgumentParser(description="台股真回測事實引擎 v2")
    ap.add_argument("--dry", action="store_true", help="只印不寫檔")
    ap.add_argument("--refresh", action="store_true", help="忽略價格快取重抓")
    ap.add_argument("--symbols", type=str, default=None, help="只算指定標的(逗號分隔代碼，如 0050,2330)")
    ap.add_argument("--blacklist", action="store_true", help="只印黑名單後結束")
    args = ap.parse_args()

    if args.blacklist:
        print_blacklist()
        return 0

    only = [c.strip() for c in args.symbols.split(",")] if args.symbols else None

    try:
        facts = build_facts(refresh=args.refresh, only_symbols=only)
    except Exception as e:  # noqa: BLE001
        print(f"[tw_facts_engine] 建構失敗，保留舊檔不動：{e}")
        return 1

    n = len(facts.get("results", {}))
    print("-" * 70)
    print(f"[tw_facts_engine] as_of={facts['as_of']} 共算出 {n} 組真回測事實")
    for k, v in facts.get("results", {}).items():
        print(f"  · [{k}] {v.get('desc','')}")
        print(f"      {v.get('summary','')}")

    print_blacklist()

    if args.dry:
        print("[tw_facts_engine] --dry：不寫檔")
        return 0

    if n == 0 and OUT_FILE.exists():
        print("[tw_facts_engine] 本次 0 項，保留既有 tw_facts_computed.json 不覆蓋")
        return 0

    # ── 防「部分抓取」把事實庫縮水（2026-07-17 上排程前補的保險）──────────────────
    # build_facts() 對抓不到的標的是「略過該項」（誠信鐵則，不編數字）——這在單次手動跑很合理，
    # 但一旦上了每天的排程就變成風險：yfinance 被限流/暫時故障時，它仍會回傳「算得出來的那幾組」，
    # 直接覆蓋 → 事實庫從 50 組掉到剩幾組。後果不只是少素材：
    #   ① 餵料端（produce_batch/_load_tw_facts、topics_from_facts、tw_lab_engine）沒素材可注入；
    #   ② **更嚴重**：fact_source_guard 的「有憑據」數字池是直接從這份檔攤平出來的
    #      （fact_source_guard.py:298 fact_pool()），池縮水 → **已經寫好、待發布的稿子**
    #      會突然變成「查無憑據」被 fail-closed 擋掉 = 產線停擺。
    # 故：新結果若不到既有的 SHRINK_GUARD_RATIO，判定為抓取異常，保留舊檔不覆蓋。
    # 舊數字仍是真回測（固定窗、可重現），只是晚一天更新——這比縮水安全得多。
    SHRINK_GUARD_RATIO = 0.6
    if OUT_FILE.exists():
        try:
            old = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            old_n = len(old.get("results") or {})
        except Exception:  # noqa: BLE001
            old_n = 0
        if old_n and n < old_n * SHRINK_GUARD_RATIO:
            print(f"[tw_facts_engine] ⚠ 本次只算出 {n} 組，既有檔有 {old_n} 組"
                  f"（不到 {SHRINK_GUARD_RATIO:.0%}）→ 判定為抓取異常（yfinance 限流/故障？），"
                  f"保留舊檔不覆蓋。請查上面的『抓取失敗』行後手動重跑 --refresh。")
            return 1

    try:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[tw_facts_engine] 已寫入 {OUT_FILE}（{n} 組事實）")
    except Exception as e:  # noqa: BLE001
        print(f"[tw_facts_engine] 寫檔失敗（不崩）：{e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
