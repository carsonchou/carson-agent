#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock_checkup_backlog_gen.py —【個股體檢·1900檔規模化】建全市場排隊清單。

背景(2026-07-15任務，Carson拍板)：「台股1900多隻可以一隻發一集」。既有 stock_checkup_facts.py
只認手工登記的 STOCK_REGISTRY(7檔)，要規模化到全市場，得先有一份「依重要性排好隊」的清單，
每天 stock_checkup_daily.py 從隊伍最前面撈一檔出來做。

排序依據：市值代理＝近期日均成交值(Volume × Close)，抓自 twdata/cache/(tw_data.py 既有的
全市場 OHLCV 快取，1900+ 檔已經在那裡，不必再打一次網路)——不用 yfinance marketCap 是因為
1900 檔的股本/市值需要另一組 API 逐檔查，會撞 rate limit；成交值本身就是「這檔夠不夠重要值得
優先介紹」的合理代理(交易冷門的殭屍股本來就不該排前面)。

已經體檢過的代號(STUDIO/stock_checkup_facts.json 的 by_code)自動標 done=true，
backlog 重新生成不會讓已發過的集數退回隊伍。

用法：
  python scripts/stock_checkup_backlog_gen.py            # 重建 STUDIO/stock_checkup_backlog.json
  python scripts/stock_checkup_backlog_gen.py --top 20    # 只印前20名(不寫檔，快速看排序對不對)

驗證：python -m py_compile scripts/stock_checkup_backlog_gen.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
REPO_ROOT = ROOT.parent                                  # D:\carson-agent
STUDIO = ROOT / "STUDIO"
CACHE_DIR = REPO_ROOT / "twdata" / "cache"
OUT_FILE = STUDIO / "stock_checkup_backlog.json"
CHECKUP_FACTS = STUDIO / "stock_checkup_facts.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_fundamentals  # noqa: E402  唯讀沿用 fetch_stock_info_table()(FinMind全市場對照表，官方名稱/產業)

# 2026-07-15：改直接掃 twdata/cache/ 檔名建全市場清單，不走 tw_data.get_universe()——
# 那支要 import twstock，只有系統 python 裝了(.venv 沒裝，local_cron 預設用 .venv 跑，
# 這樣寫可以讓本腳本兩種 python 都能跑，不必額外把它加進 PLAYWRIGHT_SCRIPTS 那種特例白名單)。
# 篩選規則：標準4碼、不以「00」開頭 → 個股(twdata/cache 實測1939檔裡1925檔符合這規則)；
# 「00」開頭(0050/0056/00878/00631L槓桿反向ETF等13檔)與少數5/6/9碼(特別股/TDR等12檔)排除——
# Carson 拍板本系列是「單獨介紹一隻股票」，ETF/非普通股不在範圍內。
_RX_STOCK_CODE = re.compile(r"^[1-9]\d{3}$")

N_TAIL_ROWS = 40   # 近N筆交易日算平均成交值(twdata/cache本身只 tail 180根，這裡再取尾端40根，抓近況)


def _scan_universe():
    """掃 twdata/cache/{code}_{TW|TWO}.csv 檔名，回傳 [(code, ticker, market), ...]（只留標準個股代碼）。"""
    out = []
    if not CACHE_DIR.exists():
        return out
    for p in CACHE_DIR.glob("*.csv"):
        stem = p.stem  # 如 "2330_TW" 或 "5388_TWO"
        if "_" not in stem:
            continue
        code, _, mkt_suffix = stem.rpartition("_")
        if not _RX_STOCK_CODE.match(code):
            continue
        if mkt_suffix == "TW":
            ticker, market = f"{code}.TW", "上市"
        elif mkt_suffix == "TWO":
            ticker, market = f"{code}.TWO", "上櫃"
        else:
            continue
        out.append((code, ticker, market))
    out.sort(key=lambda x: x[0])
    return out


def _turnover_proxy(ticker: str):
    """讀 twdata/cache/{ticker安全檔名}.csv 尾端N筆，算平均(Volume×Close)當市值/重要性代理。
    抓不到/資料太短 → 回 None(該檔會被排到隊伍最後，不是直接排除——仍給機會，只是優先度低)。"""
    safe = ticker.replace(".", "_")
    p = CACHE_DIR / f"{safe}.csv"
    if not p.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_csv(p)
        if "Close" not in df.columns or "Volume" not in df.columns:
            return None
        df = df.tail(N_TAIL_ROWS)
        df = df[(df["Volume"] > 0) & (df["Close"] > 0)]
        if len(df) < 5:
            return None
        turnover = (df["Volume"] * df["Close"]).mean()
        return float(turnover) if turnover == turnover else None  # NaN check
    except Exception:  # noqa: BLE001
        return None


def _done_codes():
    if not CHECKUP_FACTS.exists():
        return {}
    try:
        d = json.loads(CHECKUP_FACTS.read_text(encoding="utf-8"))
        return d.get("by_code") or {}
    except Exception:  # noqa: BLE001
        return {}


def build_backlog():
    universe = _scan_universe()  # [(code, ticker, market), ...]
    done = _done_codes()
    info_table = stock_fundamentals.fetch_stock_info_table()  # 全市場官方名稱/產業對照表(7天快取)
    rows = []
    n_missing_cache = 0
    for code, ticker, market in universe:
        proxy = _turnover_proxy(ticker)
        if proxy is None:
            n_missing_cache += 1
        name = (info_table.get(code) or {}).get("name") or (done.get(code) or {}).get("name") or code
        rows.append({
            "code": code, "name": name, "ticker": ticker, "market": market,
            "turnover_proxy": proxy,
            "done": code in done,
            "skip": False, "skip_reason": "",
        })
    # 排序：有成交值代理的依大到小排前面；沒有(快取缺檔/資料太短)的排最後，組內仍依代號穩定排序
    rows.sort(key=lambda r: (r["turnover_proxy"] is None, -(r["turnover_proxy"] or 0), r["code"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    n_done = sum(1 for r in rows if r["done"])
    return {
        "generated_at": _dt.date.today().isoformat(),
        "method": "近40筆快取交易日平均(Volume×Close)當市值/重要性代理，抓自 twdata/cache/(tw_data.get_universe 全市場清單)",
        "n_total": len(rows), "n_done": n_done, "n_missing_turnover_data": n_missing_cache,
        "items": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="只印前N名(不寫檔)")
    args = ap.parse_args()

    bl = build_backlog()
    if args.top:
        print(f"【個股體檢·backlog 前{args.top}名】(共{bl['n_total']}檔，已體檢{bl['n_done']}檔，"
              f"{bl['n_missing_turnover_data']}檔缺成交值代理資料)")
        for r in bl["items"][:args.top]:
            mark = "✓已體檢" if r["done"] else "  待體檢"
            tp = f"{r['turnover_proxy']/1e8:.2f}億" if r["turnover_proxy"] else "（無代理資料）"
            print(f"  #{r['rank']:<4} [{mark}] {r['code']} {r['name']}　近期日均成交值≈{tp}")
        return 0

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[stock_checkup_backlog_gen] 已寫入 {OUT_FILE}")
    print(f"  共 {bl['n_total']} 檔，已體檢 {bl['n_done']} 檔，"
          f"{bl['n_missing_turnover_data']} 檔缺成交值代理資料(排隊伍最後)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
