# -*- coding: utf-8 -*-
"""
tw_pledge_lending.py — 台股質押借貸 + 買入策略

功能：
  1. 查詢股票即時報價（TWSE MIS API）
  2. 計算質押借貸額度（依質押成數 LTV）
  3. 計算買入股數與成本
  4. 輸出完整策略摘要

用法：
  python tw_pledge_lending.py --symbol 009816 --shares 10000 --ltv 0.6
"""
import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests


# ─── 設定 ────────────────────────────────────────────────────────────────────

@dataclass
class PledgeConfig:
    symbol: str = "009816"
    initial_shares: int = 10000          # 持有股數
    ltv_ratio: float = 0.60              # 質押成數（60%）
    loan_rate: float = 0.025             # 年利率 2.5%
    buy_commission: float = 0.001425     # 買進手續費
    sell_commission: float = 0.001425    # 賣出手續費
    transaction_tax: float = 0.003       # 交易稅（股票 0.3%，ETF 0.1%）
    loan_days: int = 365                 # 借款天數


@dataclass
class QuoteResult:
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float
    volume: int
    high: float
    low: float
    open: float
    prev_close: float
    market: str
    timestamp: str
    source: str = "TWSE MIS"


@dataclass
class PledgeResult:
    # 持有部位
    symbol: str
    name: str
    current_price: float
    initial_shares: int
    initial_value: float

    # 借貸條件
    ltv_ratio: float
    max_loan_amount: float
    loan_rate: float

    # 買入計算
    usable_loan: float                   # 扣除手續費後可用金額
    additional_shares: int               # 可買入股數（張 × 1000）
    buy_cost: float                      # 實際買入金額
    commission_paid: float               # 手續費
    net_borrowed: float                  # 實際動用借款

    # 總計
    total_shares: int
    total_value: float
    leverage_ratio: float

    # 成本
    annual_interest: float               # 年化利息
    daily_interest: float                # 日利息
    loan_days: int
    total_interest: float                # 借款期間總利息

    # 損益平衡
    breakeven_return_pct: float          # 需要幾 % 報酬才能打平利息


# ─── 報價模組 ──────────────────────────────────────────────────────────────────

def _twse_quote(symbol: str, retries: int = 3) -> Optional[QuoteResult]:
    """查詢 TWSE MIS 即時報價（上市）。"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    params = {"ex_ch": f"tse_{symbol}.tw", "json": "1", "delay": "0"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("msgArray", [])
            if not items:
                return None
            row = items[0]

            def safe_float(val, default=0.0):
                try:
                    return float(val) if val not in ("-", "", None) else default
                except (ValueError, TypeError):
                    return default

            price = safe_float(row.get("z")) or safe_float(row.get("b"))
            prev_close = safe_float(row.get("y"))
            change = price - prev_close if prev_close else 0.0
            change_pct = (change / prev_close * 100) if prev_close else 0.0

            return QuoteResult(
                symbol=symbol,
                name=row.get("n", symbol),
                price=price,
                change=round(change, 2),
                change_pct=round(change_pct, 2),
                volume=int(safe_float(row.get("v", "0").replace(",", ""))),
                high=safe_float(row.get("h")),
                low=safe_float(row.get("l")),
                open=safe_float(row.get("o")),
                prev_close=prev_close,
                market="上市",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return None


def _otc_quote(symbol: str, retries: int = 3) -> Optional[QuoteResult]:
    """查詢 OTC（上櫃）報價。"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    params = {"ex_ch": f"otc_{symbol}.tw", "json": "1", "delay": "0"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("msgArray", [])
            if not items:
                return None
            row = items[0]

            def safe_float(val, default=0.0):
                try:
                    return float(val) if val not in ("-", "", None) else default
                except (ValueError, TypeError):
                    return default

            price = safe_float(row.get("z")) or safe_float(row.get("b"))
            prev_close = safe_float(row.get("y"))
            change = price - prev_close if prev_close else 0.0
            change_pct = (change / prev_close * 100) if prev_close else 0.0

            return QuoteResult(
                symbol=symbol,
                name=row.get("n", symbol),
                price=price,
                change=round(change, 2),
                change_pct=round(change_pct, 2),
                volume=int(safe_float(row.get("v", "0").replace(",", ""))),
                high=safe_float(row.get("h")),
                low=safe_float(row.get("l")),
                open=safe_float(row.get("o")),
                prev_close=prev_close,
                market="上櫃",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return None


def _yfinance_fallback(symbol: str) -> Optional[QuoteResult]:
    """yfinance 備援報價（離線或非交易時間使用）。"""
    try:
        import yfinance as yf
        for suffix in [".TW", ".TWO"]:
            ticker_str = f"{symbol}{suffix}"
            t = yf.Ticker(ticker_str)
            hist = t.history(period="2d", progress=False)
            if hist is not None and len(hist) > 0:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
                change = price - prev
                change_pct = (change / prev * 100) if prev else 0.0
                info = t.info or {}
                return QuoteResult(
                    symbol=symbol,
                    name=info.get("longName", symbol),
                    price=round(price, 2),
                    change=round(change, 2),
                    change_pct=round(change_pct, 2),
                    volume=int(hist["Volume"].iloc[-1]),
                    high=float(hist["High"].iloc[-1]),
                    low=float(hist["Low"].iloc[-1]),
                    open=float(hist["Open"].iloc[-1]),
                    prev_close=round(prev, 2),
                    market="上市" if suffix == ".TW" else "上櫃",
                    timestamp=str(hist.index[-1].date()),
                    source="yfinance（備援）",
                )
    except Exception:
        pass
    return None


def get_quote(symbol: str) -> Optional[QuoteResult]:
    """取得報價，依序嘗試 TWSE → OTC → yfinance。"""
    q = _twse_quote(symbol)
    if q and q.price > 0:
        return q
    q = _otc_quote(symbol)
    if q and q.price > 0:
        return q
    return _yfinance_fallback(symbol)


# ─── 質押借貸計算 ────────────────────────────────────────────────────────────────

def calculate_pledge(config: PledgeConfig, price: float, name: str = "") -> PledgeResult:
    """
    根據持有股數、現價、質押成數計算借貸額度與可買入股數。

    台灣股票以「張」（1000 股）為單位交易。
    """
    # 持有市值
    initial_value = config.initial_shares * price

    # 最高借款額度
    max_loan = initial_value * config.ltv_ratio

    # 每張成本（含手續費）
    cost_per_lot = price * 1000 * (1 + config.buy_commission)

    # 可買張數（無條件捨去，確保資金夠用）
    lots_buyable = int(max_loan / cost_per_lot)
    if lots_buyable <= 0:
        lots_buyable = 0

    additional_shares = lots_buyable * 1000
    buy_cost = additional_shares * price
    commission_paid = buy_cost * config.buy_commission
    net_borrowed = buy_cost + commission_paid          # 實際動用借款

    # 總部位
    total_shares = config.initial_shares + additional_shares
    total_value = total_shares * price
    leverage_ratio = total_value / initial_value if initial_value else 1.0

    # 利息計算
    annual_interest = net_borrowed * config.loan_rate
    daily_interest = annual_interest / 365
    total_interest = daily_interest * config.loan_days

    # 損益平衡：需要幾 % 報酬才打平利息
    breakeven_return_pct = (total_interest / initial_value * 100) if initial_value else 0.0

    return PledgeResult(
        symbol=config.symbol,
        name=name,
        current_price=price,
        initial_shares=config.initial_shares,
        initial_value=round(initial_value, 0),
        ltv_ratio=config.ltv_ratio,
        max_loan_amount=round(max_loan, 0),
        loan_rate=config.loan_rate,
        usable_loan=round(max_loan, 0),
        additional_shares=additional_shares,
        buy_cost=round(buy_cost, 0),
        commission_paid=round(commission_paid, 0),
        net_borrowed=round(net_borrowed, 0),
        total_shares=total_shares,
        total_value=round(total_value, 0),
        leverage_ratio=round(leverage_ratio, 4),
        annual_interest=round(annual_interest, 0),
        daily_interest=round(daily_interest, 2),
        loan_days=config.loan_days,
        total_interest=round(total_interest, 0),
        breakeven_return_pct=round(breakeven_return_pct, 4),
    )


# ─── 輸出格式化 ──────────────────────────────────────────────────────────────────

def _fmt(n: float, decimal: int = 0) -> str:
    if decimal == 0:
        return f"{n:,.0f}"
    return f"{n:,.{decimal}f}"


def print_quote(q: QuoteResult) -> None:
    sign = "+" if q.change >= 0 else ""
    print(f"\n{'─'*52}")
    print(f"  {q.symbol} {q.name}  [{q.market}]")
    print(f"{'─'*52}")
    print(f"  現價    : {q.price:.2f}")
    print(f"  漲跌    : {sign}{q.change:.2f}  ({sign}{q.change_pct:.2f}%)")
    print(f"  開/高/低: {q.open:.2f} / {q.high:.2f} / {q.low:.2f}")
    print(f"  昨收    : {q.prev_close:.2f}")
    print(f"  成交量  : {_fmt(q.volume)} 股")
    print(f"  時間    : {q.timestamp}  （{q.source}）")
    print(f"{'─'*52}")


def print_pledge_summary(r: PledgeResult, config: PledgeConfig) -> None:
    print(f"\n{'═'*52}")
    print(f"  質押借貸 + 買入策略  — {r.symbol} {r.name}")
    print(f"{'═'*52}")

    print(f"\n【持有部位】")
    print(f"  股數         : {_fmt(r.initial_shares)} 股（{r.initial_shares//1000} 張）")
    print(f"  現價         : {r.current_price:.2f} 元")
    print(f"  持倉市值     : {_fmt(r.initial_value)} 元")

    print(f"\n【質押借貸條件】")
    print(f"  質押成數     : {r.ltv_ratio*100:.0f}%")
    print(f"  最高借款額度 : {_fmt(r.max_loan_amount)} 元")
    print(f"  借款年利率   : {r.loan_rate*100:.2f}%")

    print(f"\n【買入 {r.symbol} 計畫】")
    print(f"  可買股數     : {_fmt(r.additional_shares)} 股（{r.additional_shares//1000} 張）")
    print(f"  買入金額     : {_fmt(r.buy_cost)} 元")
    print(f"  手續費       : {_fmt(r.commission_paid)} 元")
    print(f"  實際動用借款 : {_fmt(r.net_borrowed)} 元")

    print(f"\n【買後總部位】")
    print(f"  總持股       : {_fmt(r.total_shares)} 股（{r.total_shares//1000} 張）")
    print(f"  總市值       : {_fmt(r.total_value)} 元")
    print(f"  槓桿倍數     : {r.leverage_ratio:.2f}x")

    print(f"\n【利息成本（借款 {r.loan_days} 天）】")
    print(f"  年化利息     : {_fmt(r.annual_interest)} 元")
    print(f"  日利息       : {_fmt(r.daily_interest, 2)} 元")
    print(f"  借款期利息   : {_fmt(r.total_interest)} 元")
    print(f"  損益平衡報酬 : {r.breakeven_return_pct:.4f}%  （相對初始市值）")

    print(f"\n【風險提示】")
    if r.leverage_ratio > 1.5:
        print(f"  ⚠  槓桿 {r.leverage_ratio:.2f}x，股價下跌 {100/r.leverage_ratio:.1f}% 即虧損本金")
    maintain_pct = (1 - 1 / r.leverage_ratio) * 100 if r.leverage_ratio > 1 else 0
    print(f"  ⚠  維持率跌破 130% 可能觸發追繳（依各券商規定）")
    print(f"  ⚠  借款利率浮動，請以實際券商報價為準")
    print(f"{'═'*52}\n")


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def run(config: PledgeConfig, manual_price: Optional[float] = None) -> Optional[PledgeResult]:
    print(f"\n查詢 {config.symbol} 報價中...", flush=True)

    if manual_price:
        price = manual_price
        name = config.symbol
        print(f"使用手動輸入價格: {price:.2f}")
    else:
        q = get_quote(config.symbol)
        if q is None or q.price <= 0:
            print(f"[錯誤] 無法取得 {config.symbol} 報價，請確認代號或改用 --price 手動輸入")
            return None
        print_quote(q)
        price = q.price
        name = q.name

    result = calculate_pledge(config, price, name)
    print_pledge_summary(result, config)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="009816 質押借貸 + 買入策略計算機",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python tw_pledge_lending.py
  python tw_pledge_lending.py --symbol 009816 --shares 20000 --ltv 0.65
  python tw_pledge_lending.py --symbol 0050 --shares 5000 --price 150.5
  python tw_pledge_lending.py --symbol 009816 --shares 10000 --days 180
        """,
    )
    parser.add_argument("--symbol", default="009816", help="股票代號（預設 009816）")
    parser.add_argument("--shares", type=int, default=10000, help="持有股數（預設 10000）")
    parser.add_argument("--ltv", type=float, default=0.60, help="質押成數 0~1（預設 0.60）")
    parser.add_argument("--rate", type=float, default=0.025, help="年利率（預設 0.025 即 2.5%%）")
    parser.add_argument("--days", type=int, default=365, help="借款天數（預設 365）")
    parser.add_argument("--price", type=float, default=None, help="手動指定現價（跳過 API）")
    args = parser.parse_args()

    if not (0 < args.ltv <= 1):
        print("[錯誤] --ltv 必須在 0~1 之間")
        sys.exit(1)
    if args.shares <= 0:
        print("[錯誤] --shares 必須大於 0")
        sys.exit(1)

    config = PledgeConfig(
        symbol=args.symbol,
        initial_shares=args.shares,
        ltv_ratio=args.ltv,
        loan_rate=args.rate,
        loan_days=args.days,
    )
    run(config, manual_price=args.price)


if __name__ == "__main__":
    main()
