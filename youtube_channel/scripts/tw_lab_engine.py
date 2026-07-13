#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tw_lab_engine.py —【台股真相實驗室】訂閱轉換 franchise 引擎(2026-07-13 訂閱轉換診斷落地)。

背景(實測診斷,STUDIO/quality_scores.json 588 支已發布片逐支核對):
  · 全站 588 支片 20326 觀看只換 27 訂閱(轉換率 0.133%)。
  · 表現最好的 8 支片(觀看 588~855)結尾 CTA 各自不同,但共通問題是──
    ①只說「追蹤」不說「訂閱」(YouTube 按鈕字面是「訂閱」,語彙不一致降低行動明確度)
    ②理由是「不然演算法不會再推你」(平台操弄語氣,不是內容價值)
    ③「系列感」是空話("這是我回測系列一支")——沒有可辨識的系列名字、沒有集數、
      沒有「訂了會固定拿到什麼」的具體承諾,觀眾聽完不知道訂閱等於訂閱到什麼。
  · 既有 ep_engine.py(自動交易機器人回測 EP 系列)其實驗證了「有記憶的連續劇」有效
    (EP_RULES 註記 EP.0 帶來遠高於單集的訂閱效率)——但那個 franchise 主題是加密網格機器人,
    頻道實測數據卻是台股題材觀看 600-850、加密題材常常 0(STUDIO/REPORTS/2026-07-13_每週贏家分析.md)。
    → 缺一個「台股主軸」的常態連載 franchise,把 ep_engine 驗證過的連續劇機制套進真正會被看的題材。

本引擎做的事:
  · 用 STUDIO/tw_stock_facts.json + tw_facts_computed.json(40 組台股真回測事實)當「素材庫」，
    依上週贏家關鍵字(0050/你猜/vs/剩多少/複利/停損/差多少/微笑曲線…)排序，依序拆成一集一組數字。
  · STUDIO/tw_lab_state.json 記集數/季/已用事實 key/上一集懸念，讓每集開頭能回顧上集、
    結尾能預告下一集「主題」(不洩題目數字,只給類別當懸念鉤)。
  · 訂閱鉤明確要求含「訂閱」二字(不是只用「追蹤」)＋具體理由(這系列=已排好的 40 組事實清單,
    訂閱才會在下一組公布時收到通知)＋系列名稱本身(可辨識、可搜尋)。

純函式、零外呼(不打 LLM/網路)，可獨立 import 測試。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from studio_common import save_json_atomic, load_json_safe  # noqa: E402

STUDIO = ROOT / "STUDIO"
TW_LAB_STATE = STUDIO / "tw_lab_state.json"
TW_FACTS = STUDIO / "tw_stock_facts.json"
TW_FACTS_COMPUTED = STUDIO / "tw_facts_computed.json"

SERIES_NAME = "台股真相實驗室"
EPISODES_PER_SEASON = 10  # 對齊 ep_engine：每 10 集收一季，重新排序(反映事實庫可能已更新 as_of)

# 上週贏家分析(STUDIO/REPORTS/2026-07-13_每週贏家分析.md)：含這些詞的片平均觀看 ≥ 全站115%。
# 拿來給 40 組事實排優先序，讓 franchise 前幾集就是已驗證會被看的角度，不是隨機順序。
WINNER_KW = ("0050", "你猜", "vs", "VS", "剩多少", "小白", "複利", "停損", "差多少",
             "手續費", "微笑曲線", "定投", "定期定額", "All in", "all in", "ALL IN",
             "一次投入", "ETF", "存股")


def _load_facts():
    """合併讀 tw_stock_facts.json + tw_facts_computed.json，回 {key: fact_dict}。
    邏輯對齊 produce_batch._load_tw_facts()（獨立複製一份，避免 tw_lab_engine ← produce_batch
    互相 import 造成循環依賴）。任何一份缺檔/壞掉都靜默跳過。"""
    merged_results: dict = {}
    as_of = ""
    for p in (TW_FACTS, TW_FACTS_COMPUTED):
        try:
            if not p.exists():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                continue
            res = d.get("results") or d.get("backtests") or {}
            if isinstance(res, dict):
                for k, v in res.items():
                    merged_results.setdefault(k, v)
            as_of = as_of or str(d.get("as_of", ""))
        except Exception:  # noqa: BLE001
            continue
    return merged_results, as_of


def _score(key, fact):
    """事實與贏家關鍵字命中數(越高越先排)；同分用 key 字串排序保證每次執行結果一致。"""
    text = " ".join([
        str(fact.get("desc", "")), str(fact.get("summary", "")), str(fact.get("claim", "")),
        " ".join(str(k) for k in (fact.get("keywords") or [])),
    ])
    return sum(1 for kw in WINNER_KW if kw in text)


# tw_stock_facts.json(5 組手工)與 tw_facts_computed.json(40 組批次算)有實質重複——
# 同一標的+同一比較法只是 key 命名習慣不同(如 allin_vs_dca_0050_10y vs dca_vs_allin__0050__10y，
# 或 hidiv_0056_vs_0050 vs hidiv_vs_mktcap__0056_vs_0050)，desc 幾乎逐字一樣，只差長短代號/
# 回看年數用字。franchise 若照 key 各自算一集，觀眾會連續兩集看到幾乎同一組數字，等於自砸
# 「一集一組新事實」的訂閱承諾。用 _dedup_sig() 把「標的代號＋比較法」正規化成同一簽名，
# fact_order() 每個簽名只留分數最高(同分留 key 字母序最前)的一筆，其餘讓下一輪/下一季再用。
_SYMBOL_ALIASES = [
    ("加權指數（大盤）", "TWII"), ("加權大盤", "TWII"), ("大盤", "TWII"),
    ("元大台灣50", "0050"), ("富邦台50", "006208"), ("元大高股息", "0056"),
    ("國泰永續高股息", "00878"), ("台積電", "2330"),
]
_PERIOD_RE = re.compile(r"近\d+年(?:（可信資料區間）)?")


def _dedup_sig(fact):
    desc = str(fact.get("desc", ""))
    for alias, code in _SYMBOL_ALIASES:
        desc = desc.replace(alias, code)
    desc = _PERIOD_RE.sub("", desc)
    desc = re.sub(r"\s+", "", desc)
    return desc


def fact_order():
    """回傳依贏家關鍵字命中數排序、且已去重(同標的+同比較法只留一筆)的 (key, fact) 清單，
    命中數同分按 key 字母序排序(確定性)。"""
    facts, _ = _load_facts()
    items = [(k, v) for k, v in facts.items() if isinstance(v, dict) and v.get("summary")]
    items.sort(key=lambda kv: (-_score(kv[0], kv[1]), kv[0]))
    seen_sig = set()
    deduped = []
    for k, v in items:
        sig = _dedup_sig(v)
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        deduped.append((k, v))
    return deduped


DEFAULT_STATE = {
    "series_name": SERIES_NAME,
    "season": 1,
    "current_ep": 0,
    "used_keys": [],
    "seeded_keys": [],
    "last_episode": {"ep": 0, "key": "", "title": "", "cliffhanger": "",
                      "comment_question": "", "slug": ""},
    "episodes": [],
}


def load_state():
    st = copy.deepcopy(DEFAULT_STATE)
    raw = load_json_safe(TW_LAB_STATE, default={}) or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is None:
                continue
            if isinstance(st.get(k), dict) and isinstance(v, dict):
                merged = dict(st[k])
                merged.update(v)
                st[k] = merged
            else:
                st[k] = v
    return st


def _save_state(st):
    try:
        save_json_atomic(TW_LAB_STATE, st)
    except Exception:  # noqa: BLE001
        pass


def pick_next(state=None):
    """回傳 (key, fact, next_key, next_fact) — 本集要用的事實 + 下一集要用的事實(給結尾預告懸念用)。
    40 組事實依 fact_order() 排序後照序發放；用完一輪(=一季)就清空 used_keys 開新季重來
    (以「資料已更新(as_of 會變)、換角度重測」名義重新覆蓋，不是硬湊集數)。
    facts 庫是空的(檔案都不存在)時回 (None, None, None, None)，呼叫端要能處理。"""
    st = state if isinstance(state, dict) else load_state()
    order = fact_order()
    if not order:
        return None, None, None, None
    used = set(st.get("used_keys") or [])
    remaining = [(k, v) for k, v in order if k not in used]
    if not remaining:
        remaining = order  # 一輪用完，新季重來
    key, fact = remaining[0]
    next_key, next_fact = (remaining[1] if len(remaining) > 1 else order[0])
    return key, fact, next_key, next_fact


def fact_data_block(key, fact, as_of=""):
    """把單一事實格式化成可直接塞進寫稿 prompt 的實證區塊(比 produce_batch._tw_facts_context
    更聚焦——只給『這集要用的這一組』，不是一次塞 6 組讓 LLM 自己選,避免混題)。"""
    if not fact:
        return ""
    desc = str(fact.get("desc") or key)
    claim = str(fact.get("claim") or fact.get("summary") or "")
    period = str(fact.get("period") or "")
    source = str(fact.get("source") or "")
    lines = [f"\n【★本集唯一指定實證數據(台股真回測·只能用這一組,不得混用其他標的/期間的數字)】",
             f"  題材：{desc}"]
    if claim:
        lines.append(f"  數字：{claim}")
    if period:
        lines.append(f"  期間：{period}")
    if as_of:
        lines.append(f"  資料截至：{as_of}")
    if source:
        lines.append(f"  資料來源：{source}")
    lines.append("（歷史回測，非未來保證；旁白引用時務必講清楚是回測歷史數字，不得喊單/報明牌/保證獲利。）")
    return "\n".join(lines)


def _peek_label(next_fact):
    """下一集事實的『類別標籤』給結尾懸念用——只給題材方向,不洩數字答案(維持懸念)。"""
    if not next_fact:
        return ""
    return str(next_fact.get("desc") or "")


def next_after(key, state=None):
    """給定本集用的事實 key，回傳(next_key, next_fact)——排序中緊接在它後面、且尚未用過的下一組。
    供 produce_batch 的題目來自 topic_bank(沒有預先算好 tw_lab_next_key)時當備援，動態算出
    『下一集要預告什麼』，不必每次都要求呼叫端自己傳 next_key。找不到就回 (None, None)。"""
    st = state if isinstance(state, dict) else load_state()
    order = fact_order()
    if not order:
        return None, None
    used = set(st.get("used_keys") or []) | {key}
    remaining = [(k, v) for k, v in order if k not in used]
    if not remaining:
        remaining = [(k, v) for k, v in order if k != key] or order
    return remaining[0]


def context_block(state, key, fact, next_key, next_fact):
    """組『前情提要＋本集定位＋下集懸念』區塊，塞進 produce_batch 的 assign。"""
    season = int(state.get("season", 1) or 1)
    ep = int(state.get("current_ep", 0) or 0) + 1
    last = state.get("last_episode") or {}
    prev_ep = int(last.get("ep", 0) or 0)
    peek = _peek_label(next_fact)
    lines = [f"\n【★{SERIES_NAME}系列連貫設定｜本支是第 {season} 季 EP{ep}】"]
    if prev_ep:
        recap = f"上一集 EP{prev_ep} 拆的是「{last.get('title') or last.get('key','')}」。"
        if last.get("cliffhanger"):
            recap += f" 上集結尾留的懸念是「{last['cliffhanger']}」，本集開頭可一句話呼應再進本集正題。"
        lines.append(recap)
    else:
        lines.append(f"這是「{SERIES_NAME}」系列的第一集——用一句話點出這是常態連載企劃："
                      "『我把台股最容易被誤會的迷思整理成一組一組真回測，一集拆一組』。")
    lines.append(f"★片名或旁白開場/結尾其中一處務必自然帶出系列名稱「{SERIES_NAME}」與集數"
                 f"「EP{ep}」字樣(可搭配主標題,不必生硬複誦)。")
    if peek:
        lines.append(f"★結尾預告下一集題材(只給方向懸念、不洩露具體數字答案，維持好奇)："
                     f"「下一集{SERIES_NAME}要拆的是『{peek}』，數字會不會顛覆你想的，先訂閱才看得到」。")
    lines.append(
        "★訂閱鉤(本系列硬性規格，務必逐字精神照走，字句可微調但不可省略任一要素)："
        "①明確用「訂閱」二字(不是只用「追蹤」——YouTube 按鈕本身寫的是訂閱，語彙要對上觀眾看到的按鈕)"
        "②具體理由=這系列已經排好一整組台股真回測要拆，訂閱是唯一會收到『下一組數字』通知的方式"
        "(不是空泛的『支持我』、也不是『不然演算法不推你』這種平台操弄語氣)"
        "③點名系列名稱，讓訂閱者知道『訂了會固定拿到什麼』。")
    return "\n".join(lines)


def build_topic(state=None):
    """回傳可直接塞進 produce_batch topic_override 的 dict，或 None(事實庫是空的)。"""
    st = state if isinstance(state, dict) else load_state()
    key, fact, next_key, next_fact = pick_next(st)
    if not fact:
        return None
    ep = int(st.get("current_ep", 0) or 0) + 1
    desc = str(fact.get("desc") or key)
    claim = str(fact.get("claim") or fact.get("summary") or "")
    angle = (f"{SERIES_NAME} EP{ep}：用真回測拆「{desc}」——{claim}"
             f"。開頭用『你猜』式懸念框題目(先問觀眾猜結果、再揭曉)，收尾照系列訂閱鉤規格。")
    return {
        "title": f"{desc}？回測揭真相",
        "angle": angle,
        "category": SERIES_NAME,
        "format": "short",
        "tw_lab_key": key,
        "tw_lab_next_key": next_key,
    }


def seed_topic_bank(n=8):
    """把接下來 n 集要用的事實預先寫進 STUDIO/topic_bank.json(source='tw_lab'，插隊到題庫最前面)，
    讓 produce_batch.pull_topic() 在日常補產時能自然抽到本系列，不必每次都靠手動 --tw-lab。
    已 seeded 過的 key 不重複塞(state.seeded_keys 追蹤)；回傳實際新增題數。"""
    st = load_state()
    order = fact_order()
    if not order:
        return 0
    used = set(st.get("used_keys") or [])
    seeded = set(st.get("seeded_keys") or [])
    skip = used | seeded
    cand = [(k, v) for k, v in order if k not in skip][:n]
    if not cand:
        return 0
    items = []
    for k, v in cand:
        desc = str(v.get("desc") or k)
        claim = str(v.get("claim") or v.get("summary") or "")
        items.append({
            "title": f"{desc}？回測揭真相",
            "angle": f"{SERIES_NAME}系列一集：{claim}。用『你猜』式懸念開場、系列訂閱鉤收尾。",
            "category": SERIES_NAME,
            "format": "short",
            "tw_lab_key": k,
        })
    try:
        import topic_bank
        added = topic_bank.add_topics(items, source="tw_lab", front=True)
    except Exception:  # noqa: BLE001
        return 0
    st["seeded_keys"] = list(seeded | {k for k, _ in cand})
    _save_state(st)
    return added


def bump_episode(state, rec, persist=True):
    """正片產出成功後遞增集數：current_ep+1、記本集、標記事實 key 已用；EP>=10 收官升季
    (季重置後 used_keys 清空，讓事實庫可以在下一季重新覆蓋——as_of 屆時通常已更新)。
    回傳更新後的 state(新 dict，不就地改傳入的 state)。persist=False 供測試用，不寫檔。"""
    st = copy.deepcopy(state) if isinstance(state, dict) else load_state()
    new_ep = int(st.get("current_ep", 0) or 0) + 1
    key = rec.get("key", "")
    entry = {
        "ep": new_ep, "season": int(st.get("season", 1) or 1),
        "key": key, "title": rec.get("title", ""), "slug": rec.get("slug", ""),
        "cliffhanger": rec.get("cliffhanger", ""),
        "comment_question": rec.get("comment_question", ""),
    }
    st["episodes"] = list(st.get("episodes") or []) + [entry]
    st["current_ep"] = new_ep
    if key:
        st["used_keys"] = list(set(st.get("used_keys") or []) | {key})
    st["last_episode"] = {
        "ep": new_ep, "key": key, "title": rec.get("title", ""),
        "cliffhanger": rec.get("cliffhanger", ""),
        "comment_question": rec.get("comment_question", ""),
        "slug": rec.get("slug", ""),
    }
    if new_ep >= EPISODES_PER_SEASON:
        st["season"] = int(st.get("season", 1) or 1) + 1
        st["current_ep"] = 0
        st["used_keys"] = []
        st["last_episode"] = copy.deepcopy(DEFAULT_STATE["last_episode"])
    if persist:
        _save_state(st)
    return st
