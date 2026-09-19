#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ep_engine.py — 【EP franchise 引擎】把「回測往死裡測機器人」EP 系列變成有記憶的連續劇。

純函式、零外呼（不打網路），可獨立 import。負責 STUDIO/ep_data.json 的狀態機：
  · 集數/季/累計損益/角色狀態持久化（讓 call_claude 讀得到上集講什麼）
  · 里程碑偵測（回本/賺10%/虧10%/翻倍/幾乎歸零）→ 觸發爆點題
  · 前情提要生成（產「上集 EP{n} 講到…懸念…」段落塞進製作 prompt）
  · bump_episode：正片產出成功後遞增 EP 號、記錄本集、EP>=10 收官升季重置

向後相容：舊 ep_data 缺欄位時 load_state 補預設不報錯（仿 ep_teaser.load_ep 的 dict+update）。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from studio_common import save_json_atomic
EP_DATA = ROOT / "STUDIO" / "ep_data.json"

EPISODES_PER_SEASON = 10  # EP>=此數＝該季收官，升下一季重置

# 角色弧線（值域）：謹慎→有信心→貪婪→危機→復甦→平反
CHARACTER_ARC = ["cautious", "confident", "greedy", "crisis", "recovering", "vindicated"]

# 里程碑門檻（正值＝報酬 >= 門檻觸發；負值＝報酬 <= 門檻觸發）
MILESTONES = {
    "break_even": 0.0,     # 回本：首度站上成本線（由虧轉盈/帳戶轉正）
    "up_10pct": 10.0,      # 賺 10%
    "down_10pct": -10.0,   # 虧 10%
    "double": 100.0,       # 翻倍
    "wipeout": -90.0,      # 幾乎歸零
}

# 角色心境 → 一句話敘事（餵進前情提要，讓旁白與 HUD 情緒連貫）
_CHAR_MOOD = {
    "cautious": "謹慎試水、半信半疑",
    "confident": "小有斬獲、開始有點信心",
    "greedy": "帳面獲利膨脹、有點上頭想加碼",
    "crisis": "遭遇大回撤、信心崩盤的危機時刻",
    "recovering": "從谷底慢慢往回爬、還驚魂未定",
    "vindicated": "熬過崩盤、策略被證明撐得住",
}

# 各里程碑對應的爆點題模板（title 可含 {ep} 佔位）
_MILESTONE_TOPIC = {
    "break_even": (
        "回測終於回本！第{ep}集帳戶由虧轉盈那一刻的關鍵",
        "用『回本』當鉤子：很多人虧著虧著就放棄，回測到終於站回成本線，講回本前最煎熬的心理與紀律"),
    "up_10pct": (
        "回測破十趴！機器人幫我賺到10%，我卻更怕了",
        "賺到 10% 的反直覺焦慮：數字越漂亮越要問守不守得住，連到獲利了結紀律"),
    "down_10pct": (
        "實測虧10%了，我要停損還是續抱？攤開真實帳戶給你看",
        "虧 10% 的抉擇：用真實回撤講停損紀律 vs 凹單，留言逼觀眾選邊"),
    "double": (
        "回測翻倍！但我為什麼準備把一半的錢先拿出來",
        "翻倍後的落袋思維：破解『抱到翻倍就財富自由』迷思，講獲利了結與複利"),
    "wipeout": (
        "實測差點歸零，機器人把我的錢快虧光了，殘酷真相全講",
        "接近歸零的最痛一集：拆解為什麼會爆、哪一步該收手，警世避雷"),
}

# pionex 寫的真數字欄位：bump 寫檔時以磁碟為準，避免蓋掉剛更新的真實損益
_REAL_FIELDS = ("investment", "account_value", "profit", "return_pct",
                "day", "bots", "max_drawdown", "highlights")

DEFAULT_STATE = {
    # ── 舊欄位（對齊現況；load 時被實檔覆蓋，缺了才用這裡的預設）──
    "premise": "我用回測『丟約一百美元給自動交易機器人』往死裡測，規則先講死",
    "series_name": "自動交易機器人回測企劃",
    "current_ep": 0,
    "day": 0,
    "return_pct": None,
    "max_drawdown": None,
    "cliffhanger": "結果可能打臉所有人",
    "account_value": None,
    "investment": None,
    "profit": None,
    "bots": 0,
    "highlights": [],
    # ── 新欄位（EP franchise 引擎）──
    "season": 1,
    "season_premise": "第一季：我用回測『丟約一百美元給自動交易機器人跑三十天』，規則先講死，看它到底賺還賠",
    "cumulative": {
        "peak_value": None,
        "trough_value": None,
        "total_return_pct": None,
        "best_ep": None,
        "worst_ep": None,
    },
    "character_state": "cautious",
    "last_episode": {
        "ep": 0,
        "hook_number": "",
        "cliffhanger": "",
        "comment_question": "",
        "slug": "",
    },
    "episodes": [],
    "milestones_hit": [],
    # 已經產過片的「事實指紋」(見 fact_signature)。EP 系列報的是真實帳戶,同一組
    # (day, return_pct) 只該有一支片；這裡記住用過的,讓 fact_is_fresh 擋掉換殼重產。
    "used_fact_sigs": [],
}


# 事實指紋只取 day/return_pct：這兩個既是影片真正宣稱的數字(第N天/報酬X%)，也是 episodes
# 每筆都有存的欄位——後者讓 used_fact_sigs 能從既有歷史回推，不必先做資料遷移就立即生效。
FACT_SIG_FIELDS = ("day", "return_pct")


def _num(x, default=0.0):
    """安全轉 float；None/非數字回 default。"""
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def load_state():
    """讀 STUDIO/ep_data.json 補齊預設欄位（仿 ep_teaser.load_ep 的 dict+update）。
    向後相容：舊檔缺欄位 → 用 DEFAULT_STATE 補；巢狀 dict（cumulative/last_episode）逐鍵合併不整段蓋掉。"""
    st = copy.deepcopy(DEFAULT_STATE)
    try:
        raw = json.loads(EP_DATA.read_text(encoding="utf-8")) if EP_DATA.exists() else {}
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v is None:
                continue  # None 不覆蓋預設（沿用 ep_teaser 慣例）
            if isinstance(st.get(k), dict) and isinstance(v, dict):
                merged = dict(st[k])
                merged.update(v)
                st[k] = merged
            else:
                st[k] = v
    return st


def advance_character(state, return_pct, drawdown):
    """依報酬率與回撤推進角色狀態機。state 可為狀態字串或整個 ep dict；回傳新的 character_state 字串。
    敘事線：cautious→confident→greedy（上行）；深回撤/大虧→crisis；crisis→recovering→vindicated（谷底翻身）。"""
    cur = state.get("character_state", "cautious") if isinstance(state, dict) else (state or "cautious")
    if cur not in CHARACTER_ARC:
        cur = "cautious"
    pct = _num(return_pct, 0.0)
    dd = abs(_num(drawdown, 0.0))

    # 深度回撤或大虧 → 一律進入危機（除非已在平反且未再崩，下面 vindicated 分支處理）
    if (dd >= 15 or pct <= -10) and cur != "vindicated":
        return "crisis"
    if cur == "crisis":
        if pct >= 10 and dd < 8:
            return "vindicated"
        if pct > -5 or dd < 10:
            return "recovering"
        return "crisis"
    if cur == "recovering":
        if pct >= 10:
            return "vindicated"
        if dd >= 12:
            return "crisis"
        return "recovering"
    if cur == "vindicated":
        # 平反後只有再度大跌才退回危機，否則守住戰果
        if dd >= 20 or pct <= -15:
            return "crisis"
        return "vindicated"
    # 上行敘事線
    if cur == "cautious":
        return "confident" if pct >= 3 else "cautious"
    if cur == "confident":
        return "greedy" if pct >= 20 else "confident"
    if cur == "greedy":
        return "greedy"
    return cur


def check_milestones(return_pct, already_hit=None):
    """回傳這次新達成、且不在 already_hit 內的里程碑 key 清單。return_pct=None → 回空。"""
    already = set(already_hit or [])
    if return_pct is None:
        return []
    try:
        pct = float(return_pct)
    except Exception:
        return []
    hits = []
    for name, thr in MILESTONES.items():
        if name in already:
            continue
        if (thr >= 0 and pct >= thr) or (thr < 0 and pct <= thr):
            hits.append(name)
    return hits


def fact_signature(src):
    """把「這集要報的真實帳戶事實」壓成指紋字串。src 可是整個 state,也可是 episodes 裡的單筆紀錄
    (兩者都有 day/return_pct)。數字正規化到小數 2 位,None 記成空值；抓不到欄位回 ""。"""
    if not isinstance(src, dict):
        return ""
    parts = []
    for k in FACT_SIG_FIELDS:
        v = src.get(k)
        if isinstance(v, bool):
            v = None
        if v is None:
            parts.append(f"{k}=")
            continue
        try:
            parts.append(f"{k}={round(float(v), 2)}")
        except (TypeError, ValueError):
            parts.append(f"{k}={v}")
    return "|".join(parts)


def used_fact_sigs(state):
    """已經產過片的事實指紋集合＝明確記錄的 used_fact_sigs ∪ 從 episodes 歷史回推的指紋。
    回推是刻意的：舊 ep_data 沒有 used_fact_sigs 欄位,但 episodes 每筆都存了 day/return_pct,
    所以 guard 對既有存量(2026-07 那 50 集)立即生效,不需要先跑資料遷移。"""
    sigs = {s for s in (state.get("used_fact_sigs") or []) if isinstance(s, str) and s}
    for rec in state.get("episodes") or []:
        if isinstance(rec, dict):
            sig = fact_signature(rec)
            if sig:
                sigs.add(sig)
    return sigs


def fact_is_fresh(state=None):
    """ep_data 現在的真實帳戶事實是否「還沒被產過片」——EP 系列產片前的事實 guard。

    False ＝ 事實沒更新,呼叫端應**乾淨跳過不產**(不是報錯、更不是換個標題再產一支)。
    根因(2026-07 實錄)：ep_data.json 是「單一當前狀態」,pionex_account.py 沒有 API key 就整支
    早退不更新它(見該檔 main() 開頭),於是 day=30/return_pct=-1.19 從 07-12 凍結至今；引擎又沒有
    「這個事實用過了」的記憶,結果同一組事實被反覆換殼——5 組事實產了 23 支片。
    判定只看事實指紋,不看標題/集數/季別等包裝層——包裝層判定正是當初失守的原因。
    帳戶沒 funded(return_pct=None)時回 False：沒有新事實就沒有 EP 可報。
    pionex 帶進新數字後指紋自然改變 → 回 True → EP 題自動恢復被抽中,不需要人工解封。"""
    st = state if isinstance(state, dict) else load_state()
    if st.get("return_pct") is None:
        return False
    sig = fact_signature(st)
    if not sig:
        return False
    return sig not in used_fact_sigs(st)


def update_cumulative(ep, current, pct):
    """更新累計戰績：峰值/谷值帳戶價值、累計報酬、最佳/最差集數。就地改 ep['cumulative'] 並回傳該 dict。
    best_ep/worst_ep 記成 {ep, return_pct}，依當集報酬更新。"""
    cum = dict(ep.get("cumulative") or {})
    cur_ep = ep.get("current_ep")
    cv = _num(current, None)
    pv = _num(pct, None)
    if cv is not None:
        if cum.get("peak_value") is None or cv > cum["peak_value"]:
            cum["peak_value"] = round(cv, 2)
        if cum.get("trough_value") is None or cv < cum["trough_value"]:
            cum["trough_value"] = round(cv, 2)
    if pv is not None:
        cum["total_return_pct"] = round(pv, 2)
        best = cum.get("best_ep")
        worst = cum.get("worst_ep")
        if not isinstance(best, dict) or pv >= best.get("return_pct", float("-inf")):
            cum["best_ep"] = {"ep": cur_ep, "return_pct": round(pv, 2)}
        if not isinstance(worst, dict) or pv <= worst.get("return_pct", float("inf")):
            cum["worst_ep"] = {"ep": cur_ep, "return_pct": round(pv, 2)}
    ep["cumulative"] = cum
    return cum


def next_episode_context(state):
    """產「上集 EP{n} 講到…懸念…」前情提要段，塞進 produce_batch 的製作指派。回傳一段可直接串進 prompt 的字串。"""
    season = int(_num(state.get("season", 1), 1))
    next_ep = int(_num(state.get("current_ep", 0), 0)) + 1
    last = state.get("last_episode") or {}
    cum = state.get("cumulative") or {}
    mood = _CHAR_MOOD.get(state.get("character_state", "cautious"), "")
    prev_ep = int(_num(last.get("ep", 0), 0))

    lines = [f"\n【★EP 前情提要與連貫設定｜本支是第 {season} 季 EP{next_ep}】"]
    if prev_ep:
        recap = f"上一集是 EP{prev_ep}，"
        recap += f"結尾留的懸念是「{last['cliffhanger']}」。" if last.get("cliffhanger") else "已經播出。"
        lines.append(recap)
        if last.get("comment_question"):
            lines.append(f"上集留言題問的是「{last['comment_question']}」，本集開頭可順勢呼應或揭曉。")
        lines.append(f"★開頭 3 秒務必先用一句話回顧 EP{prev_ep} 的懸念再進本集，讓追更觀眾無縫接上、新觀眾也秒懂這是系列實測續集。")
    else:
        lines.append(f"這是系列的新一集。前提：{state.get('season_premise') or state.get('premise', '')}")

    tr = cum.get("total_return_pct")
    if tr is not None:
        lines.append(f"目前累計報酬約 {tr}%，主角心境：{mood}。旁白與 HUD 數字要與此連貫。")
    elif mood:
        lines.append(f"主角目前心境：{mood}。")
    lines.append(f"★片尾除 loop、續集鉤、訂閱追更鉤外，補一句全頻道導流：「這是 EP{next_ep}，其他實驗 EP1 到 EP{max(next_ep - 1, 1)} 都在播放清單，一次追完」。")
    return "\n".join(lines)


def _start_new_season(st):
    """收官升季：季+1、集數歸零、角色/累計/里程碑重置（episodes 保留為跨季歷史）。
    ⚠️ used_fact_sigs 刻意**不清空**（與 tw_lab_engine 的 used_keys 相反）：tw_lab 的事實庫會隨
    as_of 更新，一輪用完換季重測是合理的；EP 報的是單一真實帳戶，同一組 (day, return_pct) 換季
    再報一次仍然是同一件事換殼。2026-07 實錄正是這樣穿透的——事實凍結在 day=30/-1.19%，季別卻
    一路 3→4→5→6 滾下去，每滾一次就多產 10 支同事實的片。"""
    st["season"] = int(_num(st.get("season", 1), 1)) + 1
    st["current_ep"] = 0
    st["character_state"] = "cautious"
    st["cumulative"] = copy.deepcopy(DEFAULT_STATE["cumulative"])
    st["milestones_hit"] = []
    st["last_episode"] = copy.deepcopy(DEFAULT_STATE["last_episode"])
    st["season_premise"] = f"第 {st['season']} 季：延續回測往死裡測，換個規則或標的再戰一輪"
    return st


def _save_state(st):
    """寫回 ep_data.json；寫前重讀磁碟的真數字/累計/角色欄位覆蓋，避免蓋掉 pionex 剛更新的真實損益。
    但若磁碟仍停留在『升季前』的舊季別(disk season != 這次要寫的 season)，代表這是
    _start_new_season() 剛做的季重置，不是外部併發寫入——此時不能拿舊季磁碟值蓋掉剛重置好的
    cumulative/character_state/milestones_hit，否則季重置形同白做，milestones_hit 永遠不會真的
    清空，導致「里程碑→題庫插隊」機制第一季後永久靜默失效。"""
    out = copy.deepcopy(st)
    try:
        if EP_DATA.exists():
            disk = json.loads(EP_DATA.read_text(encoding="utf-8"))
            if isinstance(disk, dict):
                for k in _REAL_FIELDS:
                    if disk.get(k) is not None:
                        out[k] = disk[k]
                if disk.get("season") == out.get("season"):
                    for k in ("milestones_hit", "character_state", "cumulative"):
                        if disk.get(k) is not None:
                            out[k] = disk[k]
                # 事實指紋一律取聯集(不分季別、不讓磁碟版覆蓋)：這是「不可遺忘」的帳,
                # 併發寫入時任一方漏記都會讓同事實再被放行一次,只能加不能減。
                _dsigs = disk.get("used_fact_sigs")
                if isinstance(_dsigs, list):
                    out["used_fact_sigs"] = sorted(
                        {s for s in _dsigs if isinstance(s, str) and s}
                        | set(out.get("used_fact_sigs") or []))
    except Exception:
        pass
    try:
        save_json_atomic(EP_DATA, out)
    except Exception:
        pass


def bump_episode(state, new_metrics=None, persist=True):
    """正片產出成功後遞增 EP 引擎狀態：current_ep+1、append episodes、更新 last_episode；
    EP>=EPISODES_PER_SEASON 收官升季重置。回傳更新後的 state（新 dict，不就地改傳入的 state）。
    persist=True 時寫回 ep_data.json（測試請傳 persist=False 避免動到正式檔）。"""
    st = copy.deepcopy(state) if isinstance(state, dict) else load_state()
    m = new_metrics or {}
    new_ep = int(_num(st.get("current_ep", 0), 0)) + 1
    ret = m.get("return_pct", st.get("return_pct"))
    day = m.get("day", st.get("day"))
    cliff = m.get("cliffhanger") or st.get("cliffhanger", "")
    rec = {
        "ep": new_ep,
        "season": int(_num(st.get("season", 1), 1)),
        "slug": m.get("slug", ""),
        "title": m.get("title", ""),
        "hook_number": m.get("hook_number", ""),
        "cliffhanger": cliff,
        "comment_question": m.get("comment_question", ""),
        "return_pct": ret,
        "day": day,
    }
    st["episodes"] = list(st.get("episodes") or []) + [rec]
    # 記下本集用掉的事實指紋 → 同一組 (day, return_pct) 之後不會再被 fact_is_fresh 放行
    _sig = fact_signature(rec)
    if _sig:
        st["used_fact_sigs"] = sorted(set(st.get("used_fact_sigs") or []) | {_sig})
    st["current_ep"] = new_ep
    st["last_episode"] = {
        "ep": new_ep,
        "hook_number": rec["hook_number"],
        "cliffhanger": rec["cliffhanger"],
        "comment_question": rec["comment_question"],
        "slug": rec["slug"],
    }
    if cliff:
        st["cliffhanger"] = cliff  # 頂層也更新，給 ep_teaser 用

    if new_ep >= EPISODES_PER_SEASON:
        st = _start_new_season(st)

    if persist:
        _save_state(st)
    return st


def milestone_topic(m, ep):
    """把里程碑轉成插隊題庫用的爆點題 dict（category='實測EP'、format='short'）。"""
    ep_disp = ep if ep else "?"
    tmpl = _MILESTONE_TOPIC.get(m)
    if tmpl:
        title = tmpl[0].format(ep=ep_disp)
        angle = tmpl[1]
    else:
        title = f"回測重大進度！第{ep_disp}集帳戶發生大事"
        angle = "用回測里程碑當鉤子，揭露回測帳戶最新戲劇性變化"
    return {
        "title": title,
        "angle": angle,
        "category": "實測EP",
        "format": "short",
        "priority": "high",
    }
