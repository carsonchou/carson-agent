# -*- coding: utf-8 -*-
"""
tw_data.py — 台股資料層

- 用 twstock 取得所有「上市 + 上櫃」「股票」代碼
- 上市 → yfinance ticker `<code>.TW`；上櫃 → `<code>.TWO`
- 用 yfinance 下載日線 OHLCV，快取成 parquet（無 parquet 引擎則退回 csv）到 twdata\
- 批次下載、失敗跳過並記錄、加小延遲避免限流
- 重跑直接讀快取
"""
import os
import time
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twdata")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# parquet 引擎偵測（環境可能沒裝 pyarrow/fastparquet）
try:
    import pyarrow  # noqa: F401
    _PARQUET = True
    _EXT = "parquet"
except Exception:
    try:
        import fastparquet  # noqa: F401
        _PARQUET = True
        _EXT = "parquet"
    except Exception:
        _PARQUET = False
        _EXT = "csv"


def get_universe():
    """回傳 [(code, ticker, market, name), ...]，涵蓋所有上市+上櫃股票。

    上市 → '<code>.TW'，上櫃 → '<code>.TWO'。
    """
    import twstock

    out = []
    for code, info in twstock.codes.items():
        if info.type != "股票":
            continue
        if info.market == "上市":
            ticker = f"{code}.TW"
        elif info.market == "上櫃":
            ticker = f"{code}.TWO"
        else:
            continue
        out.append((code, ticker, info.market, info.name))
    # 依代碼排序，穩定可重現
    out.sort(key=lambda x: x[0])
    return out


def _cache_path(ticker: str) -> str:
    safe = ticker.replace(".", "_")
    return os.path.join(CACHE_DIR, f"{safe}.{_EXT}")


def _read_cache(path: str):
    if _EXT == "parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df


def _write_cache(df: pd.DataFrame, path: str):
    if _EXT == "parquet":
        df.to_parquet(path)
    else:
        df.to_csv(path)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """把 yfinance 下載結果整理成單層欄位 OHLCV，index 為日期。"""
    if isinstance(df.columns, pd.MultiIndex):
        # 取第 0 層（Price 類別），丟掉 ticker 層
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    cols = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in cols if c in df.columns]].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[df["Close"] > 0]
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def load_ohlcv(ticker: str, period: str = "max", use_cache: bool = True,
               sleep: float = 0.4, max_retries: int = 2):
    """下載（或讀快取）單一 ticker 的日線 OHLCV。

    回傳 DataFrame（Open/High/Low/Close/Volume）或 None（失敗）。
    """
    path = _cache_path(ticker)
    if use_cache and os.path.exists(path):
        try:
            df = _read_cache(path)
            if len(df) > 0:
                return df
        except Exception:
            pass  # 快取壞了就重抓

    import yfinance as yf

    df = None
    for attempt in range(max_retries + 1):
        try:
            raw = yf.download(ticker, period=period, progress=False,
                              auto_adjust=False, threads=False)
            if raw is not None and len(raw) > 0:
                df = _normalize(raw)
                break
        except Exception:
            df = None
        if attempt < max_retries:
            time.sleep(sleep * (attempt + 1))
    if df is None or len(df) == 0:
        return None
    try:
        _write_cache(df, path)
    except Exception:
        pass
    if sleep:
        time.sleep(sleep)
    return df


def cache_exists(ticker: str) -> bool:
    return os.path.exists(_cache_path(ticker))
