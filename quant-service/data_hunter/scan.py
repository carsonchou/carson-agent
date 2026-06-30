# -*- coding: utf-8 -*-
"""
scan.py — 台股「數據獵手」掃描引擎

一輪掃描做的事：
  1. 抓宇宙(~130 檔)日線(優先 yfinance 批次即時刷新，失敗退回 twdata/cache 快取)
  2. 每檔算 RSI / MA20 / MA60 / SuperTrend / MACD / 5日動能 → 個股強弱分(0-100)
  3. 聚合：市場溫度 gauge(平均RSI+站上20MA比例+漲跌家數)、產業板塊熱流、強弱榜
  4. 偵測訊號：做多(SuperTrend 翻多+RSI健康) / 做空(跌破20MA 或 SuperTrend 翻空)
  5. 寫 state.json 給看板；對「新出現」的訊號推 ntfy(去重，不洗版)

重用 quant-service 既有：indicators(指標)、tw_stock_data(備援抓價)、notify(推播)。
只讀價、不下單。

用法：
  python scan.py            # 即時刷新 + 掃描 + 推播一次
  python scan.py --no-push  # 不推播(測試)
  python scan.py --cache    # 只讀快取不連網(最快)
"""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
QS = HERE.parent                       # quant-service/
ROOT = QS.parent                       # carson-agent/
CACHE_DIR = ROOT / "twdata" / "cache"
STATE_FILE = HERE / "state.json"
SIG_LOG = HERE / "signals_log.json"    # 已推過的訊號(去重)

sys.path.insert(0, str(QS))            # 讓 indicators / notify / tw_stock_data 可匯入
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from universe import all_codes, INDUSTRIES, INDUSTRY_HUE          # noqa: E402
from indicators import calc_rsi, calc_ma, calc_supertrend, calc_macd  # noqa: E402

# .env(NTFY_TOPIC / LINE_NOTIFY_TOKEN) 由 quant-service 載入
try:
    from dotenv import load_dotenv
    load_dotenv(QS / ".env")
except Exception:
    pass

ST_PERIOD, ST_MULT = 10, 3.0
RSI_PERIOD = 14
DATA_PERIOD = "6mo"
# 盤中分時模式參數：15 分 K，抓近 5 日(約 90 根，足夠 MA60/SuperTrend)
INTRADAY_PERIOD, INTRADAY_INTERVAL = "5d", "15m"


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


def _bulk_yf(codes: list[str], suffix: str, intraday: bool = False) -> dict[str, pd.DataFrame]:
    """yfinance 一次批次抓多檔(同市場)。回傳 {code: df}；失敗回空 dict。
    intraday=True 抓 15 分 K(近5日)；否則抓日線(近6月)。"""
    out: dict[str, pd.DataFrame] = {}
    try:
        import yfinance as yf
    except Exception:
        return out
    period, interval = (INTRADAY_PERIOD, INTRADAY_INTERVAL) if intraday else (DATA_PERIOD, "1d")
    tickers = [f"{c}{suffix}" for c in codes]
    try:
        raw = yf.download(" ".join(tickers), period=period, interval=interval, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True, timeout=30)
    except Exception:
        return out
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


def load_universe_data(use_cache_only: bool = False, intraday: bool = False) -> dict[str, pd.DataFrame]:
    """回傳 {code: OHLCV df(大寫欄位, index=日期/時間)}。即時優先，缺的退快取(日線)。
    intraday=True 抓 15 分 K；快取只有日線，故盤中模式缺的不退快取。"""
    rows = all_codes()
    codes = [c for c, _, _ in rows]
    data: dict[str, pd.DataFrame] = {}

    if not use_cache_only:
        # 上市(.TW) 與 上櫃(.TWO) 各批次抓一次；台股代號多為上市，先 .TW 再對缺的試 .TWO
        fresh = _bulk_yf(codes, ".TW", intraday=intraday)
        data.update(fresh)
        missing = [c for c in codes if c not in data]
        if missing:
            data.update(_bulk_yf(missing, ".TWO", intraday=intraday))

    # 日線模式：仍缺的(或純快取模式)退回快取。盤中模式快取無分時資料，不退。
    if not intraday:
        for c in codes:
            if c not in data:
                df = _read_cache(c)
                if df is not None:
                    data[c] = df
    return data


# ── 個股分析 ──────────────────────────────────────────────────────────────
def _lower(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={x: x.lower() for x in df.columns})


def analyse_one(df_raw: pd.DataFrame) -> dict | None:
    if df_raw is None or len(df_raw) < 22:
        return None
    # 只取最近 180 根：半年足夠算所有指標，避免 SuperTrend 迴圈在 20 年全歷史上爆慢
    df = _lower(df_raw.tail(180).reset_index(drop=True))
    close = df["close"].astype(float)
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    chg = round((price - prev) / prev * 100, 2) if prev else 0.0
    mom5 = round((price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100, 2) if len(close) >= 6 else 0.0

    rsi = calc_rsi(df, period=RSI_PERIOD).get("rsi")
    ma = calc_ma(df, periods=[20, 60])
    ma20, ma60 = ma["ma"].get(20), ma["ma"].get(60)
    st_today = calc_supertrend(df, ST_PERIOD, ST_MULT).get("direction")
    st_prev = calc_supertrend(df.iloc[:-1].reset_index(drop=True), ST_PERIOD, ST_MULT).get("direction") \
        if len(df) > ST_PERIOD + 2 else None
    macd = calc_macd(df)

    above20 = ma20 is not None and price > ma20
    above60 = ma60 is not None and price > ma60
    prev_above20 = ma20 is not None and prev >= ma20  # 約略(用今日MA20近似前日，足夠判剛跌破)

    # 個股強弱分 0-100：RSI(40%) + 站上MA20(15) + 站上MA60(15) + SuperTrend多(15) + 5日動能(15)
    score = 0.0
    if rsi is not None:
        score += 0.40 * rsi
    score += 15 if above20 else 0
    score += 15 if above60 else 0
    score += 15 if st_today == "UP" else 0
    score += max(-15, min(15, mom5 * 1.5))  # 動能折算 ±15
    score = round(max(0, min(100, score)), 1)

    # 訊號判定
    signal = None
    reason = ""
    if st_prev == "DOWN" and st_today == "UP" and rsi is not None and 30 <= rsi <= 70:
        signal, reason = "long", f"SuperTrend 翻多，RSI {rsi:.0f} 健康區"
    elif st_prev == "UP" and st_today == "DOWN":
        signal, reason = "short", f"SuperTrend 翻空，跌勢轉折"
    elif ma20 is not None and price < ma20 and prev >= ma20:
        signal, reason = "short", f"跌破 20MA（{ma20:.1f}）"

    return {
        "price": round(price, 2), "chg": chg, "mom5": mom5,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "above20": above20, "above60": above60,
        "st": st_today, "macd_trend": macd.get("trend"),
        "score": score, "signal": signal, "reason": reason,
    }


# ── 聚合 ──────────────────────────────────────────────────────────────────
def _temp_label(t: float) -> tuple[str, str]:
    if t >= 75:   return "超強", "#ff3b6b"
    if t >= 60:   return "偏多", "#ff9f45"
    if t >= 45:   return "中性", "#ffd75e"
    if t >= 30:   return "偏弱", "#4fd1c5"
    return "超弱", "#3b82f6"


def build_state(data: dict[str, pd.DataFrame], use_cache_only: bool, intraday: bool = False) -> dict:
    code_meta = {c: (n, ind) for c, n, ind in all_codes()}
    stocks: list[dict] = []
    for code, df in data.items():
        a = analyse_one(df)
        if not a:
            continue
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
    temperature = round(0.50 * avg_rsi + 0.35 * breadth + 0.15 * adr_score, 1)
    t_label, t_color = _temp_label(temperature)

    # 產業板塊熱流
    sectors: list[dict] = []
    for ind in INDUSTRIES:
        members = [s for s in stocks if s["industry"] == ind]
        if not members:
            continue
        avg_chg = round(sum(s["chg"] for s in members) / len(members), 2)
        bull = round(sum(1 for s in members if s["above20"]) / len(members) * 100, 0)
        avg_score = round(sum(s["score"] for s in members) / len(members), 1)
        leader = max(members, key=lambda s: s["chg"])
        sectors.append({
            "name": ind, "avg_chg": avg_chg, "bull_pct": bull,
            "score": avg_score, "count": len(members), "hue": INDUSTRY_HUE.get(ind, 200),
            "leader": f"{leader['name']} {leader['chg']:+.1f}%",
        })
    sectors.sort(key=lambda s: s["score"], reverse=True)

    # 強弱榜
    by_score = sorted(stocks, key=lambda s: s["score"], reverse=True)
    strong = [_card(s) for s in by_score[:8]]
    weak = [_card(s) for s in by_score[-8:][::-1]]

    # 訊號
    longs = [_sig(s) for s in stocks if s["signal"] == "long"]
    shorts = [_sig(s) for s in stocks if s["signal"] == "short"]
    longs.sort(key=lambda s: s["score"], reverse=True)
    shorts.sort(key=lambda s: s["score"])

    return {
        "ok": True,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "date": str(date.today()),
        "source": "cache" if use_cache_only else "live",
        "mode": "intraday" if intraday else "daily",
        "universe": n,
        "gauge": {
            "temperature": temperature, "label": t_label, "color": t_color,
            "avg_rsi": avg_rsi, "breadth": breadth,
            "adv": adv, "dec": dec, "flat": flat, "adr": adr,
        },
        "sectors": sectors,
        "strong": strong,
        "weak": weak,
        "signals": {"long": longs, "short": shorts},
    }


def _card(s: dict) -> dict:
    return {"code": s["code"], "name": s["name"], "industry": s["industry"],
            "price": s["price"], "chg": s["chg"], "rsi": s["rsi"], "score": s["score"],
            "st": s["st"]}


def _sig(s: dict) -> dict:
    d = _card(s)
    d.update({"side": s["signal"], "reason": s["reason"]})
    return d


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
    SIG_LOG.write_text(json.dumps({"date": str(date.today()), "keys": sorted(keys)},
                                  ensure_ascii=False, indent=2), encoding="utf-8")


def push_new_signals(state: dict) -> int:
    """只推今天還沒推過的訊號，回傳本次新推數。"""
    pushed = _load_pushed()
    fresh: list[dict] = []
    for side in ("long", "short"):
        for s in state["signals"][side]:
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
    lines = [f"🎯 數據獵手｜市場溫度 {g['temperature']}（{state['gauge']['label']}）",
             f"漲{g['adv']}/跌{g['dec']}　站上20MA {g['breadth']}%", "━━━━━━━━━━━━"]
    for s in fresh:
        icon = "🟢做多" if s["side"] == "long" else "🔴做空"
        lines.append(f"{icon} {s['code']} {s['name']} {s['price']}")
        lines.append(f"   {s['reason']}（強弱 {s['score']}）")
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
def run_once(push: bool = True, cache_only: bool = False, intraday: bool = False) -> dict:
    t0 = time.time()
    mode_txt = "盤中15分K" if intraday else ("快取日線" if cache_only else "即時日線")
    print(f"[hunter] 載入宇宙資料（{mode_txt}）…")
    data = load_universe_data(use_cache_only=cache_only, intraday=intraday)
    print(f"[hunter] 取得 {len(data)} 檔，計算指標中…")
    state = build_state(data, use_cache_only=cache_only, intraday=intraday)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if not state.get("ok"):
        print(f"[hunter] ✗ 掃描無資料：{state.get('error')}")
        return state

    g = state["gauge"]
    nl, ns = len(state["signals"]["long"]), len(state["signals"]["short"])
    print(f"[hunter] 溫度 {g['temperature']}（{g['label']}）｜漲{g['adv']}/跌{g['dec']}"
          f"｜站上20MA {g['breadth']}%｜做多訊號{nl} 做空{ns}")
    print(f"[hunter] 板塊最強：{state['sectors'][0]['name']}（{state['sectors'][0]['avg_chg']:+.1f}%）"
          f"／最弱：{state['sectors'][-1]['name']}（{state['sectors'][-1]['avg_chg']:+.1f}%）")

    if push:
        n = push_new_signals(state)
        print(f"[hunter] 推播 {n} 個新訊號" if n else "[hunter] 無新訊號可推")
    print(f"[hunter] 完成，耗時 {time.time()-t0:.1f}s → {STATE_FILE.name}")
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="不推播(測試)")
    ap.add_argument("--cache", action="store_true", help="只讀快取不連網(日線)")
    ap.add_argument("--intraday", action="store_true", help="盤中 15 分 K 即時模式")
    args = ap.parse_args()
    run_once(push=not args.no_push, cache_only=args.cache, intraday=args.intraday)


if __name__ == "__main__":
    main()
