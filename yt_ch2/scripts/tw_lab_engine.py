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
# legacy 退役判定的**單一真相來源**（2026-07-17 收斂）：原本這裡自己複製了一份
# _LEGACY_SUPERSEDED_BY，跟 tw_facts_engine 那份重複 —— 而「同一個規則實作兩次必然 drift」
# 正是這次一連串誠信事故的共同成因，所以收斂成一份，由 computed 的產生者持有（它最清楚 schema）。
# 循環 import 檢查：tw_facts_engine 模組層只 import 標準庫（argparse/datetime/json/sys/time/
# pathlib），pandas/yfinance 都在函式內才 import，且它不 import 本模組 → 無循環、無重量級副作用。
# 這裡刻意用**模組層 import**（與上面 studio_common 同風格）：萬一它壞了就讓 tw_lab_engine
# 整支 import 失敗，由 produce_batch 既有的 try/except 攔下(franchise 那批跳過、產線續跑)，
# 而**不是**靜默退回「沒有去重」把 legacy 放回素材池——誠信 gate 只能 fail-closed，不能 fail-open。
from tw_facts_engine import drop_superseded_legacy  # noqa: E402

STUDIO = ROOT / "STUDIO"
TW_LAB_STATE = STUDIO / "tw_lab_state.json"
TW_FACTS = STUDIO / "tw_stock_facts.json"
TW_FACTS_COMPUTED = STUDIO / "tw_facts_computed.json"

SERIES_NAME = "台股真相實驗室"
EPISODES_PER_SEASON = 10  # 對齊 ep_engine：每 10 集收一季，重新排序(反映事實庫可能已更新 as_of)

# ── franchise 產出格式(2026-07-19 訂閱轉換診斷落地)──────────────────────────
# 診斷(STUDIO/quality_scores.json 188 支有數據片逐支核對 + Analytics creatorContentType 90d):
#   · 173 支 Short 訂閱數上限就是 1；拿到 2/3/4/9 訂閱的片**全部**是長片或開播預告,沒有例外。
#   · 帶「追劇鉤」的 EP/系列/實測 Shorts 66 支只換 2 訂閱;同題材長片 10 支換 4 訂閱(1/6 片數、2 倍訂閱)。
#   · 產線自己早算過(daily_publish.py:588):Shorts 訂閱轉換 0.080% vs 長片 0.43–0.96%,
#     去離群值後雙比例 z=3.81 p=0.0001。方向鐵證。
# 結論:這個 franchise 的**存在理由就是訂閱轉換**(見檔頭),卻一直產成 Shorts=結構上換不到訂閱。
# 故 franchise 正片改走長片。長片走【多事實 bundle】(produce_batch 既有的 _tw_facts_context
# 已為台股題注入多組相關真回測)撐 8-10 分鐘深段,不是把單一事實硬拉長;誠信不變:每個數字都來自
# 注入的真事實、不得自行編造或換算(見 produce_batch.TW_LAB_LONG_RULES)。
# ⚠️ 這是「franchise 主力格式」的單一開關;要回短片或做長短混排,只改這一個常數即可。
FRANCHISE_FORMAT = "long"

# 上週贏家分析(STUDIO/REPORTS/2026-07-13_每週贏家分析.md)：含這些詞的片平均觀看 ≥ 全站115%。
# 拿來給 40 組事實排優先序，讓 franchise 前幾集就是已驗證會被看的角度，不是隨機順序。
WINNER_KW = ("0050", "你猜", "vs", "VS", "剩多少", "小白", "複利", "停損", "差多少",
             "手續費", "微笑曲線", "定投", "定期定額", "All in", "all in", "ALL IN",
             "一次投入", "ETF", "存股")


# ── legacy 事實庫「同一件事、兩個答案」的結構性封鎖（2026-07-17 已發布誠信事故）─────
# 事故：tw_stock_facts.json(legacy, tw_stock_data.py 產) 與 tw_facts_computed.json
# (tw_facts_engine.py 產) 是同一組回測的兩份快照，但**回測窗口不同**，故數字互斥：
#   · legacy buyhold_vs_timing_twii ：_fetch_close(^TWII, 20) → 近 20.1 年 → 長抱年化 10.2%、
#     擇時 8.9% → 結論「長抱贏」
#   · computed buyhold_vs_timing__TWII：period="max" → 1997-07-02~ 共 29 年 → 長抱年化 5.7%、
#     擇時 6.9% → 結論「擇時贏」
# 兩者各自算術上都對，但講的是同一個問題(台股大盤長抱 vs 跌破年線擇時)，結論卻相反。
# 已發布災情：Jad4_8skToo(S1EP10, 用 computed 講「長抱 5.7% 輸擇時 6.9%」) 與
# ogQukwzFn1s(S2EP3, 用 legacy 講「長抱 10.1% 贏擇時 8.8%」) 兩支片同時在線互打臉。
# 為什麼舊的 _dedup_sig() 沒擋住：它比對 desc 文字，而兩支引擎的 desc 措辭不同
# ("大盤 長抱不動 vs 跌破年線就跑的簡單擇時" vs "加權指數（大盤） 長抱不動 vs 簡單擇時（年線）")
# → 簽名不同 → 兩組都進了 seeded_keys → 各自出了一集。文字比對本質上防不住這件事。
#
# 修法：改用**結構性**(key 對 key)封鎖，不靠措辭。legacy 全部 5 組事實的主題，computed
# 都有對應且更完整的版本(50 組 ⊃ legacy 5 組)，且 computed 每筆都帶 period/start/end/
# method/source/computed_at(legacy 全缺)，故 computed 存在時一律以 computed 為準、丟棄 legacy。
# 另一個非丟不可的理由：legacy 的窗口是 `today - 20*366 天` 的**滾動窗**，每天重算會漂移
# (已發布 EP1 講 0050 十年 All-in「813%」，今天同一個 key 已變成 804.5%)，等於已發布影片的
# 數字事後永遠對不回來、fact_source_guard 溯源必然查無憑據。computed 的 __full 系列是固定起點。
# 保留 fallback：萬一 computed 缺檔/該組算不出來，legacy 仍可用(總比沒有真數據好)。
# 判定表與實作見 tw_facts_engine.LEGACY_SUPERSEDED_BY / drop_superseded_legacy()（單一真相來源）。


def _load_facts():
    """合併讀 tw_stock_facts.json + tw_facts_computed.json，回 ({key: fact_dict}, as_of)。
    邏輯對齊 produce_batch._load_tw_facts()（獨立複製一份，避免 tw_lab_engine ← produce_batch
    互相 import 造成循環依賴）。任何一份缺檔/壞掉都靜默跳過。
    2026-07-17 起：computed 有對應版本的 legacy key 一律丟棄
    （見 tw_facts_engine.drop_superseded_legacy），確保 franchise 結構上不可能對同一件事
    引用到兩個互斥的答案。"""
    merged_results: dict = {}
    origin: dict = {}          # key -> 來源檔名（決定 as_of 要報哪一份的日期）
    as_of_by_file: dict = {}
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
                    if k not in merged_results:
                        merged_results[k] = v
                        origin[k] = p.name
            as_of_by_file[p.name] = str(d.get("as_of", ""))
        except Exception:  # noqa: BLE001
            continue

    _before = set(merged_results)
    merged_results = drop_superseded_legacy(merged_results)
    for _dropped in _before - set(merged_results):
        origin.pop(_dropped, None)

    # as_of 要如實反映「活下來的事實實際來自哪份檔」——不能再像舊版一樣無腦取第一份
    # (legacy 每天重算 as_of=今天，computed 可能是前幾天算的；報 legacy 的日期會把
    #  computed 的數字標成今天算的，那本身就是一種不實標註)。
    files_used = {origin[k] for k in merged_results if k in origin}
    if TW_FACTS_COMPUTED.name in files_used:
        as_of = as_of_by_file.get(TW_FACTS_COMPUTED.name, "")
    else:
        as_of = as_of_by_file.get(TW_FACTS.name, "")
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
    """回傳依贏家關鍵字命中數排序的 (key, fact) 清單；同簽名(同標的+同比較法)的多組事實會被
    **排到不同輪次**而不是丟掉，命中數同分按 key 字母序排序(確定性)。

    🔴 2026-07-17 修「排序把最好的素材丟進垃圾桶」：
    上面那段註解一直宣稱同簽名的「其餘讓下一輪/下一季再用」，但舊實作是
    `if sig in seen_sig: continue` —— 那是**永久丟棄**，不是延後：fact_order() 每次都重算且
    確定性排序，被丟的永遠是同一批，於是它們**一輪都輪不到**。實測後果：事實池 50 組 →
    fact_order 只剩 45，被吃掉的 5 組**全是 `__full`**(0050近12年/0056近18年/006208近14年/
    2330近26年/TWII近29年)——資訊量最大、期間最長的那批，而保留的是較短的 `__10y`。
    更實際的傷害：seed_topic_bank 的 `skip = used | seeded` 已涵蓋 42/45，franchise
    **只剩 3 題可種**(素材見底)；那 5 組 `__full` 從沒被 seed 過，卻因為被丟出 order 而
    **結構上永遠拿不到**。修好後可種題數 3 → 8。

    為什麼是「排到後面」而不是「直接移除這道去重」：
      · 這道去重**原本的用途**(檔頭註解寫明)是擋 legacy vs computed 的跨檔重複
        (allin_vs_dca_0050_10y vs dca_vs_allin__0050__10y)——那件事現在已由
        tw_facts_engine.drop_superseded_legacy() 用 **key 對 key** 結構性解決，
        而且解得比文字比對正確(文字比對正是當初漏掉 buyhold_vs_timing 那組、釀成
        Jad4_8skToo/ogQukwzFn1s 兩支片互打臉的原因)。所以它當「丟棄器」已無價值。
      · 但它編碼的**顧慮仍然成立**：本 franchise 的賣點就是「一集一組新事實」，
        `dca_vs_allin__0050__10y`(近10年) 與 `__full`(近12年) 分數相同 → 排序後**緊鄰**
        → 連續兩集講幾乎同一件事，正是檔頭註解怕的那個自砸招牌。
      · 故保留簽名、只把角色從**丟棄**改成**延後**：第一輪每個簽名各出一組(依分數)，
        第二輪才輪到同簽名的第二組 → 零損失 + 最大間隔，正是註解一直宣稱的行為。
    (`_dedup_sig` 洗掉「近N年」在這個新角色下是**正確**的：我們要的就是「同標的同比較法」
     這個粒度來決定誰該被拉開；期間不同 = 不同事實，所以只拉開、不合併。)
    """
    facts, _ = _load_facts()
    items = [(k, v) for k, v in facts.items() if isinstance(v, dict) and v.get("summary")]
    items.sort(key=lambda kv: (-_score(kv[0], kv[1]), kv[0]))
    groups: dict = {}
    for k, v in items:
        groups.setdefault(_dedup_sig(v), []).append((k, v))
    # dict 保序(Py3.7+)且 items 已排序 → groups 依「該簽名最高分那組」的分數序排列，確定性。
    out = []
    rnd = 0
    while True:
        wave = [g[rnd] for g in groups.values() if len(g) > rnd]
        if not wave:
            break
        out.extend(wave)
        rnd += 1
    return out


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


def _fact_period(fact):
    """回傳這組事實可信的回測期間字串；抓不到回 ""。
    2026-07-17 事故修補：legacy 事實(tw_stock_data.py 產)完全沒有 period/start/end 欄位，
    舊版 fact_data_block 遇到就**靜默省略「期間」那一行** → 寫稿 LLM 拿不到任何年數資訊
    → 自己瞎猜一個。已發布的 ogQukwzFn1s(S2EP3) 就是這樣把 20.1 年的回測數字講成
    「大盤長抱10年」、標題還寫「10年回測揭真相」。年數是誠信聲稱的一部分，不能靠猜，
    故這裡從 data.start/end 或 data.years 補算，讓期間永遠有值。"""
    period = str(fact.get("period") or "").strip()
    if period and period != "?~?":
        return period
    data = fact.get("data")
    if isinstance(data, dict):
        start, end = data.get("start"), data.get("end")
        if start and end:
            return f"{start}~{end}"
        # 崩盤類事實(crash_panic_sell__* / crash_buy_the_dip__*)：tw_facts_engine
        # calc_crash_episode() 回的是 peak_date/trough_date/latest_date，沒有 start/end，
        # 導致上游 add() 把 period 組成字面上的 "?~?" 餵給寫稿 LLM。這類事實的聲稱其實是
        # 「崩跌前高點買進 → 抱/賣 → 到最新一天」，故期間＝peak_date~latest_date。
        peak, latest = data.get("peak_date"), data.get("latest_date")
        if peak and latest:
            return f"{peak}~{latest}"
        years = data.get("years")
        try:
            if years is not None and float(years) > 0:
                return f"回測區間長度 {float(years):.1f} 年（原始事實未記起訖日）"
        except (TypeError, ValueError):
            pass
    return ""


def fact_data_block(key, fact, as_of="", long_mode=False):
    """把單一事實格式化成可直接塞進寫稿 prompt 的實證區塊(比 produce_batch._tw_facts_context
    更聚焦——只給『這集要用的這一組』，不是一次塞 6 組讓 LLM 自己選,避免混題)。

    long_mode(2026-07-19 訂閱轉換診斷·長片變體):長片(8-10 分鐘)拿單一事實會被迫灌水→低完播→
    換不到訂閱。長片模式下,這組事實是本集**主軸**(脊椎),但允許搭配 produce_batch 另注入的
    【本片實證數據】多組同題材真回測充實深段——把「只能用這一組」放寬成「主軸這組必用、其餘限注入的
    真數字」。誠信不放寬:一個數字都不能自己編/換算/估,period 的年數硬規則照樣生效。
    long_mode=False(預設)行為與舊版 byte-identical,短片路徑零變化。"""
    if not fact:
        return ""
    desc = str(fact.get("desc") or key)
    claim = str(fact.get("claim") or fact.get("summary") or "")
    period = _fact_period(fact)
    source = str(fact.get("source") or "")
    if long_mode:
        header = ("\n【★本集主軸實證數據(台股真回測·本集的脊椎,必用;其餘細節限用另一區塊"
                  "【本片實證數據】的注入真數字,一律不得自行編造/換算/估計)】")
    else:
        header = "\n【★本集唯一指定實證數據(台股真回測·只能用這一組,不得混用其他標的/期間的數字)】"
    lines = [header, f"  題材：{desc}"]
    if claim:
        lines.append(f"  數字：{claim}")
    if period:
        lines.append(f"  期間：{period}")
        lines.append("  ★年數硬規則：標題/旁白只要提到回測年數，必須與上面「期間」一致，"
                     "不得四捨五入到另一個整數年、不得自己另編一個年數(例如期間是 20.1 年就不能講「10年回測」)。")
    else:
        # fail-closed：沒有可信期間就明令不准講年數，寧可少一個賣點也不能讓 LLM 掰
        lines.append("  ★期間：未知(本組事實沒有可信的起訖/年數欄位)——標題與旁白一律"
                     "不得出現任何回測年數或「近N年」字樣。")
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
        "format": FRANCHISE_FORMAT,
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
            "format": FRANCHISE_FORMAT,
            "tw_lab_key": k,
        })
    try:
        import topic_bank
        added = topic_bank.add_topics(items, source="tw_lab", front=True)
    except Exception:  # noqa: BLE001
        # 2026-09-05:**不要吞**。呼叫端(produce_batch 的 `seed_topic_bank(2)`)
        # 已經備好 `except Exception: print("[warn] 台股真相實驗室種題略過…")`,
        # 而這裡 return 0 把例外吃掉 —— 那則 warn 從來沒有機會印過。
        # **內層靜默,讓外層準備好的告警變成一個不會叫的警報。**
        # 「不寫 state」的語意不受影響:raise 走不到下面的 _save_state(),
        # seeded_keys 仍不會被標記,下一輪照樣重試(這點原本就是對的)。
        # 呼叫端 catch 了,整批產製不會中斷,只多印一行 warn。
        # ⚠️ 同一份 tw_lab_engine.py 在 youtube_channel/ 與 yt_ch2/ 各有一份
        #    (逐位元組相同),兩處必須一起改 —— 這個 repo 的慣犯就是
        #    「同一件事兩份實作,只修了其中一份」。
        raise
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
