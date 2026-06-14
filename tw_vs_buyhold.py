# 策略 vs 買進持有(buy&hold) — 看策略在大牛標的上是不是「該賺的沒賺到」
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import yfinance as yf, pandas as pd
import strategy

# (名稱, ticker, 模式參數)
def params_long2():
    p = strategy.Params(); p.erThr=0.26; p.adxOn=25; p.minVotes=2; p.trailMidR=2.5; p.trailTightR=3.5; p.tp2R=3.5; p.peakArmK=2.0; p.chandMult=3.5; p.baseLen=10; return p
def params_0050():
    p = strategy.Params(); p.baseLen=20; p.erThr=0.36; p.adxOn=25; p.minVotes=2; p.chandMult=3.0; p.trailMidR=2.8; p.trailTightR=2.5; p.tp2R=4.5; p.peakArmK=2.5; return p

cases = [('00631L 正2','00631L.TW',params_long2(),False),
         ('00675L 富邦正2','00675L.TW',params_long2(),False),
         ('0050','0050.TW',params_0050(),False),
         ('006208','006208.TW',params_long2(),False)]
print(f"{'標的':<16}{'策略淨利%':>10}{'買進持有%':>11}{'策略MaxDD%':>11}{'B&H MaxDD%':>11}{'交易':>6}")
print('-'*70)
for name, tk, p, short in cases:
    df = yf.download(tk, period='max', auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df[['Open','High','Low','Close','Volume']].dropna()
    m,_,_ = strategy.backtest(df, cost_model='tw_real', p=p, allow_short=short)
    c = df['Close']
    bh_ret = (c.iloc[-1]/c.iloc[0]-1)*100
    bh_dd = ((c-c.cummax())/c.cummax()).min()*-100
    print(f"{name:<16}{m['net_profit_pct']:>+10.1f}{bh_ret:>+11.1f}{m['max_dd_pct']:>11.1f}{bh_dd:>11.1f}{m['n_trades']:>6}")
