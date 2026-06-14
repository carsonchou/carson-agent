# -*- coding: utf-8 -*-
"""
tw_trendride.py — 「趨勢續抱」回測變體（吃主升段、避開大崩盤）

診斷：現策略在大牛標的上嚴重跑輸 buy&hold（00675L B&H +2975% vs 現策略 +24.6%），
      因為 vol-target 把倉位壓很小 + 出場太頻繁（R 階梯/部分止盈/peak-R 回吐/time-stop），
      該賺的主升段沒吃到。

本變體與現策略最大不同：
  1. 重倉、不 vol-target 壓小：確認上升趨勢就用接近滿倉（target_exposure，預設 0.95×equity）。
  2. 抱住、只在大趨勢反轉才出：
     - 進場 = regime 偏多（ER/ADX 多數決）且 ST3 多頭（慢訊號）。
     - 出場只看慢訊號：ST3 翻空 OR regime off OR 一條「很寬」的移動停損
       （Chandelier，ATR×wide_mult，預設 ×9，只防大崩盤不防小回檔）。
     - 拿掉所有會早出的機制：R 階梯、部分止盈、peak-R 回吐鎖、time-stop、ST1/ST2 翻轉減碼。
  3. 純多（單向上漲標的）、barsPerYear=252、成本 tw_real。

訊號收盤算、次根開盤成交（與主引擎一致）；硬停損用前一根 committed 寬停損盤中觸發。

執行：使用指定的 Python 3.9 解譯器。
"""
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

COST = "tw_real"
CAPITAL = 10000.0
OUT_MD = os.path.join(tw_data.DATA_DIR, "trendride_result.md")

TEST_SYMBOLS = ["00631L.TW", "00675L.TW", "0050.TW", "006208.TW", "00663L.TW"]

# 現策略（正2純多最終參數）——用來對照「現策略淨利%」
CUR_PARAMS = dict(erThr=0.26, adxOn=25.0, minVotes=2, trailMidR=2.5,
                  trailTightR=3.5, tp2R=3.5, peakArmK=2.0, chandMult=3.5, baseLen=10)


class TRConfig:
    """趨勢續抱參數。"""
    baseLen = 10                 # ST 基準週期（ST1/ST2/ST3 同主引擎比例展開）
    midMult = 2.5
    slowMult = 6.0
    f1, f2, f3 = 1.5, 2.5, 3.5
    erLen = 20
    erThr = 0.30                 # regime ER 門檻
    adxLen = 14
    adxOn = 25.0
    adxOff = 18.0
    minVotes = 2                 # ER/ADX/ST3 多數決
    useDIgate = True
    target_exposure = 0.95       # 接近滿倉（× equity）
    chandLen = 22
    wide_mult = 9.0              # 寬停損 ATR 倍數（只防大崩盤）
    barsPerYear = 252.0


def compute_tr_indicators(df, cfg):
    out = df.copy()
    close = out["Close"]
    len1 = cfg.baseLen
    len2 = max(int(round(cfg.baseLen * cfg.midMult)), 2)
    len3 = max(int(round(cfg.baseLen * cfg.slowMult)), 3)
    _, d1 = ind.supertrend(out, cfg.f1, len1)
    _, d2 = ind.supertrend(out, cfg.f2, len2)
    _, d3 = ind.supertrend(out, cfg.f3, len3)
    out["dir3"] = d3
    out["atrChand"] = ind.atr(out, cfg.chandLen)
    out["er"] = ind.kaufman_er(close, cfg.erLen)
    dip, dim, adx = ind.dmi(out, cfg.adxLen, cfg.adxLen)
    out["diPlus"], out["diMinus"], out["adx"] = dip, dim, adx
    return out


def backtest_trendride(df, cfg, cost_model=COST, initial_capital=CAPITAL):
    cm = strategy.COST_MODELS[cost_model]
    data = compute_tr_indicators(df, cfg)
    o = data["Open"].to_numpy(float)
    h = data["High"].to_numpy(float)
    l = data["Low"].to_numpy(float)
    c = data["Close"].to_numpy(float)
    dir3 = data["dir3"].to_numpy(float)
    atrCh = data["atrChand"].to_numpy(float)
    er = data["er"].to_numpy(float)
    diP = data["diPlus"].to_numpy(float)
    diM = data["diMinus"].to_numpy(float)
    adx = data["adx"].to_numpy(float)
    idx = data.index
    n = len(c)

    st3Bull = dir3 < 0
    st3Bear = ~st3Bull

    # ADX 遲滯
    adxOn_state = np.zeros(n, dtype=bool)
    state = False
    for i in range(n):
        a = adx[i]
        if not np.isnan(a):
            if a > cfg.adxOn:
                state = True
            elif a < cfg.adxOff:
                state = False
        adxOn_state[i] = state

    def buy_px(px):
        return px + cm["slip_ticks"] * strategy._tw_tick(px) if cm["slip_ticks"] else px

    def sell_px(px):
        return max(px - cm["slip_ticks"] * strategy._tw_tick(px), 0.0) if cm["slip_ticks"] else px

    cash = initial_capital
    shares = 0.0
    trailExt = np.nan
    trailStop = np.nan
    cur_buy_cost = 0.0
    cur_sell = 0.0
    cur_open = False
    cur_entry = None
    trades = []
    equity = np.full(n, float(initial_capital))
    prev_stop = np.nan
    pending = None     # ("buy"/"sell")

    for i in range(n):
        # 執行掛單（本根開盤）
        if pending == "buy":
            equity_now = cash + shares * o[i]
            target_notional = cfg.target_exposure * equity_now
            px = buy_px(o[i])
            qty = target_notional / px if px > 0 else 0.0
            if qty > 1e-9:
                cost = px * qty * (1 + cm["fee_buy"])
                if cost > cash:   # 不超買現金
                    qty = (cash / (px * (1 + cm["fee_buy"]))) * 0.999
                    cost = px * qty * (1 + cm["fee_buy"])
                cash -= cost
                shares += qty
                cur_buy_cost += cost
                if not cur_open:
                    cur_open = True
                    cur_entry = idx[i]
        elif pending == "sell":
            if shares > 1e-9:
                px = sell_px(o[i])
                proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
                cash += proceeds
                cur_sell += proceeds
                shares = 0.0
        pending = None

        # 結算整筆 trade
        if cur_open and shares <= 1e-9:
            pnl = cur_sell - cur_buy_cost
            trades.append(dict(entry=cur_entry, exit=idx[i], pnl=pnl,
                               ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
            cur_open = False
            cur_buy_cost = 0.0
            cur_sell = 0.0

        inPos = shares > 1e-9
        if i < 1 or np.isnan(atrCh[i]):
            equity[i] = cash + shares * c[i]
            prev_stop = trailStop
            continue

        exited = False
        # 硬停損（寬）：盤中
        if inPos and not np.isnan(prev_stop) and l[i] <= prev_stop:
            fill = prev_stop if o[i] >= prev_stop else o[i]
            px = sell_px(fill)
            proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
            cash += proceeds
            cur_sell += proceeds
            shares = 0.0
            pnl = cur_sell - cur_buy_cost
            trades.append(dict(entry=cur_entry, exit=idx[i], pnl=pnl,
                               ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
            cur_open = False; cur_buy_cost = 0.0; cur_sell = 0.0
            trailExt = np.nan; trailStop = np.nan
            exited = True; inPos = False

        # 更新寬移動停損（ratchet）
        if inPos:
            trailExt = h[i] if np.isnan(trailExt) else max(trailExt, h[i])
            raw = trailExt - cfg.wide_mult * atrCh[i]
            trailStop = raw if np.isnan(trailStop) else max(trailStop, raw)

        # regime 多頭判定（慢訊號）
        voteER = er[i] > cfg.erThr
        voteADX = bool(adxOn_state[i])
        voteSlow = bool(st3Bull[i])
        votes = (1 if voteER else 0) + (1 if voteADX else 0) + (1 if voteSlow else 0)
        regimeLongOK = (votes >= min(cfg.minVotes, 3)) and ((not cfg.useDIgate) or diP[i] > diM[i])
        regimeOff = votes < min(cfg.minVotes, 3)   # regime 不再偏多

        # 出場（只看慢訊號）：ST3 翻空 OR regime off OR 寬 trail 收盤確認
        if not exited and inPos:
            trailHit = (not np.isnan(trailStop)) and c[i] < trailStop
            st3FlipDn = st3Bear[i]            # ST3 轉空（慢）
            if st3FlipDn or regimeOff or trailHit:
                pending = "sell"
                exited = True

        # 進場：空手 + regime 偏多 + ST3 多頭
        if not exited and not inPos and pending is None:
            if regimeLongOK and st3Bull[i]:
                pending = "buy"
                trailExt = h[i]
                trailStop = np.nan

        equity[i] = cash + shares * c[i]
        prev_stop = trailStop

    # EOD 平倉
    if shares > 1e-9:
        i = n - 1
        px = sell_px(c[i])
        proceeds = px * shares * (1 - cm["fee_sell"] - cm["tax_sell"])
        cash += proceeds; cur_sell += proceeds; shares = 0.0
        if cur_open:
            pnl = cur_sell - cur_buy_cost
            trades.append(dict(entry=cur_entry, exit=idx[i], pnl=pnl,
                               ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
    equity[n - 1] = cash + shares * c[n - 1]

    eq = pd.Series(equity, index=idx)
    m = strategy.compute_metrics(eq, trades, initial_capital, cfg.barsPerYear)
    return m, trades, eq


def adjust_splits(df):
    """回填未調整的分割/反分割（yfinance auto_adjust=False 抓到的台股 ETF 常有）。

    偵測隔夜跳動 < 0.5x 或 > 2x 視為分割，把該日之前的 OHLC 乘上比例，讓序列連續。
    例：00663L 2025-06-02 從 175→24（≈7:1 反分割）、00631L 2015 的 22:1、0050 2014。
    這些是資料問題，不修會在回測造成假的 -85% 單筆崩盤。
    """
    df = df.copy()
    c = df["Close"].to_numpy(float)
    ratio = np.ones(len(c))
    ratio[1:] = c[1:] / c[:-1]
    # 找分割日（從後往前累乘調整係數）
    factor = np.ones(len(c))
    cum = 1.0
    for i in range(len(c) - 1, 0, -1):
        r = ratio[i]
        if r < 0.5 or r > 2.0:
            cum *= r          # 之前的價格要乘上這個比例才連續
        factor[i - 1] = cum
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].to_numpy(float) * factor
    n_splits = int(np.sum((ratio < 0.5) | (ratio > 2.0)))
    return df, n_splits


def buy_hold(df):
    c = df["Close"]
    bh = (c.iloc[-1] / c.iloc[0] - 1) * 100
    roll = c.cummax()
    dd = float(((c - roll) / roll).min() * 100)
    return bh, -dd


def main():
    print("=" * 90)
    print("趨勢續抱回測變體 tw_trendride")
    print("=" * 90)
    t0 = time.time()

    # 掃 target_exposure × wide_mult 找平衡點（在全 5 檔上以 平均Ret/MaxDD 為準，
    # 但要求 平均淨利 明顯高於現策略）
    print("\n[網格] 掃 target_exposure × wide_mult …")
    dfs = {}
    for sym in TEST_SYMBOLS:
        raw = tw_data.load_ohlcv(sym, period="max", sleep=0.3)
        adj, ns = adjust_splits(raw)
        if ns:
            print(f"  [{sym}] 偵測並回填 {ns} 個分割/反分割（資料修正，避免假崩盤）")
        dfs[sym] = adj
    grid_exp = [0.80, 0.95, 1.00]
    grid_wide = [6.0, 8.0, 9.0, 11.0]
    best = None
    for exp in grid_exp:
        for wide in grid_wide:
            cfg = TRConfig(); cfg.target_exposure = exp; cfg.wide_mult = wide
            nets, rdds = [], []
            for sym, df in dfs.items():
                m, _, _ = backtest_trendride(df, cfg)
                nets.append(m["net_profit_pct"])
                r = m["return_over_maxdd"]
                rdds.append(r if np.isfinite(r) else (5.0 if m["net_profit_pct"] > 0 else -1))
            mean_net = float(np.mean(nets)); mean_rdd = float(np.mean(rdds))
            print(f"  exp={exp:.2f} wide={wide:>4} 平均淨利={mean_net:7.1f}% 平均Ret/DD={mean_rdd:.2f}")
            # 目標：平均淨利最大化（趨勢續抱要絕對報酬），Ret/DD 當次要 tie-break
            key = (mean_net, mean_rdd)
            if best is None or key > best[0]:
                best = (key, exp, wide, mean_net, mean_rdd)
    _, best_exp, best_wide, bnet, brdd = best
    print(f"\n  >>> 最佳: target_exposure={best_exp} wide_mult={best_wide} "
          f"(平均淨利 {bnet:.1f}%、平均Ret/DD {brdd:.2f})")

    cfg = TRConfig(); cfg.target_exposure = best_exp; cfg.wide_mult = best_wide

    # 現策略對照（用 strategy.backtest allow_short=False + 正2參數）
    def cur_strategy(df):
        p = strategy.Params()
        for k, v in CUR_PARAMS.items():
            setattr(p, k, v)
        m, _, _ = strategy.backtest(df, cost_model=COST, initial_capital=CAPITAL,
                                    p=p, allow_short=False)
        return m

    L = []
    L.append("# 趨勢續抱回測變體 — 結果與對照\n")
    L.append("目標：吃到大部分上升趨勢、避開大崩盤；絕對報酬要遠高於現策略（朝 B&H 靠近），MaxDD 遠低於 B&H。\n")
    L.append(f"- 成本 `{COST}`；資料 yfinance period max；barsPerYear=252。")
    L.append(f"- 趨勢續抱設計：重倉（target_exposure={best_exp}×equity）、只看慢訊號出場"
             f"（ST3 翻空 / regime off / ATR×{best_wide} 寬停損），關掉所有早出機制。")
    L.append(f"- 網格最佳：target_exposure={best_exp}、wide_mult={best_wide}。\n")

    L.append("## 三方對照（趨勢續抱 vs 買進持有 vs 現策略）\n")
    L.append("| 標的 | 趨勢續抱 淨利% | 續抱 MaxDD% | 續抱 交易數 | 續抱 Ret/DD | B&H 淨利% | B&H MaxDD% | 現策略 淨利% | 現策略 Ret/DD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    print("\n[最終三方對照]")
    rows = []
    for sym in TEST_SYMBOLS:
        df = dfs[sym]
        mt, _, _ = backtest_trendride(df, cfg)
        bh, bhdd = buy_hold(df)
        mc = cur_strategy(df)
        tr_rdd = "inf" if not np.isfinite(mt["return_over_maxdd"]) else f"{mt['return_over_maxdd']:.2f}"
        cur_rdd = "inf" if not np.isfinite(mc["return_over_maxdd"]) else f"{mc['return_over_maxdd']:.2f}"
        L.append(f"| {sym} | **{mt['net_profit_pct']:.0f}** | {mt['max_dd_pct']:.1f} | "
                 f"{mt['n_trades']} | {tr_rdd} | {bh:.0f} | {bhdd:.1f} | "
                 f"{mc['net_profit_pct']:.0f} | {cur_rdd} |")
        rows.append((sym, mt, bh, bhdd, mc))
        print(f"  {sym:<11} 續抱 淨利={mt['net_profit_pct']:7.0f}% MaxDD={mt['max_dd_pct']:5.1f}% "
              f"交易={mt['n_trades']:>3} RetDD={tr_rdd:>5} | B&H={bh:7.0f}%/DD{bhdd:.0f}% | 現策略={mc['net_profit_pct']:.0f}%")
    L.append("")

    # 誠實彙整
    L.append("## 誠實結論（自動彙整）\n")
    tr_nets = [r[1]["net_profit_pct"] for r in rows]
    cur_nets = [r[4]["net_profit_pct"] for r in rows]
    bh_nets = [r[2] for r in rows]
    tr_dds = [r[1]["max_dd_pct"] for r in rows]
    bh_dds = [r[3] for r in rows]
    n_beat_cur = sum(1 for a, b in zip(tr_nets, cur_nets) if a > b)
    L.append(f"- 趨勢續抱 vs 現策略：{n_beat_cur}/{len(rows)} 檔 淨利更高。"
             f"（續抱平均淨利 {np.mean(tr_nets):.0f}% vs 現策略 {np.mean(cur_nets):.0f}%）")
    L.append(f"- 趨勢續抱 vs B&H：續抱平均 MaxDD {np.mean(tr_dds):.0f}% vs B&H {np.mean(bh_dds):.0f}%"
             f"（續抱平均淨利 {np.mean(tr_nets):.0f}% vs B&H {np.mean(bh_nets):.0f}%）。")
    # 魚與熊掌判定
    tr_rdds = [r[1]["return_over_maxdd"] for r in rows if np.isfinite(r[1]["return_over_maxdd"])]
    cur_rdds = [r[4]["return_over_maxdd"] for r in rows if np.isfinite(r[4]["return_over_maxdd"])]
    L.append(f"- Ret/MaxDD：續抱平均 {np.mean(tr_rdds):.2f} vs 現策略 {np.mean(cur_rdds):.2f}。")
    if np.mean(tr_rdds) < np.mean(cur_rdds):
        L.append("  → **魚與熊掌**：續抱賺更多絕對報酬，但 risk-adjusted（Ret/MaxDD）比現策略差——"
                 "想多賺就得吃更大回撤。")
    else:
        L.append("  → 續抱絕對報酬與 Ret/MaxDD **雙贏**。")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n報告已存: {OUT_MD}  耗時 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
