#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ep0_engine.py — 【系列說明片】確定性產製引擎(舊稱 EP.0 開播預告)。

為什麼有這支(2026-07-17 Analytics 90d 實測):
  全頻道訂閱轉換的贏家不是任何 Shorts，而是**系列說明/開播型長片**：
    · ijCNjwEDRnc「實測企劃 EP.0 規則先講死」 300 觀看 → 9 訂閱 = 3.00%(佔全頻道訂閱 25%)
    · Zm5zLEAs30Y「TradingView 全攻略開播」     80 觀看 → 4 訂閱 = 5.00%
    · 對照(n 小,只當方向參考勿當定論):Shorts 平均約 0.080%、長片 0.43–0.96%
  最高轉換那支完播率只有 25.88% → **本格式的 KPI 是訂閱，不是完播**。

★骨架(7 拍，蒸餾自上述兩支已驗證範本，不是憑空設計)：
  ①敵人 ②宣告系列存在 ③身分憑證 ④規則先講死 ⑤規模承諾 ⑥為什麼你該追 ⑦CTA明講訂閱+加入鉤
  轉換機制＝「宣告系列存在 + 規則先講死 + 承諾未來還有一整組」三件事，
  **不需要「這是第零集」這個謊也成立**(2026-07-17 誠信稽核結論)。

★2026-07-17 誠信大修(獨立驗證判定前一版「不可用:會對觀眾說謊」)——四個破口與修法：
  1. 【假話】舊 tw_lab 規則②宣稱「手續費、稅、滑價都算進去」。複驗 tw_facts_engine.py:471/:677
     明寫「未計手續費/滑價」，全檔零成本模型，55 組回測沒有一組計成本。
     ⚠️ 這句還長在「規則先講死」段——那段全部的作用是證明「我值得你訂」。
     用假話證明誠信＝拿誠信換訂閱，比不做還糟。
     → 改成**誠實講出這個限制**(見 COST_DISCLOSURE):不含成本 ⇒ 高週轉策略(停利)在我這裡被高估。
       這句是**自我設限**，方向天生安全:就算哪天真的加了成本模型，最壞也只是低報自己。
  2. 【定位假】兩支都自稱「開播/第零集」，但兩個系列都已公開播出(實測 tw_lab 14 支已發布、
     個股體檢 EP1 台積電 rwdhTBAfXQI 已發布)。觀眾點一下頻道就戳破。
     → 定位由 _published() 讀 uploaded_ledger 真檔**算出來**:已發布>0 一律走「系列說明/中途加入」，
       premiere 語氣結構上不可能生成;另加 mode='premiere' 顯式 fail-closed 拒產。
  3. 【數字灌水】舊 _inv_tw_lab 只讀 used_keys，但 tw_lab_engine.py:337 每季收官會清空該欄位
     (它是「本季已用」不是「歷來」)→ 宣稱數字會灌水，且**越播越膨脹**(下季重置會宣稱「跑完 55 組」)。
     → used = used_keys ∪ episodes[].key(episodes 不會被季重置清空，是歷來權威名單)。
  4. 【語意重複】事實庫同一組回測有兩個名字(legacy tw_stock_facts.json vs tw_facts_computed.json)，
     且**數字還不一樣**(實測 buyhold_vs_timing_twii 年化 10.2%/20.1年 vs buyhold_vs_timing__TWII
     年化 5.7%/29年 —— 同一件事兩個答案，legacy 是過期快照)。直接數 key 會把同一組回測數兩次。
     → _canon() 語意去重(見該函式)。實測 55 key → 47 組 → 未用 29 組(舊算法會宣稱 46,灌水 58%)。
  5. 【fail-closed 破口】舊 `stock = max(ready, planned)`:checkup facts 損壞/清空而 backlog 還在時
     ready=0/planned=1916 → max 過關，實測真的產出「目前體檢完 0 檔」這種荒謬承諾。
     → 改 min():任一邊塌掉就拒產。

★誠信總原則(本檔的存在理由)：
  **宣稱句必須能從真實檔案算出或查證，不可寫死在 SERIES 表當文案。**
  SERIES 表只放「不含數字、且已複驗為真」的靜態素材;所有帶數字/帶定位的句子一律由
  inventory()+_published() 的真實存量**算出來** → 結構上不可能開空頭支票。
  數字一律取**保守下界**(寧可低報):語意去重寧可多併，published 取可查證的精確值。

★為什麼確定性模板、不走 LLM：
  1. 骨架已由實證定死，LLM 只會偏離
  2. produce_batch.HOOK_RULES 全是「完播率＝唯一KPI」「前 3 秒丟精確數字」——與本格式的訂閱 KPI
     直接衝突，還會逼 LLM 生數字 → 誠信風險
  3. 結構上不含**自稱**績效數字(範本裡的 812% 是引用敵人的神話，不是自稱)→ 天生過 fact_guard
  4. 零 LLM 成本

★集數連續性(memory 記載過 EP 編號大亂事故)：
  build_topic() 刻意**不設** _is_ep / _is_tw_lab 旗標 —— produce_batch 的 _bump_ep/_bump_tw_lab
  只在那兩個旗標為真時遞增集數。本片是系列說明不是正片，不可吃掉一集編號。
  ⚠️ 標題也**刻意不含「EP<數字>」**:daily_publish.py:309 的 _EP_NUM_RE 會把「EP.0」認成
     「台股真相實驗室第 0 集」→ 整個系列的發布順序閘會拿它當最小集數擋住 EP9/EP10。
     現在標題無 EP token → _series_of() 回 (None, None) → 不受該閘影響。

用法：
  python scripts/ep0_engine.py --list                    # 列各系列狀態、存量與已發布集數
  python scripts/ep0_engine.py --dry tw_lab              # 只印稿，不寫檔(驗證用)
  python scripts/ep0_engine.py --dry --mode premiere tw_lab   # 驗 fail-closed(已發布>0 應拒產)
  python scripts/ep0_engine.py --out <dir> tw_lab        # 寫 .md/.voice.txt 到指定目錄(不碰 output/)
  python -m produce_batch --ep0 tw_lab                   # 走正式產線(配音+渲染)

驗證：python -m py_compile scripts/ep0_engine.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"

# 存量下限:低於這個數就不准產(承諾會變空頭支票)。
# 定在 8 是因為承諾語氣是「一整組已經排好」，個位數撐不起這句話。
MIN_STOCK = 8


def _load(path: Path):
    """讀 JSON，讀不到/壞檔回 None(絕不丟例外中斷產線)。"""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────
# 已發布集數(定位的命脈:決定這支是「開播」還是「中途加入指南」)
# ─────────────────────────────────────────────────────────────────────

def _ledger() -> dict:
    """uploaded_ledger.json = {slug: video_id}，已發布的唯一權威。"""
    d = _load(LEDGER)
    return d if isinstance(d, dict) else {}


def _pub_tw_lab() -> int:
    """台股真相實驗室已發布集數 = state.episodes[].slug 真的在 ledger 裡的數量(實測 14)。
    ⚠️ 不可改用「標題/slug 關鍵字比對」:slugify 只留前 26 字，系列名掛在標題尾端會被截斷——
       實測 ledger 裡只有 3 支 slug 還看得到「臺股真相」，用關鍵字數會少報 11 支(14→3)。
       episodes[] 是引擎自己寫的權威名單，與 ledger 交集才是「真的發出去了」。"""
    st = _load(STUDIO / "tw_lab_state.json") or {}
    led = _ledger()
    return sum(1 for e in (st.get("episodes") or [])
               if isinstance(e, dict) and e.get("slug") and led.get(e["slug"]))


def _pub_checkup() -> int:
    """個股體檢已發布集數(實測 1:L_個股體檢EP1台積電… → rwdhTBAfXQI)。
    本系列沒有 state 檔，改用產線慣例:標題固定把「個股體檢」放最前面故 slug 不會被截斷
    (依據同 playlist_engine._match_stock_checkup 的理由)。"""
    return sum(1 for slug in _ledger() if "個股體檢" in slug)


# ─────────────────────────────────────────────────────────────────────
# 語意去重(治「同一組回測換個名字被數兩次」)
# ─────────────────────────────────────────────────────────────────────
# 事實庫有兩份檔、兩套命名(legacy 單底線 vs computed 雙底線)，同一組回測會有兩個 key：
#   allin_vs_dca_0050_10y  ↔ dca_vs_allin__0050__10y
#   buyhold_vs_timing_twii ↔ buyhold_vs_timing__TWII
#   hidiv_0056_vs_0050     ↔ hidiv_vs_mktcap__0056_vs_0050
# 另外 crash_panic_sell__X__Y 與 crash_buy_the_dip__X__Y 共用**同一個 data dict**
# (實測數值完全相同，只是挑不同欄位講故事)→ 是 1 組回測 2 種講法，不是 2 組回測。
#
# 去重做法:把 key 拆成 (家族, 標的集合, 參數集合) 三元組當語意指紋。
# 家族用 frozenset 比對 → allin_vs_dca 與 dca_vs_allin 天生同一組(集合無序)。
_TICKER_RE = re.compile(r"^(?:\d{4,6}[a-z]?|twii)$")
_PARAM_RE = re.compile(r"^(?:\d+y|full|\d+pct|\d+ma|bear\d{4}|covid\d{4}|crisis\d{4})$")

# 同一種回測的不同寫法 → 收斂成同一個家族名。
# 未列入的家族用「token 排序後接起來」當名字:認不出來就**不合併**(寧可分開算,不會誤併)。
_FAMILY_ALIASES = {
    frozenset({"allin", "vs", "dca"}): "dca_vs_allin",
    frozenset({"hidiv", "vs"}): "hidiv_vs_mktcap",
    frozenset({"hidiv", "vs", "mktcap"}): "hidiv_vs_mktcap",
    frozenset({"crash", "buy", "the", "dip"}): "crash_event",
    frozenset({"crash", "panic", "sell"}): "crash_event",
}


def _canon(key: str) -> tuple:
    """回 key 的語意指紋 (家族, 標的, 參數)。同指紋＝同一組回測，只能算一次。"""
    toks = [t for t in re.split(r"_+", str(key).lower()) if t]
    syms = frozenset(t for t in toks if _TICKER_RE.match(t))
    params = frozenset(t for t in toks if _PARAM_RE.match(t))
    fam = frozenset(t for t in toks if t not in syms and t not in params)
    return (_FAMILY_ALIASES.get(fam) or "_".join(sorted(fam)), syms, params)


def _fact_keys() -> set:
    """兩份事實檔的所有 key(tw_lab_engine 同源)。"""
    keys = set()
    for name in ("tw_stock_facts.json", "tw_facts_computed.json"):
        d = _load(STUDIO / name) or {}
        r = d.get("results")
        if isinstance(r, dict):
            keys |= set(r.keys())
        elif isinstance(r, list):
            for it in r:
                if isinstance(it, dict) and it.get("key"):
                    keys.add(str(it["key"]))
    return keys


# ─────────────────────────────────────────────────────────────────────
# 存量查證(誠信命脈:承諾的數字全部從這裡算出來)
# ─────────────────────────────────────────────────────────────────────

def _inv_tw_lab() -> dict:
    """台股真相實驗室:數「還沒拍過的真回測」組數(語意去重後)。
    used 必須是 used_keys ∪ episodes[].key —— 只讀 used_keys 會灌水,因為
    tw_lab_engine.py:337 每季收官清空 used_keys(那欄是「本季已用」不是「歷來」)。"""
    keys = _fact_keys()
    groups: dict = {}
    for k in keys:
        groups.setdefault(_canon(k), []).append(k)

    st = _load(STUDIO / "tw_lab_state.json") or {}
    used_keys = set(st.get("used_keys") or [])
    ep_keys = {e.get("key") for e in (st.get("episodes") or [])
               if isinstance(e, dict) and e.get("key")}
    used = {k for k in (used_keys | ep_keys) if k}
    used_groups = {_canon(k) for k in used}

    unused = [g for g in groups if g not in used_groups]
    done = len(set(groups) & used_groups)
    return {
        "ready": len(unused),      # 事實已算完、還沒拍 → 立刻可產的集數(語意去重後的保守下界)
        "planned": len(unused),    # 本系列 ready 即 planned(事實已在庫，不需再算)
        "done": done,
        "published": _pub_tw_lab(),
        "detail": (f"事實檔 {len(keys)} 個 key → 語意去重 {len(groups)} 組(同一組回測換名字只算一次)；"
                   f"已用 {len(used)} key = {len(used_groups)} 組"
                   f"(used_keys {len(used_keys)} ∪ episodes {len(ep_keys)})；"
                   f"未用 {len(unused)} 組；已發布 {_pub_tw_lab()} 集"),
    }


def _inv_checkup() -> dict:
    """個股體檢:backlog 是全台股清單(n_total)，每日 cron 05:50 撈下一檔算事實。
    ready = 事實已算好的檔數，planned = backlog 還沒做的檔數。
    ⚠️ 兩者差很大是**正常**的(一天一檔)，所以承諾要分開講:
       「已經體檢完 N 檔」用 ready，「清單上有 M 檔」用 total —— 不可拿 total 冒充已完成。
    rubric = 體檢表項目數(n_facts + skipped)。實測 10 檔全部 = 13 → 尺確實是同一把;
    但填得滿的只有 5 檔(00878 只有 7/13、2327 與 2344 各 8/13、2412 與 2882 各 12/13)，
    ETF 沒財報就沒營收/EPS/毛利率 → **結構上不可能齊**。故「同一把尺」只能講到
    「同一份表」，不可暗示「每一檔都填滿」;差額由引擎的 skipped 欄位誠實揭露。"""
    bl = _load(STUDIO / "stock_checkup_backlog.json") or {}
    items = bl.get("items") or []
    todo = [i for i in items if isinstance(i, dict) and not i.get("done")]
    fc = _load(STUDIO / "stock_checkup_facts.json") or {}
    by = fc.get("by_code") or {}

    rubrics, n_skipped_codes = set(), 0
    for v in by.values():
        if not isinstance(v, dict):
            continue
        sk = v.get("skipped") or []
        if sk:
            n_skipped_codes += 1
        n = v.get("n_facts")
        if isinstance(n, int):
            rubrics.add(n + len(sk))
    # 尺不一致就回 None → 規則句不准宣稱「同一份 N 項表」(結構上擋掉「同一把尺」這種假話)
    rubric = next(iter(rubrics)) if len(rubrics) == 1 else None

    return {
        "ready": len(by),          # 事實已算完的檔數(可誠實說「已經體檢完」)
        "planned": len(todo),      # backlog 還沒做的檔數(可誠實說「清單上還有」)
        "done": len(items) - len(todo),
        "total": len(items),
        "rubric": rubric,
        "n_skipped_codes": n_skipped_codes,
        "published": _pub_checkup(),
        "detail": (f"backlog n_total {bl.get('n_total')}、已做 {len(items) - len(todo)}、"
                   f"未做 {len(todo)}；facts by_code 已算好 {len(by)} 檔"
                   f"(體檢表 {rubric} 項；其中 {n_skipped_codes} 檔有項目查無資料)；"
                   f"已發布 {_pub_checkup()} 集"),
    }


# ─────────────────────────────────────────────────────────────────────
# 系列註冊表
# ─────────────────────────────────────────────────────────────────────
# ⚠️ 這張表**只准放不含數字、且已複驗為真的靜態素材**。
#    任何帶數字或帶定位(第幾集/開播/已做幾集)的句子一律由下面的 _title/_turn/_rules/_promise/_join
#    從 inventory()+_published() 的真實檔案算出來。寫死在這裡＝繞過所有防線(前一版就是這樣說謊的)。

# 【誠實揭露:回測不含交易成本】
# 依據(2026-07-17 親自複驗):tw_facts_engine.py:471「未計手續費/滑價」、:677 同;
# 全檔零成本模型，55 組回測沒有一組把手續費/稅/滑價算進去。
# 這句是**自我設限**，方向天生安全:哪天真的加了成本模型，最壞只是低報自己，不會變成謊話。
COST_DISCLOSURE = (
    "但有個限制我先講死:我的回測沒有把手續費跟滑價算進去。"
    "所以像停利這種進進出出的做法，在我的數字裡是被高估的——真實世界只會更差。"
    "這種對我自己不利的話，我也照講。"
)

SERIES = {
    "tw_lab": {
        "name": "台股真相實驗室",
        "inv": _inv_tw_lab,
        "min_stock": MIN_STOCK,
        # ①敵人
        "enemy": ("台股的存股常識，幾乎都是這樣傳的:「長期一定賺」「跌了就加碼」「停利落袋為安」。"
                  "講的人很有信心，但你問他數據呢？沒有。就是「大家都這麼說」。"),
        # ③身分憑證
        "cred": ("這裡是量化阿森，這個頻道只做一件事:把每一個講法拿去回測，用數據說話，不喊單、也不報明牌。"),
        # ⑥為什麼你該追
        "why": ("為什麼要做這個？因為我自己也受夠了那種「聽起來很有道理，但沒有人真的去驗」的說法。"
                "如果一個常識，只有在嘴上講的時候才成立，那它根本不值得你拿錢去試。"
                "我想做的，是那種你看完之後，真的有能力自己判斷「這套說法到底能不能信」的內容。"),
        "cta_reason": "如果你也想知道，這些說法攤在數據前面到底剩下什麼",
        "category": "台股真相實驗室",
        "hashtags": ["#台股", "#存股", "#0050", "#回測", "#ETF", "#定期定額", "#台股真相實驗室", "#量化阿森"],
        "broll": ["taiwan stock exchange", "stock market chart", "backtest equity curve", "data chart"],
    },
    "checkup": {
        "name": "個股體檢系列",
        "inv": _inv_checkup,
        "min_stock": MIN_STOCK,
        "enemy": ("你有沒有發現，網路上講個股的影片，幾乎都在講同樣那幾檔？"
                  "剩下一千多檔，沒人講。不是因為它們不重要，是因為講它們沒有流量。"
                  "而那些有人講的，翻來覆去也只有一句「這檔會漲」——問他為什麼，就沒有下文了。"),
        "cred": ("這裡是量化阿森，這個頻道只做一件事:把每一檔股票的事實攤開，用數據說話，不喊單、也不報明牌。"),
        "why": ("為什麼要這樣做？因為「沒人講」不等於「不用查」。"
                "你手上那檔冷門股，可能整個 YouTube 都找不到一支認真講它的影片。"
                "我想做的，就是那個你想查任何一檔台股，都查得到一份誠實體檢報告的地方。"),
        "cta_reason": "如果你手上也有一檔沒人講的股票，想看看它的體檢報告長什麼樣",
        "category": "個股體檢",
        "hashtags": ["#台股", "#個股分析", "#財報", "#基本面", "#存股", "#個股體檢", "#量化阿森"],
        "broll": ["taiwan stock exchange", "financial report", "stock market chart", "data analytics dashboard"],
    },
}


# ─────────────────────────────────────────────────────────────────────
# 帶數字/帶定位的句子:一律從真實存量算出來
# ─────────────────────────────────────────────────────────────────────

def _title(key: str, inv: dict) -> str:
    """⚠️ 標題刻意不含「EP<數字>」(見檔頭「集數連續性」)。"""
    pub = int(inv.get("published", 0))
    if key == "tw_lab":
        if pub <= 0:
            return "台股真相實驗室開播｜你聽過的存股常識，我一條一條拿回測驗給你看｜規則先講死"
        return f"台股真相實驗室｜已經拆完 {pub} 集，還有 {inv['ready']} 組真回測排隊中｜規則先講死"
    if key == "checkup":
        if pub <= 0:
            return "個股體檢系列開播｜台股一檔一集，我用同一份體檢表量完整個市場｜規則先講死"
        return f"個股體檢系列｜台股 {inv['total']} 檔一檔一集，已經體檢完 {inv['ready']} 檔｜規則先講死"
    return ""


def _turn(key: str, inv: dict) -> str:
    """②宣告系列存在。已發布>0 → 結構上不可能講出「這是第零集」。"""
    name = SERIES[key]["name"]
    pub = int(inv.get("published", 0))
    if pub <= 0:
        return f"所以我決定開一個新系列:{name}。這支是第零集，我要先把規則講清楚。"
    return (f"所以我開了一個系列:{name}，到今天已經播出 {pub} 集。"
            f"這支不是第幾集——這支是系列說明:我把規則先講死，你再決定要不要跟。")


def _rules(key: str, inv: dict) -> list:
    """④規則先講死。這段的全部作用是證明「我值得你訂」——**一個字都不能是假的**。"""
    if key == "tw_lab":
        return [
            "第一，每一集只驗一個講法，一次講一件事，不混在一起讓你看不出破綻。",
            "第二，回測跑的是真實歷史行情，標的跟區間是機械掃出來的、不是我挑的。" + COST_DISCLOSURE,
            "第三，結果如實公開。驗出來是對的我就說對，打臉我自己的我也照播，不剪掉。",
            "第四，我不報明牌、不喊進出、不保證任何收益——我只負責把數據攤開，怎麼用是你的決定。",
        ]
    if key == "checkup":
        rubric = inv.get("rubric")
        ready, n_skip = int(inv.get("ready", 0)), int(inv.get("n_skipped_codes", 0))
        if rubric:
            # 尺一致(每檔都跑同一份 N 項表)才准這樣講;差額由 skipped 誠實揭露。
            first = (f"第一，每一檔都跑同一份 {rubric} 項體檢表:營收、獲利、配息、股價走勢、"
                     f"還有它在崩盤時到底跌成什麼樣。同一份表，不換標準。"
                     f"但我要先說清楚:表上的項目不是每一檔都填得滿——已經體檢的 {ready} 檔裡有 {n_skip} 檔"
                     f"有項目查不到，最常見的是 ETF 根本沒有財報，就沒有營收跟毛利率這些欄位。"
                     f"查不到的我直接標「查無資料」，不會用估算矇過去。")
        else:
            # 尺不一致 → 不准宣稱「同一份表」。
            first = ("第一，體檢項目以公開財報與歷史行情查得到的為準，"
                     "查不到的我直接標「查無資料」，不會用估算矇過去。")
        return [
            first,
            "第二，數字全部來自公開財報與歷史行情，我只做整理跟計算，不加我自己的預測。",
            "第三，好的壞的都講。體檢出來難看的，我照播，不會為了怕得罪誰就跳過。",
            "第四，這是介紹，不是推薦。我不會跟你說任何一檔該買還是該賣，也不保證任何收益——"
            "體檢報告給你，判斷是你的事。",
        ]
    return []


def _promise(key: str, inv: dict) -> str:
    """⑤規模承諾:數字**全部**來自 inventory() 的真實存量。
    這是誠信命脈——承諾的每個數字都可回查 STUDIO 的真檔，結構上不可能編造。"""
    if key == "tw_lab":
        # ready = 語意去重後、還沒拍過的真回測組數 → 「還有 N 組沒拆」可查證
        return (f"這不是講講而已。我手上還有 {inv['ready']} 組已經跑好的真回測沒拆，"
                f"一組一集，一路拆下去。")
    if key == "checkup":
        # ⚠️ ready(已算完) 與 total(清單總數) 分開講，不可混為一談
        return (f"這不是講講而已。台股 {inv['total']} 檔，我已經全部排進清單，"
                f"目前體檢完 {inv['ready']} 檔，每天再往下做一檔，做到整個市場都量完為止。")
    return ""


def _join(key: str, inv: dict) -> str:
    """⑦加入鉤:已發布>0 → 講「中途加入」而不是「第一集」。
    ⚠️ pub==1 要單獨講:「前面 1 集都還在，想從哪一集開始補都行」是通順度破口
    (只有一集哪來的「哪一集」)，句子雖不假但會露出模板的馬腳。"""
    pub = int(inv.get("published", 0))
    if key == "tw_lab":
        if pub <= 0:
            return "第一集，我要驗的是台股最多人信、也最少人查的那一條。"
        if pub == 1:
            return "已經播出的那一集就在頻道上，你可以先去看它長什麼樣。"
        return f"你現在跟進來剛好——前面 {pub} 集都還在，想從哪一集開始補都行。"
    if key == "checkup":
        if pub <= 0:
            return "第一集，從市場上最多人抱、卻最少人真的查過它體質的那一檔開始。"
        if pub == 1:
            return "第一集已經在頻道上了，你可以先去看一份體檢報告長什麼樣。"
        return f"你現在跟進來剛好——前面 {pub} 集都還在，想查哪一檔就從哪一集開始。"
    return ""


def _heading2(key: str, inv: dict) -> str:
    return "所以我開一個新系列" if int(inv.get("published", 0)) <= 0 else "這個系列已經在跑了"


def inventory(key: str) -> dict | None:
    """回本系列的真實題庫存量;系列不存在回 None。"""
    s = SERIES.get(key)
    if not s:
        return None
    try:
        return s["inv"]()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {key} 存量查證失敗:{str(exc)[:80]}", file=sys.stderr)
        return None


def build_script(key: str, mode: str = "auto") -> dict | None:
    """組確定性的系列說明稿。回可直接當 produce_batch script_override 的 d dict。
    存量不足 / 定位對不上真實檔案 → 回 None(fail-closed，寧可不產也不對觀眾說謊)。

    mode: 'auto'(預設，依已發布集數自動選) | 'premiere'(開播預告) | 'guide'(中途加入指南)
    """
    s = SERIES.get(key)
    if not s:
        print(f"[FATAL] 未知系列:{key}(可用:{', '.join(SERIES)})", file=sys.stderr)
        return None
    inv = inventory(key)
    if not inv:
        print(f"[FATAL] {s['name']}:存量查不到，拒產。", file=sys.stderr)
        return None

    # ── fail-closed ①:定位不可造假 ──────────────────────────────────
    pub = int(inv.get("published", 0))
    if mode == "premiere" and pub > 0:
        print(f"[FATAL] {s['name']}:已發布 {pub} 集，拒產「開播預告」——"
              f"觀眾點一下頻道就戳破。改用 --mode guide 或 auto。{inv['detail']}", file=sys.stderr)
        return None
    if mode == "guide" and pub <= 0:
        print(f"[FATAL] {s['name']}:一集都還沒發布，拒產「中途加入指南」——"
              f"沒有「前面幾集」可以加入。改用 --mode premiere 或 auto。{inv['detail']}", file=sys.stderr)
        return None
    if mode not in ("auto", "premiere", "guide"):
        print(f"[FATAL] 未知 mode:{mode}", file=sys.stderr)
        return None
    resolved = mode if mode != "auto" else ("guide" if pub > 0 else "premiere")

    # ── fail-closed ②:存量不可造假 ──────────────────────────────────
    # ⚠️ 用 min() 不是 max():舊版 max() 讓 checkup 在 facts 清空(ready=0)、backlog 還在
    #    (planned=1916)時照樣過關，實測產出「目前體檢完 0 檔」的荒謬承諾。
    #    承諾句同時用到 ready 與 planned，任一邊塌掉整句就不成立 → 取小的當閘。
    stock = min(int(inv.get("ready", 0)), int(inv.get("planned", 0)))
    if stock < s["min_stock"]:
        print(f"[FATAL] {s['name']}:題庫存量 {stock} < 下限 {s['min_stock']}，"
              f"拒產(承諾會變空頭支票)。{inv['detail']}", file=sys.stderr)
        return None

    rules = _rules(key, inv)
    if not rules:
        print(f"[FATAL] {s['name']}:規則段組不出來，拒產。", file=sys.stderr)
        return None
    rules_txt = "\n\n".join(rules)
    title = _title(key, inv)
    # ⑦CTA:字面必須有「訂閱」二字(兩支範本共同點;produce_batch._ensure_sub_hook 也吃這個)
    cta = (f"{_join(key, inv)}{s['cta_reason']}，"
           f"那就先按個訂閱，跟著這個系列一起看下去。我們下支見。")

    voice = "\n\n".join([
        s["enemy"],                 # ①敵人
        _turn(key, inv),            # ②宣告系列存在(定位由已發布集數算出來)
        s["cred"],                  # ③身分憑證
        "先把規則訂死。",             # ④規則先講死
        rules_txt,
        _promise(key, inv),         # ⑤規模承諾(存量算出來的)
        s["why"],                   # ⑥為什麼你該追
        cta,                        # ⑦CTA
    ])
    # 去掉 markdown 粗體記號(給人看的 ** 配音不能唸出來)
    voice = voice.replace("**", "")

    segments = [
        {"heading": "他們都這樣講", "broll": ["social media scam", "youtube editing timeline"]},
        {"heading": _heading2(key, inv), "broll": s["broll"][:2]},
        {"heading": "這個頻道只做一件事", "broll": ["data analytics dashboard", "financial graph animation"]},
        {"heading": "規則先講死", "broll": ["checklist", "rules document"]},
        {"heading": "存量攤給你看", "broll": s["broll"][1:3] or ["data chart"]},
        {"heading": "為什麼要這樣做", "broll": ["warning sign", "stock market chart"]},
        {"heading": "訂閱，跟著看下去", "broll": ["subscribe button"] + s["broll"][:1]},
    ]

    desc = "\n\n".join([
        s["enemy"] + _turn(key, inv),
        "規則:" + " ".join(f"{'①②③④'[i]} {r.split('，', 1)[-1] if '，' in r else r}"
                           for i, r in enumerate(rules[:4])).replace("**", ""),
        _promise(key, inv),
        f"這個頻道「量化阿森｜Carson Quant」只做一件事:把每一個說法拆給你看，用數據說話。"
        f"這是「{s['name']}」的系列說明，規則先講死，訂閱不錯過下一集。",
        "⚠️ 風險聲明:本影片為資訊與觀念分享，不構成任何投資建議。過去績效不代表未來表現，投資請自行承擔決策後果。",
    ])

    return {
        "title": title,
        "voice_text": voice,
        "segments": segments,
        "description": desc,
        "hashtags": s["hashtags"],
        # ⚠️ 刻意不設 _is_ep / _is_tw_lab:本片是系列說明不是正片，設了會被 _bump_ep/_bump_tw_lab
        #    吃掉一集編號(見檔頭「集數連續性」)。
        "_is_ep0": True,
        "_ep0_series": key,
        "_ep0_mode": resolved,      # 供稽核:這支用的是開播還是中途加入定位
        "_ep0_published": pub,      # 供稽核:算定位時看到的已發布集數
        "_ep0_inventory": inv,      # 供稽核:這支承諾的數字是用哪組存量算的
    }


def build_topic(key: str, mode: str = "auto") -> dict | None:
    """回 produce_batch topic_override(讓 gate 知道這是指定題、別重生換題)。"""
    s = SERIES.get(key)
    if not s:
        return None
    inv = inventory(key)
    if not inv:
        return None
    return {
        "title": _title(key, inv),
        "angle": f"{s['name']} 系列說明:規則先講死。KPI 是訂閱不是完播。",
        "category": s["category"],
        "format": "long",
        "ep0_series": key,
    }


def _fmt_status(key: str) -> str:
    s = SERIES[key]
    inv = inventory(key)
    if not inv:
        return f"  {key:10} {s['name']:12} 存量查不到"
    stock = min(int(inv.get("ready", 0)), int(inv.get("planned", 0)))
    pub = int(inv.get("published", 0))
    ok = "可產" if stock >= s["min_stock"] else f"存量不足(<{s['min_stock']})"
    mode = "guide(中途加入指南)" if pub > 0 else "premiere(開播預告)"
    return (f"  {key:10} {s['name']:12} ready={inv['ready']:<6} planned={inv['planned']:<6} "
            f"published={pub:<4} {ok}  定位={mode}\n"
            f"             └ {inv['detail']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="系列說明片確定性產製引擎")
    ap.add_argument("series", nargs="?", help=f"系列代號({', '.join(SERIES)})")
    ap.add_argument("--list", action="store_true", help="列各系列狀態、存量與已發布集數")
    ap.add_argument("--dry", action="store_true", help="只印稿，不寫檔")
    ap.add_argument("--mode", default="auto", choices=["auto", "premiere", "guide"],
                    help="定位:auto(依已發布集數自動選) / premiere(開播預告) / guide(中途加入指南)")
    ap.add_argument("--out", default=None, help="寫 .md/.voice.txt 到指定目錄(驗證用，不碰 output/)")
    args = ap.parse_args()

    if args.list or not args.series:
        print("系列狀態(存量與已發布集數全讀 STUDIO/ledger 真檔):")
        for k in SERIES:
            print(_fmt_status(k))
        if not args.series:
            print("\n用法:ep0_engine.py --dry <series> | --out <dir> <series>")
        return 0

    d = build_script(args.series, args.mode)
    if not d:
        return 2

    if args.dry or not args.out:
        print(f"=== {d['title']} ===\n")
        print(d["voice_text"])
        print(f"\n--- 字數:{len(d['voice_text'])} ---")
        print(f"--- 定位:{d['_ep0_mode']}(已發布 {d['_ep0_published']} 集) ---")
        print(f"--- 存量佐證:{d['_ep0_inventory']['detail']} ---")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import produce_batch as pb
    slug = pb.slugify(d["title"], "L")
    (out / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
    (out / f"{slug}.md").write_text(pb.build_md(d), encoding="utf-8")
    print(f"[ok] 已寫:{out / (slug + '.md')}")
    print(f"[ok] 已寫:{out / (slug + '.voice.txt')}")
    print(f"[存量佐證] {d['_ep0_inventory']['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
