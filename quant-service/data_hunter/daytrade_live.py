# -*- coding: utf-8 -*-
"""
daytrade_live.py — 盤中即時當沖決策引擎（選池→即時掃描→大腦檢討→出場→排行→戰績→推播）

每 2 分：批次抓 MIS 即時價(~20秒延遲,含五檔)→更新盤中累積器(VWAP/ORB/量能/五檔/RS/regime)→
偵測嚴格觸發(爆量突破多日高/ORB/強勢續攻/爆量跌破多日低，二次確認殺假突破)→算智慧停利與 R 結構→
交給 daytrade_brain 逐單估勝率/淨EV/分級/部位/檢討→只放行「值得做」→推 ntfy(去重)＋寫 state_daytrade.json。

＊誠實：MIS ~20秒延遲非逐筆；VWAP/ORB/五檔/量性質由 2 分輪詢累積為近似值；需 app 從 09:00 開著。
用法：python daytrade_live.py --once   （盤中對真 MIS 跑一輪，不推播）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
STATE = HERE / "state_daytrade.json"
TWDATA = ROOT / "twdata" / "daytrade.json"
INTRADAY = ROOT / "twdata" / "daytrade_intraday.json"
BOOK = HERE / "daytrade_book.json"
PUSHED = HERE / "daytrade_pushed.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import scan
import universe
import realtime_quote as rq
import daytrade_brain as brain
import daytrade_eligibility as elig
from health import _squash

POOL_MAX = 150
SESSION_START = 9 * 60          # 09:00
SESSION_END = 13 * 60 + 30      # 13:30
ORB_END = 9 * 60 + 15           # 09:15


def _sq(x, lo, hi):
    v = _squash(x, lo, hi)
    return v if v is not None else 0.0


def _r(x, n=2):
    return round(x, n) if x is not None else None


def _now_min(now: datetime) -> int:
    return now.hour * 60 + now.minute


def _elapsed_frac(now: datetime) -> float:
    m = _now_min(now)
    return max(0.05, min(1.0, (m - SESSION_START) / (SESSION_END - SESSION_START)))


def _tod(now: datetime) -> str:
    m = _now_min(now)
    if m <= 9 * 60 + 30:
        return "開盤"
    if m >= 13 * 60:
        return "尾盤"
    return "盤中"


# ── CDP 樞紐點 + 關鍵價位地圖 ────────────────────────────────────────────────
def cdp_map(prev_h, prev_l, prev_c) -> dict:
    if None in (prev_h, prev_l, prev_c):
        return {}
    cdp = (prev_h + prev_l + 2 * prev_c) / 4
    rng = prev_h - prev_l
    return {"CDP": round(cdp, 2), "AH": round(cdp + rng, 2), "NH": round(2 * cdp - prev_l, 2),
            "NL": round(2 * cdp - prev_h, 2), "AL": round(cdp - rng, 2)}


def _next_round(p: float, up: bool) -> float:
    step = 5 if p < 100 else 10 if p < 500 else 50 if p < 1000 else 100
    import math
    return math.ceil(p / step) * step if up else math.floor(p / step) * step


# ── 1. 當沖池 ────────────────────────────────────────────────────────────────
def build_pool(full: bool = True, use_cache_only: bool = True) -> list[dict]:
    rows = universe.load_full_universe() if full else universe.all_codes()
    name_of = {c: n for c, n, _ in rows}
    ind_of = {c: i for c, _, i in rows}
    data = scan.load_universe_data(rows, use_cache_only=use_cache_only, intraday=False)
    eligd = elig.load()
    # 籌碼/當沖比
    codes_all = list(data.keys())
    try:
        mm = scan.margin_mod.load_margin(codes_all, offline=True) if scan.margin_mod else {}
    except Exception:
        mm = {}
    try:
        cm = scan.chips.load_chips(codes_all, days=scan.CHIP_DAYS, offline=True) if scan.chips else {}
    except Exception:
        cm = {}
    pool = []
    for code, df in data.items():
        try:
            core = scan._analyse_core(code, df, drop_last=False)
            if not core:
                continue
            d = scan._lower(df.tail(70).reset_index(drop=True))
            high, low, close = d["high"].astype(float), d["low"].astype(float), d["close"].astype(float)
            vol = d["volume"].astype(float)
            if len(close) < 20:
                continue
            adr = core.get("adr_pct")
            turn = core.get("turnover_60d")
            if adr is None or adr < 2.5 or not turn:
                continue
            big = turn >= 3e8
            small_hot = turn >= 5e7 and adr >= 4
            if not (big or small_hot):
                continue
            atr22 = scan._atr_last(scan._lower(df.tail(180).reset_index(drop=True)), scan.CHAND_LEN)
            avg_vol20 = float(vol.tail(20).mean())            # 股數
            vl = core.get("vol_lots") or 0
            m = mm.get(code, {}); lots = m.get("day_trade_lots")
            dtp = (round(lots / vl * 100, 1) if (lots and vl > 0 and lots / vl * 100 <= 100) else None)
            pscore = (_sq(adr, 3, 8) * .4 + _sq(dtp, 10, 40) * .35 + _sq(turn / 1e8, 1, 20) * .25)
            st = elig.status(code, eligd)
            if st["disposition"]:            # 處置分盤 → 剔除(不能現沖)
                continue
            crec = cm.get(code, {}) if isinstance(cm.get(code), dict) else {}
            pool.append({
                "code": code, "name": name_of.get(code, code), "industry": ind_of.get(code, ""),
                "prev_close": round(float(close.iloc[-1]), 2),
                "prev_high": round(float(high.iloc[-1]), 2), "prev_low": round(float(low.iloc[-1]), 2),
                "recent_high20": round(float(high.tail(20).max()), 2),
                "recent_low20": round(float(low.tail(20).min()), 2),
                "recent_high60": round(float(high.tail(60).max()), 2),
                "recent_low60": round(float(low.tail(60).min()), 2),
                "atr22": _r(atr22), "adr_pct": adr, "avg_vol20": avg_vol20,
                "day_trade_pct": dtp, "turnover_60d": turn,
                "consec_buy_days": crec.get("consec_buy_days") or 0,
                "attention": st["attention"], "can_daytrade": st["can_daytrade"],
                "pscore": round(pscore, 3),
            })
        except Exception:
            continue
    pool.sort(key=lambda x: x["pscore"], reverse=True)
    return pool[:POOL_MAX]


# ── 2. 盤中累積器(持久化) ────────────────────────────────────────────────────
def _load_intraday(today: str) -> dict:
    try:
        obj = json.loads(INTRADAY.read_text(encoding="utf-8"))
        if obj.get("date") == today:
            return obj
    except Exception:
        pass
    return {"date": today, "per_code": {}, "index": {"vwap_num": 0.0, "vwap_den": 0.0}}


def _save_intraday(acc: dict) -> None:
    try:
        INTRADAY.parent.mkdir(parents=True, exist_ok=True)
        tmp = INTRADAY.with_suffix(".tmp")
        tmp.write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, INTRADAY)
    except Exception:
        pass


def _update_acc(acc_c: dict, q: dict, now: datetime, avg_vol20: float) -> dict:
    """更新單檔累積器並回傳盤中特徵。q=MIS _parse 結果。"""
    price = q.get("price"); vol_lots = q.get("volume") or 0
    cum_shares = vol_lots * 1000                     # MIS 張→股，對齊日均量(股)
    o, h, l = q.get("open"), q.get("high"), q.get("low")
    pc = q.get("prev_close")
    a = acc_c
    # VWAP 累積
    prev_cum = a.get("cum_vol", 0.0)
    dvol = max(0.0, cum_shares - prev_cum)
    if price is not None:
        if a.get("vwap_den", 0.0) <= 0 and dvol <= 0:
            a["vwap_num"] = price * max(cum_shares, 1); a["vwap_den"] = max(cum_shares, 1)
        else:
            a["vwap_num"] = a.get("vwap_num", 0.0) + price * dvol
            a["vwap_den"] = a.get("vwap_den", 0.0) + dvol
    a["cum_vol"] = cum_shares
    vwap = (a["vwap_num"] / a["vwap_den"]) if a.get("vwap_den") else price
    # ORB
    m = _now_min(now)
    if m <= ORB_END and not a.get("orb_frozen"):
        a["orb_h"] = max(a.get("orb_h", h or price or 0), h or price or 0)
        a["orb_l"] = min(a.get("orb_l", l or price or 1e9), l or price or 1e9)
    elif m > ORB_END:
        a["orb_frozen"] = True
    # 當日高低
    a["day_h"] = max(a.get("day_h", h or price or 0), h or price or 0)
    a["day_l"] = min(a.get("day_l", l or price or 1e9), l or price or 1e9)
    # 五檔力道
    bid_sum = sum(x.get("vol", 0) for x in (q.get("bid") or []))
    ask_sum = sum(x.get("vol", 0) for x in (q.get("ask") or []))
    ob_ratio = round(bid_sum / ask_sum, 2) if ask_sum else None
    prev_bid = a.get("bid_sum", bid_sum)
    pull = bool(prev_bid > 0 and bid_sum < prev_bid * 0.5)     # 委買驟減=抽單
    a["bid_sum"] = bid_sum
    # 量能投影
    frac = _elapsed_frac(now)
    vol_ratio = round((cum_shares / frac) / avg_vol20, 2) if avg_vol20 and avg_vol20 > 0 else None
    # 量性質(攻擊/出貨)：帶量且收在當日高段=攻擊、收在低段/翻黑=出貨
    rng = (a["day_h"] - a["day_l"]) or 1
    pos_in_range = (price - a["day_l"]) / rng if price is not None else 0.5
    chg_pct = q.get("chg_pct")
    vol_type = "中性"
    if vol_ratio and vol_ratio >= 1.5:
        if pos_in_range >= 0.7 and (chg_pct or 0) > 0:
            vol_type = "攻擊量"
        elif pos_in_range <= 0.3 or (chg_pct or 0) < 0:
            vol_type = "出貨量"
    # 背離：創當日新高但量能未同步放大
    prev_peak_vr = a.get("peak_vr", 0)
    new_high = price is not None and price >= a["day_h"] * 0.999
    divergence = bool(new_high and vol_ratio is not None and vol_ratio < max(1.3, prev_peak_vr * 0.8))
    if vol_ratio:
        a["peak_vr"] = max(prev_peak_vr, vol_ratio)
    return {
        "price": price, "chg_pct": chg_pct, "open": o, "prev_close": pc,
        "vwap": _r(vwap), "vwap_dev": _r((price / vwap - 1) * 100) if (price and vwap) else None,
        "orb_h": _r(a.get("orb_h")), "orb_l": _r(a.get("orb_l")), "orb_frozen": a.get("orb_frozen", False),
        "day_h": _r(a["day_h"]), "day_l": _r(a["day_l"]),
        "ob_ratio": ob_ratio, "pull_order": pull, "vol_ratio": vol_ratio,
        "vol_type": vol_type, "divergence": divergence, "new_high": new_high,
        "new_low": price is not None and price <= a["day_l"] * 1.001,
        "pos_in_range": round(pos_in_range, 2),
    }


# ── 3. 大盤 regime ──────────────────────────────────────────────────────────
def _regime(idx: dict, iacc: dict) -> dict:
    chg = idx.get("chg_pct") if idx else None
    price = idx.get("price") if idx else None
    vol_num = iacc.get("vwap_num", 0.0); vol_den = iacc.get("vwap_den", 0.0)
    ivwap = (vol_num / vol_den) if vol_den else price
    above = bool(price and ivwap and price >= ivwap)
    if chg is None:
        return {"label": "中性", "index_chg": None, "index_vs_vwap": "—"}
    if chg <= -0.8:
        label = "弱勢日"
    elif chg >= 0.4 and above:
        label = "趨勢多日"
    elif chg <= -0.4 and not above:
        label = "趨勢空日"
    else:
        label = "震盪日"
    return {"label": label, "index_chg": chg, "index_vs_vwap": "above" if above else "below"}


def _mkt_align(direction: str, regime: str) -> float:
    long = direction == "long"
    if regime == "趨勢多日":
        return 1.0 if long else 0.0
    if regime in ("趨勢空日", "弱勢日"):
        return 0.0 if long else 1.0
    return 0.5


# ── 4. 觸發 + 二次確認 + 環境自適應 + 智慧停利 ──────────────────────────────
def _vol_gate(regime: str, direction: str) -> float:
    if regime == "震盪日":
        return 2.2
    if regime == "趨勢多日" and direction == "long":
        return 1.6
    if regime in ("趨勢空日", "弱勢日") and direction == "short":
        return 1.6
    return 1.8


def _targets(entry, risk, direction, p):
    long = direction == "long"
    tp1 = round(entry + risk, 2) if long else round(entry - risk, 2)
    tp2 = round(entry + 2 * risk, 2) if long else round(entry - 2 * risk, 2)
    nr = _next_round(entry, up=long)
    # room 到結構壓力/支撐
    room_R = round(abs(nr - entry) / risk, 2) if risk else None
    if room_R is None or room_R < 1.0:
        room_R = 2.5
    return [tp1, tp2, "移動"], min(room_R, 3.0), nr


def detect_signals(pool: list[dict], acc: dict, regime: dict, quotes: dict, now: datetime) -> list[dict]:
    cands = []
    pool_by = {p["code"]: p for p in pool}
    reg = regime["label"]
    for code, q in quotes.items():
        p = pool_by.get(code)
        if p is None or q.get("price") is None:
            continue
        a = acc["per_code"].setdefault(code, {})
        feat = _update_acc(a, q, now, p.get("avg_vol20") or 0)
        price, chg = feat["price"], feat["chg_pct"] or 0
        vwap = feat["vwap"]
        for direction in ("long", "short"):
            long = direction == "long"
            gate = _vol_gate(reg, direction)
            vr = feat["vol_ratio"] or 0
            hit, setup = False, None
            # 爆量突破多日高 / 跌破多日低
            if long and feat["new_high"] and price >= p["recent_high20"] and vr >= gate and chg >= 1.5:
                hit, setup = True, "爆量突破多日高"
            elif (not long) and feat["new_low"] and price <= p["recent_low20"] and vr >= gate and chg <= -1.5:
                hit, setup = True, "爆量跌破多日低"
            # ORB 突破/跌破
            elif long and feat["orb_frozen"] and feat["orb_h"] and price > feat["orb_h"] and vr >= max(1.5, gate - 0.3):
                hit, setup = True, "開盤區間突破"
            elif (not long) and feat["orb_frozen"] and feat["orb_l"] and price < feat["orb_l"] and vr >= max(1.5, gate - 0.3):
                hit, setup = True, "開盤區間跌破"
            if not hit:
                continue
            # 方向必須站對 VWAP 邊(核心過濾)
            if vwap and ((long and price < vwap) or ((not long) and price > vwap)):
                continue
            # 二次確認：armed→下一輪仍守 level 才確認；趨勢順勢可即發
            level = price
            armed = a.get("armed")
            trend_ok = (reg == "趨勢多日" and long) or (reg in ("趨勢空日", "弱勢日") and not long)
            confirmed = False
            if armed and armed.get("dir") == direction and armed.get("ts") != now.isoformat(timespec="minutes"):
                held = price >= armed["level"] if long else price <= armed["level"]
                if held:
                    confirmed = True
                else:
                    a["armed"] = {"dir": direction, "level": level, "ts": now.isoformat(timespec="minutes")}
                    continue
            else:
                a["armed"] = {"dir": direction, "level": level, "ts": now.isoformat(timespec="minutes")}
                if not (trend_ok and reg != "震盪日"):
                    continue           # 非趨勢順勢 → 需等下一輪確認
            # 回踩不追高：噴出過遠改建議回踩進場
            atr = p.get("atr22") or (price * 0.01)
            entry = price
            entry_type = "現價"
            if abs(price - level) > 0.6 * atr:
                entry = round(vwap or level, 2)
                entry_type = "回踩VWAP不破再進"
            risk = max(min(0.6 * atr, entry * 0.025), entry * 0.008)
            stop = round(entry - risk, 2) if long else round(entry + risk, 2)
            targets, room_R, nr = _targets(entry, risk, direction, p)
            cands.append({
                "code": code, "name": p["name"], "dir": direction, "setup": setup,
                "ts": now.strftime("%H:%M"), "price": price, "chg": chg,
                "entry": entry, "entry_type": entry_type, "stop": stop, "targets": targets,
                "risk": round(risk, 2), "room_R": room_R, "next_level": nr,
                "vwap_dev": feat["vwap_dev"], "vol_ratio": feat["vol_ratio"], "ob_ratio": feat["ob_ratio"],
                "vol_type": feat["vol_type"], "pull_order": feat["pull_order"], "divergence": feat["divergence"],
                "confirmed": confirmed, "orb_break": setup.startswith("開盤"),
                "break_atr": round(abs(price - p["recent_high20" if long else "recent_low20"]) / atr, 2),
                "rs": None, "mtf": None, "inst": _sq(p.get("consec_buy_days"), 0, 5),
                "attention": p.get("attention"), "can_daytrade": p.get("can_daytrade"),
                "is_etf": code.startswith("00"),
            })
    return cands


# ── 5. 主編排 ────────────────────────────────────────────────────────────────
def _load_pushed(today: str) -> set:
    try:
        obj = json.loads(PUSHED.read_text(encoding="utf-8"))
        return set(obj.get("keys", [])) if obj.get("date") == today else set()
    except Exception:
        return set()


def _save_pushed(today: str, keys: set) -> None:
    try:
        tmp = PUSHED.with_suffix(".tmp")
        tmp.write_text(json.dumps({"date": today, "keys": sorted(keys)}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PUSHED)
    except Exception:
        pass


def _push_msg(s: str) -> str:
    return s


def scan_live(pool: list[dict], push: bool = True, now: datetime | None = None,
              quotes: dict | None = None, index_quote: dict | None = None,
              cfg: dict | None = None, book_stats: dict | None = None,
              weights: dict | None = None) -> dict:
    """一輪掃描。quotes/index_quote 可注入(測試不連網)；否則對真 MIS 抓。"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    cfg = cfg or {}
    codes = [p["code"] for p in pool]
    if quotes is None:
        quotes = rq.fetch_quotes_batch(codes)
    if index_quote is None:
        try:
            idxs = rq.fetch_indices()
            index_quote = next((x for x in idxs if x.get("name") == "加權指數"), None)
            if index_quote:
                index_quote = {"price": index_quote.get("price"), "chg_pct": index_quote.get("chg_pct")}
        except Exception:
            index_quote = None
    acc = _load_intraday(today)
    # index VWAP 累積(粗略：以指數價×1 當量)
    if index_quote and index_quote.get("price"):
        acc["index"]["vwap_num"] = acc["index"].get("vwap_num", 0.0) + index_quote["price"]
        acc["index"]["vwap_den"] = acc["index"].get("vwap_den", 0.0) + 1
    regime = _regime(index_quote or {}, acc["index"])
    idx_chg = (index_quote or {}).get("chg_pct") or 0
    tod = _tod(now)
    minutes_to_close = SESSION_END - _now_min(now)

    cands = detect_signals(pool, acc, regime, quotes, now)
    signals, filtered = [], []
    for c in cands:
        c["rs"] = _r((c["chg"] or 0) - idx_chg)
        m = dict(c)
        m["mkt_align"] = _mkt_align(c["dir"], regime["label"])
        m["disposition"] = not c.get("can_daytrade", True)
        m["exec_ok"] = _exec_ok(quotes.get(c["code"]), c["dir"], cfg)
        ctx = {"regime": regime["label"], "tod": tod, "streak": _streak(),
               "minutes_to_close": minutes_to_close}
        v = brain.verdict(m, c["dir"], c["setup"], ctx, book_stats, cfg, weights)
        c["brain"] = {"p": v["p"], "conf": v["conf"], "ev_R": v["ev_R"], "ev_net_R": v["ev_net_R"],
                      "ev_net_twd": v["ev_net_twd"], "breakeven": v["breakeven"], "grade": v["grade"],
                      "size_lots": v["size"].get("lots"), "size_note": v["size"].get("note"),
                      "kelly": v["size"].get("kelly"), "review": v["review"],
                      "contrib": v["contrib"], "flags": v["flags"], "factors": v["factors"]}
        c["factors_disp"] = {"vwap_dev": c["vwap_dev"], "rs": c["rs"], "ob_ratio": c["ob_ratio"],
                             "vol_ratio": c["vol_ratio"], "vol_type": c["vol_type"], "mtf": c.get("mtf")}
        c["exec"] = {"ok": m["exec_ok"], "suggest": _exec_suggest(c, quotes.get(c["code"]))}
        c["grade"] = v["grade"]
        c["elig"] = {"can_daytrade": c.get("can_daytrade"), "disposition": m["disposition"],
                     "attention": c.get("attention")}
        (signals if v["ok"] else filtered).append(c)

    signals.sort(key=lambda x: x["brain"]["ev_net_R"], reverse=True)
    # 熔斷
    cb = _circuit_breaker(cfg)
    # 推播(只推值得做 S/A；熔斷後停推)
    if push and scan._market_open_now() and not cb["tripped"]:
        pushed = _load_pushed(today)
        for c in signals:
            key = f"{today}:{c['code']}:{c['dir']}"
            if key in pushed:
                continue
            _emit_push(c, regime)
            _record_book(c, today)            # 前向追蹤(批2 評估出場)
            pushed.add(key)
        _save_pushed(today, pushed)

    ranks = _build_ranks(pool, acc, quotes)
    out = {
        "generated_at": now.isoformat(timespec="seconds"), "market_open": scan._market_open_now(),
        "pool_n": len(pool), "regime": regime, "circuit_breaker": cb,
        "signals": signals, "filtered": filtered, "ranks": ranks,
        "book_summary": _book_summary(), "daily_report": _load_reports(today), "tod": tod,
    }
    _write(out)
    _save_intraday(acc)
    return out


def _exec_ok(q, direction, cfg) -> bool:
    if not q:
        return True
    want = (cfg or {}).get("ev_lots", 1)
    side = q.get("ask") if direction == "long" else q.get("bid")   # 多方吃賣單、空方吃買單
    qty = sum(x.get("vol", 0) for x in (side or []))
    return qty >= want


def _exec_suggest(c, q) -> str:
    return f"限價 {c['entry']}"


def _streak() -> int:
    try:
        b = json.loads(BOOK.read_text(encoding="utf-8")).get("trades", [])
        recent = [t for t in b if t.get("result") in ("win", "loss")][-5:]
        s = 0
        for t in reversed(recent):
            if t["result"] == "loss":
                s += 1
            else:
                break
        return s
    except Exception:
        return 0


def _circuit_breaker(cfg) -> dict:
    limit = (cfg or {}).get("max_day_loss_R", -3)
    try:
        b = json.loads(BOOK.read_text(encoding="utf-8"))
        if b.get("updated") == date.today().isoformat():
            day_R = sum(t.get("ret_R", 0) or 0 for t in b.get("trades", [])
                        if t.get("ts", "").startswith(date.today().isoformat()) or True)
        else:
            day_R = 0
    except Exception:
        day_R = 0
    return {"tripped": day_R <= limit, "day_pnl_R": round(day_R, 2), "limit_R": limit}


def _record_book(c, today):
    try:
        b = json.loads(BOOK.read_text(encoding="utf-8")) if BOOK.exists() else {"trades": []}
    except Exception:
        b = {"trades": []}
    b["updated"] = today
    if any(t.get("code") == c["code"] and t.get("dir") == c["dir"]
           and t.get("date") == today for t in b["trades"]):
        return
    b["trades"].append({
        "date": today, "code": c["code"], "name": c["name"], "dir": c["dir"], "setup": c["setup"],
        "entry": c["entry"], "stop": c["stop"], "tp": c["targets"], "ts": today + "T" + c["ts"],
        "pred_p": c["brain"]["p"], "pred_ev": c["brain"]["ev_net_R"], "grade": c["grade"],
        "factors": c["brain"].get("factors") or {}, "status": "open", "result": None,
        "post_h": c["price"], "post_l": c["price"],
    })
    try:
        tmp = BOOK.with_suffix(".tmp")
        tmp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, BOOK)
    except Exception:
        pass


def _book_summary() -> dict:
    try:
        b = json.loads(BOOK.read_text(encoding="utf-8"))
        fin = [t for t in b.get("trades", []) if t.get("result") in ("win", "loss")]
        n = len(fin)
        wr = round(sum(1 for t in fin if t["result"] == "win") / n, 3) if n else None
        avgR = round(sum(t.get("ret_R", 0) or 0 for t in fin) / n, 2) if n else None
        return {"n": n, "winrate": wr, "avg_R": avgR, "learning": "累積中" if n < brain.LOGISTIC_MIN_N else "logistic"}
    except Exception:
        return {"n": 0, "winrate": None, "avg_R": None, "learning": "累積中"}


def _build_ranks(pool, acc, quotes) -> dict:
    rows = []
    for code, q in quotes.items():
        a = acc["per_code"].get(code, {})
        p = next((x for x in pool if x["code"] == code), None)
        vr = None
        if p and p.get("avg_vol20"):
            frac = _elapsed_frac(datetime.now())
            vr = round(((q.get("volume") or 0) * 1000 / frac) / p["avg_vol20"], 2)
        amp = None
        if a.get("day_h") and a.get("day_l") and q.get("prev_close"):
            amp = round((a["day_h"] - a["day_l"]) / q["prev_close"] * 100, 2)
        bid = sum(x.get("vol", 0) for x in (q.get("bid") or []))
        ask = sum(x.get("vol", 0) for x in (q.get("ask") or []))
        rows.append({"code": code, "name": p["name"] if p else code, "chg": q.get("chg_pct"),
                     "vol_ratio": vr, "amp": amp, "ob": round(bid / ask, 2) if ask else None})
    def top(key, rev=True, n=10):
        return sorted([r for r in rows if r.get(key) is not None], key=lambda x: x[key], reverse=rev)[:n]
    return {"up": top("chg"), "down": top("chg", rev=False), "vol": top("vol_ratio"),
            "amp": top("amp"), "orderbook": top("ob")}


def _emit_push(c, regime):
    try:
        import notify
        b = c["brain"]
        arrow = "🔴 當沖做多" if c["dir"] == "long" else "🟢 當沖做空"
        conf = f"{int(b['conf'][0]*100)}-{int(b['conf'][1]*100)}"
        tps = "/".join(str(t) for t in c["targets"])
        msg = (f"{arrow}｜{c['code']} {c['name']}  [{c['grade']}級] 勝率{int(b['p']*100)}%({conf}) · 淨期望{b['ev_net_R']:+.2f}R\n"
               f"進場 {c['entry']}{'(可回踩)' if '回踩' in c['entry_type'] else ''} · 停損 {c['stop']} · 停利 {tps} · 損平 {b['breakeven']}"
               + (f" · 建議{b['size_lots']}張" if b.get("size_lots") else "") + "\n"
               f"{b['review']}\n⚠當日平倉·嚴設停損·非投資建議")
        notify.broadcast(msg, title=f"當沖訊號｜{c['code']} {c['name']} [{c['grade']}]", priority="high")
    except Exception:
        pass


def _load_reports(today):
    return {"pre": None, "post": None}


def _write(out: dict) -> None:
    for path in (STATE, TWDATA):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            pass


def load_daytrade() -> dict | None:
    for path in (STATE, TWDATA):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    if "--pool" in sys.argv:
        pl = build_pool()
        print(f"[daytrade] 當沖池 {len(pl)} 檔；前10：")
        for p in pl[:10]:
            print(f"  {p['code']} {p['name'][:6]:6} adr{p['adr_pct']} 當沖比{p['day_trade_pct']} {p['pscore']}")
        raise SystemExit(0)
    pool = build_pool()
    out = scan_live(pool, push=("--push" in sys.argv))
    print(f"[daytrade] regime={out['regime']['label']} 訊號{len(out['signals'])} 擋{len(out['filtered'])}")
    for s in out["signals"][:8]:
        b = s["brain"]
        print(f"  [{s['grade']}] {s['dir']} {s['code']} {s['name'][:6]} 進{s['entry']} 損{s['stop']} "
              f"勝率{b['p']} 淨EV{b['ev_net_R']} · {b['review']}")
