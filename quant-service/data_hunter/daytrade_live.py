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

POOL_MAX = int(os.getenv("DT_POOL_MAX", 2500))          # 安全上限(>全市場，實務全收；分層輪掃管理載)
TIER1_SEED = int(os.getenv("DT_TIER1_SEED", 400))       # 核心種子(pool_score top-N，每輪都掃)
TIER2_SLICES = int(os.getenv("DT_TIER2_SLICES", 3))     # 長尾分幾片(=全市場幾輪掃完)
HOT_VR = float(os.getenv("DT_HOT_VR", 2.0))             # 動態熱股：量能投影倍數門檻
HOT_CHG = float(os.getenv("DT_HOT_CHG", 4.0))           # 動態熱股：|漲跌%| 門檻
HOT_NEAR_LIMIT = 1.0                                    # 距漲跌停 <1% = 敲門
HOT_MAX = int(os.getenv("DT_HOT_MAX", 200))             # 熱股集上限(滿了汰換最弱)
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


# ── 1. 全市場基準宇宙（不預先淘汰；分層輪掃在 scan_live） ─────────────────────
def build_universe(full: bool = True, use_cache_only: bool = True) -> list[dict]:
    """每日建全市場基準(~1925檔)。只要有足夠日線資料就收(不用 turnover/adr 門檻淘汰、
    處置股只標旗標不剔除)——讓大腦在決策層擋，而非掃描層漏掉昨冷今熱的飆股。依 pool_score 排序。"""
    rows = universe.load_full_universe() if full else universe.all_codes()
    name_of = {c: n for c, n, _ in rows}
    ind_of = {c: i for c, _, i in rows}
    data = scan.load_universe_data(rows, use_cache_only=use_cache_only, intraday=False)
    eligd = elig.load()
    codes_all = list(data.keys())
    try:
        mm = scan.margin_mod.load_margin(codes_all, offline=True) if scan.margin_mod else {}
    except Exception:
        mm = {}
    try:
        cm = scan.chips.load_chips(codes_all, days=scan.CHIP_DAYS, offline=True) if scan.chips else {}
    except Exception:
        cm = {}
    uni = []
    for code, df in data.items():
        try:
            core = scan._analyse_core(code, df, drop_last=False)
            if not core:
                continue
            d = scan._lower(df.tail(70).reset_index(drop=True))
            high, low, close = d["high"].astype(float), d["low"].astype(float), d["close"].astype(float)
            vol = d["volume"].astype(float)
            if len(close) < 20:                       # 唯一淘汰：資料不足
                continue
            adr = core.get("adr_pct")
            turn = core.get("turnover_60d")
            atr22 = scan._atr_last(scan._lower(df.tail(180).reset_index(drop=True)), scan.CHAND_LEN)
            avg_vol20 = float(vol.tail(20).mean())            # 股數
            vl = core.get("vol_lots") or 0
            m = mm.get(code, {}); lots = m.get("day_trade_lots")
            dtp = (round(lots / vl * 100, 1) if (lots and vl > 0 and lots / vl * 100 <= 100) else None)
            pscore = (_sq(adr, 3, 8) * .4 + _sq(dtp, 10, 40) * .35 + _sq((turn or 0) / 1e8, 1, 20) * .25)
            st = elig.status(code, eligd)
            crec = cm.get(code, {}) if isinstance(cm.get(code), dict) else {}
            pc = round(float(close.iloc[-1]), 2)
            uni.append({
                "code": code, "name": name_of.get(code, code), "industry": ind_of.get(code, ""),
                "prev_close": pc,
                "prev_high": round(float(high.iloc[-1]), 2), "prev_low": round(float(low.iloc[-1]), 2),
                "recent_high20": round(float(high.tail(20).max()), 2),
                "recent_low20": round(float(low.tail(20).min()), 2),
                "recent_high60": round(float(high.tail(60).max()), 2),
                "recent_low60": round(float(low.tail(60).min()), 2),
                "atr22": _r(atr22), "adr_pct": adr, "avg_vol20": avg_vol20,
                "day_trade_pct": dtp, "turnover_60d": turn,
                "limit_up": round(pc * 1.1, 2), "limit_down": round(pc * 0.9, 2),
                "consec_buy_days": crec.get("consec_buy_days") or 0,
                "attention": st["attention"], "can_daytrade": st["can_daytrade"],
                "pscore": round(pscore, 3),
            })
        except Exception:
            continue
    uni.sort(key=lambda x: x["pscore"], reverse=True)
    return uni[:POOL_MAX]


build_pool = build_universe          # 向後相容別名


# ── 分層輪掃選取 ＋ 動態熱股 ─────────────────────────────────────────────────
def _select_scan_codes(universe: list[dict], acc: dict):
    """核心(pool_score top-N ∪ 動態熱股)每輪掃；長尾跨步切片，TIER2_SLICES 輪掃完全市場。"""
    seed = [u["code"] for u in universe[:TIER1_SEED]]
    hot = list(acc.get("hot", {}).keys())
    tier1 = list(dict.fromkeys(seed + hot))
    rest = [u["code"] for u in universe[TIER1_SEED:]]
    slices = max(1, TIER2_SLICES)
    rot = acc.get("rot", 0) % slices
    tier2 = rest[rot::slices]                          # 跨步切片：slices 輪內每檔剛好一次
    acc["rot"] = (rot + 1) % slices
    codes = list(dict.fromkeys(tier1 + tier2))
    return codes, {"universe_n": len(universe), "tier1_n": len(tier1), "hot_n": len(hot),
                   "swept": len(codes), "rot": rot, "slices": slices}


def _update_hot(acc: dict, ubycode: dict, feats: dict, now: datetime) -> None:
    """盤中動態抓新熱股：爆量/大漲跌/漲跌停敲門 → 進 hot 集(當日高頻盯)，滿 HOT_MAX 留最強。"""
    hot = acc.setdefault("hot", {})
    for code, f in feats.items():
        u = ubycode.get(code)
        vr = f.get("vol_ratio") or 0
        chg = abs(f.get("chg_pct") or 0)
        px = f.get("price")
        near = False
        if u and px and u.get("limit_up") and u.get("limit_down"):
            near = (abs(px - u["limit_up"]) / u["limit_up"] * 100 < HOT_NEAR_LIMIT
                    or abs(px - u["limit_down"]) / u["limit_down"] * 100 < HOT_NEAR_LIMIT)
        if vr >= HOT_VR or chg >= HOT_CHG or near:
            strength = round(max(vr / HOT_VR, chg / HOT_CHG, 1.2 if near else 0), 2)
            if code not in hot:
                hot[code] = {"since": now.strftime("%H:%M"), "score": strength}
            else:
                hot[code]["score"] = max(hot[code]["score"], strength)
    if len(hot) > HOT_MAX:
        keep = sorted(hot.items(), key=lambda kv: kv[1]["score"], reverse=True)[:HOT_MAX]
        acc["hot"] = dict(keep)


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


def detect_signals(pool: list[dict], acc: dict, regime: dict, quotes: dict, now: datetime):
    """回 (cands, feats)：feats[code]=本輪盤中特徵，供動態熱股判定不重算。"""
    cands = []
    feats = {}
    pool_by = {p["code"]: p for p in pool}
    reg = regime["label"]
    for code, q in quotes.items():
        p = pool_by.get(code)
        if p is None or q.get("price") is None:
            continue
        a = acc["per_code"].setdefault(code, {})
        feat = _update_acc(a, q, now, p.get("avg_vol20") or 0)
        feats[code] = feat
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
                "vwap": vwap, "vwap_dev": feat["vwap_dev"], "vol_ratio": feat["vol_ratio"], "ob_ratio": feat["ob_ratio"],
                "vol_type": feat["vol_type"], "pull_order": feat["pull_order"], "divergence": feat["divergence"],
                "confirmed": confirmed, "orb_break": setup.startswith("開盤"),
                "break_atr": round(abs(price - p["recent_high20" if long else "recent_low20"]) / atr, 2),
                "rs": None, "mtf": None, "inst": _sq(p.get("consec_buy_days"), 0, 5),
                "attention": p.get("attention"), "can_daytrade": p.get("can_daytrade"),
                "is_etf": code.startswith("00"),
            })
    return cands, feats


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
    acc = _load_intraday(today)
    codes, tier_meta = _select_scan_codes(pool, acc)          # 分層輪掃：核心∪熱股 + 當前長尾片
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
    # index VWAP 累積(粗略：以指數價×1 當量)
    if index_quote and index_quote.get("price"):
        acc["index"]["vwap_num"] = acc["index"].get("vwap_num", 0.0) + index_quote["price"]
        acc["index"]["vwap_den"] = acc["index"].get("vwap_den", 0.0) + 1
    regime = _regime(index_quote or {}, acc["index"])
    idx_chg = (index_quote or {}).get("chg_pct") or 0
    tod = _tod(now)
    minutes_to_close = SESSION_END - _now_min(now)

    bstats = book_stats if book_stats is not None else _book_stats()
    wts = weights if weights is not None else _fit_weights()
    cands, feats = detect_signals(pool, acc, regime, quotes, now)
    _update_hot(acc, {u["code"]: u for u in pool}, feats, now)   # 動態抓盤中新熱股
    signals, filtered = [], []
    for c in cands:
        c["rs"] = _r((c["chg"] or 0) - idx_chg)
        m = dict(c)
        m["mkt_align"] = _mkt_align(c["dir"], regime["label"])
        m["disposition"] = not c.get("can_daytrade", True)
        m["exec_ok"] = _exec_ok(quotes.get(c["code"]), c["dir"], cfg)
        ctx = {"regime": regime["label"], "tod": tod, "streak": _streak(),
               "minutes_to_close": minutes_to_close}
        v = brain.verdict(m, c["dir"], c["setup"], ctx, bstats, cfg, wts)
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
            _record_book(c, today, regime["label"], tod)   # 前向追蹤
            pushed.add(key)
        _save_pushed(today, pushed)

    # 前向追蹤：更新未平倉出場、記錄被擋單(A/B 驗證)
    try:
        _update_book_outcomes(quotes, today, out_market_open := scan._market_open_now())
        _record_blocked(filtered, today)
    except Exception:
        pass

    ranks = _build_ranks(pool, acc, quotes)
    # 🔥 盤中新熱股列（hot 集 ∩ 本輪有報價者，附現況）
    ubycode = {u["code"]: u for u in pool}
    hot_list = []
    for code, h in (acc.get("hot") or {}).items():
        q = quotes.get(code); u = ubycode.get(code)
        hot_list.append({"code": code, "name": (u or {}).get("name", code),
                         "since": h.get("since"), "score": h.get("score"),
                         "chg": (q or {}).get("chg_pct"),
                         "vol_ratio": (feats.get(code) or {}).get("vol_ratio")})
    hot_list.sort(key=lambda x: x.get("score") or 0, reverse=True)
    out = {
        "generated_at": now.isoformat(timespec="seconds"), "market_open": scan._market_open_now(),
        "pool_n": tier_meta["swept"], "regime": regime, "circuit_breaker": cb,
        "signals": signals, "filtered": filtered, "ranks": ranks, "hot_list": hot_list,
        "book_summary": _book_summary(), "daily_report": _load_reports(today), "tod": tod,
        **tier_meta,
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


def _record_book(c, today, regime="中性", tod="盤中"):
    b = _load_book()
    b["updated"] = today
    if any(t.get("code") == c["code"] and t.get("dir") == c["dir"]
           and t.get("date") == today and t.get("status") != "blocked" for t in b.get("trades", [])):
        return
    b.setdefault("trades", []).append({
        "date": today, "code": c["code"], "name": c["name"], "dir": c["dir"], "setup": c["setup"],
        "regime": regime, "tod": tod,
        "entry": c["entry"], "stop": c["stop"], "tp": c["targets"], "ts": today + "T" + c["ts"],
        "pred_p": c["brain"]["p"], "pred_ev": c["brain"]["ev_net_R"], "grade": c["grade"],
        "factors": c["brain"].get("factors") or {}, "status": "open", "result": None,
        "post_h": c["price"], "post_l": c["price"],
    })
    _save_book(b)


def _load_book() -> dict:
    try:
        return json.loads(BOOK.read_text(encoding="utf-8"))
    except Exception:
        return {"trades": []}


def _save_book(b: dict) -> None:
    try:
        tmp = BOOK.with_suffix(".tmp")
        tmp.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, BOOK)
    except Exception:
        pass


def _update_book_outcomes(quotes: dict, today: str, market_open: bool) -> None:
    """前向追蹤：更新未平倉訊號的訊號後高低，判先碰停損=loss/先碰tp1=win；收盤未達→收盤平倉結算 R。
    停損優先(當沖 whipsaw 保守假設)。blocked(被擋)單同法評估供 A/B 驗證。"""
    b = _load_book()
    changed = False
    for t in b.get("trades", []):
        if t.get("result") or t.get("date") != today:
            continue
        long = t["dir"] == "long"
        entry, stop = t["entry"], t["stop"]
        tp1 = t["tp"][0] if isinstance(t.get("tp"), list) else t.get("tp")
        risk = abs(entry - stop) or (entry * 0.01)
        q = quotes.get(t["code"]); px = q.get("price") if q else None
        if px is not None:
            t["post_h"] = max(t.get("post_h", px), px)
            t["post_l"] = min(t.get("post_l", px), px)
            changed = True
        ph, pl = t.get("post_h", entry), t.get("post_l", entry)
        if long:
            if pl <= stop:
                t.update(result="loss", ret_R=-1.0, exit=stop, exit_reason="停損"); changed = True
            elif tp1 and ph >= tp1:
                t.update(result="win", ret_R=round((tp1 - entry) / risk, 2), exit=tp1, exit_reason="停利tp1"); changed = True
        else:
            if ph >= stop:
                t.update(result="loss", ret_R=-1.0, exit=stop, exit_reason="停損"); changed = True
            elif tp1 and pl <= tp1:
                t.update(result="win", ret_R=round((entry - tp1) / risk, 2), exit=tp1, exit_reason="停利tp1"); changed = True
        if not t.get("result") and not market_open and px is not None:
            won = (px > entry) if long else (px < entry)
            t.update(result="win" if won else "loss",
                     ret_R=round(((px - entry) if long else (entry - px)) / risk, 2),
                     exit=px, exit_reason="收盤平倉"); changed = True
    if changed:
        _save_book(b)


def _record_blocked(filtered: list, today: str) -> None:
    """記錄被大腦擋下的單(A/B 追蹤)：事後同法評估，證明擋對了。"""
    if not filtered:
        return
    b = _load_book()
    have = {(t["code"], t["dir"]) for t in b.get("trades", []) if t.get("date") == today}
    for c in filtered[:5]:
        if (c["code"], c["dir"]) in have:
            continue
        b.setdefault("trades", []).append({
            "date": today, "code": c["code"], "name": c["name"], "dir": c["dir"], "setup": c.get("setup"),
            "entry": c["entry"], "stop": c["stop"], "tp": c["targets"], "ts": today + "T" + c.get("ts", ""),
            "status": "blocked", "result": None, "post_h": c["price"], "post_l": c["price"],
            "pred_p": c["brain"].get("p"),
        })
        have.add((c["code"], c["dir"]))
    b["updated"] = today
    _save_book(b)


def _book_stats() -> dict:
    """給大腦 win_prob 的分層經驗勝率：setup 與 setup|regime|tod 兩層 + 各 setup 平均賺R。"""
    b = _load_book()
    fin = [t for t in b.get("trades", []) if t.get("status") != "blocked" and t.get("result") in ("win", "loss")]
    agg = {}
    def _acc(key, t):
        r = agg.setdefault(key, {"n": 0, "win": 0, "winR": []})
        r["n"] += 1
        if t["result"] == "win":
            r["win"] += 1; r["winR"].append(t.get("ret_R", 1) or 1)
    for t in fin:
        _acc(t.get("setup", "?"), t)
        _acc(f"{t.get('setup','?')}|{t.get('regime','中性')}|{t.get('tod','盤中')}", t)
    out = {}
    for k, r in agg.items():
        out[k] = {"n": r["n"], "winrate": round(r["win"] / r["n"], 3),
                  "avg_win_R": round(sum(r["winR"]) / len(r["winR"]), 2) if r["winR"] else 1.5}
    return out


def _fit_weights():
    try:
        return brain.fit_logistic(_load_book().get("trades", []))
    except Exception:
        return None


def _book_summary() -> dict:
    b = _load_book()
    trades = b.get("trades", [])
    fin = [t for t in trades if t.get("status") != "blocked" and t.get("result") in ("win", "loss")]
    blocked = [t for t in trades if t.get("status") == "blocked" and t.get("result") in ("win", "loss")]
    n = len(fin)
    wr = round(sum(1 for t in fin if t["result"] == "win") / n, 3) if n else None
    avgR = round(sum(t.get("ret_R", 0) or 0 for t in fin) / n, 2) if n else None
    preds = [t.get("pred_p") for t in fin if t.get("pred_p") is not None]
    avg_pred = round(sum(preds) / len(preds), 3) if preds else None
    # 各 setup
    by = {}
    for t in fin:
        s = t.get("setup", "?"); r = by.setdefault(s, {"n": 0, "win": 0})
        r["n"] += 1; r["win"] += 1 if t["result"] == "win" else 0
    by_setup = {s: {"n": r["n"], "winrate": round(r["win"] / r["n"], 2)} for s, r in by.items()}
    # A/B：被擋單事後沒賺的比例
    blk_noprofit = sum(1 for t in blocked if (t.get("ret_R") or 0) <= 0)
    learning = _fit_weights()
    return {"n": n, "winrate": wr, "avg_R": avgR, "avg_pred_p": avg_pred,
            "brain_hit": wr, "calib_gap": round((avg_pred - wr), 3) if (avg_pred and wr is not None) else None,
            "by_setup": by_setup, "blocked_n": len(blocked), "blocked_noprofit": blk_noprofit,
            "learning": ("logistic(n=%d)" % n) if learning else "累積中(啟發式)"}


def _build_ranks(pool, acc, quotes) -> dict:
    rows = []
    pby = {x["code"]: x for x in pool}
    for code, q in quotes.items():
        a = acc["per_code"].get(code, {})
        p = pby.get(code)
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


REPORTS = HERE / "daytrade_reports.json"


def _load_reports(today: str) -> dict:
    try:
        r = json.loads(REPORTS.read_text(encoding="utf-8"))
        return {"pre": r.get("pre"), "post": r.get("post")} if r.get("date") == today else {"pre": None, "post": None}
    except Exception:
        return {"pre": None, "post": None}


def _save_reports(today: str, **kw) -> None:
    r = {"date": today}
    try:
        old = json.loads(REPORTS.read_text(encoding="utf-8"))
        if old.get("date") == today:
            r.update({k: old.get(k) for k in ("pre", "post")})
    except Exception:
        pass
    r.update(kw)
    try:
        tmp = REPORTS.with_suffix(".tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, REPORTS)
    except Exception:
        pass


def premarket_report(pool: list[dict], push: bool = True) -> str:
    """盤前(08:45)：今日當沖池 top10 + 重點位階 + 預期環境。"""
    today = date.today().isoformat()
    top = pool[:10]
    lines = ["📋 今日當沖池 top10（依活躍度）："]
    for p in top:
        lines.append(f"  {p['code']} {p['name'][:6]} · ADR{p.get('adr_pct')}% · 昨高{p.get('recent_high20')} 昨低{p.get('recent_low20')}")
    lines.append("重點：突破昨高爆量做多、跌破昨低爆量做空；開盤15分ORB定區間。當日平倉、嚴設停損。")
    txt = "\n".join(lines)
    _save_reports(today, pre=txt)
    if push:
        try:
            import notify
            notify.broadcast(txt, title="盤前當沖準備", priority="default")
        except Exception:
            pass
    return txt


def postmarket_report(push: bool = True) -> str:
    """盤後(13:35)：今日戰績總結 + 大腦命中率 + A/B 擋單驗證。"""
    today = date.today().isoformat()
    # 收盤先把未平倉的用最後結果結算(無 quote → 略過，靠盤中最後一輪已結)
    s = _book_summary()
    wr = f"{s['winrate']*100:.0f}%" if s.get("winrate") is not None else "—"
    txt = (f"📊 今日當沖總結：{s.get('n',0)} 單結算 · 勝率 {wr} · 平均 {s.get('avg_R')}R\n"
           f"大腦命中 {wr} · 自學 {s.get('learning')}\n"
           f"擋掉 {s.get('blocked_n',0)} 單，{s.get('blocked_noprofit',0)} 單事後確實沒賺（擋對了）\n"
           f"明日再戰，嚴守紀律。")
    _save_reports(today, post=txt)
    if push:
        try:
            import notify
            notify.broadcast(txt, title="盤後當沖總結", priority="default")
        except Exception:
            pass
    return txt


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
    if "--pool" in sys.argv or "--universe" in sys.argv:
        pl = build_universe()
        print(f"[daytrade] 全市場基準 {len(pl)} 檔；核心前10：")
        for p in pl[:10]:
            print(f"  {p['code']} {p['name'][:6]:6} adr{p['adr_pct']} 當沖比{p['day_trade_pct']} {p['pscore']}")
        raise SystemExit(0)
    pool = build_universe()
    out = scan_live(pool, push=("--push" in sys.argv))
    print(f"[daytrade] 全市場{out.get('universe_n')} 本輪掃{out.get('swept')} 核心{out.get('tier1_n')}(熱{out.get('hot_n')}) "
          f"regime={out['regime']['label']} 訊號{len(out['signals'])} 擋{len(out['filtered'])}")
    for s in out["signals"][:8]:
        b = s["brain"]
        print(f"  [{s['grade']}] {s['dir']} {s['code']} {s['name'][:6]} 進{s['entry']} 損{s['stop']} "
              f"勝率{b['p']} 淨EV{b['ev_net_R']} · {b['review']}")
