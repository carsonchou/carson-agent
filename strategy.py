# -*- coding: utf-8 -*-
"""
strategy.py — Triple SuperTrend v4 Champion v5 的 Python 移植（LONG-ONLY）

忠實移植 triple_supertrend_v4_FINAL.pine 的「多單那一半」。空單略過（台股融券限制）。

移植範圍（對應 Pine 區塊）：
  區2  三重 SuperTrend ST1/ST2/ST3（baseLen=10, midMult=2.5, slowMult=6; f1/f2/f3=1.5/2.5/3.5）
  區4  VT-Core 波動率估計（ATR% 年化、relVol、volFloor、breathClamp）；barsPerYear=252
  區5  Regime：Kaufman ER(20, erThr=0.36) + ADX(14, adxOn/Off=25/18 遲滯) + ST3 → 多數決(minVotes=2) + DI 閘
  區7  倉位 VT-Core（targetVol=15%、maxGross=1.5、wL1/L2/L3=0.4/0.3/0.3、ER 凸性加碼、vol-brake）
  區8  R-multiple + Chandelier ratchet（chandLen=22, chandMult=3.0=1R）+ R 階梯 + 保本 + TP 階梯 + peak-R 回吐鎖
  區9  全出場：trail 觸停 / time-stop（45 根、R<0.5）；雙ST反轉全出場預設 false
  區10 部分止盈(tp1R1.5/10%, tp2R4.5/10%) + ST 翻轉部分減碼 + regime-fade + cut-to-flat + 硬停損
  區11 進場/加碼：L1 首倉(ST1 翻轉 + regime)、L2/L3 winners-add-only 浮盈加碼

執行模型（對齊 Pine process_orders_on_close=true）：
  - 訊號於 bar i 收盤計算，成交價以 bar i+1「開盤」近似（Pine 收盤掛單→次根成交慣例）。
  - 硬停損（broker stop）：用前一根 committed 的 trailStop，本根 low<=stop 即盤中以停損價成交。

成本模型（可切換 --cost）：
  pine    : 手續費 0.05%/邊 + 滑價 2 tick 近似（買 +2tick、賣 -2tick）
  tw_real : 手續費 0.1425% 買 + 0.1425% 賣 + 賣出證交稅 0.3%（round-trip ≈ 0.585%）

每檔獨立、初始資金 10000。一個完整「建倉→全平」視為一筆 trade（PF/勝率/交易數依此）。
"""
import numpy as np
import pandas as pd

import indicators as ind


class Params:
    # 趨勢 SuperTrend
    # ★ 台股優化參數（2026-06，train/test OOS 驗證；平均PF 0.996→1.232）：
    #   baseLen 10→7, chandMult 3.0→3.5, erThr 0.36→0.30, adxOn 25→28, minVotes 2→3
    baseLen = 7           # 台股優化（原 crypto 10）
    midMult = 2.5
    slowMult = 6.0
    f1, f2, f3 = 1.5, 2.5, 3.5
    # Regime
    useRegime = True
    erLen = 20
    erThr = 0.30          # 台股優化（原 crypto 0.36）
    adxLen = 14
    adxOn = 28.0          # 台股優化（原 crypto 25）
    adxOff = 18.0
    minVotes = 3          # 台股優化（原 crypto 2，三票全到才進）
    useDIgate = True
    # 倉位 VT-Core
    targetVol = 0.15
    volLen = 20
    barsPerYear = 252.0
    wL1, wL2, wL3 = 0.40, 0.30, 0.30
    useConvAdd = True
    maxGross = 1.5
    useVolBrake = True
    brakeLen = 100
    brakeK = 1.8
    # 出場
    chandLen = 22
    chandMult = 3.5       # 台股優化（原 crypto 3.0，停損放寬、1R 更大）
    useRStep = True
    trailMidR = 2.8
    trailTightR = 2.5
    useBE = True
    kBE = 1.0
    multBE = 0.6
    usePartialTP = True
    tp1R = 1.5
    tp1Pct = 10.0
    tp2R = 4.5
    tp2Pct = 10.0
    useBEonTP1 = True
    useTPstairBE = True
    usePeakRatchet = True
    useBreathGiveback = True
    peakArmK = 2.5
    usePartialST = True
    useRegimeFade = True
    fadeK = 0.6
    fadeCoolBars = 5
    twoSTRevExitFull = False
    useTimeStop = True
    timeStopBars = 45
    timeStopR = 0.5
    useHardStop = True
    cooldownBars = 4


COST_MODELS = {
    "pine": dict(fee_buy=0.0005, fee_sell=0.0005, tax_sell=0.0, slip_ticks=2),
    "tw_real": dict(fee_buy=0.001425, fee_sell=0.001425, tax_sell=0.003, slip_ticks=0),
}


def _tw_tick(price: float) -> float:
    if price < 10:
        return 0.01
    elif price < 50:
        return 0.05
    elif price < 100:
        return 0.1
    elif price < 500:
        return 0.5
    elif price < 1000:
        return 1.0
    return 5.0


def compute_indicators(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"]

    len1 = p.baseLen
    len2 = max(int(round(p.baseLen * p.midMult)), 2)
    len3 = max(int(round(p.baseLen * p.slowMult)), 3)

    _, dir1 = ind.supertrend(out, p.f1, len1)
    _, dir2 = ind.supertrend(out, p.f2, len2)
    _, dir3 = ind.supertrend(out, p.f3, len3)
    out["dir1"], out["dir2"], out["dir3"] = dir1, dir2, dir3

    out["atrAdx"] = ind.atr(out, p.adxLen)
    out["atrChand"] = ind.atr(out, p.chandLen)
    out["atrPct"] = out["atrAdx"] / close

    vol_ann_atr = out["atrPct"] * np.sqrt(p.barsPerYear)
    inst_vol = vol_ann_atr.copy()
    vol_floor = ind.rolling_percentile(inst_vol, p.brakeLen, 5)
    vol_floor = vol_floor.where(~vol_floor.isna(), 0.02).clip(lower=0.001)
    inst_vol = inst_vol.fillna(vol_floor)
    inst_vol = pd.concat([inst_vol, vol_floor], axis=1).max(axis=1)
    vol_median = ind.rolling_median(inst_vol, p.brakeLen)
    vol_median = vol_median.where(~vol_median.isna(), inst_vol)
    vol_median = pd.concat([vol_median, vol_floor], axis=1).max(axis=1)
    out["instVolAnn"] = inst_vol
    out["relVol"] = inst_vol / vol_median

    out["er"] = ind.kaufman_er(close, p.erLen)

    di_plus, di_minus, adx = ind.dmi(out, p.adxLen, p.adxLen)
    out["diPlus"], out["diMinus"], out["adx"] = di_plus, di_minus, adx
    return out


def _tranche_top(on3, on2, on1, n3, n2, n1):
    return n3 if on3 else (n2 if on2 else (n1 if on1 else 0.0))


def _apply_drain(want, l1On, l2On, l3On, n1, n2, n3):
    """top-first（L3→L2→L1）扣 want 股數，回傳 (l1On,l2On,l3On,n1,n2,n3, drained)。"""
    done = 0.0
    r3, r2, r1 = n3, n2, n1
    if r3 > 1e-9 and want - done > 1e-9:
        take = min(want - done, r3); r3 -= take; done += take
    if r2 > 1e-9 and want - done > 1e-9:
        take = min(want - done, r2); r2 -= take; done += take
    if r1 > 1e-9 and want - done > 1e-9:
        take = min(want - done, r1); r1 -= take; done += take
    return (r1 > 1e-9, r2 > 1e-9, r3 > 1e-9, r1, r2, r3, done)


def backtest_long_only(df: pd.DataFrame, cost_model: str = "pine",
                       initial_capital: float = 10000.0, p: Params = None):
    """回傳 (metrics dict, trades list, equity Series)。"""
    if p is None:
        p = Params()
    cm = COST_MODELS[cost_model]
    data = compute_indicators(df, p)

    o = data["Open"].to_numpy(float)
    h = data["High"].to_numpy(float)
    l = data["Low"].to_numpy(float)
    c = data["Close"].to_numpy(float)
    dir1 = data["dir1"].to_numpy(float)
    dir2 = data["dir2"].to_numpy(float)
    dir3 = data["dir3"].to_numpy(float)
    atrChand = data["atrChand"].to_numpy(float)
    instVol = data["instVolAnn"].to_numpy(float)
    relVol = data["relVol"].to_numpy(float)
    er = data["er"].to_numpy(float)
    diPlus = data["diPlus"].to_numpy(float)
    diMinus = data["diMinus"].to_numpy(float)
    adx = data["adx"].to_numpy(float)
    idx = data.index
    n = len(c)

    st1Bull = dir1 < 0
    st2Bull = dir2 < 0
    st3Bull = dir3 < 0
    st1Bear = ~st1Bull
    st2Bear = ~st2Bull

    def flip_up(bull, i):
        return bool(bull[i]) and (i == 0 or not bull[i - 1])

    def flip_dn(bear, i):
        return bool(bear[i]) and (i == 0 or not bear[i - 1])

    # ADX 遲滯
    adxOn_state = np.zeros(n, dtype=bool)
    state = False
    for i in range(n):
        a = adx[i]
        if not np.isnan(a):
            if a > p.adxOn:
                state = True
            elif a < p.adxOff:
                state = False
        adxOn_state[i] = state

    # 倉位狀態
    l1On = l2On = l3On = False
    notL1 = notL2 = notL3 = 0.0
    entryPx = np.nan
    entryRisk = np.nan
    entryBar = -1
    trailExt = np.nan
    trailStop = np.nan
    tp1Done = tp2Done = False
    peakR = 0.0
    peakBar = 0
    fadeArmed = True
    lastFadeBar = -100000
    cooldownUntil = 0

    cash = initial_capital
    shares = 0.0
    avg_cost = 0.0  # 每股平均成本（含買入手續費攤入）

    trades = []        # 完整 round-trip 交易
    equity_curve = np.full(n, float(initial_capital))
    prev_trailStop = np.nan
    pending = []       # 待下一根開盤成交：("buy",qty) / ("sell",qty,reason) / ("close",reason)

    # 當前 position 累計（用於整筆 trade PnL）
    cur_buy_cost = 0.0    # 累計買入支出（含費）
    cur_sell_proceeds = 0.0  # 累計賣出收入（扣費稅）
    cur_open = False
    cur_entry_date = None

    sizeBase = initial_capital
    totW = p.wL1 + p.wL2 + p.wL3

    def qty_for(w, close_px, inst_vol_i):
        vt = p.targetVol / inst_vol_i if inst_vol_i > 0 else 1.0
        notion = vt * sizeBase * w
        n_cap = sizeBase * p.maxGross * (w / totW) if totW > 0 else sizeBase * p.maxGross
        notion = min(notion, n_cap)
        q = notion / close_px if close_px > 0 else 0.0
        return max(q, 0.0)

    def buy_px(px):
        if cm["slip_ticks"]:
            px = px + cm["slip_ticks"] * _tw_tick(px)
        return px

    def sell_px(px):
        if cm["slip_ticks"]:
            px = px - cm["slip_ticks"] * _tw_tick(px)
        return max(px, 0.0)

    def reset_position(cur_i):
        nonlocal l1On, l2On, l3On, notL1, notL2, notL3
        nonlocal entryPx, entryRisk, entryBar, trailExt, trailStop
        nonlocal tp1Done, tp2Done, peakR, peakBar, fadeArmed
        l1On = l2On = l3On = False
        notL1 = notL2 = notL3 = 0.0
        entryPx = np.nan
        entryRisk = np.nan
        entryBar = -1
        trailExt = np.nan
        trailStop = np.nan
        tp1Done = tp2Done = False
        peakR = 0.0
        peakBar = cur_i
        fadeArmed = True

    for i in range(n):
        # ---- (0) 執行上一根掛單（本根開盤成交）----
        if pending:
            for act in pending:
                if act[0] == "buy":
                    px = buy_px(o[i]); qty = act[1]
                    gross = px * qty
                    cost = gross * (1 + cm["fee_buy"])
                    cash -= cost
                    new_sh = shares + qty
                    avg_cost = (avg_cost * shares + cost) / new_sh if new_sh > 0 else 0.0
                    shares = new_sh
                    cur_buy_cost += cost
                    if not cur_open:
                        cur_open = True
                        cur_entry_date = idx[i]
                else:  # sell / close
                    if act[0] == "sell":
                        qty = min(act[1], shares); reason = act[2]
                    else:
                        qty = shares; reason = act[1]
                    if qty > 1e-9:
                        px = sell_px(o[i])
                        gross = px * qty
                        proceeds = gross * (1 - cm["fee_sell"] - cm["tax_sell"])
                        cash += proceeds
                        shares -= qty
                        cur_sell_proceeds += proceeds
                        if shares <= 1e-9:
                            shares = 0.0
                            avg_cost = 0.0
            pending = []

        # position 結束結算（全平且無待買入）
        if cur_open and shares <= 1e-9 and not any(a[0] == "buy" for a in pending):
            pnl = cur_sell_proceeds - cur_buy_cost
            trades.append(dict(entry=cur_entry_date, exit=idx[i],
                               buy_cost=cur_buy_cost, sell_proceeds=cur_sell_proceeds,
                               pnl=pnl, ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
            cur_open = False
            cur_buy_cost = 0.0
            cur_sell_proceeds = 0.0

        inPos = shares > 1e-9

        if i < 1 or np.isnan(atrChand[i]) or np.isnan(instVol[i]):
            equity_curve[i] = cash + shares * c[i]
            prev_trailStop = trailStop
            continue

        exitedThisBar = False

        # ---- (1) 硬停損（本根盤中）----
        if p.useHardStop and inPos and not np.isnan(prev_trailStop):
            if l[i] <= prev_trailStop:
                fill = prev_trailStop if o[i] >= prev_trailStop else o[i]
                # 立即成交（不掛單）
                px = sell_px(fill); qty = shares
                proceeds = px * qty * (1 - cm["fee_sell"] - cm["tax_sell"])
                cash += proceeds
                cur_sell_proceeds += proceeds
                shares = 0.0
                avg_cost = 0.0
                # 結算 trade
                pnl = cur_sell_proceeds - cur_buy_cost
                trades.append(dict(entry=cur_entry_date, exit=idx[i],
                                   buy_cost=cur_buy_cost, sell_proceeds=cur_sell_proceeds,
                                   pnl=pnl, ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
                cur_open = False
                cur_buy_cost = 0.0
                cur_sell_proceeds = 0.0
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False

        # ---- R 與 trailStop（收盤）----
        if inPos:
            rDenom = entryRisk if not np.isnan(entryRisk) else p.chandMult * atrChand[i]
            rBasePx = entryPx if not np.isnan(entryPx) else avg_cost
            R = (c[i] - rBasePx) / rDenom if rDenom > 0 else 0.0
            if R > peakR:
                peakR = R; peakBar = i
        else:
            R = 0.0
            rDenom = p.chandMult * atrChand[i]
            rBasePx = c[i]

        multStep = (p.chandMult if not p.useRStep else
                    (p.chandMult if R < 1 else (p.trailMidR if R < 2 else p.trailTightR)))
        beActive = (p.useBE and R >= p.kBE) or (p.useBEonTP1 and tp1Done)
        breathClamp = min(max(relVol[i], 1.0), p.brakeK) if not np.isnan(relVol[i]) else 1.0
        effGiveback = p.multBE * (breathClamp if p.useBreathGiveback else 1.0)
        peakFloorOn = p.usePeakRatchet and inPos and peakR > effGiveback * p.peakArmK
        stairRungs = (1 if tp1Done else 0) + (1 if tp2Done else 0)
        tpStairOn = p.useTPstairBE and inPos and stairRungs > 0
        tpStairFloorL = rBasePx + stairRungs * p.multBE * rDenom

        if inPos:
            trailExt = h[i] if np.isnan(trailExt) else max(trailExt, h[i])
            rawStop = trailExt - multStep * atrChand[i]
            trailStop = rawStop if np.isnan(trailStop) else max(trailStop, rawStop)
            if beActive:
                trailStop = max(trailStop, rBasePx + p.multBE * rDenom)
            if tpStairOn:
                trailStop = max(trailStop, tpStairFloorL)
            if peakFloorOn:
                trailStop = max(trailStop, rBasePx + (peakR - effGiveback) * rDenom)

        # ---- (2) 全出場 ----
        if not exitedThisBar and inPos:
            trailHit = (not np.isnan(trailStop)) and c[i] < trailStop
            twoSTRev = bool(st1Bear[i] and st2Bear[i])
            stage = (1 if l1On else 0) + (1 if l2On else 0) + (1 if l3On else 0)
            tsAge = (i - entryBar) if entryBar >= 0 else 0
            timeStop = (p.useTimeStop and entryBar >= 0 and tsAge >= p.timeStopBars
                        and R < p.timeStopR and stage < 3)
            reason = None
            if trailHit:
                reason = "TrailL"
            elif p.twoSTRevExitFull and twoSTRev:
                reason = "2STrevL"
            elif timeStop:
                reason = "TimeStop"
            if reason:
                pending.append(("close", reason))
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False

        # ---- (3) 部分止盈 ----
        if not exitedThisBar and inPos and p.usePartialTP:
            posAbs = shares
            if R >= p.tp1R and not tp1Done:
                q = posAbs * p.tp1Pct / 100.0
                if q > 1e-9:
                    pending.append(("sell", q, "TP1"))
                    l1On, l2On, l3On, notL1, notL2, notL3, _ = _apply_drain(
                        q, l1On, l2On, l3On, notL1, notL2, notL3)
                tp1Done = True
            if R >= p.tp2R and not tp2Done:
                q = posAbs * p.tp2Pct / 100.0
                if q > 1e-9:
                    pending.append(("sell", q, "TP2"))
                    l1On, l2On, l3On, notL1, notL2, notL3, _ = _apply_drain(
                        q, l1On, l2On, l3On, notL1, notL2, notL3)
                tp2Done = True

        # ---- (4) ST 翻轉部分減碼 ----
        if not exitedThisBar and inPos and p.usePartialST:
            cutL1 = flip_dn(st1Bear, i) and (l1On or l2On or l3On)
            cutL2 = (not cutL1) and flip_dn(st2Bear, i) and (l2On or l3On)
            if cutL1 or cutL2:
                tr = _tranche_top(l3On, l2On, l1On, notL3, notL2, notL1)
                if tr > 1e-9:
                    pending.append(("sell", min(tr, shares), "cutST"))
                    l1On, l2On, l3On, notL1, notL2, notL3, _ = _apply_drain(
                        tr, l1On, l2On, l3On, notL1, notL2, notL3)

        # ---- (5) regime-fade ----
        if (not inPos) or er[i] >= p.erThr:
            fadeArmed = True
        if not exitedThisBar and inPos and p.useRegimeFade and p.erThr > 0:
            fadeTrig = er[i] < p.erThr * p.fadeK
            fadeReady = fadeArmed and (i - lastFadeBar) >= p.fadeCoolBars
            stage = (1 if l1On else 0) + (1 if l2On else 0) + (1 if l3On else 0)
            if fadeTrig and stage >= 2 and fadeReady:
                tr = _tranche_top(l3On, l2On, l1On, notL3, notL2, notL1)
                if tr > 1e-9:
                    pending.append(("sell", min(tr, shares), "fade"))
                    l1On, l2On, l3On, notL1, notL2, notL3, _ = _apply_drain(
                        tr, l1On, l2On, l3On, notL1, notL2, notL3)
                fadeArmed = False
                lastFadeBar = i

        # ---- (6) cut-to-flat ----
        if not exitedThisBar and inPos:
            stage_now = (1 if l1On else 0) + (1 if l2On else 0) + (1 if l3On else 0)
            if stage_now == 0:
                pending.append(("close", "CutToFlat"))
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False

        # ---- (7) 進場 / 加碼 ----
        canEnter = i >= cooldownUntil and not exitedThisBar
        voteER = er[i] > p.erThr
        voteADX = bool(adxOn_state[i])
        voteSlow = bool(st3Bull[i])
        votes = (1 if voteER else 0) + (1 if voteADX else 0) + (1 if voteSlow else 0)
        voteLongPass = votes >= min(p.minVotes, 3)
        dirLong = diPlus[i] > diMinus[i]
        diLongOK = (not p.useDIgate) or dirLong
        regimeLongOK = (not p.useRegime) or (voteLongPass and diLongOK)

        curLongStage = (1 if l1On else 0) + (1 if l2On else 0) + (1 if l3On else 0)
        l1Cond = (curLongStage == 0 and not inPos and flip_up(st1Bull, i)
                  and regimeLongOK and canEnter)
        volBrakeOn = p.useVolBrake and (not np.isnan(relVol[i])) and relVol[i] > p.brakeK
        addOK = (not volBrakeOn) and R > 0
        l2Cond = (curLongStage == 1 and l1On and inPos and flip_up(st2Bull, i)
                  and bool(st1Bull[i]) and addOK)
        l3Cond = (curLongStage == 2 and l1On and l2On and inPos and flip_up(st3Bull, i)
                  and bool(st1Bull[i]) and bool(st2Bull[i]) and addOK)
        convMult = (min(max(er[i] / p.erThr, 0.5), 1.0)
                    if (p.useConvAdd and p.erThr > 0) else 1.0)

        if l1Cond:
            q = qty_for(p.wL1, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("buy", q))
                entryRisk = p.chandMult * atrChand[i]
                entryPx = c[i]
                trailExt = h[i]
                trailStop = np.nan
                entryBar = i
                peakR = 0.0
                peakBar = i
                fadeArmed = True
                l1On = True
                notL1 = q
        elif l2Cond:
            q = qty_for(p.wL2 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("buy", q)); l2On = True; notL2 = q
        elif l3Cond:
            q = qty_for(p.wL3 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("buy", q)); l3On = True; notL3 = q

        equity_curve[i] = cash + shares * c[i]
        prev_trailStop = trailStop

    # EOD 平倉
    if shares > 1e-9:
        i = n - 1
        px = sell_px(c[i]); qty = shares
        proceeds = px * qty * (1 - cm["fee_sell"] - cm["tax_sell"])
        cash += proceeds
        cur_sell_proceeds += proceeds
        shares = 0.0
        if cur_open:
            pnl = cur_sell_proceeds - cur_buy_cost
            trades.append(dict(entry=cur_entry_date, exit=idx[i],
                               buy_cost=cur_buy_cost, sell_proceeds=cur_sell_proceeds,
                               pnl=pnl, ret=pnl / cur_buy_cost if cur_buy_cost > 0 else 0.0))
            cur_open = False
    equity_curve[n - 1] = cash + shares * c[n - 1]

    equity = pd.Series(equity_curve, index=idx)
    metrics = compute_metrics(equity, trades, initial_capital, p.barsPerYear)
    return metrics, trades, equity


def compute_metrics(equity: pd.Series, trades: list, initial_capital: float,
                    bars_per_year: float) -> dict:
    final_eq = float(equity.iloc[-1])
    net_profit_pct = (final_eq / initial_capital - 1.0) * 100.0

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    n_trades = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_profit = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = float("inf")
    else:
        pf = 0.0
    win_rate = (len(wins) / n_trades * 100.0) if n_trades else 0.0

    # 最大回撤（基於 equity 曲線）
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    max_dd_pct = float(-dd.min() * 100.0) if len(dd) else 0.0

    ret_over_dd = (net_profit_pct / max_dd_pct) if max_dd_pct > 1e-9 else (
        float("inf") if net_profit_pct > 0 else 0.0)

    # 年化 Sharpe（基於日 equity 報酬）
    eq_ret = equity.pct_change().dropna()
    if len(eq_ret) > 1 and eq_ret.std(ddof=0) > 1e-12:
        sharpe = (eq_ret.mean() / eq_ret.std(ddof=0)) * np.sqrt(bars_per_year)
    else:
        sharpe = 0.0

    return dict(
        net_profit_pct=round(net_profit_pct, 2),
        profit_factor=(round(pf, 3) if np.isfinite(pf) else float("inf")),
        max_dd_pct=round(max_dd_pct, 2),
        n_trades=int(n_trades),
        win_rate_pct=round(win_rate, 2),
        return_over_maxdd=(round(ret_over_dd, 3) if np.isfinite(ret_over_dd) else float("inf")),
        sharpe=round(float(sharpe), 3),
        final_equity=round(final_eq, 2),
    )


def backtest(df: pd.DataFrame, cost_model: str = "pine",
             initial_capital: float = 10000.0, p: Params = None,
             allow_short: bool = True):
    """多空雙向回測（Triple SuperTrend v5 完整鏡像）。

    - allow_short=False → 只做多，結果與 backtest_long_only() 完全一致（回歸相容）。
    - allow_short=True  → 多空對稱：空單那側忠實鏡像 Pine FINAL（regime 偏空 + ST 翻空進場、
      S2/S3 浮盈加碼、Chandelier 上軌 ratchet trail、R 階梯、保本、部分止盈、peak-R 回吐鎖、
      ST 翻多部分減碼、regime-fade、time-stop、硬停損、cut-to-flat、cooldown）。

    倉位為單一方向（contiguous-stack；任一時刻只持多或只持空，與 Pine position_size 單符號一致）。

    成本模型（含放空）：賣出（無論開空或平多）皆計賣方費+稅；買入（無論開多或平空）計買方費。
    放空對台股不完全寫實，但邏輯先做出；標的若為台指期/正2/反1 可實戰。

    回傳 (metrics dict, trades list, equity Series)。trades 內含 side 欄位。
    """
    if p is None:
        p = Params()
    cm = COST_MODELS[cost_model]
    data = compute_indicators(df, p)

    o = data["Open"].to_numpy(float)
    h = data["High"].to_numpy(float)
    l = data["Low"].to_numpy(float)
    c = data["Close"].to_numpy(float)
    dir1 = data["dir1"].to_numpy(float)
    dir2 = data["dir2"].to_numpy(float)
    dir3 = data["dir3"].to_numpy(float)
    atrChand = data["atrChand"].to_numpy(float)
    instVol = data["instVolAnn"].to_numpy(float)
    relVol = data["relVol"].to_numpy(float)
    er = data["er"].to_numpy(float)
    diPlus = data["diPlus"].to_numpy(float)
    diMinus = data["diMinus"].to_numpy(float)
    adx = data["adx"].to_numpy(float)
    idx = data.index
    n = len(c)

    st1Bull = dir1 < 0
    st2Bull = dir2 < 0
    st3Bull = dir3 < 0
    st1Bear = ~st1Bull
    st2Bear = ~st2Bull
    st3Bear = ~st3Bull

    def flip_up(bull, i):
        return bool(bull[i]) and (i == 0 or not bull[i - 1])

    def flip_dn(bear, i):
        return bool(bear[i]) and (i == 0 or not bear[i - 1])

    # ADX 遲滯
    adxOn_state = np.zeros(n, dtype=bool)
    state = False
    for i in range(n):
        a = adx[i]
        if not np.isnan(a):
            if a > p.adxOn:
                state = True
            elif a < p.adxOff:
                state = False
        adxOn_state[i] = state

    # 倉位狀態（contiguous-stack；t1/t2/t3 各 tranche，方向由 side 決定）
    side = 0                       # +1 long, -1 short, 0 flat
    t1On = t2On = t3On = False
    not1 = not2 = not3 = 0.0
    entryPx = np.nan
    entryRisk = np.nan
    entryBar = -1
    trailExt = np.nan              # 多: highest high；空: lowest low
    trailStop = np.nan
    tp1Done = tp2Done = False
    peakR = 0.0
    peakBar = 0
    fadeArmed = True
    lastFadeBar = -100000
    cooldownUntil = 0

    cash = initial_capital
    shares = 0.0                   # 絕對股數（>0）
    avg_cost = 0.0                 # 多: 每股買入成本；空: 每股賣出收入（建倉均價）
    pos_sign = 0                   # 實際持股方向（+1/-1），只在 shares 歸零時清 0；
                                   # 與狀態機 side 不同——side 可能在掛單平倉時提前 reset，
                                   # MTM 必須用實際持股方向，否則持倉那根會少算市值。

    trades = []
    equity_curve = np.full(n, float(initial_capital))
    prev_trailStop = np.nan
    pending = []                   # ("open",qty) / ("reduce",qty,reason) / ("close",reason)

    # 當前 position 累計（用於整筆 trade PnL）
    cur_open_cash = 0.0            # 建倉現金流（多: 付出買入成本；空: 收到賣出收入）
    cur_close_cash = 0.0          # 平倉現金流（多: 收到賣出收入；空: 付出買回成本）
    cur_open = False
    cur_entry_date = None
    cur_side = 0

    sizeBase = initial_capital
    totW = p.wL1 + p.wL2 + p.wL3

    def qty_for(w, close_px, inst_vol_i):
        vt = p.targetVol / inst_vol_i if inst_vol_i > 0 else 1.0
        notion = vt * sizeBase * w
        n_cap = sizeBase * p.maxGross * (w / totW) if totW > 0 else sizeBase * p.maxGross
        notion = min(notion, n_cap)
        q = notion / close_px if close_px > 0 else 0.0
        return max(q, 0.0)

    def buy_px(px):
        if cm["slip_ticks"]:
            px = px + cm["slip_ticks"] * _tw_tick(px)
        return px

    def sell_px(px):
        if cm["slip_ticks"]:
            px = px - cm["slip_ticks"] * _tw_tick(px)
        return max(px, 0.0)

    def reset_position(cur_i):
        nonlocal side, t1On, t2On, t3On, not1, not2, not3
        nonlocal entryPx, entryRisk, entryBar, trailExt, trailStop
        nonlocal tp1Done, tp2Done, peakR, peakBar, fadeArmed
        side = 0
        t1On = t2On = t3On = False
        not1 = not2 = not3 = 0.0
        entryPx = np.nan
        entryRisk = np.nan
        entryBar = -1
        trailExt = np.nan
        trailStop = np.nan
        tp1Done = tp2Done = False
        peakR = 0.0
        peakBar = cur_i
        fadeArmed = True

    def finalize_trade(exit_i):
        """結算整筆 round-trip。多: pnl = 平倉收入 - 建倉成本；
        空: pnl = 開倉賣出收入 - 平倉買回成本。"""
        nonlocal cur_open, cur_open_cash, cur_close_cash, cur_side
        if cur_side > 0:
            pnl = cur_close_cash - cur_open_cash
            basis = cur_open_cash
        else:
            pnl = cur_open_cash - cur_close_cash
            basis = cur_open_cash
        trades.append(dict(entry=cur_entry_date, exit=idx[exit_i],
                           side=("long" if cur_side > 0 else "short"),
                           open_cash=cur_open_cash, close_cash=cur_close_cash,
                           pnl=pnl, ret=(pnl / basis if basis > 0 else 0.0)))
        cur_open = False
        cur_open_cash = 0.0
        cur_close_cash = 0.0
        cur_side = 0

    def exec_open(exec_px, qty, dir_sign, fill_i):
        """開倉成交（多=買入；空=賣出開倉）。"""
        nonlocal cash, shares, avg_cost, cur_open, cur_entry_date, cur_side, cur_open_cash, pos_sign
        pos_sign = dir_sign
        if dir_sign > 0:
            px = buy_px(exec_px)
            cost = px * qty * (1 + cm["fee_buy"])
            cash -= cost
            new_sh = shares + qty
            avg_cost = (avg_cost * shares + cost) / new_sh if new_sh > 0 else 0.0
            shares = new_sh
            cur_open_cash += cost
        else:
            px = sell_px(exec_px)
            proceeds = px * qty * (1 - cm["fee_sell"] - cm["tax_sell"])
            cash += proceeds
            new_sh = shares + qty
            avg_cost = (avg_cost * shares + proceeds) / new_sh if new_sh > 0 else 0.0
            shares = new_sh
            cur_open_cash += proceeds
        if not cur_open:
            cur_open = True
            cur_entry_date = idx[fill_i]
            cur_side = dir_sign

    def exec_reduce(exec_px, qty, dir_sign):
        """部分/全部平倉成交（平多=賣出；平空=買回）。回傳實際成交股數。"""
        nonlocal cash, shares, avg_cost, cur_close_cash, pos_sign
        qty = min(qty, shares)
        if qty <= 1e-9:
            return 0.0
        if dir_sign > 0:   # 平多 → 賣出
            px = sell_px(exec_px)
            proceeds = px * qty * (1 - cm["fee_sell"] - cm["tax_sell"])
            cash += proceeds
            cur_close_cash += proceeds
        else:              # 平空 → 買回
            px = buy_px(exec_px)
            cost = px * qty * (1 + cm["fee_buy"])
            cash -= cost
            cur_close_cash += cost
        shares -= qty
        if shares <= 1e-9:
            shares = 0.0
            avg_cost = 0.0
            pos_sign = 0
        return qty

    def mtm(i):
        """權益 = 現金 + 部位市值。空單市值貢獻 = 開倉收入 - 回補成本估計，
        以 cash + side*shares*close 表達淨值（空單 cash 已含賣出收入）。"""
        return cash + pos_sign * shares * c[i]

    for i in range(n):
        # ---- (0) 執行上一根掛單（本根開盤成交）----
        if pending:
            for act in pending:
                if act[0] == "open":
                    exec_open(o[i], act[1], act[2], i)
                elif act[0] == "reduce":
                    exec_reduce(o[i], act[1], act[3])
                elif act[0] == "close":
                    exec_reduce(o[i], shares, act[1])
            pending = []

        # position 結束結算（全平且無待開倉）
        if cur_open and shares <= 1e-9 and not any(a[0] == "open" for a in pending):
            finalize_trade(i)

        inPos = shares > 1e-9

        if i < 1 or np.isnan(atrChand[i]) or np.isnan(instVol[i]):
            equity_curve[i] = cash + pos_sign * shares * c[i]
            prev_trailStop = trailStop
            continue

        exitedThisBar = False
        isLong = side > 0
        isShort = side < 0

        # ---- (1) 硬停損（本根盤中）----
        if p.useHardStop and inPos and not np.isnan(prev_trailStop):
            hit = (l[i] <= prev_trailStop) if isLong else (h[i] >= prev_trailStop)
            if hit:
                if isLong:
                    fill = prev_trailStop if o[i] >= prev_trailStop else o[i]
                    exec_reduce(fill, shares, +1)
                else:
                    fill = prev_trailStop if o[i] <= prev_trailStop else o[i]
                    exec_reduce(fill, shares, -1)
                finalize_trade(i)
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False
                isLong = isShort = False

        # ---- R 與 trailStop（收盤）----
        if inPos:
            rDenom = entryRisk if not np.isnan(entryRisk) else p.chandMult * atrChand[i]
            rBasePx = entryPx if not np.isnan(entryPx) else avg_cost
            if isLong:
                R = (c[i] - rBasePx) / rDenom if rDenom > 0 else 0.0
            else:
                R = (rBasePx - c[i]) / rDenom if rDenom > 0 else 0.0
            if R > peakR:
                peakR = R; peakBar = i
        else:
            R = 0.0
            rDenom = p.chandMult * atrChand[i]
            rBasePx = c[i]

        multStep = (p.chandMult if not p.useRStep else
                    (p.chandMult if R < 1 else (p.trailMidR if R < 2 else p.trailTightR)))
        beActive = (p.useBE and R >= p.kBE) or (p.useBEonTP1 and tp1Done)
        breathClamp = min(max(relVol[i], 1.0), p.brakeK) if not np.isnan(relVol[i]) else 1.0
        effGiveback = p.multBE * (breathClamp if p.useBreathGiveback else 1.0)
        peakFloorOn = p.usePeakRatchet and inPos and peakR > effGiveback * p.peakArmK
        stairRungs = (1 if tp1Done else 0) + (1 if tp2Done else 0)
        tpStairOn = p.useTPstairBE and inPos and stairRungs > 0

        if isLong:
            trailExt = h[i] if np.isnan(trailExt) else max(trailExt, h[i])
            rawStop = trailExt - multStep * atrChand[i]
            trailStop = rawStop if np.isnan(trailStop) else max(trailStop, rawStop)
            if beActive:
                trailStop = max(trailStop, rBasePx + p.multBE * rDenom)
            if tpStairOn:
                trailStop = max(trailStop, rBasePx + stairRungs * p.multBE * rDenom)
            if peakFloorOn:
                trailStop = max(trailStop, rBasePx + (peakR - effGiveback) * rDenom)
        elif isShort:
            trailExt = l[i] if np.isnan(trailExt) else min(trailExt, l[i])
            rawStop = trailExt + multStep * atrChand[i]
            trailStop = rawStop if np.isnan(trailStop) else min(trailStop, rawStop)
            if beActive:
                trailStop = min(trailStop, rBasePx - p.multBE * rDenom)
            if tpStairOn:
                trailStop = min(trailStop, rBasePx - stairRungs * p.multBE * rDenom)
            if peakFloorOn:
                trailStop = min(trailStop, rBasePx - (peakR - effGiveback) * rDenom)

        # ---- (2) 全出場 ----
        if not exitedThisBar and inPos:
            if isLong:
                trailHit = (not np.isnan(trailStop)) and c[i] < trailStop
                twoSTRev = bool(st1Bear[i] and st2Bear[i])
            else:
                trailHit = (not np.isnan(trailStop)) and c[i] > trailStop
                twoSTRev = bool(st1Bull[i] and st2Bull[i])
            stage = (1 if t1On else 0) + (1 if t2On else 0) + (1 if t3On else 0)
            tsAge = (i - entryBar) if entryBar >= 0 else 0
            timeStop = (p.useTimeStop and entryBar >= 0 and tsAge >= p.timeStopBars
                        and R < p.timeStopR and stage < 3)
            reason = None
            if trailHit:
                reason = "Trail"
            elif p.twoSTRevExitFull and twoSTRev:
                reason = "2STrev"
            elif timeStop:
                reason = "TimeStop"
            if reason:
                pending.append(("close", side, reason))
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False

        # ---- (3) 部分止盈 ----
        if not exitedThisBar and inPos and p.usePartialTP:
            posAbs = shares
            if R >= p.tp1R and not tp1Done:
                q = posAbs * p.tp1Pct / 100.0
                if q > 1e-9:
                    pending.append(("reduce", q, "TP1", side))
                    t1On, t2On, t3On, not1, not2, not3, _ = _apply_drain(
                        q, t1On, t2On, t3On, not1, not2, not3)
                tp1Done = True
            if R >= p.tp2R and not tp2Done:
                q = posAbs * p.tp2Pct / 100.0
                if q > 1e-9:
                    pending.append(("reduce", q, "TP2", side))
                    t1On, t2On, t3On, not1, not2, not3, _ = _apply_drain(
                        q, t1On, t2On, t3On, not1, not2, not3)
                tp2Done = True

        # ---- (4) ST 翻轉部分減碼 ----
        if not exitedThisBar and inPos and p.usePartialST:
            if isLong:
                cut1 = flip_dn(st1Bear, i) and (t1On or t2On or t3On)
                cut2 = (not cut1) and flip_dn(st2Bear, i) and (t2On or t3On)
            else:
                cut1 = flip_up(st1Bull, i) and (t1On or t2On or t3On)
                cut2 = (not cut1) and flip_up(st2Bull, i) and (t2On or t3On)
            if cut1 or cut2:
                tr = _tranche_top(t3On, t2On, t1On, not3, not2, not1)
                if tr > 1e-9:
                    pending.append(("reduce", min(tr, shares), "cutST", side))
                    t1On, t2On, t3On, not1, not2, not3, _ = _apply_drain(
                        tr, t1On, t2On, t3On, not1, not2, not3)

        # ---- (5) regime-fade ----
        if (not inPos) or er[i] >= p.erThr:
            fadeArmed = True
        if not exitedThisBar and inPos and p.useRegimeFade and p.erThr > 0:
            fadeTrig = er[i] < p.erThr * p.fadeK
            fadeReady = fadeArmed and (i - lastFadeBar) >= p.fadeCoolBars
            stage = (1 if t1On else 0) + (1 if t2On else 0) + (1 if t3On else 0)
            if fadeTrig and stage >= 2 and fadeReady:
                tr = _tranche_top(t3On, t2On, t1On, not3, not2, not1)
                if tr > 1e-9:
                    pending.append(("reduce", min(tr, shares), "fade", side))
                    t1On, t2On, t3On, not1, not2, not3, _ = _apply_drain(
                        tr, t1On, t2On, t3On, not1, not2, not3)
                fadeArmed = False
                lastFadeBar = i

        # ---- (6) cut-to-flat ----
        if not exitedThisBar and inPos:
            stage_now = (1 if t1On else 0) + (1 if t2On else 0) + (1 if t3On else 0)
            if stage_now == 0:
                pending.append(("close", side, "CutToFlat"))
                reset_position(i)
                cooldownUntil = i + p.cooldownBars
                exitedThisBar = True
                inPos = False

        # ---- (7) 進場 / 加碼 ----
        canEnter = i >= cooldownUntil and not exitedThisBar
        voteER = er[i] > p.erThr
        voteADX = bool(adxOn_state[i])
        votes_long = (1 if voteER else 0) + (1 if voteADX else 0) + (1 if bool(st3Bull[i]) else 0)
        votes_short = (1 if voteER else 0) + (1 if voteADX else 0) + (1 if bool(st3Bear[i]) else 0)
        eff_min = min(p.minVotes, 3)
        dirLong = diPlus[i] > diMinus[i]
        dirShort = diMinus[i] > diPlus[i]
        diLongOK = (not p.useDIgate) or dirLong
        diShortOK = (not p.useDIgate) or dirShort
        regimeLongOK = (not p.useRegime) or ((votes_long >= eff_min) and diLongOK)
        regimeShortOK = (not p.useRegime) or ((votes_short >= eff_min) and diShortOK)

        curStage = (1 if t1On else 0) + (1 if t2On else 0) + (1 if t3On else 0)
        volBrakeOn = p.useVolBrake and (not np.isnan(relVol[i])) and relVol[i] > p.brakeK
        addOK = (not volBrakeOn) and R > 0
        convMult = (min(max(er[i] / p.erThr, 0.5), 1.0)
                    if (p.useConvAdd and p.erThr > 0) else 1.0)

        # 多單進場/加碼
        l1Cond = (curStage == 0 and not inPos and flip_up(st1Bull, i)
                  and regimeLongOK and canEnter)
        l2Cond = (isLong and curStage == 1 and t1On and flip_up(st2Bull, i)
                  and bool(st1Bull[i]) and addOK)
        l3Cond = (isLong and curStage == 2 and t1On and t2On and flip_up(st3Bull, i)
                  and bool(st1Bull[i]) and bool(st2Bull[i]) and addOK)
        # 空單進場/加碼（鏡像；只有 allow_short 才開首倉）
        s1Cond = (allow_short and curStage == 0 and not inPos and flip_dn(st1Bear, i)
                  and regimeShortOK and canEnter)
        s2Cond = (isShort and curStage == 1 and t1On and flip_dn(st2Bear, i)
                  and bool(st1Bear[i]) and addOK)
        s3Cond = (isShort and curStage == 2 and t1On and t2On and flip_dn(st3Bear, i)
                  and bool(st1Bear[i]) and bool(st2Bear[i]) and addOK)

        if l1Cond:
            q = qty_for(p.wL1, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, +1))
                side = +1; entryRisk = p.chandMult * atrChand[i]; entryPx = c[i]
                trailExt = h[i]; trailStop = np.nan; entryBar = i
                peakR = 0.0; peakBar = i; fadeArmed = True; t1On = True; not1 = q
        elif s1Cond:
            q = qty_for(p.wL1, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, -1))
                side = -1; entryRisk = p.chandMult * atrChand[i]; entryPx = c[i]
                trailExt = l[i]; trailStop = np.nan; entryBar = i
                peakR = 0.0; peakBar = i; fadeArmed = True; t1On = True; not1 = q
        elif l2Cond:
            q = qty_for(p.wL2 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, +1)); t2On = True; not2 = q
        elif l3Cond:
            q = qty_for(p.wL3 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, +1)); t3On = True; not3 = q
        elif s2Cond:
            q = qty_for(p.wL2 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, -1)); t2On = True; not2 = q
        elif s3Cond:
            q = qty_for(p.wL3 * convMult, c[i], instVol[i])
            if q > 1e-9:
                pending.append(("open", q, -1)); t3On = True; not3 = q

        equity_curve[i] = cash + pos_sign * shares * c[i]
        prev_trailStop = trailStop

    # EOD 平倉
    if shares > 1e-9:
        i = n - 1
        exec_reduce(c[i], shares, side if side != 0 else +1)
        if cur_open:
            finalize_trade(i)
    equity_curve[n - 1] = cash + pos_sign * shares * c[n - 1]

    equity = pd.Series(equity_curve, index=idx)
    metrics = compute_metrics(equity, trades, initial_capital, p.barsPerYear)
    return metrics, trades, equity
