#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock_checkup_facts.py —【個股體檢·數據引擎】新系列「個股體檢」的事實庫。

背景（2026-07-15 任務，Carson 拍板新系列）：
頻道武器庫已有 tw_facts_engine.py（含息還原/資料清洗/CAGR·回撤方法論，鎖在一份精選
標的清單）與 twdata/cache/（tw_universe_facts.py 抓的全市場 1900+ 檔，但只 tail(180)
根K棒，是給動能訊號用的短窗快取，**不夠算 20 年體檢**）。本引擎補上「任意輸入一檔
代號 → 算出完整體檢報告」的能力：重用 tw_facts_engine 的含息還原/資料清洗/CAGR·MDD
數學（import 不複製，同一套邏輯只有一個真相來源），額外新增「持有體驗」類事實
（套牢期/腰斬次數/崩盤三段區間）——這是本系列的差異化核心，一般财經頻道只講報酬率，
不講「你要熬過幾年套牢」。

誠信鐵則（這個系列的生死線，同 tw_facts_engine 但再次強調）：
  - 只陳述歷史數據，不預測未來、不建議買賣、不給目標價、不喊「該進場/該出場」。
  - 個股點名＝歷史公開事實陳述（合法）；「介紹」≠「推薦」，語氣全程中性體檢。
  - 抓不到 / 資料不足(< MIN_YEARS) → 該項略過，寫進 facts["skipped"] 明確揭露，
    絕不編造或用示意數字冒充。
  - 每組事實都附 key/claim/data/method/period/source/computed_at/disclaimer
    （schema 與 tw_facts_computed.json 相容，供 fact_source_guard 溯源）。

用法：
  python scripts/stock_checkup_facts.py --code 2330            # 算 2330，寫入/合併進 STUDIO/stock_checkup_facts.json
  python scripts/stock_checkup_facts.py --code 2330 --dry      # 只印不寫
  python scripts/stock_checkup_facts.py --code 2330 --refresh  # 忽略價格快取重抓
  python scripts/stock_checkup_facts.py --backlog              # 印下集候選名單（未體檢過的優先）
  python scripts/stock_checkup_facts.py --next                 # 算 backlog 裡第一個還沒體檢過的代號

驗證：python -m py_compile scripts/stock_checkup_facts.py
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

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
STUDIO = ROOT / "STUDIO"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── 重用 tw_facts_engine 的數學/清洗邏輯（唯一真相來源，不複製）──────────────
from tw_facts_engine import (  # noqa: E402
    _sanitize_series, cagr, max_drawdown, calmar, pct, years_span,
    slice_trailing, calc_dca_vs_allin, DISCLAIMER, MIN_YEARS, MIN_BARS,
    CACHE_DIR as _SHARED_CACHE_DIR, pd_ts,
)
# 2026-07-15 任務(Carson拍板)：個股體檢加基本面。stock_fundamentals.py 是獨立的 FinMind
# 資料引擎(營收/EPS/毛利/股利/估值位置)，這裡只呼叫它的公開函式、不複製邏輯(唯一真相來源)。
import stock_fundamentals  # noqa: E402

OUT_FILE = STUDIO / "stock_checkup_facts.json"
CACHE_DIR = _SHARED_CACHE_DIR    # 跟 tw_facts_engine 共用同一份含息還原快取（同代碼＝同資料，別重抓）
CACHE_MAX_AGE_H = 20

SOURCE_NOTE = ("Yahoo Finance（yfinance，auto_adjust=True 含息還原收盤價；"
               "已過 _sanitize_series 清洗，砍除疑似分割/單位淨值重編未回溯調整的假跳空；"
               "與 tw_facts_engine.py 共用同一套資料清洗方法論）")

CHECKUP_HORIZON_YEARS = 20.0   # 主體檢窗口：20年，資料不足則退回「上市至今」

# ── 個股登記簿（EP1 + 下集候選池，Carson 拍板）──────────────────────────────
# 之後要體檢的代號不在這裡也能跑（--code 任意代號 + 選配 --name 覆蓋顯示名），
# 這份只是「已知名稱」查詢表 + 下集排隊順序。
STOCK_REGISTRY = {
    "2330":  {"name": "台積電",         "kind": "stock", "ticker": "2330.TW"},
    "2317":  {"name": "鴻海",           "kind": "stock", "ticker": "2317.TW"},
    "2454":  {"name": "聯發科",         "kind": "stock", "ticker": "2454.TW"},
    "2603":  {"name": "長榮",           "kind": "stock", "ticker": "2603.TW"},
    "2412":  {"name": "中華電",         "kind": "stock", "ticker": "2412.TW"},
    "2882":  {"name": "國泰金",         "kind": "stock", "ticker": "2882.TW"},
    "00878": {"name": "國泰永續高股息", "kind": "etf",   "ticker": "00878.TW"},
}
# 下集池順序（EP1＝2330 已產，不排在候選池裡；照 Carson 拍板順序）
# ⚠️ 2026-07-15 規模化後此清單已退役為「手動測試用」：正式排隊改走
#    STUDIO/stock_checkup_backlog.json(1900+檔·依成交值排序,由 stock_checkup_backlog_gen.py 生成)，
#    每日出集由 stock_checkup_daily.py 驅動。--next/--backlog 兩個 CLI 入口保留但只看這份小清單，
#    別拿它們當正式產線指令(正式產線 = cron 的 stock_checkup_daily.py)。
CHECKUP_BACKLOG = ["2317", "2454", "2603", "2412", "2882", "00878"]

BENCH_CODE = "0050"
BENCH_NAME = "元大台灣50"
BENCH_TICKER = "0050.TW"

# 崩盤三段區間（tw_facts_engine 只有 2020/2022，體檢系列多補 2008 金融海嘯——
# 「持有體驗」是本系列差異化核心，越多歷史風暴對照越有說服力）
CRASH_WINDOWS = {
    "crisis2008": {"label": "2008金融海嘯", "start": "2008-01-01", "end": "2008-11-30"},
    "covid2020":  {"label": "2020新冠崩盤", "start": "2020-01-01", "end": "2020-06-30"},
    "bear2022":   {"label": "2022台股熊市", "start": "2022-01-01", "end": "2022-12-31"},
}


# ── 資料層：抓 + 快取（含息還原收盤價；跟 tw_facts_engine 同套邏輯，泛化成任意代號）──
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


def _download(ticker):
    import yfinance as yf
    df = yf.download(ticker, period="max", auto_adjust=True, progress=False, threads=False)
    if df is None or len(df) == 0:
        return None
    col = df["Close"]
    if hasattr(col, "columns"):
        col = col.iloc[:, 0]
    s = col.dropna()
    import pandas as pd
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def fetch_series(code, ticker=None, refresh=False):
    """回傳 code 的含息還原收盤價 pd.Series；抓不到回 None。
    ticker 未給時預設 f"{code}.TW"（上市），抓不到再試 f"{code}.TWO"（上櫃）。"""
    if not refresh:
        cached = _load_cache(code)
        if cached is not None:
            return _sanitize_series(cached)
    tickers = [ticker] if ticker else [f"{code}.TW", f"{code}.TWO"]
    for tk in tickers:
        try:
            s = _download(tk)
        except Exception as exc:  # noqa: BLE001
            print(f"[stock_checkup_facts] {code}（{tk}）抓取失敗：{exc}")
            s = None
        if s is not None and len(s) >= 60:
            s = _sanitize_series(s)
            if s is not None and len(s) >= 60:
                _save_cache(code, s)
                return s
    return None


def resolve_name(code, name_override=None):
    if name_override:
        return name_override
    if code in STOCK_REGISTRY:
        return STOCK_REGISTRY[code]["name"]
    # 2026-07-15 規模化到1900+檔：未登錄代號改查 FinMind TaiwanStockInfo 全市場對照表
    # (7天快取，公開官方掛牌名稱，不是編的)；查不到才退回代碼本身當名稱。
    try:
        info = stock_fundamentals.fetch_stock_info_table()
        real_name = (info.get(code) or {}).get("name")
        if real_name:
            return real_name
    except Exception:  # noqa: BLE001
        pass
    return code  # 未登錄代號且查無官方名稱：用代碼本身當名稱（不編公司名）


def resolve_ticker(code):
    if code in STOCK_REGISTRY:
        return STOCK_REGISTRY[code]["ticker"]
    return None  # 未登錄：走 fetch_series 的 .TW/.TWO 自動 fallback


# ── 事實類型 A：20年(或上市至今)含息還原總報酬/年化/最大回撤 ────────────────
def calc_long_horizon(s):
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    if span > CHECKUP_HORIZON_YEARS:
        s_use = slice_trailing(s, CHECKUP_HORIZON_YEARS)
        label = f"近{CHECKUP_HORIZON_YEARS:.0f}年"
    else:
        s_use = s
        label = f"上市以來（資料可信區間）約{span:.1f}年"
    use_span = years_span(s_use)
    y0, y1 = float(s_use.iloc[0]), float(s_use.iloc[-1])
    tr = y1 / y0 - 1.0
    cagr_val = cagr(y0, y1, use_span)
    mdd = max_drawdown(s_use)
    cal = calmar(cagr_val, mdd)
    return {
        "label": label, "years": round(use_span, 1),
        "start": str(s_use.index[0].date()), "end": str(s_use.index[-1].date()),
        "total_return": tr, "cagr": cagr_val, "max_drawdown": mdd, "calmar": cal,
        "summary": (f"{label}含息還原總報酬 {pct(tr)}（年化 {pct(cagr_val)}、"
                    f"最大回撤 {pct(mdd)}"
                    + (f"、卡瑪比率 {cal:.2f}）" if cal is not None else "）")),
    }


# ── 事實類型 B：最慘一年 / 最猛一年（年度報酬序列，計整年至少約100個交易日）───

# 🔴 2026-08-31 未完結年度要標示。本函式收年度報酬時的門檻是「至少約 100 交易日」,
# 所以**還沒過完的今年**會被收進來 —— 而舊的 summary 字面稱它「完整年度」,
# 等於把半年的漲幅講成一整年的。實例:欣興 3037「最猛一年是 2026年,該年報酬 263.3%」,
# 而 2026 只有 129 根(完整年度 244~251 根)。548 檔裡有 50 檔(9%)踩到。
#
# 標示刻意寫進**那一年自己的片語裡**,不是加在句尾當補充句 —— 句尾的補充是
# 可以被單獨丟掉的(同日實測:警語獨立成句時,28 句裡 18 句把它丟了)。
_FULL_YEAR_BARS = 200   # 完整年度實測 244~251 根;低於 200 就不是完整年度


def _yr_label(row, series):
    """把年度標成「2008年」或「2026年(僅到 07-17、尚未過完)」。"""
    y = row["year"]
    if row.get("n_bars", 0) >= _FULL_YEAR_BARS:
        return f"{y}年"
    try:
        last = series.index[-1]
        if last.year == y:
            return f"{y}年（僅到 {last.month:02d}-{last.day:02d}、尚未過完）"
    except Exception:  # noqa: BLE001
        pass
    return f"{y}年（資料不足一整年）"

def calc_annual_extremes(s):
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    import pandas as pd
    rows = []
    for yr, grp in s.groupby(s.index.year):
        grp = grp.sort_index()
        if len(grp) < 100:   # 上市/資料首尾的殘年，樣本太薄不列入極值比較
            continue
        p0, p1 = float(grp.iloc[0]), float(grp.iloc[-1])
        if p0 <= 0:
            continue
        rows.append({"year": int(yr), "return": p1 / p0 - 1.0, "n_bars": len(grp)})
    if len(rows) < 3:
        return None
    rows.sort(key=lambda r: r["return"])
    worst, best = rows[0], rows[-1]
    return {
        "n_full_years": len(rows),
        "years": round(span, 1),
        "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "worst_year": worst, "best_year": best,
        "annual_returns": rows,
        "summary": (f"年度資料共 {len(rows)} 年（{_yr_label(worst, s)}最慘，"
                    f"報酬 {pct(worst['return'])}；{_yr_label(best, s)}最強，"
                    f"報酬 {pct(best['return'])}）"),
    }


# ── 事實類型 C：單筆 All-in vs 月定投(10年) vs 同期 0050 買進持有 ────────────
def calc_three_way_showdown(stock_s, bench_s, stock_name, years=10.0):
    if stock_s is None or bench_s is None:
        return None
    span = years_span(stock_s)
    if span < MIN_YEARS:
        return None
    s_use = slice_trailing(stock_s, years) if span > years else stock_s
    common_start = max(s_use.index[0], bench_s.index[0])
    s_use = s_use[s_use.index >= common_start]
    b_use = bench_s[bench_s.index >= common_start]
    if len(s_use) < MIN_BARS or len(b_use) < MIN_BARS:
        return None
    use_span = years_span(s_use)
    if use_span < MIN_YEARS:
        return None
    stock_pack = calc_dca_vs_allin(s_use)
    if not stock_pack:
        return None
    b_tr = float(b_use.iloc[-1]) / float(b_use.iloc[0]) - 1.0
    b_cagr = cagr(b_use.iloc[0], b_use.iloc[-1], years_span(b_use))
    b_mdd = max_drawdown(b_use)
    return {
        "years": round(use_span, 1),
        "start": str(common_start.date()), "end": str(s_use.index[-1].date()),
        "stock_allin": stock_pack["allin"], "stock_dca": stock_pack["dca"],
        "bench": {"ticker": BENCH_CODE, "total_return": b_tr, "cagr": b_cagr, "max_drawdown": b_mdd},
        "summary": (f"近{round(use_span,1)}年（{common_start.date()}起，可信資料共同起點）：{stock_name}"
                    f"單筆All in總報酬 {pct(stock_pack['allin']['total_return'])}"
                    f"（年化 {pct(stock_pack['allin']['cagr'])}、最大回撤 {pct(stock_pack['allin']['max_drawdown'])}）；"
                    f"{stock_name}每月定期定額總報酬 {pct(stock_pack['dca']['total_return'])}"
                    f"（年化 {pct(stock_pack['dca']['cagr'])}、最大回撤 {pct(stock_pack['dca']['max_drawdown'])}）；"
                    # 🔴 2026-08-22 根因修復：這裡原本寫「**同期**買進持有 0050」。「同期」是
                    # 相對詞，只在本段(近 N 年)的脈絡裡成立；而寫稿的 LLM 拿到的是
                    # long_horizon(18~20 年)與本組(10 年)**兩條並排的 claim**，它把「同期」
                    # 連同 0050 的數字整個抄去接 20 年的個股報酬，「同期」就從敘述變成謊。
                    # 實測:已出廠體檢片 80% 中招、產線現況仍 50%——prompt 軟規則(LONG_RULES ⓜ)
                    # 壓不住，gate 攔了也只是重生賭運氣(三次全中就停產)。把期間寫死進數字旁邊，
                    # 讓「抄過去」這個動作本身就自帶期間，才是結構上的修法。
                    # 🔴 2026-08-28 再修一次:上一版把年數寫在「買進持有」**前面**,
                    # 而模型抄的是「總報酬 751.5%」那一小段 —— 期間留在原地,抄過去就掉了。
                    # 實測 08-28 一天 19 支因期間偷換被 fail-closed,而且**剝掉 prompt 洩漏
                    # 後照樣中**(不是假陽性)。被咬的句子長這樣:
                    #   「比較**這段期間**購買0050的投資報酬率約為712.0%」
                    #   「**同期**投資臺灣加權指數的0050，總報酬率約為701.9%」
                    # ——句子裡一個年數都沒有,模型用「這段期間/同期」指涉前文,
                    # 而前文常常是 20 年的個股報酬。
                    # 也就是說:把 claim 裡的「同期」兩個字拿掉沒有用,**模型會自己造同義詞**。
                    # 唯一結構上有效的做法是把年數**黏進數字本身**,讓它變成一個抄不散的整體:
                    #   「總報酬 751.5%」→「近10.0年總報酬 751.5%」
                    # 這樣不管模型抄哪一小段,年數都跟著走。
                    f"同一{round(use_span,1)}年區間（{common_start.date()}起）買進持有 "
                    f"{BENCH_NAME}（0050）"
                    f"近{round(use_span,1)}年總報酬 {pct(b_tr)}"
                    f"（近{round(use_span,1)}年年化 {pct(b_cagr)}、"
                    f"近{round(use_span,1)}年最大回撤 {pct(b_mdd)}）"
                    # ⚠️ 只給 **0050** 的三個數字黏年數,個股那兩段不動 ——
                    # 個股報酬本來就在同句的近N年脈絡裡,再黏一次只會讓旁白唸起來囉唆,
                    # 而期間偷換的方向一律是「拿 10 年的 0050 去配 20 年的個股」,
                    # 要防的是 0050 那個數字被抄走時掉了期間。
                    f"〔此 0050 數字**只適用這{round(use_span,1)}年**，不可拿去跟其他組"
                    f"(如上市以來/近20年)的個股報酬並列說「同期」;"
                    f"引用時務必連「近{round(use_span,1)}年」一起寫〕"),
    }


# ── 事實類型 D：持有體驗——最長套牢期(ATH到下個ATH) ──────────────────────────
def calc_underwater(s):
    """最長「創新高→下個新高」間隔天數；若目前仍未創新高，計到最新一天並標註仍在套牢中。"""
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    running_peak = float(s.iloc[0])
    prev_ath_date = s.index[0]
    max_gap_days = 0
    max_gap_start, max_gap_end = None, None
    for dt_, px in s.items():
        px = float(px)
        if px >= running_peak:
            gap_days = (dt_ - prev_ath_date).days
            if gap_days > max_gap_days:
                max_gap_days = gap_days
                max_gap_start, max_gap_end = prev_ath_date, dt_
            running_peak = px
            prev_ath_date = dt_
    still_underwater = float(s.iloc[-1]) < running_peak
    tail_gap_days = (s.index[-1] - prev_ath_date).days
    ongoing = False
    if still_underwater and tail_gap_days > max_gap_days:
        max_gap_days = tail_gap_days
        max_gap_start, max_gap_end = prev_ath_date, None
        ongoing = True
    if max_gap_start is None:
        return None
    years_gap = max_gap_days / 365.25
    return {
        "years": round(span, 1), "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "max_underwater_days": max_gap_days, "max_underwater_years": round(years_gap, 1),
        "from_ath_date": str(max_gap_start.date()),
        "to_new_ath_date": str(max_gap_end.date()) if max_gap_end is not None else None,
        "ongoing": ongoing,
        "summary": (
            (f"史上最長套牢期：從 {max_gap_start.date()} 創高後，一路等到 {max_gap_end.date()} 才創下個新高，"
             f"整整等了 {round(years_gap,1)} 年（{max_gap_days} 天）")
            if not ongoing else
            (f"目前正處於史上最長套牢期：從 {max_gap_start.date()} 創高至今（{s.index[-1].date()}）"
             f"已經 {round(years_gap,1)} 年（{max_gap_days} 天）還沒創下一個新高")
        ),
    }


# ── 事實類型 E：持有體驗——腰斬(-50%)次數 ────────────────────────────────────
def calc_halvings(s):
    """從每個新高點算起，跌幅觸及 -50% 的distinct事件數（重新武裝條件＝再創出高於前次的新高）。"""
    if s is None or len(s) < MIN_BARS:
        return None
    span = years_span(s)
    if span < MIN_YEARS:
        return None
    running_peak = float(s.iloc[0])
    peak_date = s.index[0]
    in_deep = False
    events = []
    for dt_, px in s.items():
        px = float(px)
        if px > running_peak:
            running_peak = px
            peak_date = dt_
            in_deep = False
            continue
        dd = px / running_peak - 1.0
        if dd <= -0.5 and not in_deep:
            events.append({"from_peak_date": str(peak_date.date()), "from_peak_price": round(running_peak, 2),
                            "halved_date": str(dt_.date()), "halved_price": round(px, 2),
                            "drawdown": round(dd, 4)})
            in_deep = True
    n = len(events)
    listed = ", ".join(f"{e['from_peak_date']}高點起跌到{e['halved_date']}腰斬" for e in events[:3])
    return {
        "years": round(span, 1), "start": str(s.index[0].date()), "end": str(s.index[-1].date()),
        "n_halvings": n, "events": events,
        "summary": (f"{round(span,1)}年資料裡，從高點算起腰斬(-50%以上)發生過 {n} 次"
                    + (f"（{listed}{'...' if n > 3 else ''}）" if n else "（一次都沒有）")),
    }


# ── 事實類型 F：崩盤三段區間表現(若持有到現在) ───────────────────────────────
def calc_crash_window(s, win_key):
    win = CRASH_WINDOWS[win_key]
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
    latest_date, latest_price = s.index[-1], float(s.iloc[-1])
    trough_dd = trough_price / peak_price - 1.0
    hold_through_return = latest_price / peak_price - 1.0
    return {
        "window": win["label"], "window_start": win["start"], "window_end": win["end"],
        "peak_date": str(peak_date.date()), "peak_price": round(peak_price, 2),
        "trough_date": str(trough_date.date()), "trough_price": round(trough_price, 2),
        "trough_drawdown": trough_dd,
        "latest_date": str(latest_date.date()), "latest_price": round(latest_price, 2),
        "hold_through_return": hold_through_return,
        "summary": (f"{win['label']}期間：從高點（{peak_date.date()}）跌到阱底（{trough_date.date()}）"
                    f"共跌 {pct(trough_dd)}；若當時沒賣、一路抱到現在（{latest_date.date()}）："
                    f"報酬 {pct(hold_through_return)}"),
    }


# ── 主流程：算一檔的完整體檢報告 ─────────────────────────────────────────────
def build_checkup(code, name_override=None, refresh=False):
    as_of = _dt.date.today().isoformat()
    name = resolve_name(code, name_override)
    ticker = resolve_ticker(code)
    kind = STOCK_REGISTRY.get(code, {}).get("kind", "stock")

    print(f"[stock_checkup_facts] 抓取 {code}（{name}）...")
    s = fetch_series(code, ticker=ticker, refresh=refresh)
    bench = fetch_series(BENCH_CODE, ticker=BENCH_TICKER, refresh=refresh)
    if s is None:
        print(f"[stock_checkup_facts] {code} 抓取失敗，無法體檢")
        return None, []
    print(f"[stock_checkup_facts] {code}（{name}）資料：{len(s)} 筆 {s.index[0].date()}~{s.index[-1].date()}"
          f"（{years_span(s):.1f} 年）")

    results = {}
    skipped = []

    def add(key, method, desc, keywords, payload):
        if not payload:
            skipped.append({"key": key, "desc": desc, "reason": "資料不足(< MIN_YEARS 或樣本不夠)，本次略過未產出"})
            return
        results[key] = {
            "key": key,
            "claim": payload.get("summary", desc),
            "desc": desc,
            "summary": payload.get("summary", desc),
            "keywords": keywords,
            "method": method,
            "symbol": f"{name}（{code}）",
            "period": f"{payload.get('start', '?')}~{payload.get('end', '?')}",
            "source": SOURCE_NOTE,
            "computed_at": as_of,
            "disclaimer": DISCLAIMER,
            "data": payload,
        }

    # ⚠️ 2026-07-15 病灶A同型bug實測抓到(見 produce_batch.py 同名教訓)：keywords 若帶
    # 「套牢」「崩盤」「持有體驗」這類跨股共用的通用描述詞，_tw_facts_context()／
    # _relevant_facts_list() 的比對邏輯是單純 `kw in text` 子字串命中，沒有標的鎖定，
    # 通用詞會讓「鴻海2317」的題目意外撈到「台積電」的事實(兩者都有「持有體驗」關鍵字)。
    # 實測驗證：keywords 只留 [code, name] 兩個字詞後，_tw_facts_context() 對
    # 「個股體檢EP2鴻海2317…」題目只回鴻海自己的事實，不再混入台積電——這是本引擎
    # keywords 刻意收斂到最小(只留能唯一辨識該標的的詞)的原因，不是漏寫。

    # A. 20年(或上市至今)總報酬/年化/最大回撤
    add(f"checkup_long_horizon__{code}",
        "20年(可信資料區間不足20年則用上市至今)含息還原總報酬/年化/最大回撤/卡瑪比率",
        f"{name} 長期含息還原體檢", [code, name],
        calc_long_horizon(s))

    # B. 最慘一年 / 最猛一年
    add(f"checkup_annual_extremes__{code}",
        "年度報酬序列(整年至少約100交易日才列入)，取最大值/最小值",
        f"{name} 最猛一年 vs 最慘一年", [code, name],
        calc_annual_extremes(s))

    # C. 單筆All-in vs 月定投(10年) vs 同期0050
    add(f"checkup_three_way__{code}",
        "近10年(資料不足10年則用共同起點全段)：單筆All-in vs 每月定期定額 vs 同一區間買進持有0050",
        f"{name} 三種買法對決：All-in / 定期定額 / 0050", [code, name],
        calc_three_way_showdown(s, bench, name) if bench is not None else None)

    # D. 持有體驗：最長套牢期
    add(f"checkup_underwater__{code}",
        "從每次創歷史新高算起，到下一次創歷史新高之間的最長間隔(天數/年數)；若目前仍未創新高則計到最新一天並標註ongoing",
        f"{name} 最長套牢期(創高到下個創高間隔)", [code, name],
        calc_underwater(s))

    # E. 持有體驗：腰斬次數
    add(f"checkup_halvings__{code}",
        "從每個新高點算起，股價跌幅觸及-50%的獨立事件數(重新武裝條件=再創出高於前次的新高)",
        f"{name} 腰斬(-50%)發生次數", [code, name],
        calc_halvings(s))

    # F. 崩盤三段區間表現
    for wk in CRASH_WINDOWS:
        r = calc_crash_window(s, wk)
        wlabel = CRASH_WINDOWS[wk]["label"]
        add(f"checkup_crash__{code}__{wk}",
            f"{wlabel}期間：高點到阱底跌幅 + 若持有至今的報酬(未計股利再投入外的其他操作)",
            f"{name}：{wlabel}期間表現", [code, name],
            r)

    # G. 基本面(2026-07-15 任務)：營收趨勢/EPS序列/毛利率/股利發放史/估值位置——見 stock_fundamentals.py。
    # 傳入已經抓好的含息還原價序列 s，讓股利殖利率計算不必重抓一次價格。
    # FinMind 抓不到/失敗不讓整支體檢失敗——fund_results 空字典時下面 update 是 no-op，
    # fund_skipped 會如實記進 skipped 揭露(不編造)。
    try:
        fund_results, fund_skipped, profile = stock_fundamentals.build_fundamentals_facts(
            code, name, price_series=s, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        print(f"[stock_checkup_facts] {code} 基本面抓取整體失敗(不影響已算出的價格面事實)：{str(exc)[:120]}")
        fund_results, fund_skipped, profile = {}, [], {}
    results.update(fund_results)
    skipped.extend(fund_skipped)

    facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": results,
             "skipped": skipped, "code": code, "name": name, "kind": kind, "profile": profile}
    return facts, skipped


def _load_existing():
    """讀共用事實庫。**讀不掉就拋,絕對不可以回空骨架。**

    🔴 2026-09-09:原本「檔案不存在」和「檔案在但讀不掉」**回同一個空骨架**,
       而 `merge_and_write()` 會拿那個骨架 + 這一支的事實 `write_text` 回 17MB 的正式檔
       ⇒ **198 支已發布片的事實一次全部消失**,而且它照樣印「已寫入」。

       這條鏈的其他兩環(`:596` 的 `write_text` 無 tmp、印「已寫入」不看結果)還在,
       但**任何一環修好都能斷鏈**,而讀取端是最便宜的那一環。

       ⚠️ 為什麼刪掉之後就回不來:`snapshot_studio.py:109` 每天 04:05 `rmtree` 掉
       `KEEP_DAYS=7` 之外的快照。而 2026-09-09 實測 —— **7 個快照夾都在,
       但這個檔只存在於其中 2 個**(它 09-07 才進 `KEY_FILES`)⇒ **復原窗口是 2 天不是 7 天。**
       靜默寫壞 → 零訊號 → 第 3 天最後一份好的被刪掉 → 永久答不出「這句數字哪來的」。

       ⚠️ **fail-closed 是刻意的**:代價是那一天的個股體檢不合併(明天重跑就好),
       換掉的是不可逆的資料毀損。這個不對稱大到不需要猶豫。
       呼叫鏈已查過會產生輸出:`stock_checkup_daily.py:441` 的 `merge_and_write` 在 try **外面**,
       `:481` 的 `process_one` 也沒有被包起來 ⇒ 例外會一路傳出 `main()`,
       traceback 落 `logs/job_stderr.log`。**這道防護不是「期望」,它失敗時會產生輸出。**

       ⚠️ 同一個形狀 09-09 在 `quota_ceiling_watch.py` 也咬過一次:
       判準綁在「解析失敗」上,而「合法 JSON 但少了關鍵鍵」照樣走進「第一次跑」那條。
       所以這裡的判準是**檔案在不在**,而且合法 JSON 也要驗形狀。
    """
    if not OUT_FILE.exists():
        # 真的第一次(或有人刻意清空重建)——這一條才可以回空骨架。
        return {"as_of": None, "disclaimer": DISCLAIMER, "results": {}, "by_code": {}}

    try:
        raw = OUT_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        size = OUT_FILE.stat().st_size if OUT_FILE.exists() else -1
        msg = (f"[stock_checkup_facts] 🔴 事實庫存在但讀不掉,拒絕繼續 —— "
               f"{OUT_FILE}({size:,} bytes):{exc!r}\n"
               f"    **不要重跑、不要刪掉它**。繼續下去會用一個空骨架覆蓋整個檔案。\n"
               f"    先去 STUDIO/_snapshots/ 找最近一份好的("
               f"⚠️ 這個檔的快照只回溯得到 2 天,snapshot_studio 每天 04:05 會刪 7 天以外的)。")
        print(msg)          # 第二條通道:落 logs/jobout/<腳本>.log
        raise RuntimeError(msg) from exc

    # 合法 JSON 不代表是這個檔。少了 results 就當成讀壞 —— 這一格是 quota 那次的教訓:
    # 判準只問「parse 成不成功」時,「合法但少鍵」會靜靜走進「第一次跑」那條路。
    # ⚠️ `results` **本身也要驗型別**,不是「鍵在不在」就好(2026-09-09 獨立驗證補的一格):
    #    `{"results": null}` / `{"results": []}` 過得了「鍵在不在」這關,
    #    後面 merge_and_write 才在 `.update()` 上拋 TypeError/AttributeError。
    #    那仍然是 fail-closed(寫入**之前**就拋、檔案零改動),但**訊息會變成一個看不懂的型別錯誤** ——
    #    而看不懂的錯誤訊息會被下一個人當成「這支壞了」去重跑,那正是最不該做的事。
    if (not isinstance(data, dict) or not isinstance(data.get("results"), dict)):
        msg = (f"[stock_checkup_facts] 🔴 事實庫 parse 得動但形狀不對,拒絕繼續 —— "
               f"{OUT_FILE}:type={type(data).__name__}、"
               f"results={type(data.get('results')).__name__ if isinstance(data, dict) else 'n/a'}、"
               f"keys={sorted(data)[:8] if isinstance(data, dict) else 'n/a'}\n"
               f"    同樣**不要重跑、不要刪掉它**,先去 STUDIO/_snapshots/ 取回"
               f"(實測 09-08 / 09-09 兩份都在且 parse 得動,再往前就沒有了)。")
        print(msg)
        raise RuntimeError(msg)
    return data


def _atomic_write_json(path: Path, obj, *, expect_results: int, expect_by_code: int,
                       min_ratio: float = 0.5, min_floor: int = 1_000_000,
                       replace_attempts: int = 6):
    """原子寫 JSON:tmp → 讀回比對 → `os.replace`。回傳 (bytes, n_results, n_by_code)。

    🔴 2026-09-09:這是「事實庫被寫壞」證據鏈的**防止**那一環。
       讀取端的 fail-closed(`_load_existing`)是**攔住**——它在下一輪才發現檔案壞了,
       而那時檔案已經死了。實測:17,918,507 bytes 的正式檔被 `open(...,'w')` 截斷後中止
       ⇒ **0 bytes**,而 0 bytes 對下游是合法的「零筆」(memory `write-truncates-before-it-fails`)。

       `Path.write_text()` 的形狀是「先截斷正式檔,再一路寫」——**中途死掉就沒有原檔了**。
       這裡改成三段,任何一段失敗時正式檔都**一個 byte 沒被碰過**:
         ① 序列化在記憶體裡做完(json.dumps 拋例外時,連 tmp 都還沒開)
         ② 寫進**同目錄**的 tmp、fsync、**讀回逐位比對 + parse 得動 + 不變量對得上**
         ③ 全過才 `os.replace`(同一個檔案系統 ⇒ 原子替換,不存在「換到一半」)
       tmp 帶 pid ⇒ 兩個行程同時跑不會互踩對方的暫存檔。

    ⚠️ **為什麼不直接用 `studio_common.save_json_atomic()`**(它存在,而且 20+ 支腳本在用):
       它做的是 tmp → `os.replace` + per-path lock + `PermissionError` 重試 + **覆寫前 `.bak`**,
       但**沒有讀回比對、沒有形狀檢查、沒有縮水下限** —— 而這條事故鏈要防的正好是那三樣。
       ⇒ 這裡自己做,不是不知道有那支。**要改的話應該是把這三格上收到 `save_json_atomic`**,
         但那會一次影響 20+ 支腳本(有些檔案本來就會合法縮水),屬於另一件事,要獨立驗。
       ⚠️ 也**刻意不做 `.bak`**:這個檔的 `.bak` 由每週日的 `checkup_industry_rank.py --apply`
          產生(實測 `stock_checkup_facts.json.bak` = 09-06 06:05,16.9 MB)。
          本函式每天跑,若也寫 `.bak` 會把「一週的深度」壓成「一天」,**備份反而變淺**。

    ⚠️ **`expect_*` 這組不變量的射程要講清楚,不要高估它**(2026-09-09 獨立驗證糾正過我一次):
       它是呼叫端從**即將寫出去的那個物件**算的,所以它只量得到「序列化 → 落盤 → 讀回」
       這一段有沒有走樣。**上游把資料弄丟了它一律看不到** —— 實測把 `_load_existing()`
       換成回空骨架,651 檔 → 1 檔而這組不變量**不會叫**。
       擋那條的是下面的**縮水下限**(問磁碟 `stat()`,不看任何 in-memory 物件)、
       `_load_existing()` 自己的 fail-closed、以及 `merge_and_write` 對**輸入**的檢查。
       (memory `verification-that-cannot-fail`:拿寫出去的內容驗寫出去的內容恆為真。
        這裡不是恆為真,但它的定義域比「檔案有沒有被寫壞」小很多。)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # ① 記憶體裡先做完
    try:
        blob = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        msg = (f"[stock_checkup_facts] 🔴 序列化失敗,正式檔一個 byte 沒被碰過 —— "
               f"{path}:{exc!r}")
        print(msg)          # 不印的話,job_stderr 以外看不到任何線索
        raise RuntimeError(msg) from exc

    # 🔴 縮水下限:這一格**不看 `_load_existing()` 的結果**,直接問磁碟。
    #    2026-09-09 獨立驗證抓到的:`expect_*` 是呼叫端從**同一個 in-memory 物件**算的,
    #    所以「上游把舊資料弄丟了」它一律看不到 —— 實測把 `_load_existing` 換成回空骨架,
    #    651 檔 → 1 檔、17.9 MB → 1,010 bytes,原本的不變量**不會叫**,還照樣印「已寫入」。
    #    (memory `verification-that-cannot-fail`:拿寫出去的東西驗寫出去的東西恆為真。)
    #    ⚠️ 合法的縮水只有「同一個代號改版後事實變少」,在 8,000+ 組裡是 < 1% 的量級;
    #       0.5 這個門檻離合法縮水很遠,離 0.006%(那次事故)更遠。
    #    要刻意重建整個檔:先把舊檔刪掉/移走,走 `_load_existing` 的「真的第一次」那條路。
    #
    # ⚠️ `min_floor`:比率門檻只對**已經累積起來的大檔**開。獨立驗證實測,單一代號佔全檔 > 50%
    #    的小檔(實務上 = **≤2 個代號的檔**)重算後會被誤擋:6 組 → 1 組,1,286 → 484 bytes(37.6%)。
    #    正式檔 651 個代號、單代號最多 14/8,137 ≈ 0.17%,打不到;但 `yt_ch2` 那份**冷啟動前幾天會撞**。
    #    這道閘門要防的是「累積了很久的帳本一次塌掉」,檔案還小的時候本來就沒有那個東西可以塌。
    prev_size = path.stat().st_size if path.exists() else 0
    if prev_size >= min_floor and len(blob) < prev_size * min_ratio:
        msg = (f"[stock_checkup_facts] 🔴 要寫的內容比現有正式檔小太多,拒絕寫入 —— "
               f"{path}:現有 {prev_size:,} bytes、要寫 {len(blob):,} bytes"
               f"({len(blob) / prev_size:.1%},門檻 {min_ratio:.0%},"
               f"只對 ≥ {min_floor:,} bytes 的檔開)。"
               f"    正式檔**一個 byte 都沒被碰過**。這通常代表上游讀到的舊資料不完整,"
               f"先查 `_load_existing()` 讀到了什麼,**不要刪檔重跑**。")
        print(msg)
        raise RuntimeError(msg)

    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        # ② tmp + fsync + 讀回
        with open(tmp, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        back = tmp.read_bytes()
        if back != blob:
            raise RuntimeError(
                f"[stock_checkup_facts] 🔴 暫存檔讀回比對不符,拒絕替換正式檔 —— "
                f"{tmp}:寫出 {len(blob):,} bytes、讀回 {len(back):,} bytes。"
                f"正式檔 {path} **一個 byte 都沒被碰過**,原資料還在。")
        reloaded = json.loads(back.decode("utf-8"))
        n_res = len(reloaded.get("results") or {})
        n_by = len(reloaded.get("by_code") or {})
        if (not isinstance(reloaded.get("results"), dict)
                or n_res != expect_results or n_by != expect_by_code):
            raise RuntimeError(
                f"[stock_checkup_facts] 🔴 暫存檔不變量不符,拒絕替換正式檔 —— "
                f"results {n_res:,} 應為 {expect_results:,}、"
                f"by_code {n_by:,} 應為 {expect_by_code:,}。"
                f"正式檔 {path} **一個 byte 都沒被碰過**,原資料還在。")
        # ③ 只有前面全過才動正式檔
        #    🔴 Windows:目標檔被任何人開著讀時,`os.replace` 會 PermissionError(WinError 5) ——
        #       這是本修法**新引入**的失敗模式,舊碼的 `write_text` 在同情境下寫得進去
        #       (2026-09-09 獨立驗證實測)。這個檔有十幾個讀取端(produce_batch /
        #       per_stock_fact_gate / fact_source_guard …),05:50 那班撞上任一個就整天白算。
        #       ⇒ 退避重試。重試期間正式檔仍然一個 byte 沒被碰過,失敗也只是「今天不合併」。
        last_exc = None
        for attempt in range(replace_attempts):
            try:
                os.replace(tmp, path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                if attempt == replace_attempts - 1:
                    break
                time.sleep(0.5 * (2 ** attempt))
        if last_exc is not None:
            msg = (f"[stock_checkup_facts] 🔴 替換正式檔失敗({replace_attempts} 次全被拒)—— "
                   f"{path}:{last_exc!r}"
                   f"    最可能是有別的程序正開著這個檔在讀(Windows 不准替換被開啟的檔)。"
                   f"    正式檔**一個 byte 都沒被碰過**,暫存檔已清掉。等那支讀完再重跑即可。")
            print(msg)
            raise RuntimeError(msg) from last_exc
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    # ④ 替換後再看一眼。⚠️ 這格**不拋**:os.replace 回來時檔案已經是驗過的那份,
    #    此時對不上最可能的解釋是「另一個行程在我們之後也寫了」——那是資訊不是我們的毀損。
    #    但它必須**產生輸出**,否則就是一格不會叫的檢查。
    final = path.stat().st_size
    if final != len(blob):
        print(f"[stock_checkup_facts] ⚠️ 替換後大小對不上:{final:,} bytes,"
              f"我們寫的是 {len(blob):,} bytes ⇒ 很可能有另一個行程在我們之後也寫了同一個檔。"
              f"資料沒有被我們寫壞(替換前已逐位驗過),但**這個檔現在不是我們那一份**。")
    return len(blob), n_res, n_by


# ── 事實庫 key 的歸屬表(2026-09-09,方案書 docs/ops/2026-09-09_design_fact_key_ownership.md §3.1)──
#
# `STUDIO/stock_checkup_facts.json` 的 `results` 是**多個寫入端共用**的 key 命名空間,
# 而 `merge_and_write()` 需要「清掉本代號改版後失效的欄位」。這兩件事只有一個東西分得開:
# **前綴**。前綴 = key 第一個 `__` 之前那一段(實測正式檔 8,137 個 key、13 個相異前綴)。
#
# ⚠️ 這兩張表是**靜態清單**,它們不會自己發現世界變了。
#    唯一讓它們過期時出聲的東西是 `merge_and_write()` 裡對未知前綴印的那行告警,
#    以及 `checkup_facts_prefix_health.py`(按前綴分組量覆蓋率)。表改了記得兩邊一起想。

# 本腳本(含它呼叫的 stock_fundamentals.build_fundamentals_facts)產出的前綴 ⇒ **可以刪**。
# 這正是原本「清掉改版後失效欄位」的用意,改版後不再產出的欄位要清得掉。
# 來源不是印象,是逐行對過程式碼:
#   · 本檔 build_checkup() 的 add(f"checkup_xxx__{code}") 六處
#   · stock_fundamentals.py:476 `key = f"checkup_{slug}__{code}"`,slug 取自同檔 PLAN 的五個項目
OWNED_PREFIXES = frozenset({
    # 價格面(本檔 build_checkup 直接產)
    "checkup_long_horizon",
    "checkup_annual_extremes",
    "checkup_three_way",
    "checkup_underwater",
    "checkup_halvings",
    "checkup_crash",            # 唯一三段式 key:checkup_crash__{code}__{window}
    # 基本面(stock_fundamentals.PLAN 的五個 slug)
    "checkup_revenue_trend",
    "checkup_eps_trend",
    "checkup_gross_margin",
    "checkup_dividend_history",
    "checkup_valuation_position",
})

# 別的寫入端產的前綴 ⇒ **保留,不出聲**(這是預期狀態,不是異常,不要每輪印它)。
#   · checkup_industry_rank.py:108  `key = f"checkup_industry_rank__{code}"`
#   · checkup_industry_rank.py:144  `key = f"checkup_industry_summary__{ind}"`(產業名,不是代號)
# 兩者都由 crontab 每週日 06:40 的 `checkup_industry_rank.py --apply` 寫入。
FOREIGN_PREFIXES = frozenset({
    "checkup_industry_rank",
    "checkup_industry_summary",
})


def _key_prefix(key: str) -> str:
    """key 的前綴 = 第一個 `__` 之前那一段。

    ⚠️ 只用 `split("__", 1)[0]`,**不要**先做別的正規化。
       memory `flattened-key-hides-evidence`:把三段式 key(`checkup_crash__2330__gfc`)
       壓平成兩段會讓同一檔的三個崩盤視窗折成一筆,證據在眼前消失。
       這裡取第一段是**取前綴**,不是壓平 —— 回傳值只拿來查表,不拿來當 key 用。
    """
    return key.split("__", 1)[0]

def merge_and_write(facts, dry=False):
    """把單一代號的體檢結果合併進共用檔（別的代號已算出的事實不動）。"""
    existing = _load_existing()
    existing.setdefault("results", {})
    existing.setdefault("by_code", {})
    # 🔴 在**動它之前**記下來 —— 事後再算就是拿結果驗結果。
    code_for_scope = facts["code"]
    others_before = sum(1 for k in existing["results"]
                        if not (k.endswith(f"__{code_for_scope}")
                                or f"__{code_for_scope}__" in k))
    codes_before = set(existing["by_code"])
    existing["as_of"] = facts["as_of"]
    existing["disclaimer"] = DISCLAIMER
    code = facts["code"]
    # 🔴 輸入端閘門:本次算出的事實,每個 key 都必須屬於本代號。
    #    判準放在**輸入**上而不是合併後的總數上,因為總數擋不住「覆寫」——
    #    `facts["results"]` 若含一個**已存在**的別人的 key,`update()` 會蓋掉它而筆數不變
    #    ⇒ 數量型判準恆等 ⇒ 不叫(獨立驗證實測:1101 的 claim 被靜默改掉)。
    #    檢查輸入只要 O(本次事實數) ≈ 14 個 key,新增和覆寫**兩種都擋得住**。
    #    ⚠️ 位置刻意排在 `if dry` **之前**:第一版排在後面,`--dry` 餵毒 key 不會叫
    #       ⇒ 拿 `--dry` 當上機前預檢就檢不到(獨立驗證第三輪指出)。
    #    母體驗過:真實 651 檔的實際歸屬 key **零個**會被判成 foreign。
    foreign = sorted(k for k in facts["results"]
                     if not (k.endswith(f"__{code}") or f"__{code}__" in k))
    if foreign:
        raise RuntimeError(
            f"[stock_checkup_facts] 🔴 {code} 本次算出的事實裡有 {len(foreign)} 個 key 不屬於它,"
            f"拒絕寫入 —— 例:{foreign[:5]}。"
            f"這些 key 會 `update()` 覆蓋掉別的代號的事實。正式檔零改動。")
    # ── 清掉這個代號舊的 key(避免改版後留下失效欄位)———— 但只清**本腳本自己的**前綴 ──
    #
    # 🔴 2026-09-09 修:舊版判準是純集合差「屬於本代號 && 不在本次輸出裡 ⇒ 刪」。
    #    那是拿**內容**去推**歸屬**,而這個 key 命名空間有不只一個寫入端 ⇒ 必然誤刪。
    #    實測損害:每天 `--count 16` 抹掉 16 檔的 `checkup_industry_rank__{code}`
    #    (`checkup_industry_rank.py --apply` 每週日 06:40 寫的),要等下個週日才長回來。
    #    09-07 之後重算過的 34 檔,留著 rank key 的是 **0 檔**;09-06 前重算的 601 檔有 471 檔留著。
    #    ⚠️ `others_after == others_before` 對這件事是**盲的** —— 那個 key 對本代號來說前後都算
    #       「自己的」,總數不變。不要因為那道閘門沒叫就以為沒事。
    #
    # 改成按前綴分屬,三分類(方案書 §3.1)。**預設值是「不要動」**:
    #    未知前綴 ⇒ 保留 + 印一行告警,**不拋例外**。
    #
    # ⚠️ 這個預設值把失效方向翻到哪一邊,講清楚:
    #    - 舊版表過期(有人加了新寫入端)⇒ **靜默刪掉別人的資料**,零訊號,要等下游發現事實不見了。
    #    - 新版表過期 ⇒ **多留幾個過時欄位 + 每輪一行告警**。資料還在,而且會出聲。
    #    這是刻意用「留下垃圾」換掉「刪掉別人的資料」,不是兩邊都顧到了。
    #
    # ⚠️ 這道判準**看不到**的東西(不要高估它):
    #    ① 它只認前綴,不認寫入端。**若哪天有別的腳本開始寫 OWNED_PREFIXES 裡的前綴,
    #       它寫的東西照樣會被這裡靜默刪掉** —— 預設保留只保護「不在表上的前綴」,
    #       保護不到「在表上、但實際歸屬換人了」的前綴。那一類要靠 ①(每個 key 記寫入端)才擋得住。
    #    ② 它只掃「key 帶得到本代號」的那些(`__{code}` 結尾或 `__{code}__` 夾在中間)。
    #       `checkup_industry_summary__{ind}` 用產業名不是代號 ⇒ 本來就進不了候選集,
    #       它被列進 FOREIGN_PREFIXES 是為了**表本身完整**(給 checkup_facts_prefix_health.py 用),
    #       不是因為這裡擋住了它。
    #    ③ 它不驗「留下來的 key 內容對不對」,只決定刪不刪。
    #
    # ⚠️ 刻意**不**做成 fail-closed 拋例外:`stock_checkup_daily.py:441` 的 `merge_and_write`
    #    在 try 外面,任何例外都會終止整輪 `--count 16`。「有人加了新寫入端」不是資料毀損,
    #    用告警,不要用停產。
    _scoped = [k for k in existing["results"]
               if k.endswith(f"__{code}") or f"__{code}__" in k]
    stale_keys = []
    _unknown: dict[str, list[str]] = {}
    for _k in _scoped:
        _p = _key_prefix(_k)
        if _p in OWNED_PREFIXES:
            stale_keys.append(_k)
        elif _p in FOREIGN_PREFIXES:
            pass                       # 別人的,保留,不出聲(這是預期狀態,不是異常)
        else:
            _unknown.setdefault(_p, []).append(_k)
    for _p in sorted(_unknown):
        # 每個未知前綴一行。**這行必須出現**,否則就是一個不會叫的檢查:
        # 表過期時唯一的訊號就是它(memory `verification-that-cannot-fail`)。
        print(f"[stock_checkup_facts] ⚠️ {code}:未知前綴 `{_p}`（{len(_unknown[_p])} 個 key，"
              f"例:{sorted(_unknown[_p])[:3]}）—— **保留不刪**。"
              f"這代表有寫入端在本表之外:若是本腳本新產的,加進 OWNED_PREFIXES;"
              f"若是別支腳本寫的,加進 FOREIGN_PREFIXES。在那之前這些 key 會一直留著。")
        # 🔴 上面那個 print 會落進 `logs/cron.log`,和 `--count 16` 每天幾百行混在一起 ⇒
        #    **沒人看得到**。方案書 §3.1 說「表過期時會出聲」,而出聲的通道沒人聽 = 等於沒出聲。
        #    ⇒ 再送一份到工廠統一日誌 `STUDIO/ops_log.txt`(同 `stock_fundamentals.py:503` 的用法)。
        # ⚠️ 整段包在 try 裡而且**絕對不能往外拋**:`stock_checkup_daily.py:441` 的
        #    `merge_and_write` 在 try **外面**,這裡拋一個例外就會終止整輪 `--count 16` ——
        #    為了「記一筆日誌」而停產,是把告警機制變成故障源。print 是保證會有的那一條通道,
        #    log_ops 是加送的;log_ops 掛掉時我們寧可只有 print,不要沒有產出。
        try:
            from ops import log_ops
            log_ops("事實庫key歸屬",
                    f"{code} 未知前綴 {_p}（{len(_unknown[_p])} 個 key）保留不刪，"
                    f"請更新 stock_checkup_facts 的 OWNED_PREFIXES / FOREIGN_PREFIXES")
        except Exception as _exc:  # noqa: BLE001
            # 連這一行都不能拋。印出來就好,讓「日誌通道自己壞了」這件事至少留下痕跡。
            print(f"[stock_checkup_facts] ⚠️ log_ops 送不出去（{_exc!r}）—— "
                  f"上面那行告警只存在於 stdout。")
    for k in stale_keys:
        existing["results"].pop(k, None)
    existing["results"].update(facts["results"])
    existing["by_code"][code] = {
        "name": facts["name"], "kind": facts["kind"], "computed_at": facts["as_of"],
        "n_facts": len(facts["results"]), "skipped": facts["skipped"],
        "profile": facts.get("profile") or {},
    }
    if dry:
        print(f"[stock_checkup_facts] --dry：不寫檔（{code} 本次算出 {len(facts['results'])} 組，"
              f"{len(facts['skipped'])} 組資料不足略過）")
        return existing
    # 🔴 結構不變量:合併一個代號,**不可以動到別的代號**。
    #
    # ⚠️ 這一整組**不是**「資料被上游弄丟」的防線 —— 它算的 `_before` 來自 `_load_existing()`
    #    的回傳值,上游回一個空骨架時 `others_before=0`、`codes_before=set()`,合併後仍然是
    #    0 和空集合 ⇒ **它不會叫**(2026-09-09 獨立驗證把 `min_ratio` 設 0 實測:檔案照樣被寫小)。
    #    擋那條的是 `_atomic_write_json` 的**縮水下限**(問磁碟 `stat()`,不看任何 in-memory 物件),
    #    以及 `_load_existing()` 自己的 fail-closed。**這裡守的是另一類失效:輸入夾帶了別人的東西。**
    #
    # 判準放在**輸入**上(實作在本函式開頭的 `foreign`,見那裡的說明)。
    # 總數這一格留著當第二道:擋「合併過程本身把 existing 改壞」(例如 stale_keys 誤刪)。
    others_after = sum(1 for k in existing["results"]
                       if not (k.endswith(f"__{code}") or f"__{code}__" in k))
    if others_after != others_before:
        raise RuntimeError(
            f"[stock_checkup_facts] 🔴 合併 {code} 動到了別的代號,拒絕寫入 —— "
            f"其他代號的事實 {others_before:,} → {others_after:,}。正式檔零改動。")
    # ⚠️ 誠實標註:下面這格**目前不可能觸發** —— `by_code` 在本函式只有 `setdefault` 和
    #    `by_code[code] = {...}`,沒有任何刪除路徑(獨立驗證逐行列過)。留著是給未來改動的絆線,
    #    **它現在不是證據**:不要因為「它沒叫」就推論代號沒掉(memory `verification-that-cannot-fail`)。
    lost_codes = codes_before - set(existing["by_code"])
    if lost_codes:
        raise RuntimeError(
            f"[stock_checkup_facts] 🔴 合併 {code} 弄丟了 {len(lost_codes)} 個代號,拒絕寫入 —— "
            f"例:{sorted(lost_codes)[:5]}。正式檔零改動。")
    # 磁碟層的不變量(抓序列化/落盤走樣),見 _atomic_write_json 的說明。
    expect_results = len(existing["results"])
    expect_by_code = len(existing["by_code"])
    n_bytes, n_res, n_by = _atomic_write_json(
        OUT_FILE, existing, expect_results=expect_results, expect_by_code=expect_by_code)
    # ⚠️ 「已寫入」這句只能印在讀回比對通過之後,而且要帶驗到的數字。
    #    舊版是寫完無條件印——檔案被截成 0 bytes 那次,它照樣印「已寫入」。
    print(f"[stock_checkup_facts] 已寫入並讀回驗證 {OUT_FILE}（{code} 本次 {len(facts['results'])} 組，"
          f"全檔累計 {n_res} 組 / {n_by} 檔，{n_bytes:,} bytes）")
    return existing


def next_backlog_code():
    """回傳 backlog 裡第一個還沒體檢過的代號；全部都算過了回 None。"""
    existing = _load_existing()
    done = set(existing.get("by_code", {}).keys())
    for code in CHECKUP_BACKLOG:
        if code not in done:
            return code
    return None


def print_backlog():
    existing = _load_existing()
    done = existing.get("by_code", {})
    print("=" * 70)
    print("【個股體檢·下集候選池】（依 Carson 拍板順序；已體檢過的標記 ✓）")
    print("=" * 70)
    for code in CHECKUP_BACKLOG:
        name = STOCK_REGISTRY.get(code, {}).get("name", code)
        mark = "✓ 已體檢" if code in done else "  待體檢"
        print(f"  [{mark}] {code} {name}")


def main():
    ap = argparse.ArgumentParser(description="個股體檢·數據引擎")
    ap.add_argument("--code", type=str, default=None, help="股票代號(如 2330)")
    ap.add_argument("--name", type=str, default=None, help="覆蓋顯示名稱(未登錄代號用)")
    ap.add_argument("--dry", action="store_true", help="只印不寫檔")
    ap.add_argument("--refresh", action="store_true", help="忽略價格快取重抓")
    ap.add_argument("--backlog", action="store_true", help="印下集候選池後結束")
    ap.add_argument("--next", action="store_true", help="算 backlog 裡第一個還沒體檢過的代號")
    args = ap.parse_args()

    if args.backlog:
        print_backlog()
        return 0

    code = args.code
    if args.next:
        code = next_backlog_code()
        if code is None:
            print("[stock_checkup_facts] backlog 全部體檢完畢，請到 CHECKUP_BACKLOG 加新代號")
            return 0
        print(f"[stock_checkup_facts] --next：選中 {code}（{STOCK_REGISTRY.get(code,{}).get('name',code)}）")

    if not code:
        print("[stock_checkup_facts] 請給 --code 2330 或 --next 或 --backlog")
        return 1

    facts, skipped = build_checkup(code, name_override=args.name, refresh=args.refresh)
    if facts is None:
        return 1

    print("-" * 70)
    print(f"[stock_checkup_facts] {code}（{facts['name']}）共算出 {len(facts['results'])} 組事實，"
          f"{len(skipped)} 組資料不足略過")
    for k, v in facts["results"].items():
        print(f"  · [{k}] {v['desc']}")
        print(f"      {v['summary']}")
    if skipped:
        print("  略過項目（資料不足，明確揭露不編造）：")
        for sk in skipped:
            print(f"    ✗ [{sk['key']}] {sk['desc']} — {sk['reason']}")

    merge_and_write(facts, dry=args.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
