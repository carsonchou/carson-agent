# -*- coding: utf-8 -*-
"""
scan.py — 台股「數據獵手」掃描引擎

一輪掃描做的事：
  1. 抓宇宙(~130 檔)日線(優先 yfinance 批次即時刷新，失敗退回 twdata/cache 快取)
  2. 每檔算 RSI / MA20 / MA60 / SuperTrend / MACD / ADX / %B / ATR → 個股強弱分(0-100，正交四維)
  3. 聚合：市場溫度 gauge(平均RSI+站上20MA比例+漲跌家數)、產業板塊熱流、強弱榜、大盤總閘
  4. 偵測訊號：做多(SuperTrend 翻多+RSI健康+量能放大+大盤偏多) / 做空警示(跌破20MA 或 SuperTrend 翻空)
     每個訊號附 ATR Chandelier 停損 stop / 停利 tp1(+1.5R) / tp2(+4.5R)
  5. 寫 state.json 給看板(原子寫入)；對「新出現且已收盤確認」的訊號推 ntfy(去重，不洗版)

重用 quant-service 既有：indicators(指標)、notify(推播)。小邏輯由 root strategy.py 移植(不整包 import)。
只讀價、不下單。

用法：
  python scan.py            # 即時刷新 + 掃描 + 推播一次
  python scan.py --no-push  # 不推播(測試)
  python scan.py --cache    # 只讀快取不連網(最快)
  python scan.py --realtime # 跟市場同步(證交所即時價覆蓋最後一根，盤中候選不推)
  python scan.py --full     # 掃全市場(~1900檔)
  python scan.py --freshen  # 只刷新快取後結束
"""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
QS = HERE.parent                       # quant-service/
ROOT = QS.parent                       # carson-agent/
CACHE_DIR = ROOT / "twdata" / "cache"
STATE_FILE = HERE / "state.json"
SIG_LOG = HERE / "signals_log.json"    # 已推過的訊號(去重)
HIST_FILE = HERE / "history.json"      # 當日已確認訊號流水(給看板回顧)

sys.path.insert(0, str(QS))            # 讓 indicators / notify 可匯入
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from universe import (all_codes, load_full_universe, INDUSTRIES,        # noqa: E402
                      INDUSTRY_HUE, industry_hue)
from indicators import calc_rsi, calc_ma, calc_macd, calc_bollinger     # noqa: E402

# .env(NTFY_TOPIC / LINE_NOTIFY_TOKEN) 由 quant-service 載入
try:
    from dotenv import load_dotenv
    load_dotenv(QS / ".env")
except Exception:
    pass

ST_PERIOD, ST_MULT = 10, 3.0
RSI_PERIOD = 14
ADX_PERIOD = 14
DATA_PERIOD = "6mo"
# 盤中分時模式參數：15 分 K，抓近 5 日(約 90 根，足夠 MA60/SuperTrend)
INTRADAY_PERIOD, INTRADAY_INTERVAL = "5d", "15m"

# ── Track1 訊號參數(移植自 root strategy.py 觀念，台股化) ──────────────────
CHAND_LEN, CHAND_MULT = 22, 3.5        # ATR Chandelier 停損(1R = 3.5×ATR22)
TP1_R, TP2_R = 1.5, 4.5                # 停利階梯(R 倍數)
VOL_MULT = 1.5                         # 做多量能濾網：當根量 > 近20日均量×1.5
LIMIT_PCT = 9.5                        # 台股漲跌停 10%；±9.5% 以上標記不可追、排除進場
INDEX_CODE = "0050"                    # 大盤總閘(0050 當代理)
YEARLINE = 240                         # 年線(約 240 交易日)


# ── 通用工具 ────────────────────────────────────────────────────────────────
def _atomic_write_text(path: Path, text: str) -> None:
    """原子寫入：寫暫存檔→os.replace(Windows 同分割區原子)，消除看板讀到寫一半。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)               # 原子替換


def _atomic_write_json(path: Path, obj) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def _market_open_now() -> bool:
    """現在是否為台股交易時段(09:00-13:35，週一~五)。盤中即時訊號標候選不推。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 <= hm <= 13 * 60 + 35


def _prev_trading_day(d: date | None = None) -> date:
    """回傳 d(預設今天)之前最近一個交易日(只避開週末，不含台股例假；粗略夠用)。"""
    d = d or date.today()
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:
        cur -= timedelta(days=1)
    return cur


# ── 資料層 ────────────────────────────────────────────────────────────────
def _cache_csv(code: str) -> Path | None:
    for suf in ("_TW", "_TWO"):
        p = CACHE_DIR / f"{code}{suf}.csv"
        if p.exists():
            return p
    return None


def _read_cache(code: str) -> pd.DataFrame | None:
    p = _cache_csv(code)
    if not p:
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if len(df) >= 22:
            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception:
        pass
    return None


def _bulk_yf(codes: list[str], suffix: str, intraday: bool = False,
             retries: int = 2) -> dict[str, pd.DataFrame]:
    """yfinance 一次批次抓多檔(同市場)。回傳 {code: df}；失敗回空 dict。
    intraday=True 抓 15 分 K(近5日)；否則抓日線(近6月)。
    auto_adjust=False：與 tw_data.py 寫的快取、證交所即時撮合價(皆原始價)基準一致，
    避免除權息股在 tail(180) 窗內人造跳空。含重試+遞增 backoff(搬 tw_data.py 樣板)。"""
    out: dict[str, pd.DataFrame] = {}
    try:
        import yfinance as yf
    except Exception:
        return out
    period, interval = (INTRADAY_PERIOD, INTRADAY_INTERVAL) if intraday else (DATA_PERIOD, "1d")
    tickers = [f"{c}{suffix}" for c in codes]
    raw = None
    for attempt in range(retries + 1):
        try:
            raw = yf.download(" ".join(tickers), period=period, interval=interval,
                              group_by="ticker", auto_adjust=False, progress=False,
                              threads=True, timeout=30)
            if raw is not None and len(raw) > 0:
                break
        except Exception:
            raw = None
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))   # 遞增 backoff
    if raw is None or len(raw) == 0:
        return out
    for c, tk in zip(codes, tickers):
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if tk not in raw.columns.get_level_values(0):
                    continue
                sub = raw[tk]
            else:
                sub = raw  # 只有一檔時 yfinance 不分層
            sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if len(sub) >= 22:
                out[c] = sub.copy()
        except Exception:
            continue
    return out


def _bulk_chunked(codes: list[str], suffix: str, intraday: bool,
                  chunk: int = 120, workers: int = 4) -> dict[str, pd.DataFrame]:
    """大宇宙分塊批次抓(每塊120檔)，避免一次抓 1900 檔整批失敗。
    I/O bound → 塊間用 ThreadPool 並行縮短牆鐘；塊內仍由 yfinance 自帶 threads 處理。"""
    out: dict[str, pd.DataFrame] = {}
    chunks = [codes[i:i + chunk] for i in range(0, len(codes), chunk)]
    if not chunks:
        return out
    miss = 0
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as ex:
        futs = {ex.submit(_bulk_yf, ch, suffix, intraday): ch for ch in chunks}
        for f in as_completed(futs):
            ch = futs[f]
            try:
                res = f.result()
            except Exception:
                res = {}
            out.update(res)
            miss += sum(1 for c in ch if c not in res)
    if miss:
        print(f"[hunter] yfinance {suffix} 缺漏 {miss}/{len(codes)} 檔(退快取/略過)")
    return out


def _f(x):
    """容錯轉 float（即時 API 無成交時回 '-'）。"""
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_realtime(codes: list[str], chunk: int = 50, workers: int = 4) -> dict[str, dict]:
    """證交所即時撮合價(twstock.realtime)，盤中約秒級延遲。回傳 {code: {open,high,low,close,volume}}。
    比 yfinance(台股延遲15-20分)真正跟市場同步。無成交/失敗的代號略過。
    twstock.realtime 對單批序列查詢(別把同一批拆併發過猛被擋)；批間用 ThreadPool 並行。"""
    out: dict[str, dict] = {}
    try:
        from twstock import realtime
    except Exception:
        return out
    chunks = [codes[i:i + chunk] for i in range(0, len(codes), chunk)]
    if not chunks:
        return out

    def grab(batch: list[str]):
        for attempt in range(2):
            try:
                r = realtime.get(batch)
                if r.get("success"):
                    return batch, r
            except Exception:
                pass
            time.sleep(0.3 * (attempt + 1))
        return batch, None

    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as ex:
        for batch, r in ex.map(grab, chunks):
            if not r:
                continue
            for c in batch:
                d = r.get(c) or {}
                rt = d.get("realtime") or {}
                close = _f(rt.get("latest_trade_price")) or _f(rt.get("best_bid_price"))
                if not close:
                    continue
                o, hi, lo = _f(rt.get("open")), _f(rt.get("high")), _f(rt.get("low"))
                vol = _f(rt.get("accumulate_trade_volume")) or 0
                out[c] = {"open": o or close, "high": max(hi or close, close),
                          "low": min(lo or close, close), "close": close,
                          "volume": vol * 1000}
    return out


def apply_realtime(data: dict[str, pd.DataFrame]) -> int:
    """把即時價覆蓋/接到每檔最後一根 K（同日覆蓋、跨日新增）。回傳成功覆蓋檔數。
    邊界保護：跨日要新接『今日 K』時，須真的在交易時段且有累計成交量(volume>0)，
    否則(週末/盤前/無撮合)不接假今日 K，避免污染當日漲跌幅基準。"""
    codes = list(data.keys())
    rt = fetch_realtime(codes)
    if not rt:
        return 0
    today = pd.Timestamp(date.today())
    open_now = _market_open_now()
    n = 0
    for c, px in rt.items():
        df = data.get(c)
        if df is None or len(df) == 0:
            continue
        row = {"Open": px["open"], "High": px["high"], "Low": px["low"],
               "Close": px["close"], "Volume": px["volume"]}
        df = df.copy()
        last = pd.Timestamp(df.index[-1]).normalize()
        if last == today:
            df.loc[df.index[-1]] = row    # 同日 → 覆蓋
        else:
            # 跨日新增今日 K：須交易時段且有累計量，否則跳過(不造假)
            if not (open_now and px["volume"] > 0):
                continue
            df.loc[today] = row
        data[c] = df
        n += 1
    return n


def freshen_cache(rows: list[tuple[str, str, str]]) -> int:
    """把宇宙最近日線抓下來『合併』進 twdata/cache(保留長歷史，只更新近期)。
    這樣即時覆蓋時，前一根=昨日收盤，當日漲跌幅才正確。回傳更新檔數。
    auto_adjust=False：與既有快取同基準。合併前對 fresh 索引 normalize 成純日期再去重
    (參 tw_data.py:81-93 _normalize)，避免時間戳毛邊造成同日兩列。"""
    codes = [c for c, _, _ in rows]
    data: dict[str, pd.DataFrame] = {}
    data.update(_bulk_chunked(codes, ".TW", intraday=False))
    miss = [c for c in codes if c not in data]
    if miss:
        data.update(_bulk_chunked(miss, ".TWO", intraday=False))
    written = 0
    for c, fresh in data.items():
        if fresh is None or len(fresh) == 0:
            continue
        fresh = fresh[["Open", "High", "Low", "Close", "Volume"]].copy()
        fresh.index = pd.to_datetime(fresh.index).normalize()   # 統一純日期
        fresh = fresh[~fresh.index.duplicated(keep="last")]
        path = _cache_csv(c) or (CACHE_DIR / f"{c}_TW.csv")
        try:
            if path.exists():
                old = pd.read_csv(path, index_col=0, parse_dates=True)
                old.index = pd.to_datetime(old.index).normalize()
                comb = pd.concat([old[["Open", "High", "Low", "Close", "Volume"]], fresh])
                comb = comb[~comb.index.duplicated(keep="last")].sort_index()
            else:
                comb = fresh
            comb.to_csv(path)
            written += 1
        except Exception:
            continue
    return written


def _cache_fresh_enough(rows: list[tuple[str, str, str]], sample: int = 8) -> bool:
    """抽樣檢查快取最後一根是否 >= 前一交易日。realtime 模式據此決定要不要先 freshen。"""
    need = _prev_trading_day()
    checked = 0
    for c, _, _ in rows:
        df = _read_cache(c)
        if df is None or len(df) == 0:
            continue
        last = pd.Timestamp(df.index[-1]).date()
        if last < need:
            return False
        checked += 1
        if checked >= sample:
            break
    return checked > 0


def load_universe_data(rows: list[tuple[str, str, str]],
                       use_cache_only: bool = False, intraday: bool = False) -> dict[str, pd.DataFrame]:
    """回傳 {code: OHLCV df(大寫欄位, index=日期/時間)}。即時優先，缺的退快取(日線)。
    intraday=True 抓 15 分 K；快取只有日線，故盤中模式缺的不退快取。"""
    codes = [c for c, _, _ in rows]
    data: dict[str, pd.DataFrame] = {}

    if not use_cache_only:
        # 上市(.TW) 先抓；缺的(多為上櫃)再以 .TWO 抓。大宇宙分塊。
        data.update(_bulk_chunked(codes, ".TW", intraday))
        missing = [c for c in codes if c not in data]
        if missing:
            data.update(_bulk_chunked(missing, ".TWO", intraday))

    # 日線模式：仍缺的(或純快取模式)退回快取。盤中模式快取無分時資料，不退。
    if not intraday:
        for c in codes:
            if c not in data:
                df = _read_cache(c)
                if df is not None:
                    data[c] = df
    return data


# ── 指標 helper(移植小邏輯，不 import root indicators) ──────────────────────
def _lower(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={x: x.lower() for x in df.columns})


def _st_dirs(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """單次計算 SuperTrend，同時回傳(今日方向, 昨日方向)。
    邏輯與 indicators.calc_supertrend 一致，但只跑一遍(省一半)且用 numpy 加速。"""
    n = len(df)
    if n < ST_PERIOD + 2:
        return None, None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ST_PERIOD, min_periods=ST_PERIOD, adjust=False).mean()
    hl2 = (high + low) / 2
    ub = (hl2 + ST_MULT * atr).to_numpy()
    lb = (hl2 - ST_MULT * atr).to_numpy()
    c = close.to_numpy()
    st = np.full(n, np.nan)
    d = np.zeros(n, dtype=int)
    p = ST_PERIOD
    for i in range(p, n):
        if i > p:
            if d[i - 1] == 1:
                lb[i] = max(lb[i], st[i - 1])
            else:
                ub[i] = min(ub[i], st[i - 1])
        prev_dir = d[i - 1] if i > p else 1
        if prev_dir == 1:
            if c[i] < lb[i]:
                d[i] = -1; st[i] = ub[i]
            else:
                d[i] = 1; st[i] = lb[i]
        else:
            if c[i] > ub[i]:
                d[i] = 1; st[i] = lb[i]
            else:
                d[i] = -1; st[i] = ub[i]
    today = "UP" if d[-1] == 1 else "DOWN"
    prev = "UP" if d[-2] == 1 else "DOWN"
    return today, prev


def _atr_last(df: pd.DataFrame, period: int = CHAND_LEN) -> float | None:
    """Wilder ATR 的最後一根值(給 Chandelier 停損用)。"""
    if len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    v = atr.iloc[-1]
    return float(v) if pd.notna(v) else None


def _adx_last(df: pd.DataFrame, period: int = ADX_PERIOD) -> float | None:
    """Wilder ADX 的最後一根值(給強弱分『趨勢』維度)。移植 strategy.py 區5 ADX 觀念。"""
    if len(df) < period * 2 + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    up = high.diff()
    dn = -low.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    v = adx.iloc[-1]
    return float(v) if pd.notna(v) else None


# ── 個股分析(記憶化) ────────────────────────────────────────────────────────
# 以「最後一列日期 + 最後收盤 + 長度」為 key 快取 analyse 結果。
# app/loop 反覆掃同一份快取時：未變的檔直接取上輪(近乎歸零)；
# realtime 模式只有真的有成交、最後收盤變動的檔才重算。memo 以 code 為鍵更新→有界(不漏)。
_ANALYSE_MEMO: dict[str, tuple[str, dict | None]] = {}


def _analyse_core(code: str, df_raw: pd.DataFrame, drop_last: bool) -> dict | None:
    """個股分析核心(重指標)。drop_last=True → 訊號/指標一律用『丟掉最後一根未收盤 K』的
    已收盤序列(移植 trading_bot/strategy/supertrend.py drop_forming/_closed_df 觀念)，
    避免盤中 forming K 造成 SuperTrend 翻轉/RSI/跌破20MA 重繪；即時價只更新顯示用 price/chg。"""
    if df_raw is None or len(df_raw) < 22:
        return None
    full = _lower(df_raw.tail(180).reset_index(drop=True))
    fclose = full["close"].astype(float)
    if len(fclose) < 2:
        return None

    # 記憶化 key：最後日期不可得(已 reset_index) → 用長度+末兩根收盤組合，足以辨識變動
    key = f"{len(full)}|{float(fclose.iloc[-1]):.4f}|{float(fclose.iloc[-2]):.4f}|{int(drop_last)}"
    cached = _ANALYSE_MEMO.get(code)
    if cached and cached[0] == key:
        return cached[1]

    # 顯示用：當日漲跌幅以『含即時(forming)那根』算；前一根=昨日收盤(realtime 前已 freshen 確保)
    price = float(fclose.iloc[-1])
    prev_px = float(fclose.iloc[-2])
    chg = round((price - prev_px) / prev_px * 100, 2) if prev_px else 0.0
    mom5 = round((price - float(fclose.iloc[-6])) / float(fclose.iloc[-6]) * 100, 2) if len(fclose) >= 6 else 0.0
    spark = [round(float(x), 2) for x in fclose.tail(20).tolist()]   # 近~20根收盤(給前端迷你走勢)

    # 訊號/指標用『已收盤』序列
    closed = full.iloc[:-1] if (drop_last and len(full) > 22) else full
    cclose = closed["close"].astype(float)
    sig_price = float(cclose.iloc[-1])         # 已收盤最後價(訊號基準)
    sig_prev = float(cclose.iloc[-2]) if len(cclose) >= 2 else sig_price

    rsi = calc_rsi(closed, period=RSI_PERIOD).get("rsi")
    ma = calc_ma(closed, periods=[20, 60])
    ma20, ma60 = ma["ma"].get(20), ma["ma"].get(60)
    # 真實前一日 MA20 = close.rolling(20).mean().shift(1)，非「今日近似前日」
    ma20_series = cclose.rolling(20).mean()
    prev_ma20 = float(ma20_series.shift(1).iloc[-1]) if len(ma20_series.dropna()) >= 2 else None
    st_today, st_prev = _st_dirs(closed)
    macd = calc_macd(closed)
    adx = _adx_last(closed)
    pctb = calc_bollinger(closed, period=20, std=2.0).get("percent_b")
    atr22 = _atr_last(closed, CHAND_LEN)
    avg_vol20 = float(closed["volume"].astype(float).rolling(20).mean().shift(1).iloc[-1]) \
        if len(closed) >= 21 else None
    cur_vol = float(full["volume"].astype(float).iloc[-1])
    relvol = round(cur_vol / avg_vol20, 2) if avg_vol20 and avg_vol20 > 0 else None
    recent_high20 = float(cclose.tail(20).max())

    above20 = ma20 is not None and sig_price > ma20
    above60 = ma60 is not None and sig_price > ma60
    no_chase = abs(chg) >= LIMIT_PCT           # 漲跌停附近：不可追、排除進場

    # ── 個股強弱分 0-100：正交四維(各 0-25)，去除 RSI 與 mom5 雙重計動能 ──
    #   趨勢(ST方向 + ADX 強度)、位置(布林 %B)、動能(RSI)、波動(relVol 參與度)
    st_up = (st_today == "UP")
    adx_norm = min((adx or 0) / 40.0, 1.0)
    trend_s = (12.5 if st_up else 0.0) + 12.5 * adx_norm
    pos_s = 25.0 * min(max(pctb if pctb is not None else 0.5, 0.0), 1.0)
    mom_s = 25.0 * ((rsi or 50.0) / 100.0)
    vol_s = 25.0 * min(max(((relvol or 1.0) - 0.5) / 1.5, 0.0), 1.0)
    score = round(max(0.0, min(100.0, trend_s + pos_s + mom_s + vol_s)), 1)

    # ── 訊號判定(全在已收盤序列上) ──
    #   做多：SuperTrend 翻多 + RSI 健康 + 非漲跌停。量能達標→firm；不足→候選(進 watch)。
    #   做空『警示/減碼』：SuperTrend 翻空 或 真實跌破前一日 MA20。
    signal = None
    reason = ""
    firm = False
    vol_ok = (relvol is not None and relvol >= VOL_MULT)
    if st_prev == "DOWN" and st_today == "UP" and rsi is not None and 30 <= rsi <= 70 and not no_chase:
        signal = "long"
        firm = vol_ok
        vtxt = f"，量能放大{relvol:.1f}x" if vol_ok else f"，量能待補({relvol:.1f}x)" if relvol is not None else ""
        reason = f"SuperTrend 翻多，RSI {rsi:.0f} 健康區{vtxt}"
    elif st_prev == "UP" and st_today == "DOWN":
        signal = "short"
        reason = "SuperTrend 翻空，跌勢轉折(警示/減碼)"
    elif (ma20 is not None and prev_ma20 is not None
          and sig_price < ma20 and sig_prev >= prev_ma20):
        signal = "short"
        reason = f"跌破 20MA（{ma20:.1f}）(警示/減碼)"

    # ── ATR Chandelier 停損 / 停利階梯(R = |close − stop| = 3.5×ATR22) ──
    stop = tp1 = tp2 = None
    if atr22 is not None and signal in ("long", "short"):
        r = CHAND_MULT * atr22
        if signal == "long":
            stop = round(sig_price - r, 2)
            tp1 = round(sig_price + TP1_R * r, 2)
            tp2 = round(sig_price + TP2_R * r, 2)
        else:
            stop = round(sig_price + r, 2)
            tp1 = round(sig_price - TP1_R * r, 2)
            tp2 = round(sig_price - TP2_R * r, 2)

    result = {
        "price": round(price, 2), "chg": chg, "mom5": mom5,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "above20": above20, "above60": above60,
        "st": st_today, "macd_trend": macd.get("trend"),
        "adx": round(adx, 1) if adx is not None else None,
        "percent_b": round(pctb, 3) if pctb is not None else None,
        "relvol": relvol, "no_chase": no_chase,
        "recent_high20": round(recent_high20, 2),
        "score": score, "signal": signal, "reason": reason, "firm": firm,
        "stop": stop, "tp1": tp1, "tp2": tp2, "spark": spark,
    }
    _ANALYSE_MEMO[code] = (key, result)
    return result


def analyse_one(df_raw: pd.DataFrame, drop_last: bool = False) -> dict | None:
    """相容舊呼叫的薄包裝(無 code 時用匿名 key，不進 memo)。"""
    return _analyse_core("_anon", df_raw, drop_last)


# ── 大盤總閘 ────────────────────────────────────────────────────────────────
def compute_index(data: dict[str, pd.DataFrame]) -> tuple[dict, bool]:
    """以 0050 當大盤代理算總閘：EMA200 / SuperTrend 方向 / 年線。
    回傳 (index_dict, mkt_long_ok)。大盤偏空時 mkt_long_ok=False → 抑制做多、調降溫度。"""
    df = data.get(INDEX_CODE)
    if df is None:
        df = _read_cache(INDEX_CODE)
    if df is None or len(df) < 30:
        return ({"name": INDEX_CODE, "price": None, "chg": None,
                 "trend": None, "above_yearline": None}, True)
    d = _lower(df.tail(max(YEARLINE + 10, 260)).reset_index(drop=True))
    close = d["close"].astype(float)
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else price
    chg = round((price - prev) / prev * 100, 2) if prev else 0.0
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
    yline = float(close.rolling(YEARLINE).mean().iloc[-1]) if len(close) >= YEARLINE else ema200
    st_today, _ = _st_dirs(d)
    above_yearline = price > yline
    trend = "UP" if (st_today == "UP" and price > ema200) else "DOWN"
    long_ok = (trend == "UP")
    return ({"name": INDEX_CODE, "price": round(price, 2), "chg": chg,
             "trend": trend, "above_yearline": above_yearline}, long_ok)


# ── 聚合 ──────────────────────────────────────────────────────────────────
def _temp_label(t: float) -> tuple[str, str]:
    if t >= 75:   return "超強", "#ff3b6b"
    if t >= 60:   return "偏多", "#ff9f45"
    if t >= 45:   return "中性", "#ffd75e"
    if t >= 30:   return "偏弱", "#4fd1c5"
    return "超弱", "#3b82f6"


def build_state(data: dict[str, pd.DataFrame], rows: list[tuple[str, str, str]],
                source: str = "live", mode: str = "daily",
                drop_last: bool = False, confirmed_mode: bool = True) -> dict:
    code_meta = {c: (n, ind) for c, n, ind in rows}
    index, mkt_long_ok = compute_index(data)

    stocks: list[dict] = []
    for code, df in data.items():
        core = _analyse_core(code, df, drop_last)
        if not core:
            continue
        a = dict(core)               # 不污染 memo
        name, ind = code_meta.get(code, (code, "其他"))
        a.update({"code": code, "name": name, "industry": ind})
        stocks.append(a)

    n = len(stocks)
    if n == 0:
        return {"ok": False, "error": "no data", "ts": datetime.now().isoformat(timespec="seconds")}

    rsis = [s["rsi"] for s in stocks if s["rsi"] is not None]
    avg_rsi = round(sum(rsis) / len(rsis), 1) if rsis else 50.0
    breadth = round(sum(1 for s in stocks if s["above20"]) / n * 100, 1)   # 站上20MA比例
    adv = sum(1 for s in stocks if s["chg"] > 0)
    dec = sum(1 for s in stocks if s["chg"] < 0)
    flat = n - adv - dec
    adr = round(adv / dec, 2) if dec else float(adv)

    # 市場溫度 0-100：平均RSI(50%) + 站上20MA比例(35%) + 漲跌家數比映射(15%)
    adr_score = 100 * adv / (adv + dec) if (adv + dec) else 50
    temperature = 0.50 * avg_rsi + 0.35 * breadth + 0.15 * adr_score
    if not mkt_long_ok:
        temperature *= 0.90          # 大盤偏空 → 調降市場溫度
    temperature = round(temperature, 1)
    t_label, t_color = _temp_label(temperature)

    # 產業板塊熱流(全市場模式只顯示成員數>=3 的板塊，避免單檔雜訊)
    by_ind: dict[str, list[dict]] = {}
    for s in stocks:
        by_ind.setdefault(s["industry"], []).append(s)
    min_members = 3 if len(stocks) > 300 else 1
    sectors: list[dict] = []
    for ind, members in by_ind.items():
        if len(members) < min_members:
            continue
        avg_chg = round(sum(s["chg"] for s in members) / len(members), 2)
        bull = round(sum(1 for s in members if s["above20"]) / len(members) * 100, 0)
        avg_score = round(sum(s["score"] for s in members) / len(members), 1)
        leader = max(members, key=lambda s: s["chg"])
        sectors.append({
            "name": ind, "avg_chg": avg_chg, "bull_pct": bull,
            "score": avg_score, "count": len(members), "hue": industry_hue(ind),
            "leader": f"{leader['name']} {leader['chg']:+.1f}%",
        })
    sectors.sort(key=lambda s: s["score"], reverse=True)

    # 強弱榜
    by_score = sorted(stocks, key=lambda s: s["score"], reverse=True)
    strong = [_card(s) for s in by_score[:8]]
    weak = [_card(s) for s in by_score[-8:][::-1]]

    # ── 訊號分流：firm 做多 + 做空警示；大盤偏空/量能不足的做多 → 降級為 watch ──
    longs_firm: list[dict] = []
    shorts_all: list[dict] = []
    watch_pool: list[dict] = []
    for s in stocks:
        if s["signal"] == "long":
            if s["firm"] and mkt_long_ok:
                longs_firm.append(_sig(s, confirmed_mode))
            else:
                # 量能待補 或 大盤偏空抑制 → 觀察名單
                why = "量能待補" if not s["firm"] else "大盤偏空抑制做多"
                watch_pool.append(_watch(s, why))
        elif s["signal"] == "short":
            shorts_all.append(_sig(s, confirmed_mode))

    # 觀察名單再補：ST 偏多、站上20MA、體質佳但尚未觸發的『最接近突破』名單(差幾%到20日高)
    for s in stocks:
        if s["signal"] is not None or not mkt_long_ok:
            continue
        if s["st"] == "UP" and s["above20"] and s["rsi"] is not None and 45 <= s["rsi"] <= 70 \
                and s["score"] >= 55 and not s["no_chase"]:
            watch_pool.append(_watch(s, "距20日高突破"))

    # watch 去重(留 gap 最小者)、依 gap 升冪(最接近觸發在前)
    seen_w: dict[str, dict] = {}
    for w in watch_pool:
        ex = seen_w.get(w["code"])
        if ex is None or w["gap_pct"] < ex["gap_pct"]:
            seen_w[w["code"]] = w
    watch_long = sorted(seen_w.values(), key=lambda w: (w["gap_pct"], -w["score"]))[:8]

    # 訊號 cap(全市場可能上百個→只留最強/最弱前 N，避免看板過長與推播洗版)
    SIG_CAP = 12
    longs_all = sorted(longs_firm, key=lambda s: s["score"], reverse=True)
    shorts_all = sorted(shorts_all, key=lambda s: s["score"])
    n_long_all, n_short_all = len(longs_all), len(shorts_all)
    longs, shorts = longs_all[:SIG_CAP], shorts_all[:SIG_CAP]

    return {
        "ok": True,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "date": str(date.today()),
        "source": source,
        "mode": mode,
        "confirmed": confirmed_mode,
        "universe": n,
        "index": index,
        "gauge": {
            "temperature": temperature, "label": t_label, "color": t_color,
            "avg_rsi": avg_rsi, "breadth": breadth,
            "adv": adv, "dec": dec, "flat": flat, "adr": adr,
        },
        "sectors": sectors,
        "strong": strong,
        "weak": weak,
        "signals": {"long": longs, "short": shorts,
                    "long_total": n_long_all, "short_total": n_short_all, "cap": SIG_CAP},
        "watch_long": watch_long,
    }


def _card(s: dict) -> dict:
    return {"code": s["code"], "name": s["name"], "industry": s["industry"],
            "price": s["price"], "chg": s["chg"], "rsi": s["rsi"], "score": s["score"],
            "st": s["st"], "spark": s["spark"]}


def _sig(s: dict, confirmed_mode: bool) -> dict:
    d = _card(s)
    # 收盤確認模式 + firm(做多)才算已確認可推；做空為警示，收盤確認即可推
    confirmed = bool(confirmed_mode and (s["firm"] if s["signal"] == "long" else True))
    d.update({"side": s["signal"], "reason": s["reason"],
              "stop": s["stop"], "tp1": s["tp1"], "tp2": s["tp2"],
              "confirmed": confirmed})
    return d


def _watch(s: dict, why: str) -> dict:
    """做多觀察名單一筆：gap_pct = 距 20 日高還要漲幾 %(已突破則 0)。"""
    gap = max(0.0, (s["recent_high20"] - s["price"]) / s["price"] * 100) if s["price"] else 0.0
    gap = round(gap, 1)
    return {"code": s["code"], "name": s["name"], "industry": s["industry"],
            "price": s["price"], "chg": s["chg"], "rsi": s["rsi"], "score": s["score"],
            "gap_pct": gap, "reason": f"{why}差 {gap}% 觸發" if gap > 0 else f"{why}(已觸及)"}


# ── 當日已確認訊號流水 ──────────────────────────────────────────────────────
def append_history(state: dict) -> int:
    """把本輪『已確認』訊號 append 落 history.json(陣列、當日、capped ~100，原子寫入)。
    realtime/盤中候選不算已確認 → 不落檔。server.py 靜態服務同目錄，前端可 fetch('history.json')。"""
    if not state.get("ok"):
        return 0
    today = state["date"]
    items: list[dict] = []
    if HIST_FILE.exists():
        try:
            obj = json.loads(HIST_FILE.read_text(encoding="utf-8"))
            if obj.get("date") == today:
                items = obj.get("items", [])
        except Exception:
            items = []
    seen = {(i.get("code"), i.get("side")) for i in items}
    added = 0
    for side in ("long", "short"):
        for s in state["signals"][side]:
            if not s.get("confirmed"):
                continue
            k = (s["code"], s["side"])
            if k in seen:
                continue
            seen.add(k)
            items.append({"ts": state["ts"], "code": s["code"], "name": s["name"],
                          "industry": s.get("industry"), "side": s["side"],
                          "price": s["price"], "chg": s.get("chg"), "reason": s["reason"],
                          "score": s["score"], "stop": s["stop"],
                          "tp1": s["tp1"], "tp2": s["tp2"]})
            added += 1
    items = items[-100:]
    if added:
        _atomic_write_json(HIST_FILE, {"date": today, "items": items})
    return added


# ── 推播去重 ──────────────────────────────────────────────────────────────
def _load_pushed() -> set[str]:
    if SIG_LOG.exists():
        try:
            obj = json.loads(SIG_LOG.read_text(encoding="utf-8"))
            if obj.get("date") == str(date.today()):
                return set(obj.get("keys", []))
        except Exception:
            pass
    return set()


def _save_pushed(keys: set[str]) -> None:
    _atomic_write_json(SIG_LOG, {"date": str(date.today()), "keys": sorted(keys)})


def push_new_signals(state: dict) -> int:
    """只推今天還沒推過、且『已收盤確認』的訊號，回傳本次新推數。盤中候選不推。"""
    if not state.get("confirmed"):
        return 0                      # 盤中(realtime/intraday)候選不推
    pushed = _load_pushed()
    fresh: list[dict] = []
    for side in ("long", "short"):
        for s in state["signals"][side]:
            if not s.get("confirmed"):
                continue
            key = f"{state['date']}:{s['code']}:{s['side']}"
            if key not in pushed:
                fresh.append(s)
                pushed.add(key)
    if not fresh:
        return 0
    try:
        from notify import broadcast
    except Exception as e:
        print(f"[hunter] notify 匯入失敗，略過推播：{e}")
        return 0

    g = state["gauge"]
    idx = state.get("index") or {}
    idx_txt = f"｜大盤 {idx.get('trend','?')}" if idx.get("trend") else ""
    lines = [f"🎯 數據獵手｜市場溫度 {g['temperature']}（{state['gauge']['label']}）{idx_txt}",
             f"漲{g['adv']}/跌{g['dec']}　站上20MA {g['breadth']}%", "━━━━━━━━━━━━"]
    for s in fresh:
        icon = "🟢做多" if s["side"] == "long" else "🔴做空"
        lines.append(f"{icon} {s['code']} {s['name']} {s['price']}")
        lines.append(f"   {s['reason']}（強弱 {s['score']}）")
        if s.get("stop") is not None:
            lines.append(f"   停損 {s['stop']}／TP1 {s['tp1']}／TP2 {s['tp2']}")
    lines.append("━━━━━━━━━━━━\n量化阿森 · 台股數據獵手")
    msg = "\n".join(lines)
    try:
        broadcast(msg, title=f"數據獵手｜{len(fresh)} 個新訊號", priority="high")
    except Exception as e:
        print(f"[hunter] 推播失敗：{e}")
        return 0
    _save_pushed(pushed)
    return len(fresh)


# ── 主程式 ────────────────────────────────────────────────────────────────
def run_once(push: bool = True, cache_only: bool = False, intraday: bool = False,
             full: bool = False, realtime: bool = False) -> dict:
    t0 = time.time()
    if full and intraday:
        print("[hunter] 全市場(~1900檔)盤中分時不切實際→自動改日線")
        intraday = False
    rows = load_full_universe() if full else all_codes()
    scope_txt = f"全市場 {len(rows)} 檔" if full else f"精選 {len(rows)} 檔"

    if realtime:
        # 跟市場同步：快取日線歷史 + 證交所即時價覆蓋最後一根
        mode_txt = "即時同步(證交所)"
        source, mode = "realtime", "realtime"
        # 強制確保前一根=前一交易日(否則當日漲跌幅基準錯)；快取太舊先 freshen
        if not _cache_fresh_enough(rows):
            print("[hunter] 快取落後前一交易日，先刷新…")
            nf = freshen_cache(rows)
            print(f"[hunter] 快取已更新 {nf} 檔")
        print(f"[hunter] 載入宇宙資料（{scope_txt}／{mode_txt}）…")
        data = load_universe_data(rows, use_cache_only=True, intraday=False)
        nrt = apply_realtime(data)
        print(f"[hunter] 即時價覆蓋 {nrt}/{len(data)} 檔（證交所撮合價）")
    else:
        mode_txt = "盤中15分K" if intraday else ("快取日線" if cache_only else "即時日線")
        source = "cache" if cache_only else "live"
        mode = "intraday" if intraday else "daily"
        print(f"[hunter] 載入宇宙資料（{scope_txt}／{mode_txt}）…")
        data = load_universe_data(rows, use_cache_only=cache_only, intraday=intraday)
    print(f"[hunter] 取得 {len(data)} 檔，計算指標中…")

    # 盤中(realtime / intraday)= 用已收盤序列判訊號(drop_last)，且為候選不推；
    # 日線/快取(收盤後)= 已收盤確認，可推。
    drop_last = realtime or intraday
    confirmed_mode = not drop_last
    state = build_state(data, rows, source=source, mode=mode,
                        drop_last=drop_last, confirmed_mode=confirmed_mode)
    _atomic_write_json(STATE_FILE, state)
    if not state.get("ok"):
        print(f"[hunter] ✗ 掃描無資料：{state.get('error')}")
        return state

    g = state["gauge"]
    idx = state["index"]
    nl, ns = len(state["signals"]["long"]), len(state["signals"]["short"])
    print(f"[hunter] 溫度 {g['temperature']}（{g['label']}）｜大盤 {idx.get('trend')}"
          f"｜漲{g['adv']}/跌{g['dec']}｜站上20MA {g['breadth']}%｜做多{nl} 做空警示{ns}"
          f"｜觀察 {len(state['watch_long'])}")
    print(f"[hunter] 板塊最強：{state['sectors'][0]['name']}（{state['sectors'][0]['avg_chg']:+.1f}%）"
          f"／最弱：{state['sectors'][-1]['name']}（{state['sectors'][-1]['avg_chg']:+.1f}%）")

    nh = append_history(state)        # 已確認訊號落流水(盤中候選 → 0)
    if nh:
        print(f"[hunter] history.json 新增 {nh} 筆已確認訊號")

    if push:
        n = push_new_signals(state)
        print(f"[hunter] 推播 {n} 個新訊號" if n else "[hunter] 無新訊號可推(或盤中候選不推)")
    print(f"[hunter] 完成，耗時 {time.time()-t0:.1f}s → {STATE_FILE.name}")
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="不推播(測試)")
    ap.add_argument("--cache", action="store_true", help="只讀快取不連網(日線)")
    ap.add_argument("--intraday", action="store_true", help="盤中 15 分 K(yfinance，延遲約15分)")
    ap.add_argument("--realtime", action="store_true", help="跟市場同步(證交所即時價覆蓋，盤中秒級)")
    ap.add_argument("--full", action="store_true", help="掃全市場(~1900檔上市櫃，twstock 產業別)")
    ap.add_argument("--freshen", action="store_true", help="只刷新快取(近期日線合併進twdata/cache)後結束")
    args = ap.parse_args()
    if args.freshen:
        rows = load_full_universe() if args.full else all_codes()
        print(f"[hunter] 刷新快取（{len(rows)} 檔）…")
        n = freshen_cache(rows)
        print(f"[hunter] 快取已更新 {n} 檔")
        return
    run_once(push=not args.no_push, cache_only=args.cache,
             intraday=args.intraday, full=args.full, realtime=args.realtime)


if __name__ == "__main__":
    main()
