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
    return code  # 未登錄代號：用代碼本身當名稱（不編公司名）


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
        "summary": (f"完整年度資料共 {len(rows)} 年：最慘一年是 {worst['year']}年，"
                    f"該年報酬 {pct(worst['return'])}；最猛一年是 {best['year']}年，"
                    f"該年報酬 {pct(best['return'])}"),
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
                    f"同期買進持有 {BENCH_NAME}（0050）總報酬 {pct(b_tr)}"
                    f"（年化 {pct(b_cagr)}、最大回撤 {pct(b_mdd)}）"),
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

    # A. 20年(或上市至今)總報酬/年化/最大回撤
    add(f"checkup_long_horizon__{code}",
        "20年(可信資料區間不足20年則用上市至今)含息還原總報酬/年化/最大回撤/卡瑪比率",
        f"{name} 長期含息還原體檢", ["個股體檢", code, name, "總報酬", "年化", "最大回撤"],
        calc_long_horizon(s))

    # B. 最慘一年 / 最猛一年
    add(f"checkup_annual_extremes__{code}",
        "年度報酬序列(整年至少約100交易日才列入)，取最大值/最小值",
        f"{name} 最猛一年 vs 最慘一年", ["個股體檢", code, name, "年度報酬", "最慘一年", "最猛一年"],
        calc_annual_extremes(s))

    # C. 單筆All-in vs 月定投(10年) vs 同期0050
    add(f"checkup_three_way__{code}",
        "近10年(資料不足10年則用共同起點全段)：單筆All-in vs 每月定期定額 vs 同期買進持有0050",
        f"{name} 三種買法對決：All-in / 定期定額 / 0050", ["個股體檢", code, name, "All in", "定期定額", "0050", "三種買法"],
        calc_three_way_showdown(s, bench, name) if bench is not None else None)

    # D. 持有體驗：最長套牢期
    add(f"checkup_underwater__{code}",
        "從每次創歷史新高算起，到下一次創歷史新高之間的最長間隔(天數/年數)；若目前仍未創新高則計到最新一天並標註ongoing",
        f"{name} 最長套牢期(創高到下個創高間隔)", ["個股體檢", code, name, "套牢", "持有體驗", "創新高"],
        calc_underwater(s))

    # E. 持有體驗：腰斬次數
    add(f"checkup_halvings__{code}",
        "從每個新高點算起，股價跌幅觸及-50%的獨立事件數(重新武裝條件=再創出高於前次的新高)",
        f"{name} 腰斬(-50%)發生次數", ["個股體檢", code, name, "腰斬", "持有體驗", "回撤"],
        calc_halvings(s))

    # F. 崩盤三段區間表現
    for wk in CRASH_WINDOWS:
        r = calc_crash_window(s, wk)
        wlabel = CRASH_WINDOWS[wk]["label"]
        add(f"checkup_crash__{code}__{wk}",
            f"{wlabel}期間：高點到阱底跌幅 + 若持有至今的報酬(未計股利再投入外的其他操作)",
            f"{name}：{wlabel}期間表現", ["個股體檢", code, name, "崩盤", wlabel, "持有體驗"],
            r)

    facts = {"as_of": as_of, "disclaimer": DISCLAIMER, "results": results,
             "skipped": skipped, "code": code, "name": name, "kind": kind}
    return facts, skipped


def _load_existing():
    if OUT_FILE.exists():
        try:
            return json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"as_of": None, "disclaimer": DISCLAIMER, "results": {}, "by_code": {}}


def merge_and_write(facts, dry=False):
    """把單一代號的體檢結果合併進共用檔（別的代號已算出的事實不動）。"""
    existing = _load_existing()
    existing.setdefault("results", {})
    existing.setdefault("by_code", {})
    existing["as_of"] = facts["as_of"]
    existing["disclaimer"] = DISCLAIMER
    code = facts["code"]
    # 先清掉這個代號舊的 key（避免改版後留下失效欄位），再灌新的
    stale_keys = [k for k in existing["results"] if k.endswith(f"__{code}") or f"__{code}__" in k]
    for k in stale_keys:
        existing["results"].pop(k, None)
    existing["results"].update(facts["results"])
    existing["by_code"][code] = {
        "name": facts["name"], "kind": facts["kind"], "computed_at": facts["as_of"],
        "n_facts": len(facts["results"]), "skipped": facts["skipped"],
    }
    if dry:
        print(f"[stock_checkup_facts] --dry：不寫檔（{code} 本次算出 {len(facts['results'])} 組，"
              f"{len(facts['skipped'])} 組資料不足略過）")
        return existing
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[stock_checkup_facts] 已寫入 {OUT_FILE}（{code} 本次 {len(facts['results'])} 組，"
          f"全檔累計 {len(existing['results'])} 組）")
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
