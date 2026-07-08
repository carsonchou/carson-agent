#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_cards.py — 跑多幣【真實】回測，蒸餾成縮圖可用的真數據卡。

用 trading_bot 的回測器（直連 Pionex 公開 K 棒、免金鑰、純讀取）跑 SuperTrend 策略，
把每個幣的真實 總報酬/最大回撤/夏普/勝率 存成 STUDIO/backtest_cards.json，
讓 make_thumbnails 自動用「真回測數字」做縮圖卡——取代示意值，也免 Carson 手動截圖。

⚠️ 需用「有 pandas 的系統 python」跑（不是 youtube_channel/.venv）。trading_bot 在本機才有，
   故本檔在本機產 JSON，再把 JSON 部署到雲端給 make_thumbnails 讀（雲端無 trading_bot）。

用法：
  python scripts/backtest_cards.py                      # 預設多幣、1H+4H
  python scripts/backtest_cards.py --coins BTC,ETH,SOL  # 自訂幣種
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

YT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = YT_ROOT.parent
BOT = REPO_ROOT / "trading_bot"
OUT = YT_ROOT / "STUDIO" / "backtest_cards.json"

# 讓 trading_bot 的回測器可被匯入
for p in (str(BOT), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
DEFAULT_INTERVALS = ["1H", "4H"]


def _distill(symbol: str, results: dict) -> dict | None:
    """從多週期結果挑一個代表卡：優先正報酬中夏普最高；全負則取夏普最高（誠實呈現）。"""
    cand = []
    for itv, r in results.items():
        if not isinstance(r, dict) or "error" in r or "total_return" not in r:
            continue
        cand.append((itv, r))
    if not cand:
        return None
    pos = [c for c in cand if c[1]["total_return"] > 0]
    pool = pos or cand
    itv, r = max(pool, key=lambda c: c[1].get("sharpe", -99))
    coin = symbol.replace("_USDT", "")
    return {
        "coin": coin,
        "symbol": symbol,
        "interval": itv,
        "total_return": r["total_return"],
        "max_drawdown": r["max_drawdown"],
        "sharpe": r["sharpe"],
        "win_rate": r["win_rate"],
        "num_trades": r["num_trades"],
        "period": f'{str(r.get("data_start",""))[:10]}~{str(r.get("data_end",""))[:10]}',
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(DEFAULT_COINS))
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS))
    ap.add_argument("--bars", type=int, default=1000)
    args = ap.parse_args(argv)

    import run_backtest as rb  # 觸發 trading_bot sys.path 設定
    feed = rb.PionexFeed(base_url="https://api.pionex.com")

    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    intervals = [s.strip() for s in args.intervals.split(",") if s.strip()]
    cards = []
    for coin in coins:
        symbol = coin if "_" in coin else f"{coin}_USDT"
        results = {}
        for itv in intervals:
            try:
                result, df = rb.run_one(feed, symbol, itv, args.bars, 10, 3.0, 2.0)
                results[itv] = {
                    "total_return": round(float(result.total_return), 6),
                    "sharpe": round(float(result.sharpe), 4),
                    "max_drawdown": round(float(result.max_drawdown), 6),
                    "win_rate": round(float(result.win_rate), 4),
                    "num_trades": int(result.num_trades),
                    "data_start": str(df.index[0]), "data_end": str(df.index[-1]),
                }
                print(f"[ok] {symbol} {itv}: ret {result.total_return*100:.1f}% "
                      f"dd {result.max_drawdown*100:.1f}% sharpe {result.sharpe:.2f}")
            except Exception as exc:  # noqa: BLE001
                print(f"[skip] {symbol} {itv}: {str(exc)[:60]}", file=sys.stderr)
        card = _distill(symbol, results)
        if card:
            cards.append(card)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": "SuperTrend(10,3.0)·2%停損",
        "engine": "trading_bot 回測·Pionex 真實K棒",
        "cards": cards,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] {len(cards)} 幣真回測卡 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
