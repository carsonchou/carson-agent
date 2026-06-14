# -*- coding: utf-8 -*-
"""
tw_adaptive.py — Regime 自適應策略（趨勢順勢 + 盤整均值回歸）

目標：讓「全台股獲利檔比例」大幅高於純趨勢版的 ~43%。純趨勢策略對盤整股無解
      （台股多盤整），所以盤整段改用均值回歸補刀。

核心：每根 K 依 regime 切換子策略（單一部位、純多、台股放空限制）：
  - 趨勢段（ADX 高 且 ER 高）→ 順勢：三重 SuperTrend / ST3 多頭跟蹤，重倉、慢訊號出
    （ST3 翻空 / regime off / 寬停損）。趨勢續抱的簡化版。
  - 盤整段（ADX 低 或 ER 低）→ 均值回歸：價格跌破布林下軌 或 RSI<30 買進，
    回到中軌(或 RSI>55) 賣出，破底停損（下軌再下 stopK×ATR）。

資料務必修分割（個股也有反分割，污染回測）；commission/slip 用 tw_real、252。

輸出 twdata\adaptive_summary.md：自適應 vs 純趨勢 在同一份修正資料上的
  獲利檔比例 / 中位PF / 中位Ret/MaxDD / 分佈 / Top20 / 盤整股對照。

用法：
  python tw_adaptive.py --sample 12      # 先驗證
  python tw_adaptive.py --all            # 全市場
執行：使用指定的 Python 3.9 解譯器。
"""
import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

import tw_data
import strategy
import indicators as ind
import tw_trendride as tr   # 借用 adjust_splits 與成本/tick

DATA_DIR = tw_data.DATA_DIR
COST_MODELS = strategy.COST_MODELS
MIN_BARS = 1000
MIN_YEARS = 5

PRIORITY = ["2330", "2317", "2454", "2412", "2308", "2881", "2882", "2303",
            "1301", "1303", "2002", "2891", "3008", "2886", "2884", "2412"]


# ----------------------------------------------------------------------------
# 自適應參數（合理預設，不過度調）
# ----------------------------------------------------------------------------
class AdaptiveParams:
    # regime 判定
    adxLen = 14
    erLen = 20
    adxTrend = 18.0          # ADX 高於此 → 趨勢傾向（v2 OOS 驗證）
    erTrend = 0.26           # ER 高於此 → 趨勢傾向（v2 OOS 驗證）
    # 趨勢子策略（簡化趨勢續抱）
    baseLen = 10
    midMult = 2.5
    slowMult = 6.0
    f1, f2, f3 = 1.5, 2.5, 3.5
    trendExposure = 0.95     # 趨勢段重倉
    wideMult = 11.0          # 趨勢段寬停損 ATR 倍（v2 固定最佳）
    minVotesTrend = 2
    # 均值回歸子策略（盤整段）
    bbLen = 30               # v2 OOS 驗證
    bbK = 2.5                # 布林標準差倍數（v2 OOS 驗證）
    rsiLen = 14
    rsiBuy = 30.0
    rsiSell = 50.0           # v2 OOS 驗證
    mrExposure = 0.60        # 盤整段倉位（較保守，盤整賺小波段）
    mrStopK = 1.5            # 破下軌再 stopK×ATR 停損
    mrMaxBars = 30           # 均值回歸單最長持有（v2 OOS 驗證）
    # 共用
    chandLen = 22
    barsPerYear = 252.0


def rsi(close, length):
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = ind.rma(up, length)
    roll_down = ind.rma(down, length)
    rs = roll_up / roll_down.replace(0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.fillna(50.0)


def compute_adaptive_indicators(df, p):
    out = df.copy()
    close = out["Close"]
    # ST3（慢趨勢）
    len3 = max(int(round(p.baseLen * p.slowMult)), 3)
    len1 = p.baseLen
    _, d1 = ind.supertrend(out, p.f1, len1)
    _, d3 = ind.supertrend(out, p.f3, len3)
    out["dir1"], out["dir3"] = d1, d3
    # ATR / ADX / ER
    out["atrChand"] = ind.atr(out, p.chandLen)
    dip, dim, adx = ind.dmi(out, p.adxLen, p.adxLen)
    out["adx"] = adx
    out["er"] = ind.kaufman_er(close, p.erLen)
    # 布林
    ma = close.rolling(p.bbLen).mean()
    sd = close.rolling(p.bbLen).std(ddof=0)
    out["bbMid"] = ma
    out["bbLower"] = ma - p.bbK * sd
    out["bbUpper"] = ma + p.bbK * sd
    # RSI
    out["rsi"] = rsi(close, p.rsiLen)
    return out


def backtest_adaptive(df, cost_model="tw_real", initial_capital=10000.0, p=None):
    """Regime 自適應回測。回傳 (metrics, trades, equity, regime_frac)。"""
    if p is None:
        p = AdaptiveParams()
    cm = COST_MODELS[cost_model]
    data = compute_adaptive_indicators(df, p)

    o = data["Open"].to_numpy(float)
    h = data["High"].to_numpy(float)
    l = data["Low"].to_numpy(float)
    c = data["Close"].to_numpy(float)
    dir1 = data["dir1"].to_numpy(float)
    dir3 = data["dir3"].to_numpy(float)
    atrCh = data["atrChand"].to_numpy(float)
    adx = data["adx"].to_numpy(float)
    er = data["er"].to_numpy(float)
    bbMid = data["bbMid"].to_numpy(float)
    bbLower = data["bbLower"].to_numpy(float)
    rsiv = data["rsi"].to_numpy(float)
    idx = data.index
    n = len(c)

    st3Bull = dir3 < 0
    st3Bear = ~st3Bull

    def buy_px(px):
        return px + cm["slip_ticks"] * strategy._tw_tick(px) if cm["slip_ticks"] else px

    def sell_px(px):
        return max(px - cm["slip_ticks"] * strategy._tw_tick(px), 0.0) if cm["slip_ticks"] else px

    cash = initial_capital
    shares = 0.0
    mode = None              # "trend" / "mr"  當前持倉的子策略
    entry_bar = -1
    trailExt = np.nan
    trailStop = np.nan
    cur_buy = 0.0
    cur_sell = 0.0
    cur_open = False
    cur_entry = None
    trades = []
    equity = np.full(n, float(initial_capital))
    prev_stop = np.nan
    pending = None           # ("buy", exposure, mode) / ("sell",)
    trend_bars = 0

    for i in range(n):
        # 執行掛單（本根開盤）
        if pending is not None:
            if pending[0] == "buy":
                exposure = pending[1]
                eq_now = cash + shares * o[i]
                px = buy_px(o[i])
                qty = (exposure * eq_now) / px if px > 0 else 0.0
                cost = px * qty * (1 + cm["fee_buy"])
                if cost > cash:
                    qty = (cash / (px * (1 + cm["fee_buy"]))) * 0.999
                    cost = px * qty * (1 + cm["fee_buy"])
                if qty > 1e-9:
                    cash -= cost
                    shares += qty
                    cur_buy += cost
                    if not cur_open:
                        cur_open = True
                        cur_entry = idx[i]
                        mode = pending[2]
                        entry_bar = i
            elif pending[0] == "sell" and shares > 1e-9:
                px = sell_px(o[i])
                proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
                cash += proceeds
                cur_sell += proceeds
                shares = 0.0
            pending = None

        if cur_open and shares <= 1e-9:
            pnl = cur_sell - cur_buy
            trades.append(dict(entry=cur_entry, exit=idx[i], mode=mode,
                               pnl=pnl, ret=pnl / cur_buy if cur_buy > 0 else 0.0))
            cur_open = False; cur_buy = 0.0; cur_sell = 0.0; mode = None

        inPos = shares > 1e-9

        # 需要的指標就緒？
        ready = not (np.isnan(atrCh[i]) or np.isnan(bbMid[i]) or np.isnan(adx[i]))
        if i < 1 or not ready:
            equity[i] = cash + shares * c[i]
            prev_stop = trailStop
            continue

        # regime 判定
        is_trend = (adx[i] >= p.adxTrend) and (er[i] >= p.erTrend)
        if is_trend:
            trend_bars += 1

        exited = False

        # ----- 持倉中：依當前 mode 出場 -----
        if inPos and mode == "trend":
            # 硬停損（寬）
            if not np.isnan(prev_stop) and l[i] <= prev_stop:
                fill = prev_stop if o[i] >= prev_stop else o[i]
                px = sell_px(fill)
                proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
                cash += proceeds; cur_sell += proceeds; shares = 0.0
                pnl = cur_sell - cur_buy
                trades.append(dict(entry=cur_entry, exit=idx[i], mode="trend",
                                   pnl=pnl, ret=pnl / cur_buy if cur_buy > 0 else 0.0))
                cur_open = False; cur_buy = 0.0; cur_sell = 0.0; mode = None
                trailExt = np.nan; trailStop = np.nan; exited = True; inPos = False
            else:
                trailExt = h[i] if np.isnan(trailExt) else max(trailExt, h[i])
                raw = trailExt - p.wideMult * atrCh[i]
                trailStop = raw if np.isnan(trailStop) else max(trailStop, raw)
                # 慢訊號出場：ST3 翻空 或 regime 已轉成「非趨勢偏多」
                regime_off = not ((adx[i] >= p.adxTrend * 0.7))   # ADX 大幅滑落
                if bool(st3Bear[i]) or regime_off or ((not np.isnan(trailStop)) and c[i] < trailStop):
                    pending = ("sell",); exited = True

        elif inPos and mode == "mr":
            # 均值回歸出場：回到中軌 / RSI>賣出 / 破底停損 / 超時
            mr_stop = bbLower[i] - p.mrStopK * atrCh[i]
            age = i - entry_bar
            hit_stop = l[i] <= mr_stop
            if hit_stop:
                fill = mr_stop if o[i] >= mr_stop else o[i]
                px = sell_px(fill)
                proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
                cash += proceeds; cur_sell += proceeds; shares = 0.0
                pnl = cur_sell - cur_buy
                trades.append(dict(entry=cur_entry, exit=idx[i], mode="mr",
                                   pnl=pnl, ret=pnl / cur_buy if cur_buy > 0 else 0.0))
                cur_open = False; cur_buy = 0.0; cur_sell = 0.0; mode = None
                exited = True; inPos = False
            elif (c[i] >= bbMid[i]) or (rsiv[i] >= p.rsiSell) or (age >= p.mrMaxBars):
                pending = ("sell",); exited = True

        # ----- 空手：依 regime 選子策略進場 -----
        if not exited and not inPos and pending is None:
            if is_trend:
                # 順勢進場：ST3 多頭 + ER/ADX 多數決（簡化：趨勢段 + ST3Bull + dir1 多頭）
                votesOK = (adx[i] >= p.adxTrend) and (er[i] >= p.erTrend)
                if bool(st3Bull[i]) and votesOK:
                    pending = ("buy", p.trendExposure, "trend")
                    trailExt = h[i]; trailStop = np.nan
            else:
                # 盤整 → 均值回歸：跌破布林下軌 或 RSI<30，且非下降趨勢（ST3 不為空才接，避免接刀）
                oversold = (c[i] <= bbLower[i]) or (rsiv[i] <= p.rsiBuy)
                not_downtrend = not bool(st3Bear[i])   # ST3 非空頭，避免在主跌段接刀
                if oversold and not_downtrend:
                    pending = ("buy", p.mrExposure, "mr")

        equity[i] = cash + shares * c[i]
        prev_stop = trailStop

    # EOD 平倉
    if shares > 1e-9:
        i = n - 1
        px = sell_px(c[i])
        proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
        cash += proceeds; cur_sell += proceeds; shares = 0.0
        if cur_open:
            pnl = cur_sell - cur_buy
            trades.append(dict(entry=cur_entry, exit=idx[i], mode=mode,
                               pnl=pnl, ret=pnl / cur_buy if cur_buy > 0 else 0.0))
    equity[n - 1] = cash + shares * c[n - 1]

    eq = pd.Series(equity, index=idx)
    m = strategy.compute_metrics(eq, trades, initial_capital, p.barsPerYear)
    regime_frac = trend_bars / n if n else 0.0
    return m, trades, eq, regime_frac


# ----------------------------------------------------------------------------
# 純趨勢對照（趨勢續抱版，同一份修正資料）
# ----------------------------------------------------------------------------
def backtest_pure_trend(df, cost_model="tw_real", initial_capital=10000.0):
    cfg = tr.TRConfig()
    cfg.target_exposure = 0.95
    cfg.wide_mult = 9.0
    m, _, _ = tr.backtest_trendride(df, cfg, cost_model=cost_model,
                                    initial_capital=initial_capital)
    return m


# ----------------------------------------------------------------------------
# 資料載入（修分割）
# ----------------------------------------------------------------------------
def load_adj(ticker):
    raw = tw_data.load_ohlcv(ticker, period="max", use_cache=True)
    if raw is None or len(raw) < MIN_BARS:
        return None
    if (raw.index[-1] - raw.index[0]).days / 365.25 < MIN_YEARS:
        return None
    adj, _ = tr.adjust_splits(raw)
    return adj


def build_targets(args, universe):
    by_code = {u[0]: u for u in universe}
    if args.symbols:
        return [by_code[s.strip()] for s in args.symbols.split(",") if s.strip() in by_code]
    if args.sample:
        pri = [by_code[c] for c in PRIORITY if c in by_code]
        rest = [u for u in universe if u[0] not in set(PRIORITY)]
        return (pri + rest)[: args.sample]
    return universe


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int)
    g.add_argument("--symbols", type=str)
    g.add_argument("--all", action="store_true")
    ap.add_argument("--cost", default="tw_real")
    args = ap.parse_args()
    if not (args.sample or args.symbols or args.all):
        args.sample = 12

    print("=" * 80)
    print("Regime 自適應策略（趨勢順勢 + 盤整均值回歸）— 全台股")
    print("=" * 80)
    t0 = time.time()
    universe = tw_data.get_universe()
    targets = build_targets(args, universe)
    print(f"Universe {len(universe)}；本次測 {len(targets)} 檔（資料修分割、≥{MIN_YEARS}年）")

    p = AdaptiveParams()
    rows = []
    n_ok = n_skip = 0
    for k, (code, ticker, market, name) in enumerate(targets, 1):
        df = load_adj(ticker)
        if df is None:
            n_skip += 1
            continue
        try:
            ma, ta_, _, rfrac = backtest_adaptive(df, args.cost, p=p)
            mt = backtest_pure_trend(df, args.cost)
        except Exception as e:
            n_skip += 1
            continue
        n_ok += 1
        rows.append(dict(code=code, name=name, market=market, bars=len(df),
                         trend_frac=rfrac,
                         a_net=ma["net_profit_pct"], a_pf=ma["profit_factor"],
                         a_dd=ma["max_dd_pct"], a_tr=ma["n_trades"],
                         a_win=ma["win_rate_pct"], a_rdd=ma["return_over_maxdd"],
                         t_net=mt["net_profit_pct"], t_pf=mt["profit_factor"],
                         t_dd=mt["max_dd_pct"], t_tr=mt["n_trades"],
                         t_rdd=mt["return_over_maxdd"]))
        if n_ok % 50 == 0:
            print(f"  進度 {k}/{len(targets)} 已測 {n_ok}（{time.time()-t0:.0f}s）")
            pd.DataFrame(rows).to_csv(os.path.join(DATA_DIR, "adaptive_per_stock.csv"), index=False)

    df_res = pd.DataFrame(rows)
    df_res.to_csv(os.path.join(DATA_DIR, "adaptive_per_stock.csv"), index=False)
    print(f"完成：測 {n_ok}、跳過 {n_skip}，耗時 {time.time()-t0:.0f}s")
    write_report(df_res, args)


def _prof_ratio(net, pf):
    return float(((net > 0) & (pf > 1)).mean()) * 100.0


def _med_pf(pf):
    return float(pf.replace([np.inf], np.nan).median())


def write_report(df, args):
    if len(df) == 0:
        print("無結果"); return
    n = len(df)
    a_prof = _prof_ratio(df["a_net"], df["a_pf"])
    t_prof = _prof_ratio(df["t_net"], df["t_pf"])

    L = []
    L.append("# Regime 自適應策略 — 全台股回測（資料已修分割）\n")
    L.append(f"- 成本 `{args.cost}`；≥{MIN_YEARS} 年；測試 **{n}** 檔。")
    L.append("- 自適應 = 趨勢段順勢（重倉、慢訊號出）+ 盤整段均值回歸（布林/RSI）。")
    L.append("- 對照「純趨勢版」(趨勢續抱) 在**同一份修正資料**上。\n")

    L.append("## ★ 自適應 vs 純趨勢（同一份修正資料）\n")
    L.append("| 指標 | 純趨勢版 | **自適應版** | 變化 |")
    L.append("|---|---|---|---|")
    L.append(f"| 獲利檔比例(PF>1且淨利>0) | {t_prof:.1f}% | **{a_prof:.1f}%** | {a_prof-t_prof:+.1f}% |")
    L.append(f"| 中位數 PF | {_med_pf(df['t_pf']):.3f} | **{_med_pf(df['a_pf']):.3f}** | {_med_pf(df['a_pf'])-_med_pf(df['t_pf']):+.3f} |")
    L.append(f"| 中位數 Ret/MaxDD | {df['t_rdd'].replace([np.inf],np.nan).median():.3f} | **{df['a_rdd'].replace([np.inf],np.nan).median():.3f}** | {df['a_rdd'].replace([np.inf],np.nan).median()-df['t_rdd'].replace([np.inf],np.nan).median():+.3f} |")
    L.append(f"| 中位數 淨利% | {df['t_net'].median():.2f} | **{df['a_net'].median():.2f}** | {df['a_net'].median()-df['t_net'].median():+.2f} |")
    L.append(f"| 中位數 交易數 | {df['t_tr'].median():.0f} | **{df['a_tr'].median():.0f}** | - |")
    L.append("")

    # 淨利分佈（自適應）
    L.append("## 自適應版 淨利% 分佈\n")
    bins = [(-1e9, -50), (-50, -20), (-20, 0), (0, 20), (20, 50), (50, 100), (100, 1e9)]
    labs = ["< -50%", "-50~-20%", "-20~0%", "0~20%", "20~50%", "50~100%", "> 100%"]
    L.append("| 區間 | 檔數 |")
    L.append("|---|---|")
    for (lo, hi), lab in zip(bins, labs):
        L.append(f"| {lab} | {int(((df['a_net']>lo)&(df['a_net']<=hi)).sum())} |")
    L.append("")

    # 盤整型個股對照（trend_frac 最低的一群 = 最盤整）
    L.append("## 盤整型個股：自適應 vs 純趨勢（證明均值回歸有補到盤整股）\n")
    L.append("取趨勢佔比(trend_frac)最低的 20 檔（最盤整），看均值回歸有沒有救到。\n")
    rangey = df.sort_values("trend_frac").head(20)
    r_a_prof = _prof_ratio(rangey["a_net"], rangey["a_pf"])
    r_t_prof = _prof_ratio(rangey["t_net"], rangey["t_pf"])
    L.append(f"- 這 20 檔盤整股：純趨勢獲利比 {r_t_prof:.0f}% → **自適應 {r_a_prof:.0f}%**；"
             f"純趨勢中位淨利 {rangey['t_net'].median():.1f}% → 自適應 {rangey['a_net'].median():.1f}%。\n")
    L.append("| 代碼 | 名稱 | 趨勢佔比 | 純趨勢淨利% | 自適應淨利% | 自適應PF | 自適應交易 |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in rangey.iterrows():
        apf = "inf" if not np.isfinite(r["a_pf"]) else f"{r['a_pf']:.2f}"
        L.append(f"| {r['code']} | {str(r['name'])[:6]} | {r['trend_frac']*100:.0f}% | "
                 f"{r['t_net']:.1f} | {r['a_net']:.1f} | {apf} | {int(r['a_tr'])} |")
    L.append("")

    # Top20（自適應 Ret/MaxDD）
    L.append("## 自適應版 Top 20（依 Ret/MaxDD）\n")
    top = df.copy()
    top["_rk"] = top["a_rdd"].replace([np.inf], 1e9)
    top = top.sort_values("_rk", ascending=False).head(20)
    L.append("| 代碼 | 名稱 | 淨利% | PF | MaxDD% | 交易 | Ret/DD | 趨勢佔比 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in top.iterrows():
        apf = "inf" if not np.isfinite(r["a_pf"]) else f"{r['a_pf']:.2f}"
        ardd = "inf" if not np.isfinite(r["a_rdd"]) else f"{r['a_rdd']:.2f}"
        L.append(f"| {r['code']} | {str(r['name'])[:6]} | {r['a_net']:.1f} | {apf} | "
                 f"{r['a_dd']:.1f} | {int(r['a_tr'])} | {ardd} | {r['trend_frac']*100:.0f}% |")
    L.append("")

    # 誠實結論
    L.append("## 誠實結論\n")
    delta = a_prof - t_prof
    if a_prof >= 60:
        L.append(f"- 自適應把全台股獲利檔比例拉到 **{a_prof:.0f}%**（純趨勢 {t_prof:.0f}%）→ 顯著改善，均值回歸有效補盤整股。")
    elif delta >= 8:
        L.append(f"- 自適應把獲利檔比例從 {t_prof:.0f}% 提到 **{a_prof:.0f}%**（+{delta:.0f}）→ 有改善但有限。")
    else:
        L.append(f"- 自適應獲利檔比例 {a_prof:.0f}% vs 純趨勢 {t_prof:.0f}%（{delta:+.0f}）→ **改善有限**。")
    if a_prof < 60:
        L.append("- **誠實說：沒有單一策略能適用所有台股**。即使加了均值回歸，過半個股仍難穩定獲利"
                 "（成本拖累 + 個股特性各異）。實務上**必須選股**——把策略套在對的標的（趨勢股用順勢、"
                 "區間震盪股用均值回歸），而非全市場無腦套。")
    L.append("")

    out = os.path.join(DATA_DIR, "adaptive_summary.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("\n" + "=" * 80)
    print(f"獲利檔比例：純趨勢 {t_prof:.1f}% → 自適應 {a_prof:.1f}%（{a_prof-t_prof:+.1f}）")
    print(f"中位PF：純趨勢 {_med_pf(df['t_pf']):.3f} → 自適應 {_med_pf(df['a_pf']):.3f}")
    print(f"中位Ret/MaxDD：自適應 {df['a_rdd'].replace([np.inf],np.nan).median():.3f}")
    print(f"報告已存：{out}")
    print("=" * 80)


if __name__ == "__main__":
    main()
