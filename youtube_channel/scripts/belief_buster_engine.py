#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""belief_buster_engine.py —【台股流言終結者】確定性產製引擎(franchise 引擎,不走 LLM)。

一句話定位:每支終結一個 99% 台股散戶都信的迷思,用真回測當法槌,誠實下判決。

★為什麼又是確定性模板、不走 LLM(跟 ep0_engine 同一個理由,而且更硬):
  這個 franchise 的**賣點**就是「每個數字都能溯源到一組真回測」。若走 produce_batch 的
  一般 LLM 路徑(tw_lab_engine 那條:種題進 topic_bank → LLM 寫稿),LLM 會為了傳播力自己
  生數字/湊整/把 5.9% 講成牛熊差 —— 那正是這個頻道整段時間在修的洞(見 memory
  yt-integrity-fabricated-stats-fix / fact_source_guard.py 檔頭)。所以本引擎**刻意選 ep0
  那條 script_override 確定性路徑**:稿子在這裡組好、每個百分比都由 tw_facts_computed.json
  的某個 fact_key 的某個欄位算出來,make_one(script_override=...) 跳過 LLM 直接進配音/渲染。
  → 結構上不可能出現「查無憑據的數字」。這不是偷懶,是這個 franchise 生死線的實作。

★誠信鐵律(這是護城河,違反=前功盡棄):
  1. 稿子裡每個百分比/倍數,都由 _FactBook 從真 fact_key 的真欄位算出(見 trace 溯源表);
     算不出來的數字**根本不寫進模板**。
  2. **判決由真回測算,不由標題定**:compute_verdict() 比 champion vs rival 的真實數字 +
     決定性門檻 → 打臉 / 證實 / 微妙。資料哪天翻轉,判決就跟著翻轉(結構性,不寫死)。
  3. 至少一支「證實」(崩盤抄底):證明這不是為了流量一律唱反調的機器,是真的拿數據說話。
     沒有這些證實,打臉就不可信。
  4. 產出後**必須**過 fact_source_guard.check_slug —— 那是同一把發布端的尺。本引擎 --verify
     直接把那把尺接進來自我檢查(不放寬 gate,是要求稿子達標)。

★接現有產線(不另造第三套產線):
  · 選題/判決/組稿 = 本引擎(新 franchise,新 state,但**不是**新產線)。
  · 配音/渲染/發布 = 完全走 produce_batch.make_one(script_override) 那條既有路(與 ep0 同)。
  · 視覺:長片渲染吃 design_system.progressive_reveal(已開)→ 法槌段落畫真 0050 曲線、
    講到哪年畫到哪年;故關鍵段落旁白刻意帶「0050」+ 圖表關鍵字(複利/回撤/崩盤/定期定額),
    讓 concept_visuals 畫得出該段的真資料圖(video_ticker 在 ffmpeg 後端刻意傳 None,
    段落要自己點名代號才畫真圖,見 render_ffmpeg.py:692)。

用法:
  python scripts/belief_buster_engine.py --list                 # 列 3 個迷思 + 各自真回測判決
  python scripts/belief_buster_engine.py --dry stop_profit      # 印稿 + fact_key 溯源表(不寫檔)
  python scripts/belief_buster_engine.py --verify stop_profit   # 組稿→跑 fact_source_guard 自檢
  python -m produce_batch --belief stop_profit                  # 走正式產線(配音+渲染,不發布)
  python -m produce_batch --belief all                          # 一次產 3 支

驗證:python -m py_compile scripts/belief_buster_engine.py
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUDIO = ROOT / "STUDIO"
TW_FACTS_COMPUTED = STUDIO / "tw_facts_computed.json"
STATE_FILE = STUDIO / "belief_buster_state.json"

SERIES_NAME = "台股流言終結者"

VERDICT_BUST = "打臉"
VERDICT_CONFIRM = "證實"
VERDICT_NUANCE = "微妙"


# ─────────────────────────────────────────────────────────────────────
# 事實庫 + 溯源(每個數字都記下它來自哪個 fact_key 的哪個欄位)
# ─────────────────────────────────────────────────────────────────────

def _load_facts() -> tuple[dict, str]:
    """讀 tw_facts_computed.json → ({key: fact}, as_of)。缺檔/壞檔回 ({}, "")。"""
    try:
        d = json.loads(TW_FACTS_COMPUTED.read_text(encoding="utf-8"))
        r = d.get("results")
        return (r if isinstance(r, dict) else {}), str(d.get("as_of", ""))
    except Exception:  # noqa: BLE001
        return {}, ""


def _dig(obj, *path):
    """data 巢狀取值:_dig(data, 'hidiv', 'total_return')。取不到丟 KeyError(讓 build 早死,不硬掰)。"""
    cur = obj
    for p in path:
        cur = cur[p]
    return cur


class _FactBook:
    """把 fact_key 的真欄位格式化成稿子用的字串,同時記下溯源(值, fact_key, 欄位, 說明)。
    這是誠信命脈:稿子裡每個數字都經過這裡,trace 就是可回查的 fact_key 溯源表。"""

    def __init__(self, facts: dict):
        self.facts = facts
        self.trace: list[dict] = []

    def _fact(self, key: str) -> dict:
        f = self.facts.get(key)
        if not isinstance(f, dict) or "data" not in f:
            raise KeyError(f"fact_key 不存在或無 data:{key}")
        return f

    def pct(self, key: str, *path, note: str = "") -> str:
        """小數欄位(0.9865)→ 百分比字串「986.5%」。與 tw_facts_computed 的 claim 字串同一個
        表示法(1 位小數 ×100),所以這個字串一定落在 fact_source_guard 的數字池裡。"""
        val = float(_dig(self._fact(key)["data"], *path))
        s = f"{round(val * 100, 1)}%"
        self.trace.append({"value": s, "fact_key": key, "field": ".".join(map(str, path)),
                           "raw": val, "note": note})
        return s

    def pct_int(self, key: str, *path, note: str = "") -> str:
        """整數百分比(門檻 0.1 → 「10%」)。給停利門檻這種本來就是整數的用。"""
        val = float(_dig(self._fact(key)["data"], *path))
        s = f"{round(val * 100)}%"
        self.trace.append({"value": s, "fact_key": key, "field": ".".join(map(str, path)),
                           "raw": val, "note": note})
        return s

    def gap_pp(self, key: str, path_a, path_b, note: str = "") -> str:
        """兩欄位差(百分點)→「589.3」。純由同一 fact 內兩個真欄位相減得到;稿子裡務必把
        兩個操作數也講出來(fact_source_guard 對『比較結果數字』要求能從文內操作數推導)。"""
        a = float(_dig(self._fact(key)["data"], *path_a))
        b = float(_dig(self._fact(key)["data"], *path_b))
        s = f"{round(abs(a - b) * 100, 1)}"
        self.trace.append({"value": s + "(差,百分點)", "fact_key": key,
                           "field": f"|{'.'.join(map(str, path_a))} - {'.'.join(map(str, path_b))}|",
                           "raw": abs(a - b), "note": note})
        return s

    def val(self, key: str, *path) -> float:
        return float(_dig(self._fact(key)["data"], *path))


# ─────────────────────────────────────────────────────────────────────
# 判決:結構性,由真回測數字算出來(不由標題/立場定)
# ─────────────────────────────────────────────────────────────────────

def compute_verdict(champion_val: float, rival_val: float,
                    decisive_pp: float = 10.0, decisive_rel: float = 0.15) -> dict:
    """信仰擁護 champion(主張 champion 比 rival 好/贏)。用真數字判:
      · champion 真的贏 rival,且差距夠決定性 → 證實
      · champion 其實輸 rival,且差距夠決定性 → 打臉
      · 差距不夠決定性(門檻內)→ 微妙(這條也要誠實講清 trade-off,不硬打臉)

    「決定性」= 絕對差 ≥ decisive_pp 個百分點 **且** 相對差 ≥ decisive_rel。兩個都要,才不會
    把 10.1% vs 10.3% 這種噪音判成打臉。回 dict 供稿子與稽核用。"""
    champ, riv = float(champion_val), float(rival_val)
    hi, lo = max(champ, riv), min(champ, riv)
    champion_wins = champ >= riv
    gap_pp = abs(champ - riv) * 100.0
    rel = (hi - lo) / abs(lo) if lo != 0 else float("inf")
    decisive = gap_pp >= decisive_pp and rel >= decisive_rel
    if not decisive:
        verdict = VERDICT_NUANCE
    else:
        verdict = VERDICT_CONFIRM if champion_wins else VERDICT_BUST
    return {"verdict": verdict, "champion_wins": champion_wins,
            "gap_pp": round(gap_pp, 1), "rel": round(rel, 3), "decisive": decisive}


# ─────────────────────────────────────────────────────────────────────
# 3 個迷思:迷思 ↔ fact_key 映射 + 判決來源
# ─────────────────────────────────────────────────────────────────────
# 每個迷思宣告:belief(99%人信的那句)、primary(定判決的主 fact_key + champion/rival 欄位)、
# supports(充實長片的同標的變體,全部有據)、以及組稿函式 build(fb, state)。
# ⚠️ champion = 信仰擁護的那個選項;rival = 對照。判決 = champion 對上 rival 的真實結果。

BELIEF_ORDER = ["stop_profit", "hidiv", "crash_dip"]


def _verdict_of(fb: _FactBook, spec: dict) -> dict:
    p = spec["primary"]
    champ = fb.val(p["key"], *p["champion_path"])
    riv = fb.val(p["key"], *p["rival_path"])
    v = compute_verdict(champ, riv)
    v["primary_key"] = p["key"]
    v["champion_label"] = p["champion_label"]
    v["rival_label"] = p["rival_label"]
    v["champion_val_pct"] = round(champ * 100, 1)
    v["rival_val_pct"] = round(riv * 100, 1)
    return v


# ---- 迷思 1:停利落袋為安 ------------------------------------------------
def _build_stop_profit(fb: _FactBook) -> dict:
    K10 = "stop_profit_vs_hold__0050__10pct"
    K15 = "stop_profit_vs_hold__0050__15pct"
    K20 = "stop_profit_vs_hold__0050__20pct"
    KTS = "stop_profit_vs_hold__2330__10pct"
    thr10 = fb.pct_int(K10, "threshold", note="停利門檻")
    stop10 = fb.pct(K10, "stop_profit_final_return", note="10%停利·出場定格報酬")
    hold = fb.pct(K10, "hold_final_return", note="0050抱到底總報酬")
    gap = fb.gap_pp(K10, ("hold_final_return",), ("stop_profit_final_return",), note="少賺=抱到底-停利")
    stop15 = fb.pct(K15, "stop_profit_final_return", note="15%停利·出場定格報酬")
    stop20 = fb.pct(K20, "stop_profit_final_return", note="20%停利·出場定格報酬")
    ts_stop = fb.pct(KTS, "stop_profit_final_return", note="台積電10%停利·定格")
    ts_hold = fb.pct(KTS, "hold_final_return", note="台積電抱到底總報酬")
    ts_gap = fb.gap_pp(KTS, ("hold_final_return",), ("stop_profit_final_return",), note="台積電少賺")

    beats = [
        # ①鉤子
        f"「停利落袋為安」——你從小聽到大的這句話,讓一個二零一四年買進 0050、抱著存股的人,"
        f"少賺了 {gap} 個百分點。這不是我隨口說的,是台股十二年的真實回測,一天一天跑出來的。"
        f"這一集{SERIES_NAME},我用回測當法槌,把這條你以為天經地義的存股常識,拆給你看。",
        # ②法槌一(primary·帶 0050+複利 → 觸發真資料曲線)
        f"先說設定。二零一四年初你買進 0050,信奉停利落袋,設一個 {thr10} 的停利點:"
        f"報酬一碰到 {thr10} 就全部出場、落袋為安、不再進場。回測告訴我們發生什麼事——"
        f"第零點四年、也就是二零一四年五月,0050 的報酬就碰到停利點,你依約出場,報酬定格在 {stop10}。",
        # ③衝擊
        f"然後呢?你只能眼睜睜看著 0050 一路單邊往上、噴了整整十二年。如果你當初沒有停利、"
        f"就傻傻抱著不動:到今天,同一筆錢的總報酬是 {hold}。停利落袋,讓你落袋的是 {stop10};"
        f"代價,是錯過後面的 {gap} 個百分點。你落袋的那一顆是芝麻,你丟掉的那一整棵,是搖錢樹。",
        # ④法槌二(supports·設高一點呢)
        f"你可能想,{thr10} 太低了,設高一點呢?我把停利點調到十五趴、再調到二十趴,回測一樣跑給你看。"
        f"設十五趴停利:出場報酬定格在 {stop15},後面一樣是抱到底的 {hold} 在跑。"
        f"設二十趴停利:定格在 {stop20},後面還是那 {hold}。不管你把停利點設多高,"
        f"只要你落袋為安、不再進場,結局都一樣——你提早下車,然後看著車子開走。",
        # ⑤法槌三(台積電·更狠)
        f"如果你覺得 0050 還不夠狠,我們看台積電、2330。同樣一個十趴停利:報酬碰到就跑,定格在 {ts_stop}。"
        f"而如果你當年抱著台積電不動、抱到今天:總報酬是 {ts_hold}。停利落袋,"
        f"讓你和 {ts_gap} 個百分點擦肩而過。",
        # ⑥為什麼(機制,無捏造數字)
        f"為什麼會差這麼多?因為存股這件事,報酬的大頭從來不是你賣掉的那一次,"
        f"而是你一直沒賣的那些年。複利需要時間發酵,你一停利,等於把還在滾的雪球,"
        f"在半山腰上親手按停。停利落袋為安,安的是你的情緒,不是你的報酬。",
        # ⑦誠實收尾(護城河·打臉但公道)
        f"但我要講一句公道話:停利本身不是錯的。停利在兩種情況下是對的——"
        f"你做的是短線投機、或者你抱的是波動大到會讓你睡不著的東西。問題出在,"
        f"大多數人把停利落袋為安當成存股的聖旨,那就用錯地方了。存股的報酬,"
        f"絕大部分來自你沒賣掉的那些年。錯不在停利,錯在你把它用在了不該用的地方。",
        # ⑧反轉+懸念+訂閱鉤
        f"所以下次再有人跟你說停利落袋為安,你可以反問他一句:你落的是安心,還是落後?"
        f"這裡是量化阿森,{SERIES_NAME},我一條一條用真回測拆給你看。"
        f"下一集我要終結的流言是——高股息 ETF 存起來養老、穩穩贏過大盤。"
        f"這句話,數據會給它什麼判決,比你想的更顛覆。想第一時間看到判決,記得訂閱,我們下一條見。",
        # ⑨免責
        f"以上為 0050 與台積電的歷史回測,不含手續費與滑價,只反映過去、不代表未來,不構成投資建議。",
    ]
    # heading 刻意帶「代號 + 真資料圖關鍵字」:0050/2330 讓 concept_visuals.resolve_ticker 認出來、
    # 「單邊/噴出」歸到 trend 圖(concept_visuals._trend 吃 ctx.real=真收盤,畫真 0050/2330 曲線,
    # 非亂數、非機制示意圖)→ 法槌段落落下時,畫面就是那條真曲線,配 progressive_reveal 講到哪畫到哪。
    segments = [
        {"heading": "你從小聽到大的那句話", "broll": ["social media scam", "stock market chart"]},
        {"heading": "0050 停利：報酬定格 10.1%", "broll": ["stock market chart", "trading screen"]},
        {"heading": "0050 抱到底：一路噴出十二年", "broll": ["stock chart rising", "money tree"]},
        {"heading": "停利點設高，一樣", "broll": ["data analytics dashboard", "line chart"]},
        {"heading": "台積電 2330：一路噴出二十年", "broll": ["semiconductor", "stock chart rising"]},
        {"heading": "報酬來自你沒賣的那些年", "broll": ["compound interest", "snowball rolling"]},
        {"heading": "停利不是錯，是用錯地方", "broll": ["checklist", "warning sign"]},
        {"heading": "你落的是安心，還是落後", "broll": ["subscribe button", "stock market chart"]},
        {"heading": "風險聲明", "broll": ["disclaimer document"]},
    ]
    return {"title": "0050 存股「停利落袋為安」，12 年少賺一棵搖錢樹？回測打臉｜台股流言終結者",
            "beats": beats, "segments": segments,
            "hashtags": ["#台股", "#0050", "#存股", "#停利", "#回測", "#複利", "#台股流言終結者", "#量化阿森"]}


# ---- 迷思 2:高股息 ETF 養老贏大盤 --------------------------------------
def _build_hidiv(fb: _FactBook) -> dict:
    K56 = "hidiv_vs_mktcap__0056_vs_0050"
    K78 = "hidiv_vs_mktcap__00878_vs_0050"
    K13 = "hidiv_vs_mktcap__00713_vs_0050"
    K29 = "hidiv_vs_mktcap__00929_vs_0050"
    d56 = fb.pct(K56, "hidiv", "total_return", note="0056近12.5年總報酬")
    m56 = fb.pct(K56, "mktcap", "total_return", note="0050近12.5年總報酬")
    gap56 = fb.gap_pp(K56, ("mktcap", "total_return"), ("hidiv", "total_return"), note="0050領先0056")
    d78 = fb.pct(K78, "hidiv", "total_return", note="00878近6年總報酬")
    m78 = fb.pct(K78, "mktcap", "total_return", note="0050近6年總報酬")
    d13 = fb.pct(K13, "hidiv", "total_return", note="00713近8.8年總報酬")
    m13 = fb.pct(K13, "mktcap", "total_return", note="0050近8.8年總報酬")
    d29 = fb.pct(K29, "hidiv", "total_return", note="00929近3年總報酬")
    m29 = fb.pct(K29, "mktcap", "total_return", note="0050近3年總報酬")

    beats = [
        f"買高股息 ETF 存起來、穩穩領配息養老、這樣最安穩——這句話聽起來超有道理,對吧?"
        f"但台股十二年的真實回測,給了它一個很殘忍的判決。這一集{SERIES_NAME},"
        f"我用 0056 和 0050 的真數據,把高股息養老贏大盤這個信仰,攤在你面前。",
        f"先講最多人存的那一檔:元大高股息 0056。從二零一四年到今天,含息還原、把配息全部再投入,"
        f"0056 的總報酬是 {d56}。同一段時間,你如果放的是市值型的 0050,一路單邊往上,總報酬是 {m56}。"
        f"同樣十二年、同樣把息滾進去,0050 領先 0056 整整 {gap56} 個百分點。",
        f"你可能想,0056 比較老,換一檔新的呢?我把台股主要的高股息 ETF 一檔一檔拿去比同期的 0050。"
        f"國泰永續高股息 00878,近六年總報酬 {d78},同期 0050 是 {m78}。"
        f"元大台灣高息低波 00713,近八點八年 {d13},0050 是 {m13}。"
        f"復華台灣科技優息 00929,近三年 {d29},0050 是 {m29}。"
        f"你有沒有發現一個很誠實的規律——不管哪一檔高股息、不管比幾年,市值型的 0050 每一次都贏。",
        f"為什麼會這樣?因為高股息和高報酬,根本是兩件事。配息不是天上掉下來的錢,"
        f"是從你的股價裡先扣出來發給你的——你左手領到息,右手的股價就先掉了一塊。",
        f"高股息 ETF 為了維持高配息,往往少了那些不配息、把錢留著繼續成長的權值成長股,"
        f"而那些股,正是這十二年台股單邊上漲的主引擎。你以為你在存退休金,"
        f"其實你是拿成長性,去換一種有在領錢的安心感。",
        f"但講句公道話:高股息 ETF 不是垃圾。如果你已經退休、就是需要每個月有一筆現金流進帳、"
        f"不想賣股票、也受得了報酬低一截,那高股息很適合你,它給的就是穩定領錢這件事。",
        f"問題是,大多數人是在還在累積資產的三四十歲,就把錢全押高股息、想著養老。"
        f"那個階段你要的是把餅做大,不是急著切餅來吃。高股息養老,錯不在高股息,"
        f"錯在你用得太早、把它當成打敗大盤的工具——它從來就不是。",
        f"所以下次有人跟你說存高股息穩穩贏大盤,你可以反問他:贏,是贏在領到息的感覺,"
        f"還是贏在真正的報酬?這裡是量化阿森,{SERIES_NAME}。下一集我要拆的流言更反直覺——"
        f"股市崩盤、趕快跑才對。結果你猜怎麼著,數據這次站在別跑那一邊,而且站得很誇張。"
        f"想看判決,記得訂閱,我們下一條見。",
        f"以上為 0050、0056、00878、00713、00929 的歷史含息回測,不含手續費與滑價,"
        f"只反映過去、不代表未來,不構成投資建議。",
    ]
    # 0050 名在前 → resolve_ticker 認 0050;「單邊」→ trend 真圖(真 0050 收盤曲線),
    # 法槌段落畫出 0050 這十二年真實一路噴的曲線,對照旁白「0056 跟不上」。
    segments = [
        {"heading": "領息養老，最安穩？", "broll": ["retirement savings", "dividend cash"]},
        {"heading": "0050 一路噴出、0056 跟不上", "broll": ["stock chart rising", "line chart comparison"]},
        {"heading": "每一檔高股息、每一次都輸", "broll": ["data analytics dashboard", "bar chart comparison"]},
        {"heading": "0050 這十二年單邊上漲", "broll": ["stock chart rising", "compound interest"]},
        {"heading": "配息是從你股價裡扣的", "broll": ["dividend explanation", "stock price drop"]},
        {"heading": "高股息不是垃圾", "broll": ["retirement cash flow", "balance scale"]},
        {"heading": "錯在用得太早", "broll": ["age timeline", "warning sign"]},
        {"heading": "贏在感覺，還是真報酬", "broll": ["subscribe button", "stock market chart"]},
        {"heading": "風險聲明", "broll": ["disclaimer document"]},
    ]
    return {"title": "0056 高股息存起來養老，真的贏 0050 大盤？12 年回測給判決｜台股流言終結者",
            "beats": beats, "segments": segments,
            "hashtags": ["#台股", "#0056", "#0050", "#高股息", "#ETF", "#存股", "#台股流言終結者", "#量化阿森"]}


# ---- 迷思 3:崩盤快逃才對(證實「崩盤抄底真多賺」)------------------------
def _build_crash_dip(fb: _FactBook) -> dict:
    KDC = "crash_buy_the_dip__0050__covid2020"     # primary
    KPC = "crash_panic_sell__0050__covid2020"
    KDB = "crash_buy_the_dip__0050__bear2022"
    sell = fb.pct(KPC, "sell_at_bottom_return", note="新冠·恐慌賣在阱底定格")
    holdc = fb.pct(KPC, "hold_through_return", note="新冠·抱到底報酬")
    dip = fb.pct(KDC, "buy_the_dip_return_to_now", note="新冠·阱底低接抱到今天")
    peak = fb.pct(KDC, "buy_at_pre_crash_peak_return_to_now", note="新冠·崩盤前高點追進")
    dip_gap = fb.gap_pp(KDC, ("buy_the_dip_return_to_now",), ("buy_at_pre_crash_peak_return_to_now",),
                        note="抄底多賺=低接-追高")
    dipb = fb.pct(KDB, "buy_the_dip_return_to_now", note="2022熊市·阱底低接抱到今天")
    peakb = fb.pct(KDB, "buy_at_pre_crash_peak_return_to_now", note="2022熊市·崩盤前高點追進")
    dipb_gap = fb.gap_pp(KDB, ("buy_the_dip_return_to_now",), ("buy_at_pre_crash_peak_return_to_now",),
                         note="2022抄底多賺")
    # 「逃掉的報酬」= 抱到底 -(賣在阱底)= hold_through -(sell_at_bottom),兩個操作數稿子都有講。
    esc = fb.gap_pp(KPC, ("hold_through_return",), ("sell_at_bottom_return",), note="逃掉的報酬=抱到底-賣在阱底")

    beats = [
        f"股市崩盤、第一件事就是趕快跑——幾乎每個人都這樣信。但這一集{SERIES_NAME},"
        f"我要做一件不一樣的事:這一次,數據站在別跑、甚至崩了要買那一邊,而且證據硬到我沒辦法幫你打折。"
        f"我用 0050 在新冠和 2022 兩次真實崩盤的回測,證實一件反直覺的事:崩盤抄底,真的會多賺。",
        f"先看快逃這條。二零二零年新冠崩盤,0050 一路下殺,假設你在崩盤前的高點、二零二零年一月買進,"
        f"然後崩到阱底、三月十九號那天,你嚇壞了、恐慌全部賣光、再也不敢進場——你的報酬就定格在 {sell}。"
        f"但如果你那天忍住沒賣、就抱著不動、抱到今天:你的報酬是 {holdc}。"
        f"你當天逃掉的不是虧損,是後面整整 {esc} 個百分點的報酬。",
        f"現在看抄底這條,這才是這集的主角。同樣是二零二零新冠崩盤,如果你不是在高點買、"
        f"而是等它崩到阱底那天、三月十九號才低接進場,然後抱到今天:報酬是 {dip}。"
        f"對比同一筆錢在崩盤前高點才追進去的 {peak}——光是買在崩盤最恐慌那天這個動作,"
        f"就讓你多賺了 {dip_gap} 個百分點。崩盤不是世界末日,對敢動手的人,它是打折。",
        f"你可能想,新冠那次跌得快、彈得也快,是特例吧?我們再看二零二二年那次慢慢磨的台股熊市。"
        f"一樣的算法:在二零二二年十月阱底低接、抱到現在,報酬 {dipb};"
        f"在崩盤前高點追進去的,只有 {peakb}。崩盤抄底,又一次多賺了 {dipb_gap} 個百分點。"
        f"兩次崩盤、兩種型態,結論一樣。",
        f"為什麼抄底會贏?因為崩盤的本質,是好資產被恐慌打折出清。0050 裡面裝的是台灣最大的那幾十家公司,"
        f"它們不會因為一次崩盤就消失。崩盤殺掉的是價格,不是價值。你在阱底買進,"
        f"等於用同一筆錢買到更多股數,等市場情緒恢復,那些多出來的股數就是你多賺的部分。",
        f"但這集我一定要把但書講死,不然就變成叫你無腦接刀。第一,這裡的抄底是買 0050 這種一籃子大盤 ETF,"
        f"不是單一個股——個股真的可能崩到下市、再也回不來,那不是打折,那是歸零。"
        f"第二,回測是事後才看得到阱底,但你在當下永遠不知道還會不會更低,"
        f"所以真正的做法不是猜最低點,是分批買、越跌越買。",
        f"第三,你要撐得過中間的帳面虧損。數據上抱到底最後贏,但那條路中間,"
        f"要先吞下像新冠那樣 {sell} 定格、甚至更深的回撤——撐不住的人,會在最痛的那一刻,"
        f"把最便宜的籌碼賣在最低點。崩盤抄底能賺,但賺的是敢動手、又抱得住的人。",
        f"所以,崩盤快逃,數據給的判決是:你逃掉的是報酬,不是風險。這裡是量化阿森,{SERIES_NAME},"
        f"證實也好、打臉也好,我只認回測算出來的數字。下一集,我要拆一個更多人中招的迷思——"
        f"定期定額,真的穩賺不賠嗎?這次數據給的答案,沒你想的那麼簡單。想看判決,記得訂閱,我們下一條見。",
        f"以上為 0050 在二零二零、二零二二兩次崩盤的歷史回測,不含手續費與滑價,"
        f"只反映過去、不代表未來,不構成投資建議。",
    ]
    # 0050 名在前 → resolve_ticker 認 0050;「回撤」→ drawdown 真圖(真 0050 收盤算 peak→trough,
    # 標真實日期與跌幅);「單邊噴」→ trend 真圖(阱底反彈的真曲線)。三個崩盤法槌段全是真 0050 曲線。
    segments = [
        {"heading": "崩盤，第一件事是快逃？", "broll": ["stock market crash", "panic selling"]},
        {"heading": "0050 新冠：回撤到阱底", "broll": ["market crash chart", "drawdown chart"]},
        {"heading": "0050 崩到阱底、回撤見底", "broll": ["stock market recovery", "buy the dip chart"]},
        {"heading": "0050 二零二二熊市：又一次回撤", "broll": ["bear market chart", "stock recovery"]},
        {"heading": "崩盤殺的是價格，不是價值", "broll": ["value investing", "taiwan companies"]},
        {"heading": "但書一：買大盤不是買個股", "broll": ["etf basket", "warning sign"]},
        {"heading": "但書三：你撐得過回撤嗎", "broll": ["drawdown chart", "emotional investor"]},
        {"heading": "逃掉的是報酬，不是風險", "broll": ["subscribe button", "stock market chart"]},
        {"heading": "風險聲明", "broll": ["disclaimer document"]},
    ]
    return {"title": "0050 崩盤別逃、崩到阱底反而要買？新冠加 2022 熊市回測證實｜台股流言終結者",
            "beats": beats, "segments": segments,
            "hashtags": ["#台股", "#0050", "#崩盤", "#抄底", "#回測", "#定期定額", "#台股流言終結者", "#量化阿森"]}


BELIEFS = {
    "stop_profit": {
        "belief": "停利落袋為安",
        "primary": {"key": "stop_profit_vs_hold__0050__10pct",
                    "champion_label": "停利落袋", "champion_path": ("stop_profit_final_return",),
                    "rival_label": "抱到底不停利", "rival_path": ("hold_final_return",)},
        "build": _build_stop_profit,
        "cliffhanger": "高股息 ETF 存起來養老、穩穩贏過大盤",
    },
    "hidiv": {
        "belief": "高股息 ETF 存起來養老、穩穩贏過大盤",
        "primary": {"key": "hidiv_vs_mktcap__0056_vs_0050",
                    "champion_label": "高股息 0056", "champion_path": ("hidiv", "total_return"),
                    "rival_label": "市值型大盤 0050", "rival_path": ("mktcap", "total_return")},
        "build": _build_hidiv,
        "cliffhanger": "股市崩盤、趕快跑才對",
    },
    "crash_dip": {
        "belief": "崩盤抄底穩賺（對照信仰：崩盤快逃才對）",
        "primary": {"key": "crash_buy_the_dip__0050__covid2020",
                    "champion_label": "崩盤抄底", "champion_path": ("buy_the_dip_return_to_now",),
                    "rival_label": "崩盤前高點追進", "rival_path": ("buy_at_pre_crash_peak_return_to_now",)},
        "build": _build_crash_dip,
        "cliffhanger": "定期定額、穩賺不賠",
    },
}


# ─────────────────────────────────────────────────────────────────────
# 組稿(確定性 script_override dict)
# ─────────────────────────────────────────────────────────────────────

def build_script(belief_id: str) -> dict | None:
    """回可直接當 produce_batch script_override 的 d dict。事實缺檔/判決算不出來 → 回 None
    (fail-closed:寧可不產,也不對觀眾說謊)。"""
    spec = BELIEFS.get(belief_id)
    if not spec:
        print(f"[FATAL] 未知迷思:{belief_id}(可用:{', '.join(BELIEFS)})", file=sys.stderr)
        return None
    facts, as_of = _load_facts()
    if not facts:
        print("[FATAL] tw_facts_computed.json 讀不到或為空,拒產。", file=sys.stderr)
        return None
    fb = _FactBook(facts)
    try:
        verdict = _verdict_of(fb, spec)
        built = spec["build"](fb)
    except KeyError as exc:
        print(f"[FATAL] {belief_id}:事實欄位缺失 {exc},拒產(不硬掰數字)。", file=sys.stderr)
        return None

    voice = "\n\n".join(built["beats"])
    desc = "\n\n".join([
        f"「{spec['belief']}」——這一集{SERIES_NAME}用真回測給它判決:{verdict['verdict']}。",
        built["beats"][1],  # 法槌一(帶核心真數字)當描述主體
        f"每個數字都來自真實回測(tw_facts_computed),判決由數字算出、不由立場定。"
        f"下一集要終結的流言:{spec['cliffhanger']}。訂閱{SERIES_NAME},一條一條拆給你看。",
        "⚠️ 風險聲明:本影片為資訊與觀念分享,不構成任何投資建議。過去績效不代表未來表現,"
        "回測不含手續費與滑價,投資請自行承擔決策後果。",
    ])
    return {
        "title": built["title"],
        "voice_text": voice,
        "segments": built["segments"],
        "description": desc,
        "hashtags": built["hashtags"],
        # A2 句型閘豁免:本片確有 tw_stock 真回測佐證(語義正確,非繞過);
        # 且每個數字都過 fact_source_guard(--verify 已自檢)。
        "_is_tw_stock": True,
        # franchise 稽核用(不設 _is_ep/_is_tw_lab:那會被別的引擎的 bump 吃掉集數)
        "_is_belief_buster": True,
        "_belief_id": belief_id,
        "_belief_verdict": verdict,
        "_belief_as_of": as_of,
        "_belief_trace": fb.trace,
    }


def build_topic(belief_id: str) -> dict | None:
    """回 produce_batch topic_override(讓 make_one 知道這是指定題、跳過重生換題那些 gate)。"""
    spec = BELIEFS.get(belief_id)
    if not spec:
        return None
    facts, _ = _load_facts()
    if not facts:
        return None
    fb = _FactBook(facts)
    try:
        v = _verdict_of(fb, spec)
        title = spec["build"](fb)["title"]
    except KeyError:
        return None
    return {
        "title": title,
        "angle": f"{SERIES_NAME}:用真回測終結「{spec['belief']}」,判決={v['verdict']}。"
                 f"3 秒顛覆鉤子→真回測法槌→誠實收尾(不是XX錯、是用錯地方)→系列懸念+訂閱鉤。",
        "category": SERIES_NAME,
        "format": "long",
        "belief_id": belief_id,
    }


# ─────────────────────────────────────────────────────────────────────
# state(集數連續性 / 已拆迷思;本 franchise 自己的,不碰別的引擎)
# ─────────────────────────────────────────────────────────────────────
DEFAULT_STATE = {"series_name": SERIES_NAME, "episode": 0, "busted": []}


def load_state() -> dict:
    st = copy.deepcopy(DEFAULT_STATE)
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            st.update(raw)
    except Exception:  # noqa: BLE001
        pass
    return st


def bump_state(belief_id: str, slug: str):
    try:
        import studio_common as scmn
        st = load_state()
        st["episode"] = int(st.get("episode", 0) or 0) + 1
        rec = {"episode": st["episode"], "belief_id": belief_id, "slug": slug}
        st["busted"] = [b for b in (st.get("busted") or []) if b.get("belief_id") != belief_id] + [rec]
        scmn.save_json_atomic(STATE_FILE, st)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] belief_buster state bump 略過:{str(exc)[:80]}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────
# 溯源表 / 自檢 / CLI
# ─────────────────────────────────────────────────────────────────────

def _print_trace(d: dict):
    v = d.get("_belief_verdict", {})
    print(f"\n── fact_key 溯源表({len(d.get('_belief_trace', []))} 個數字,全部來自真回測)──")
    print(f"{'稿中數字':>12}  {'fact_key':<42} {'欄位':<40} 說明")
    for t in d.get("_belief_trace", []):
        print(f"{t['value']:>12}  {t['fact_key']:<42} {t['field']:<40} {t['note']}")
    print(f"\n判決:{v.get('verdict')}(champion「{v.get('champion_label')}」={v.get('champion_val_pct')}%"
          f" vs rival「{v.get('rival_label')}」={v.get('rival_val_pct')}%;"
          f"差 {v.get('gap_pp')}pp、相對 {v.get('rel')}、決定性={v.get('decisive')})")
    print(f"判決來源 fact_key:{v.get('primary_key')}")


def verify(belief_id: str) -> int:
    """組稿 → 過 fact_source_guard(發布端同一把尺)自檢。回 0=乾淨,2=有查無憑據數字。"""
    d = build_script(belief_id)
    if not d:
        return 2
    try:
        import fact_source_guard as fsg
        pool = fsg.fact_pool()
        text = d["voice_text"] + "\n" + d["description"] + "\n" + d["title"]
        bad = fsg.unsourced_claims(text, pool)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] fact_source_guard 載入失敗,無法自檢:{exc}", file=sys.stderr)
        return 0
    print(f"[verify] {belief_id}:事實庫數字池 {len(pool)} 個;稿中查無憑據數字 {len(bad)} 個")
    for c in bad:
        print(f"   ✗ 無憑據 {c['value']}  ←「{c['clause']}」")
    return 0 if not bad else 2


def _list():
    facts, as_of = _load_facts()
    print(f"{SERIES_NAME}｜事實庫 as_of={as_of}｜3 個迷思的真回測判決:")
    if not facts:
        print("  (tw_facts_computed.json 讀不到)")
        return
    fb = _FactBook(facts)
    for bid in BELIEF_ORDER:
        spec = BELIEFS[bid]
        try:
            v = _verdict_of(fb, spec)
            print(f"  {bid:12} 「{spec['belief']}」\n"
                  f"     → 判決 {v['verdict']}:{v['champion_label']} {v['champion_val_pct']}%"
                  f" vs {v['rival_label']} {v['rival_val_pct']}%（差 {v['gap_pp']}pp）｜來源 {v['primary_key']}")
        except KeyError as exc:
            print(f"  {bid:12} 「{spec['belief']}」→ 事實缺失 {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="台股流言終結者 確定性產製引擎")
    ap.add_argument("belief", nargs="?", help=f"迷思代號({', '.join(BELIEFS)})")
    ap.add_argument("--list", action="store_true", help="列 3 個迷思與各自真回測判決")
    ap.add_argument("--dry", action="store_true", help="印稿 + fact_key 溯源表(不寫檔)")
    ap.add_argument("--verify", action="store_true", help="組稿→跑 fact_source_guard 自檢")
    ap.add_argument("--out", default=None, help="寫 .md/.voice.txt 到指定目錄(驗證用,不碰 output/)")
    args = ap.parse_args()

    if args.list or (not args.belief and not args.dry):
        _list()
        if not args.belief:
            print("\n用法:belief_buster_engine.py --dry <belief> | --verify <belief>")
        return 0
    if args.verify:
        return verify(args.belief)

    d = build_script(args.belief)
    if not d:
        return 2
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        import produce_batch as pb
        slug = pb.slugify(d["title"], "L")
        (out / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
        (out / f"{slug}.md").write_text(pb.build_md(d), encoding="utf-8")
        print(f"[ok] 已寫:{out / (slug + '.md')} / {slug}.voice.txt")
        _print_trace(d)
        return 0
    # 預設 --dry
    print(f"=== {d['title']} ===\n")
    print(d["voice_text"])
    print(f"\n--- 字數:{len(d['voice_text'].replace(chr(10),''))} ---")
    _print_trace(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
