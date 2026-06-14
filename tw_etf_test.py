# 測試策略在「會走趨勢的台股標的」：大盤指數 + ETF（趨勢策略該套的地方）
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import yfinance as yf, pandas as pd
import strategy

syms = [
    ('0050 台灣50', '0050.TW'),
    ('006208 富邦台50', '006208.TW'),
    ('0056 高股息', '0056.TW'),
    ('00631L 台50正2', '00631L.TW'),
    ('2330 台積電', '2330.TW'),
    ('^TWII 大盤指數', '^TWII'),
]
print(f"{'標的':<16}{'淨利%':>9}{'PF':>7}{'回撤%':>8}{'交易':>6}{'勝率%':>7}{'Ret/DD':>8}{'Sharpe':>8}")
print('-' * 72)
for name, tk in syms:
    try:
        df = yf.download(tk, period='max', auto_adjust=True, progress=False)
        if df is None or len(df) == 0:
            print(f"{name:<16} 無資料"); continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        if len(df) < 750:
            print(f"{name:<16} 資料不足 ({len(df)})"); continue
        m, trades, eq = strategy.backtest_long_only(df, cost_model='tw_real', p=strategy.Params())
        print(f"{name:<16}{m['net_profit_pct']:>+9.1f}{m['profit_factor']:>7.2f}{m['max_dd_pct']:>8.1f}{m['n_trades']:>6}{m['win_rate_pct']:>7.0f}{m['return_over_maxdd']:>8.2f}{m['sharpe']:>8.2f}  ({len(df)}根)")
    except Exception as e:
        print(f"{name:<16} ERROR {e}")
