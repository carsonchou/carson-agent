# -*- coding: utf-8 -*-
"""
verify_short.py — 多空雙向回歸 + 驗證

1. 回歸測試：backtest(allow_short=False) 必須與 backtest_long_only() 完全一致
   （指標 + equity 曲線逐點相同），確保沒破壞既有 long-only 結果。
2. 驗證：在 2330.TW / 00631L.TW / ^TWII 上各跑 long-only 與 long+short，
   印出 淨利%/PF/交易數/MaxDD/Ret-DD/勝率 對照，並確認空單有實際進場。

執行：使用指定的 Python 3.9 解譯器執行本檔。
"""
import sys
import warnings

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

import tw_data
import strategy


def fmt(m):
    pf = "inf" if not np.isfinite(m["profit_factor"]) else "%.2f" % m["profit_factor"]
    rdd = "inf" if not np.isfinite(m["return_over_maxdd"]) else "%.2f" % m["return_over_maxdd"]
    return ("淨利=%7.1f%%  PF=%5s  交易=%3d  MaxDD=%5.1f%%  Ret/DD=%6s  勝率=%.0f%%"
            % (m["net_profit_pct"], pf, m["n_trades"], m["max_dd_pct"], rdd, m["win_rate_pct"]))


def regression():
    print("=" * 100)
    print("回歸測試：backtest(allow_short=False) == backtest_long_only()")
    print("=" * 100)
    allpass = True
    keys = ["net_profit_pct", "profit_factor", "max_dd_pct", "n_trades",
            "win_rate_pct", "return_over_maxdd", "sharpe"]
    for t in ["2330.TW", "00631L.TW", "2317.TW", "2308.TW", "^TWII"]:
        df = tw_data.load_ohlcv(t, period="max", sleep=0.4)
        if df is None:
            print(t, "下載失敗"); continue
        for cost in ["tw_real", "pine"]:
            m_old, _, eq_old = strategy.backtest_long_only(df, cost_model=cost)
            m_new, _, eq_new = strategy.backtest(df, cost_model=cost, allow_short=False)
            match = all(str(m_old[k]) == str(m_new[k]) for k in keys)
            eqmatch = np.allclose(eq_old.values, eq_new.values, atol=1e-6)
            if not (match and eqmatch):
                allpass = False
            print("  %-10s %-8s metrics=%s equity=%s"
                  % (t, cost, "PASS" if match else "FAIL", "PASS" if eqmatch else "FAIL"))
    print("\n  >>> 回歸總結:", "全部 PASS（long-only 結果可重現）" if allpass else "有 FAIL！")
    return allpass


def validate():
    print("\n" + "=" * 100)
    print("驗證：long-only vs long+short（多空雙向）")
    print("=" * 100)
    for sym in ["2330.TW", "00631L.TW", "^TWII"]:
        df = tw_data.load_ohlcv(sym, period="max", sleep=0.4)
        if df is None:
            print(sym, "下載失敗"); continue
        print("-" * 100)
        print("%s  (%d bars, %s ~ %s)" % (sym, len(df), df.index[0].date(), df.index[-1].date()))
        for cost in ["tw_real", "pine"]:
            m_l, _, _ = strategy.backtest(df, cost_model=cost, allow_short=False)
            m_ls, tr_ls, _ = strategy.backtest(df, cost_model=cost, allow_short=True)
            n_short = sum(1 for t in tr_ls if t["side"] == "short")
            n_long = sum(1 for t in tr_ls if t["side"] == "long")
            print(" [%s]" % cost)
            print("   long-only  :", fmt(m_l))
            print("   long+short :", fmt(m_ls), " (多 %d / 空 %d 筆)" % (n_long, n_short))


if __name__ == "__main__":
    ok = regression()
    validate()
    sys.exit(0 if ok else 1)
