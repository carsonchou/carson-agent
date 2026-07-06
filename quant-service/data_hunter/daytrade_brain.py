# -*- coding: utf-8 -*-
"""
daytrade_brain.py — 盤中當沖「量化淨EV檢討大腦」（純函式、可單測、不連網）

把 VWAP位階/RS/五檔力道/量能/大盤regime/獲利空間/多框/量性質/二次確認/法人傾向 等
全變成因子 → 估勝率(啟發式先驗 → 各setup×regime×時段經驗貝式收縮 → 實盤≥50筆自學 logistic
→ Wilson 信心區間) → 扣成本(手續費+當沖證交稅0.15%+滑價)算**淨期望值** → S/A/B 分級 →
半Kelly/固定風險%建議部位(連敗降碼) → 一句檢討 → gate 只放行「值得做」。

＊誠實：勝率為模型估計非保證；成本用參數化費率估算；冷啟動走啟發式先驗。
"""
from __future__ import annotations

import math
from health import _squash

# ── 成本常數 ──
FEE_RATE = 0.001425          # 券商手續費率
FEE_MIN = 20                 # 單筆最低手續費
DAYTRADE_TAX = 0.0015        # 當沖證交稅(現沖減半 0.3%→0.15%)

# ── 因子權重(啟發式；自學習後由 logistic 覆蓋)。合計=1.0 ──
WEIGHTS = {
    "f_vol": .13, "f_break": .10, "f_vwap": .14, "f_rs": .11, "f_ob": .08,
    "f_mkt": .11, "f_orb": .05, "f_room": .10, "f_mtf": .06, "f_voltype": .05,
    "f_confirm": .04, "f_inst": .03,
}
FACTOR_LABEL = {
    "f_vol": "爆量", "f_break": "突破力道", "f_vwap": "VWAP位階", "f_rs": "領漲強度",
    "f_ob": "五檔力道", "f_mkt": "大盤同向", "f_orb": "開盤突破", "f_room": "獲利空間",
    "f_mtf": "多框一致", "f_voltype": "攻擊量", "f_confirm": "二次確認", "f_inst": "法人傾向",
}

K_PSEUDO = 20                # 貝式收縮偽計數
LOGISTIC_MIN_N = 50          # 自學習最低樣本


def _sq(x, lo, hi):
    v = _squash(x, lo, hi)
    return v if v is not None else 0.5


def _dir_ratio(ratio, long: bool):
    """五檔力道方向化：做多用 bid/ask，做空用 ask/bid。"""
    if not ratio or ratio <= 0:
        return 1.0
    return ratio if long else 1.0 / ratio


def _vwap_score(dev_fav):
    """VWAP 位階倒U：站對邊且乖離適中最高分，逆邊或追高低分。dev_fav=有利方向乖離%。"""
    if dev_fav < 0:            # 站錯邊(多在VWAP下/空在VWAP上)
        return max(0.1, 0.3 + 0.1 * dev_fav)
    if dev_fav <= 1.5:         # 剛站穩~適中 → 升到峰值
        return 0.65 + 0.35 * (dev_fav / 1.5)
    if dev_fav <= 3.0:         # 略高
        return 1.0 - 0.35 * ((dev_fav - 1.5) / 1.5)
    return max(0.2, 0.65 - 0.15 * (dev_fav - 3.0))   # 追高衰減


def _mtf_score(mtf, long):
    if mtf in ("三多",) and long:
        return 1.0
    if mtf in ("三空",) and not long:
        return 1.0
    if mtf == "分歧":
        return 0.3
    return 0.15                # 逆向


def factors(m: dict, direction: str) -> dict:
    """由盤中特徵 m 算全因子(0..1，方向感知)。"""
    long = direction == "long"
    sgn = (lambda x: x) if long else (lambda x: -x)
    voltype = {"攻擊量": 1.0, "中性": 0.5, "出貨量": 0.0}.get(m.get("vol_type"), 0.5)
    ob = _dir_ratio(m.get("ob_ratio"), long)
    f_ob = _sq(ob, 1.0, 3.0)
    if m.get("pull_order"):        # 抽單 → 五檔力道打折
        f_ob *= 0.7
    return {
        "f_vol": _sq(m.get("vol_ratio"), 1.5, 4.0),
        "f_break": _sq(m.get("break_atr"), 0.1, 1.5),
        "f_vwap": _vwap_score(sgn(m.get("vwap_dev") or 0.0)),
        "f_rs": _sq(sgn(m.get("rs") or 0.0), 0.0, 3.0),
        "f_ob": f_ob,
        "f_mkt": float(m.get("mkt_align", 0.5)),
        "f_orb": 1.0 if m.get("orb_break") else 0.5,
        "f_room": _sq(m.get("room_R"), 1.0, 3.0),
        "f_mtf": _mtf_score(m.get("mtf"), long),
        "f_voltype": voltype,
        "f_confirm": 1.0 if m.get("confirmed") else 0.4,
        "f_inst": _sq(m.get("inst"), 0.0, 1.0),
    }


def _score(f: dict, weights: dict) -> float:
    num = sum(weights.get(k, 0) * v for k, v in f.items() if v is not None)
    den = sum(weights.get(k, 0) for k, v in f.items() if v is not None)
    return num / den if den else 0.5


def _wilson(p: float, n: int, z: float = 1.96):
    if n <= 0:
        return (max(0.0, p - 0.25), min(1.0, p + 0.25))
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, center - half), 3), round(min(1.0, center + half), 3))


def win_prob(f: dict, setup: str, regime: str, tod: str,
             book_stats: dict | None = None, weights: dict | None = None):
    """回 (p_base, conf_lo, conf_hi, source)。book_stats[(setup,regime,tod)]={'n','winrate'}。"""
    w = weights or WEIGHTS
    score = _score(f, w)
    p_prior = 0.35 + 0.40 * score
    n, p_emp = 0, None
    if book_stats:
        rec = book_stats.get(f"{setup}|{regime}|{tod}") or book_stats.get(setup)
        if rec and rec.get("n"):
            n, p_emp = int(rec["n"]), float(rec["winrate"])
    if n and p_emp is not None:
        p = (n * p_emp + K_PSEUDO * p_prior) / (n + K_PSEUDO)
        lo, hi = _wilson(p_emp, n)
    else:
        p = p_prior
        lo, hi = _wilson(p_prior, 0)
    source = "logistic" if weights else "heuristic"
    return round(min(max(p, 0.15), 0.90), 3), lo, hi, source


def _penalties(m: dict, ctx: dict, room_R):
    """回 (penalty_mult, flags, critical)。critical=True → 直接不放行。"""
    flags, mult, critical = [], 1.0, False
    dev = m.get("vwap_dev") or 0.0
    if abs(dev) > 3.0:
        flags.append("追高乖離"); mult *= 0.85
    if ctx.get("minutes_to_close", 999) < 40:
        flags.append("接近收盤"); mult *= 0.80
    if room_R is not None and room_R < 1.5:
        flags.append("空間不足"); mult *= 0.80
    if m.get("divergence"):
        flags.append("價量背離"); mult *= 0.85
    if float(m.get("mkt_align", 0.5)) < 0.5:
        flags.append("逆大盤"); mult *= 0.85
    if m.get("attention"):
        flags.append("注意股"); mult *= 0.85
    if m.get("pull_order"):
        flags.append("五檔抽單"); mult *= 0.90
    if m.get("reentry"):
        flags.append("再進場需更強"); mult *= 0.85
    if m.get("disposition"):
        flags.append("處置分盤不可現沖"); critical = True
    if m.get("exec_ok") is False:
        flags.append("流動性不足"); critical = True
    return mult, flags, critical


def net_ev(p: float, entry: float, stop: float, lots: int,
           avg_win_R: float = 1.5, fee_disc: float = 0.3, is_etf: bool = False) -> dict:
    """扣成本淨期望值 + 損益兩平點。回 {ev_gross_R, cost_R, ev_net_R, ev_net_twd, breakeven}。"""
    risk_pts = abs(entry - stop) or (entry * 0.01)
    shares = max(lots, 1) * 1000
    amt = entry * shares
    fee = max(FEE_MIN, amt * FEE_RATE * fee_disc)         # 進場手續費
    fee_exit = max(FEE_MIN, amt * FEE_RATE * fee_disc)    # 出場手續費(近似同額)
    tax = amt * (0.001 if is_etf else DAYTRADE_TAX)       # 當沖證交稅(賣出)
    total_cost = fee + fee_exit + tax
    cost_R = total_cost / (risk_pts * shares)
    ev_gross_R = p * avg_win_R - (1 - p) * 1.0
    ev_net_R = ev_gross_R - cost_R
    ev_net_twd = round(ev_net_R * risk_pts * shares)
    breakeven = round(entry + total_cost / shares, 2)      # 多方；空方對稱由呼叫端處理方向
    return {"ev_gross_R": round(ev_gross_R, 3), "cost_R": round(cost_R, 3),
            "ev_net_R": round(ev_net_R, 3), "ev_net_twd": ev_net_twd,
            "breakeven": breakeven, "total_cost": round(total_cost)}


def grade(p: float, ev_net_R: float, conf_lo: float, room_R) -> str:
    room_R = room_R or 0
    if p >= 0.62 and ev_net_R >= 0.5 and conf_lo >= 0.45 and room_R >= 2.0:
        return "S"
    if ev_net_R >= 0.30 and p >= 0.55 and room_R >= 1.5:
        return "A"
    if ev_net_R >= 0.15 and p >= 0.50:
        return "B"
    return "-"


def position_size(p: float, rr: float, entry: float, stop: float,
                  cfg: dict | None, streak: int = 0) -> dict:
    """半Kelly ∩ 固定風險% → 建議張數。連敗降碼。cfg={capital,risk_pct,max_lots}。"""
    cfg = cfg or {}
    risk_pts = abs(entry - stop) or (entry * 0.01)
    kelly = max(0.0, min(0.25, 0.5 * (p - (1 - p) / max(rr, 0.1))))
    cap = cfg.get("capital")
    if not cap:
        return {"lots": None, "kelly": round(kelly, 3), "note": "設定本金後給張數建議"}
    risk_amt = cap * (cfg.get("risk_pct", 1.0) / 100.0)
    lots_risk = risk_amt / (risk_pts * 1000)             # 固定風險% = 風險紀律主軸
    lots_kelly = (cap * kelly) / (entry * 1000)          # Kelly notional 上限(避免過度下注)
    cut = streak >= cfg.get("streak_cut_n", 3)
    # 以固定風險為主、Kelly 只在明顯更保守時才壓低；連敗減半；資金夠一張則至少 1 張
    lots = lots_risk
    if lots_kelly > 0 and lots_kelly < lots_risk * 0.5:
        lots = lots_kelly
    if cut:
        lots *= 0.5
    lots = round(lots)
    if lots < 1 and lots_risk >= 0.5 and not cut:
        lots = 1
    lots = max(0, min(lots, cfg.get("max_lots", 999)))
    return {"lots": lots, "kelly": round(kelly, 3),
            "note": f"風險{cfg.get('risk_pct',1.0)}%" + ("·連敗降碼" if cut else "")}


def _review(direction, grade_, p, ev, size, top_factors, flags, room_R, ok):
    dtxt = "做多" if direction == "long" else "做空"
    if ok:
        pos = f"·建議{size['lots']}張" if size.get("lots") else ""
        return (f"{'＋'.join(top_factors)}，空間{room_R:.1f}R→[{grade_}級] "
                f"勝率{p*100:.0f}% 淨期望{ev:+.2f}R 值得{dtxt}{pos}")
    why = "·".join(flags) if flags else "期望值/勝率不足"
    return f"{why}→不建議{dtxt}"


def verdict(m: dict, direction: str, setup: str, ctx: dict,
            book_stats: dict | None = None, cfg: dict | None = None,
            weights: dict | None = None, avg_win_R: float = 1.5) -> dict:
    """完整逐單檢討：因子→勝率→淨EV→分級→部位→gate→檢討。"""
    f = factors(m, direction)
    room_R = m.get("room_R")
    p_base, lo, hi, source = win_prob(f, setup, ctx.get("regime", "中性"),
                                      ctx.get("tod", "盤中"), book_stats, weights)
    pmult, flags, critical = _penalties(m, ctx, room_R)
    p = round(min(max(p_base * pmult, 0.15), 0.90), 3)
    lots_for_ev = (cfg or {}).get("ev_lots", 1)
    ev = net_ev(p, m["entry"], m["stop"], lots_for_ev, avg_win_R,
                (cfg or {}).get("fee_disc", 0.3), m.get("is_etf", False))
    size = position_size(p, avg_win_R, m["entry"], m["stop"], cfg, ctx.get("streak", 0))
    g = grade(p, ev["ev_net_R"], lo, room_R)
    ok = (not critical and g in ("S", "A")
          and ev["ev_net_R"] >= 0.30 and p >= 0.55 and (room_R or 0) >= 1.5)
    contrib = {k: round(WEIGHTS.get(k, 0) * v, 3) for k, v in f.items()}
    top = sorted(contrib, key=contrib.get, reverse=True)[:3]
    top_labels = [FACTOR_LABEL[k] for k in top]
    review = _review(direction, g, p, ev["ev_net_R"], size, top_labels, flags, room_R or 0, ok)
    return {
        "ok": ok, "grade": g if ok else ("B" if g == "B" else "-"),
        "p": p, "conf": [lo, hi], "source": source,
        "ev_R": ev["ev_gross_R"], "ev_net_R": ev["ev_net_R"], "cost_R": ev["cost_R"],
        "ev_net_twd": ev["ev_net_twd"], "breakeven": ev["breakeven"],
        "room_R": room_R, "size": size, "flags": flags, "critical": critical,
        "contrib": {k: contrib[k] for k in top}, "factors": f, "review": review,
    }


def fit_logistic(book: list[dict], iters: int = 300, lr: float = 0.3):
    """實盤戰績 finalized(win/loss)≥50 筆 → 純 Python 梯度下降 logistic 學因子權重。
    回 dict{factor:weight}(已重正規化為非負合計1) 或 None(樣本不足→走啟發式)。"""
    rows = [t for t in book if t.get("result") in ("win", "loss") and t.get("factors")]
    if len(rows) < LOGISTIC_MIN_N:
        return None
    keys = list(WEIGHTS.keys())
    X = [[float(t["factors"].get(k, 0.5)) for k in keys] for t in rows]
    y = [1.0 if t["result"] == "win" else 0.0 for t in rows]
    w = [0.0] * len(keys)
    b = 0.0
    n = len(X)
    for _ in range(iters):
        gw = [0.0] * len(keys)
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(w[j] * xi[j] for j in range(len(keys)))
            pred = 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))
            err = pred - yi
            gb += err
            for j in range(len(keys)):
                gw[j] += err * xi[j]
        b -= lr * gb / n
        for j in range(len(keys)):
            w[j] -= lr * gw[j] / n
    pos = {keys[j]: max(0.0, w[j]) for j in range(len(keys))}
    s = sum(pos.values())
    if s <= 0:
        return None
    return {k: round(v / s, 4) for k, v in pos.items()}
