# -*- coding: utf-8 -*-
"""
analyst.py — 金融分析團隊：四維度選股分析器

四個視角，四位老師的邏輯：
  朱家泓  — KD 技術三招（趨勢 × 位置 × 指標）
  阿斯匹靈 — 投信作帳選股法（三大法人籌碼三層濾網）
  權證小哥 — K棒主力動向（爆量光頭大紅K + 高檔掉手線警示）
  張捷    — 產業強弱評估（趨勢強度 + 相對大盤）

每個維度輸出 0-100 分 + 文字判讀，最後給綜合評分與建議。

用法：
  python analyst.py 2330
  python analyst.py 2330 6669 3533
  python analyst.py --scan            # 掃精選宇宙，輸出四維共振候選股
  python analyst.py --push 2330       # 分析後推 Telegram
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
QS = HERE.parent
ROOT = QS.parent

sys.path.insert(0, str(QS))
sys.path.insert(0, str(HERE))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 複用 scan.py 的資料層和指標函數 ───────────────────────────────────────
import scan as _scan

try:
    import chips as _chips
except Exception:
    _chips = None
try:
    import margin as _margin_mod
except Exception:
    _margin_mod = None
try:
    import tdcc as _tdcc_mod
except Exception:
    _tdcc_mod = None
try:
    from notify import broadcast as _broadcast
except Exception:
    _broadcast = None

CHIP_DAYS = 10


# ── analyst 自足指標（不依賴 scan.py，避免耦合核心掃描檔）────────────────────
# 這兩支型態指標為 analyst 專用，實作於此以保持本模組自足；scan.py 完全不需改。
# 輸入 df 皆為「小寫欄位」的 OHLCV DataFrame（呼叫端已 _scan._lower 處理）。
def _kd_last(df: pd.DataFrame, n: int = 9,
             k_period: int = 3, d_period: int = 3) -> tuple:
    """台股標準 KD 隨機指標 (9,3,3)，朱家泓金叉/死叉判定。

    RSV = (C − 最低價_n) / (最高價_n − 最低價_n) × 100
    K   = 前K × (1−1/k_period) + RSV × (1/k_period)   初始 50
    D   = 前D × (1−1/d_period) + K   × (1/d_period)   初始 50
    （9,3,3 → k_period=d_period=3，權重 1/3，即台灣券商軟體通用平滑法）

    回傳 (K, D, golden, death)：
      golden = 今日 K 由下上穿 D（黃金交叉）
      death  = 今日 K 由上下穿 D（死亡交叉）
    資料不足回 (None, None, False, False)。
    """
    if df is None or len(df) < n + 2:
        return None, None, False, False
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    rng = (hh - ll).replace(0, np.nan)
    rsv = ((close - ll) / rng * 100).clip(0, 100).fillna(50.0)

    a_k = 1.0 / k_period
    a_d = 1.0 / d_period
    k = d = 50.0
    prev_k = prev_d = None
    started = False
    for i in range(len(df)):
        if pd.isna(hh.iloc[i]) or pd.isna(ll.iloc[i]):
            continue
        prev_k, prev_d = k, d
        k = k * (1 - a_k) + float(rsv.iloc[i]) * a_k
        d = d * (1 - a_d) + k * a_d
        started = True
    if not started or prev_k is None:
        return None, None, False, False
    golden = bool(prev_k <= prev_d and k > d)
    death = bool(prev_k >= prev_d and k < d)
    return round(k, 2), round(d, 2), golden, death


def _bald_red_k(df: pd.DataFrame, gain_thr: float = 0.05, vol_mult: float = 2.0,
                upper_shadow_max: float = 0.15, base_days: int = 15,
                base_range_max: float = 0.20) -> bool:
    """橫盤爆量光頭大紅K（權證小哥「主力發車」型態）。全部條件成立才 True：
      ① 今日漲幅 ≥ 5%（相對前一日收盤）
      ② 今量 ≥ 20日均量 × 2（爆量）
      ③ 上影線小：(high−close)/(high−low) < 0.15（收在高點=光頭）
      ④ 前15日橫盤：前15日收盤（不含今日）高低差 < 20%
    「今日」= df 最後一列（呼叫端已裁成已收盤序列）。資料不足回 False。
    """
    if df is None or len(df) < 22:
        return False
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    c = float(close.iloc[-1])
    pc = float(close.iloc[-2])
    h = float(high.iloc[-1])
    l = float(low.iloc[-1])
    if pc <= 0 or h <= l:
        return False

    # ① 今日漲幅 ≥ 5%
    if (c - pc) / pc < gain_thr:
        return False
    # ③ 上影線小（光頭）
    if (h - c) / (h - l) >= upper_shadow_max:
        return False
    # ② 爆量（今量 ≥ 20日均量 ×2）
    avg20 = float(vol.iloc[-21:-1].mean())
    if not (avg20 > 0 and float(vol.iloc[-1]) >= avg20 * vol_mult):
        return False
    # ④ 前15日橫盤（不含今日，收盤高低差 < 20%）
    base = close.iloc[-(base_days + 1):-1]
    lo = float(base.min())
    if lo <= 0 or (float(base.max()) - lo) / lo >= base_range_max:
        return False
    return True


# ── 資料載入 ───────────────────────────────────────────────────────────────
def _load_ohlcv(code: str) -> pd.DataFrame | None:
    """嘗試 yfinance → 快取，回傳 OHLCV DataFrame（大寫欄位，日線）。"""
    for suf in (".TW", ".TWO"):
        # retries=1：互動查詢限縮 yfinance 重試次數，確保單檔 <10s（含 timeout=30 內建）
        res = _scan._bulk_yf([code], suf, intraday=False, retries=1)
        if res.get(code) is not None and len(res[code]) >= 30:
            return res[code]
    df = _scan._read_cache(code)
    return df if df is not None and len(df) >= 30 else None


def _load_chips_rec(code: str) -> dict | None:
    if _chips is None:
        return None
    try:
        # offline=True：只讀本地快取，絕不即時探網（比照 query.py 教訓，避免卡死）
        m = _chips.load_chips([code], days=CHIP_DAYS, offline=True)
        return m.get(code)
    except Exception:
        return None


def _load_margin_rec(code: str) -> dict | None:
    if _margin_mod is None:
        return None
    try:
        m = _margin_mod.load_margin([code], offline=True)   # 只讀快取，不探網
        return m.get(code)
    except Exception:
        return None


def _load_tdcc_rec(code: str) -> dict | None:
    if _tdcc_mod is None:
        return None
    try:
        m = _tdcc_mod.load_tdcc([code], offline=True)   # 只讀快取，不探 22 日網
        return m.get(code)
    except Exception:
        return None


# ── 視角 1：朱家泓（KD 技術三招）─────────────────────────────────────────
def _view_zhujiahe(code: str, df: pd.DataFrame) -> dict:
    """
    招式一：KD 黃金交叉（趨勢起點）
    招式二：起漲任意門（趨勢 + 位置 + KD）
    招式三：KD 鈍化判斷（>80守均線；<20補空）
    """
    closed = _scan._lower(df.tail(180).reset_index(drop=True))
    if len(closed) > 22:
        closed = closed.iloc[:-1]   # 用已收盤序列（與 scan.py 邏輯一致）

    kd_k, kd_d, golden, death = _kd_last(closed)
    st_today, _ = _scan._st_dirs(closed)
    ma = _scan.calc_ma(closed, periods=[20, 60])
    ma20 = ma["ma"].get(20)
    ma60 = ma["ma"].get(60)
    rsi_val = _scan.calc_rsi(closed, period=14).get("rsi")
    close_last = float(closed["close"].iloc[-1])

    above20 = ma20 is not None and close_last > ma20
    above60 = ma60 is not None and close_last > ma60
    st_up = (st_today == "UP")

    # 評分
    score = 0
    notes: list[str] = []

    if st_up:
        score += 30
        notes.append("✅ SuperTrend 多頭趨勢")
    else:
        notes.append("❌ SuperTrend 空頭/無趨勢")

    if golden:
        score += 30
        notes.append(f"✅ KD 黃金交叉（K={kd_k:.0f}/D={kd_d:.0f}）")
    elif kd_k is not None and kd_d is not None:
        if kd_k > kd_d:
            score += 10
            notes.append(f"⚠ KD 多排列（K={kd_k:.0f}/D={kd_d:.0f}，尚未交叉）")
        elif death:
            notes.append(f"❌ KD 死亡交叉（K={kd_k:.0f}/D={kd_d:.0f}）")
        else:
            notes.append(f"— KD 空排列（K={kd_k:.0f}/D={kd_d:.0f}）")

    if above20:
        score += 20
        notes.append("✅ 站上 MA20")
    else:
        notes.append("❌ 跌破 MA20")

    if above60:
        score += 10
        notes.append("✅ 站上 MA60")
    else:
        notes.append("— 尚未突破 MA60")

    if rsi_val is not None:
        if 50 <= rsi_val <= 75:
            score += 10
            notes.append(f"✅ RSI {rsi_val:.0f}（動能健康區）")
        elif rsi_val > 75:
            notes.append(f"⚠ RSI {rsi_val:.0f}（過熱，KD鈍化區，改守均線）")
        elif rsi_val < 30:
            notes.append(f"⚠ RSI {rsi_val:.0f}（超賣，可能低檔鈍化）")
        else:
            score += 5
            notes.append(f"— RSI {rsi_val:.0f}")

    verdict = ("強力做多" if score >= 70 else
               "技術偏多" if score >= 50 else
               "中性觀望" if score >= 30 else "技術偏空")

    return {"view": "朱家泓 KD技術三招", "score": min(score, 100),
            "verdict": verdict, "notes": notes,
            "kd_k": kd_k, "kd_d": kd_d, "kd_golden": golden, "st": st_today}


# ── 視角 2：阿斯匹靈（投信作帳選股法）────────────────────────────────────
def _view_aspirin(code: str, chips_rec: dict | None,
                  margin_rec: dict | None, tdcc_rec: dict | None) -> dict:
    """
    三層濾網：
      L1：投信持股 3-5%（近10日積極買超）
      L2：外資同向（至少同向）
      L3：融資減少 + 融券增加 + 集保散戶流出
    進場：10MA；停損：月線；部位：單檔10%
    """
    score = 0
    notes: list[str] = []

    # L1：投信連買
    if chips_rec is not None:
        tc = chips_rec.get("trust_consec_days") or 0
        ts = chips_rec.get("trust_net_sum") or 0
        tn = chips_rec.get("trust_net") or 0
        if tc >= 7:
            score += 40
            notes.append(f"✅ 投信單獨連買 {tc} 日（強力作帳訊號）")
        elif tc >= 5:
            score += 30
            notes.append(f"✅ 投信連買 {tc} 日（作帳確認中）")
        elif tc >= 3:
            score += 20
            notes.append(f"⚠ 投信連買 {tc} 日（達阿斯匹靈門檻，觀察中）")
        elif tn > 0:
            score += 5
            notes.append(f"— 投信今日買超 {tn:+,} 張（尚未連買）")
        else:
            notes.append(f"❌ 投信未連買（連買 {tc} 日，今日 {tn:+,} 張）")

        # L2：外資同向
        fn = chips_rec.get("foreign_net") or 0
        cd = chips_rec.get("consec_buy_days") or 0
        if fn > 0 and cd >= 2:
            score += 30
            notes.append(f"✅ 外資同向連買 {cd} 日（+{fn:,} 張）")
        elif fn > 0:
            score += 15
            notes.append(f"⚠ 外資今日買超 {fn:+,} 張（連買 {cd} 日）")
        else:
            notes.append(f"❌ 外資未同向（今日 {fn:+,} 張）")
    else:
        notes.append("— 三大法人資料不可用")

    # L3a：融資減少
    if margin_rec is not None:
        mc = margin_rec.get("margin_chg") or 0
        mb = margin_rec.get("margin_balance") or 0
        if mc < 0:
            score += 15
            notes.append(f"✅ 融資減少 {mc:+,} 張（籌碼乾淨）")
        elif mc > 0:
            notes.append(f"❌ 融資增加 {mc:+,} 張（散戶追進，謹慎）")
        else:
            notes.append(f"— 融資持平（餘額 {mb:,} 張）")
    else:
        notes.append("— 融資券資料不可用")

    # L3b：集保散戶流出
    if tdcc_rec is not None:
        pct = tdcc_rec.get("small_chg_pct") or 0
        if tdcc_rec.get("retail_exit"):
            score += 15
            notes.append(f"✅ 集保散戶流出 {abs(pct):.1f}%（主力吸籌訊號）")
        elif tdcc_rec.get("retail_surge"):
            notes.append(f"⚠ 集保散戶大量進場 +{pct:.1f}%（過熱警示）")
        else:
            notes.append(f"— 集保散戶變化 {pct:+.1f}%（週更新）")
    else:
        notes.append("— 集保戶數資料不可用")

    verdict = ("高確信做多" if score >= 75 else
               "籌碼偏多" if score >= 50 else
               "籌碼中性" if score >= 25 else "籌碼偏空")

    return {"view": "阿斯匹靈 投信作帳法", "score": min(score, 100),
            "verdict": verdict, "notes": notes}


# ── 視角 3：權證小哥（K棒主力動向）───────────────────────────────────────
def _view_warrant(code: str, df: pd.DataFrame) -> dict:
    """
    主力追蹤三招：
    ① 光頭大紅棒：橫盤爆量 5%+ 光頭 → 主力發車
    ② 高檔掉手線：實體小+下影長+高點出現 → 主力出貨警示
    ③ 量能分析：今日相對量能 vs 20日均量
    """
    closed = _scan._lower(df.tail(180).reset_index(drop=True))
    if len(closed) > 22:
        closed = closed.iloc[:-1]

    score = 0
    notes: list[str] = []
    warnings: list[str] = []

    # 光頭大紅K
    bald_red = _bald_red_k(closed)
    if bald_red:
        score += 50
        notes.append("⚡ 爆量光頭大紅K（橫盤發車訊號，主力積極拉抬）")

    # 量能分析
    vol = closed["volume"].astype(float)
    close = closed["close"].astype(float)
    avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) >= 22 else None
    cur_vol = float(vol.iloc[-1])
    relvol = round(cur_vol / avg_vol, 2) if avg_vol and avg_vol > 0 else None

    if relvol is not None:
        if relvol >= 3.0:
            score += 30
            notes.append(f"✅ 極強量能 {relvol:.1f}x（主力積極介入）")
        elif relvol >= 2.0:
            score += 20
            notes.append(f"✅ 放量 {relvol:.1f}x（量能確認）")
        elif relvol >= 1.5:
            score += 10
            notes.append(f"⚠ 量能 {relvol:.1f}x（略增，觀察）")
        else:
            notes.append(f"— 量能 {relvol:.1f}x（縮量，無主力介入）")

    # 今日漲幅
    c_now = float(close.iloc[-1])
    c_prev = float(close.iloc[-2]) if len(close) >= 2 else c_now
    chg = (c_now - c_prev) / c_prev * 100 if c_prev else 0
    if chg >= 5:
        score += 20
        notes.append(f"✅ 漲幅 {chg:.1f}%（主力強拉特徵）")
    elif chg >= 2:
        score += 10
        notes.append(f"— 漲幅 {chg:.1f}%")
    elif chg <= -3:
        warnings.append(f"⚠ 跌幅 {chg:.1f}%（注意賣壓）")

    # 高檔掉手線警示（實體小+下影長+出現在相對高點）
    if len(closed) >= 5:
        h = float(closed["high"].iloc[-1])
        l = float(closed["low"].iloc[-1])
        c = float(closed["close"].iloc[-1])
        o = float(closed["open"].iloc[-1])
        hl = h - l
        body = abs(c - o)
        lower_shadow = min(c, o) - l
        recent_high = float(close.tail(20).max())
        is_near_high = c >= recent_high * 0.95
        if (hl > 0 and body / hl < 0.25 and lower_shadow / hl > 0.5
                and is_near_high and c > c_prev * 1.0):
            score = max(0, score - 20)
            warnings.append("⚠ 高檔掉手線（主力出貨警示，考慮減碼）")

    all_notes = notes + warnings
    if not all_notes:
        all_notes = ["— 無明顯K棒主力訊號"]

    verdict = ("主力強力介入" if score >= 60 else
               "量能偏多" if score >= 35 else
               "無明顯主力" if score >= 15 else "主力缺席/出貨")

    return {"view": "權證小哥 K棒主力", "score": min(score, 100),
            "verdict": verdict, "notes": all_notes, "relvol": relvol,
            "bald_red_k": bald_red}


# ── 視角 4：張捷（產業強弱評估）──────────────────────────────────────────
def _view_zhang(code: str, df: pd.DataFrame, industry: str = "未分類") -> dict:
    """
    張捷選股邏輯（量化可得的替代指標）：
    - 趨勢強度（ADX > 25 = 有趨勢）→ 代替「產業還在成長嗎」
    - 相對大盤強度（vs 0050）→ 代替「台灣供應鏈主導地位」
    - 站上年線（240日MA）→ 「月盈則虧」刪去法反面
    - 60日新高 → 「伺服器比重季季上升」的量化替代
    張捷方法核心有部分需人工判斷（產業比重/毛利率），此處附提示。
    """
    closed = _scan._lower(df.tail(280).reset_index(drop=True))
    if len(closed) > 22:
        closed = closed.iloc[:-1]

    score = 0
    notes: list[str] = []

    # ADX 趨勢強度
    adx = _scan._adx_last(closed)
    if adx is not None:
        if adx >= 35:
            score += 30
            notes.append(f"✅ ADX={adx:.0f}：趨勢強勁（代表產業正向加速）")
        elif adx >= 25:
            score += 20
            notes.append(f"✅ ADX={adx:.0f}：有趨勢（符合張捷「產業還在成長」條件）")
        elif adx >= 15:
            score += 10
            notes.append(f"⚠ ADX={adx:.0f}：弱趨勢（觀察是否開始加速）")
        else:
            notes.append(f"❌ ADX={adx:.0f}：無趨勢（張捷：刪去候選）")

    # 年線（240日）
    close_s = closed["close"].astype(float)
    yearline = float(close_s.rolling(240).mean().iloc[-1]) if len(close_s) >= 240 else None
    price = float(close_s.iloc[-1])
    if yearline is not None:
        if price > yearline * 1.1:
            score += 25
            notes.append(f"✅ 站上年線 +{(price/yearline-1)*100:.0f}%（長線多頭格局）")
        elif price > yearline:
            score += 15
            notes.append(f"✅ 站上年線（長線支撐）")
        else:
            notes.append(f"❌ 跌破年線（張捷：月盈則虧，列入刪去）")

    # 60日新高（動能擴張）
    hi60 = bool(price >= float(close_s.tail(60).max())) if len(close_s) >= 20 else False
    if hi60:
        score += 25
        notes.append("✅ 60日新高（比重持續上升的量化替代訊號）")
    else:
        gap_to_hi = (float(close_s.tail(60).max()) - price) / price * 100
        notes.append(f"— 距60日高點尚差 {gap_to_hi:.1f}%")

    # 相對大盤（粗略用 mom5 替代）
    if len(close_s) >= 6:
        mom5 = (price - float(close_s.iloc[-6])) / float(close_s.iloc[-6]) * 100
        if mom5 >= 5:
            score += 20
            notes.append(f"✅ 近5日漲幅 {mom5:+.1f}%（相對強勢）")
        elif mom5 >= 0:
            notes.append(f"— 近5日漲幅 {mom5:+.1f}%")
        else:
            notes.append(f"⚠ 近5日跌幅 {mom5:+.1f}%（相對弱勢）")

    # 張捷人工判斷提示
    notes.append(f"📌 人工補充（張捷法）：確認 {industry} 產業比重 ≥50%、毛利率 ≥30%、白牌客戶比重")

    verdict = ("產業強勢領漲" if score >= 75 else
               "產業趨勢向上" if score >= 50 else
               "中性/觀察" if score >= 25 else "產業趨勢不明")

    return {"view": "張捷 產業強弱", "score": min(score, 100),
            "verdict": verdict, "notes": notes, "industry": industry}


# ── 綜合分析 ───────────────────────────────────────────────────────────────
WEIGHTS = {"朱家泓": 0.25, "阿斯匹靈": 0.35, "權證小哥": 0.20, "張捷": 0.20}


def _lookup_meta(code: str) -> tuple[str, str]:
    """從精選宇宙查 (name, industry)；找不到回 (code, '')。"""
    try:
        from universe import all_codes, load_full_universe
        for c, n, ind in all_codes():
            if c == code:
                return n, ind
        for c, n, ind in load_full_universe():
            if c == code:
                return n, ind
    except Exception:
        pass
    return code, ""


def analyze_one(code: str, name: str = "", industry: str = "") -> dict | None:
    """對單一股票跑四維度分析，回傳完整結果字典。"""
    if not name or not industry:
        auto_name, auto_ind = _lookup_meta(code)
        name = name or auto_name
        industry = industry or auto_ind
    df = _load_ohlcv(code)
    if df is None:
        return None

    chips_rec = _load_chips_rec(code)
    margin_rec = _load_margin_rec(code)
    tdcc_rec = _load_tdcc_rec(code)

    v1 = _view_zhujiahe(code, df)
    v2 = _view_aspirin(code, chips_rec, margin_rec, tdcc_rec)
    v3 = _view_warrant(code, df)
    v4 = _view_zhang(code, df, industry or "未分類")

    # 加權總分
    total = round(
        v1["score"] * WEIGHTS["朱家泓"] +
        v2["score"] * WEIGHTS["阿斯匹靈"] +
        v3["score"] * WEIGHTS["權證小哥"] +
        v4["score"] * WEIGHTS["張捷"], 1
    )

    # 多維度共振計數（≥50分才算該維度確認）
    confirm = sum(1 for v in [v1, v2, v3, v4] if v["score"] >= 50)

    # 綜合建議
    if total >= 70 and confirm >= 3:
        recommendation = "🟢 強力做多候選（三維以上共振）"
    elif total >= 55 and confirm >= 2:
        recommendation = "🟡 做多候選（兩維共振，量能確認後進場）"
    elif total >= 40:
        recommendation = "⚪ 觀察名單（條件未齊，等突破確認）"
    else:
        recommendation = "🔴 不宜進場（多維度偏空）"

    return {
        "code": code, "name": name or code, "industry": industry,
        "date": str(date.today()), "total_score": total,
        "confirm_dims": confirm,
        "recommendation": recommendation,
        "views": {"朱家泓": v1, "阿斯匹靈": v2, "權證小哥": v3, "張捷": v4},
    }


# ── 報告輸出 ────────────────────────────────────────────────────────────────
def _bar(score: int, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_report(result: dict) -> None:
    code = result["code"]
    name = result["name"]
    total = result["total_score"]
    confirm = result["confirm_dims"]
    rec = result["recommendation"]

    SEP = "═" * 58
    print(f"\n{SEP}")
    print(f"  {code} {name}  金融分析團隊報告")
    print(f"  {result['date']}  產業：{result['industry'] or '未分類'}")
    print(SEP)
    print(f"\n  總分 {total:.0f}/100  {_bar(int(total))}  {confirm}/4 維度共振")
    print(f"  {rec}\n")
    print("─" * 58)

    for key, v in result["views"].items():
        sc = v["score"]
        print(f"\n【{v['view']}】  {sc}/100  {_bar(sc, 15)}")
        print(f"  → {v['verdict']}")
        for note in v["notes"]:
            print(f"    {note}")

    print(f"\n{SEP}\n")


def to_telegram(result: dict) -> str:
    code = result["code"]
    name = result["name"]
    total = result["total_score"]
    confirm = result["confirm_dims"]
    rec = result["recommendation"]
    lines = [
        f"📊 金融分析團隊｜{code} {name}",
        f"總分 {total:.0f}/100  {confirm}/4 維度共振",
        f"{rec}",
        "━━━━━━━━━━━━",
    ]
    for key, v in result["views"].items():
        sc = v["score"]
        lines.append(f"【{v['view'][:5]}】{sc}分 → {v['verdict']}")
        # 只放最重要的前2條
        for note in v["notes"][:2]:
            lines.append(f"  {note}")
    lines.append("━━━━━━━━━━━━")
    lines.append("量化阿森 · 金融分析團隊")
    return "\n".join(lines)


# ── 掃描模式（全宇宙四維度共振候選）──────────────────────────────────────
def scan_universe(top_n: int = 10) -> list[dict]:
    """掃精選宇宙，取出四維度總分最高的前 N 支，只顯示做多候選。"""
    from universe import all_codes
    rows = all_codes()
    # 先用 scan.py 批次載資料
    data = _scan.load_universe_data(rows, use_cache_only=True)
    chip_map = _chips.load_chips([c for c, _, _ in rows], days=CHIP_DAYS, offline=True) if _chips else {}
    margin_map = _margin_mod.load_margin([c for c, _, _ in rows], offline=True) if _margin_mod else {}
    tdcc_map = _tdcc_mod.load_tdcc([c for c, _, _ in rows], offline=True) if _tdcc_mod else {}

    results: list[dict] = []
    for code, name, ind in rows:
        df = data.get(code)
        if df is None or len(df) < 30:
            continue
        v1 = _view_zhujiahe(code, df)
        v2 = _view_aspirin(code, chip_map.get(code), margin_map.get(code), tdcc_map.get(code))
        v3 = _view_warrant(code, df)
        v4 = _view_zhang(code, df, ind)
        total = round(
            v1["score"] * 0.25 + v2["score"] * 0.35 +
            v3["score"] * 0.20 + v4["score"] * 0.20, 1
        )
        confirm = sum(1 for v in [v1, v2, v3, v4] if v["score"] >= 50)
        results.append({
            "code": code, "name": name, "industry": ind,
            "total_score": total, "confirm_dims": confirm,
            "scores": {k: v["score"] for k, v in
                       zip(["朱家泓", "阿斯匹靈", "權證小哥", "張捷"], [v1, v2, v3, v4])},
        })

    results.sort(key=lambda r: (r["confirm_dims"], r["total_score"]), reverse=True)
    return results[:top_n]


# ── CLI ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="金融分析團隊四維度分析器")
    ap.add_argument("codes", nargs="*", help="股票代號，如 2330 6669")
    ap.add_argument("--scan", action="store_true", help="掃精選宇宙四維度共振候選股")
    ap.add_argument("--top", type=int, default=10, help="--scan 顯示前N名（預設10）")
    ap.add_argument("--push", action="store_true", help="分析後推 Telegram")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（供程式串接）")
    args = ap.parse_args()

    if args.scan:
        print("[analyst] 掃描精選宇宙中，只用本地快取…")
        top = scan_universe(top_n=args.top)
        SEP = "─" * 58
        print(f"\n{'═'*58}")
        print(f"  金融分析團隊｜四維度共振候選股  TOP {args.top}")
        print(f"{'═'*58}")
        for r in top:
            sc = r["scores"]
            print(f"  {r['code']} {r['name']:10s} "
                  f"總分{r['total_score']:4.0f}  {r['confirm_dims']}/4維 "
                  f"朱{sc['朱家泓']:3.0f} 阿{sc['阿斯匹靈']:3.0f} "
                  f"權{sc['權證小哥']:3.0f} 張{sc['張捷']:3.0f}  {r['industry']}")
        print(f"{'═'*58}\n")
        return

    if not args.codes:
        ap.print_help()
        return

    all_results = []
    for code in args.codes:
        print(f"[analyst] 分析 {code} 中…")
        res = analyze_one(code)
        if res is None:
            print(f"[analyst] {code} 無法取得資料，略過")
            continue
        all_results.append(res)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print_report(res)
        if args.push and _broadcast is not None:
            msg = to_telegram(res)
            try:
                _broadcast(msg, title=f"金融分析｜{code} {res['name']}", priority="default")
                print(f"[analyst] Telegram 已推送 {code}")
            except Exception as e:
                print(f"[analyst] 推送失敗：{e}")

    if len(all_results) > 1 and not args.json:
        print(f"\n{'═'*58}")
        print("  綜合比較")
        print(f"{'═'*58}")
        for r in sorted(all_results, key=lambda x: x["total_score"], reverse=True):
            print(f"  {r['code']} {r['name']:10s}  "
                  f"總分 {r['total_score']:4.1f}  {r['confirm_dims']}/4維  {r['recommendation'][:12]}")
        print(f"{'═'*58}\n")


if __name__ == "__main__":
    main()
