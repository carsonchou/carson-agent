#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock_checkup_daily.py —【個股體檢·每日自動出集】1900檔規模化的每日驅動腳本。

背景(2026-07-15任務，Carson拍板)：「台股1900多隻可以一隻發一集」。有了 backlog(排隊清單，
見 stock_checkup_backlog_gen.py)，這支負責「每天從隊伍最前面撈一檔 → 算基本面+價格體檢事實
→ 種一個高優先的長片題目進 topic_bank → 產線當天自然抽到出片」。

流程(冪等，同一天重跑第二次直接跳過不重算)：
  1. backlog 不存在就先生一份(stock_checkup_backlog_gen.build_backlog())。
  2. 挑隊伍裡第一個 done=false 且 skip=false 的代號，跑 stock_checkup_facts.build_checkup()
     (含 stock_fundamentals 的基本面事實)。抓不到/資料不足(上市<3年等) → 標 skip=true 附理由，
     繼續往下一個候選試(有上限，防止整天卡在連續一串新股)，不編造、不硬做。
  3. 成功算出事實 → merge_and_write 進 STUDIO/stock_checkup_facts.json，backlog 標 done=true。
  4. 只針對「這檔新產生的 fact_key」呼叫 LLM 生 2-4 個題目(重用 topics_from_facts.py 的
     build_prompt/去重/誠信溯源邏輯，不整批重跑全部歷史事實——backlog 長到 1900 檔後，
     若每天重新生成所有事實的題目，LLM 成本會線性爆炸)，寫入 topic_bank.json。
     這些題目的 fact_key 天生帶 checkup_ 前綴 → produce_batch.pull_topic() 的 _rank() 已把
     checkup_ 前綴列入 winner 優先層級，當天產線自然優先抽到。

quota/rate 紀律(2026-07-17 實測校準)：FinMind 免費層的限制是 **300 requests/小時**(不是「每天幾檔」;
官方 finmind.github.io/quickstart：無 token 300/hr、有 token 600/hr;超量回 HTTP 402
"Requests reach the upper limit."。本專案 .env 未設 FINMIND_TOKEN → 走 300/hr 這層)。
實測(--count 2 與 --count 3 各跑一輪,共 20 call,全 HTTP 200 零 402,單次請求 avg 0.29s)：
  **一檔 = 4 個 FinMind call**(MonthRevenue / FinancialStatements / Dividend / PER;
  FinancialStatements 被 calc_eps_trend 與 calc_gross_margin 共用,靠 fundamentals_cache 命中
  只打 1 次 —— 前提是兩者共用 FIN_STMT_FETCH_YEARS 窗口,見 stock_fundamentals.py 的紅字警告)。
  TaiwanStockInfo 全市場表 7 天快取且全代號共用,平常不打。價格序列走 yfinance,不吃 FinMind。
故 --count 8 = 32 call = 每小時額度的 11%,離 300/hr 很遠;最壞情況(8 成功 + MAX_FAILS 5 失敗)
= 13 檔 × 4 = 52 call = 17%。原註解「免費層每天只處理 1 檔，絕不暴衝 rate limit」是**未實測的
保守假設**,把每小時額度誤當每日額度,已於本次校正。

用法：
  python scripts/stock_checkup_daily.py                # 正式跑：算下一檔 + 種題(每天限跑一次)
  python scripts/stock_checkup_daily.py --dry-run       # 只印會選中誰，不寫檔不呼叫LLM
  python scripts/stock_checkup_daily.py --force         # 忽略「今天已經跑過」的冪等檢查(測試用)
  python scripts/stock_checkup_daily.py --count 2       # 一次做2檔(補進度用，正式cron別加這個)

驗證：python -m py_compile scripts/stock_checkup_daily.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import re                       # 🔴 2026-09-04 補:c7a9c8e6(09-01)的標題去重用了 re.sub
                               # 卻沒 import,seed_topics_for_code 每次都 NameError
                               # → 題庫餵料端從 09-02 起天天掛,09-04 產線產出 0 支
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent          # youtube_channel/
STUDIO = ROOT / "STUDIO"
sys.path.insert(0, str(Path(__file__).resolve().parent))

BACKLOG_FILE = STUDIO / "stock_checkup_backlog.json"
STATE_FILE = STUDIO / "stock_checkup_daily_state.json"
# 🔴 2026-07-17 實測修正:本意是「資料不足的檔別一路撞下去整天卡死」＝**失敗**預算,但原本寫成
# 總嘗試預算(attempts < MAX_ATTEMPTS,成功的檔也計數)→ --count 只要 >5 就永遠只做得到 5 檔
# (--count 8 會回報「完成 5/8」),加量無效且無聲。改成只計失敗:最壞嘗試 count + MAX_FAILS 檔
# (8+5=13 檔 × 4 個 FinMind call = 52 call,仍遠低於免費層 300/hr,見下方 quota 註解)。
MAX_FAILS = 5      # 本次執行容許幾檔「資料不足」;超過就收工(防止一路撞到都是新股，整天卡死)
FETCH_FAIL_LIMIT = 3   # 🔴 同一檔連續抓取失敗幾次才**永久**排除。1 次不算 ——
                       # 2026-09-07:一次 yfinance 抖動誤殺 36 檔(重測 36/36 都抓得到)
MAX_SEED_FAILS = 3  # 🔴 2026-09-05 新增:連續幾檔「種題丟例外」就中止本輪。
                    # 為什麼要有:09-02/09-03 的 NameError 是「每一檔都會炸」那一類,
                    # 而當時沒有 try/except,第一檔就把整支帶走 → --count 16 的 15 個名額蒸發。
                    # 包了 try/except 之後失效模式會反過來:16 檔全部照跑、每檔都白付一次
                    # FinMind、種出 0 題。熔斷把系統性錯誤的損失壓在 3 檔。
                    # 為什麼算「連續」不算「累計」:偶發的 LLM 逾時不該中止整輪,
                    # 只有「連著炸」才是系統性的。**只有種題成功才歸零** ——
                    # process_one 失敗走 skip 的那條路**不重置**,那是刻意的:
                    # skip 不是一次種題事件,它沒有提供「種題現在正常」的證據。
                    # 所以「炸、skip、炸、skip、炸」會熔斷,這是對的。
# Carson拍板：一檔股票=一集10分鐘長片(公司是誰→基本面→價格體檢→估值位置→結尾，見
# TW_STOCK_CHECKUP_RULES)，不是短片系列。LLM 用通用 prompt 生題時偶爾會判成 short(2026-07-15
# 實測：13組事實生出15題只有short，因為 topics_from_facts.build_prompt 是共用邏輯不知道這系列
# 只做長片)——這裡強制覆蓋成 long。
# 🔴 2026-07-15 改 1 題/檔：原本留 2 個候選「給抽題選擇餘地」，但兩個都是 OPEN 的 checkup_
# fact_key 題,produce_batch 的 checkup 專屬層會照插入順序把第二題也產出來=同一檔兩集近重複
# 內容(實測 2317 多出 2 支無編號雜題)。候選在本函式內已過完守門才寫入,不存在「唯一候選被擋
# 整檔卡死」——被擋會在寫入前就換下一個 LLM 候選。
MAX_TOPICS_PER_CODE = 1

# 代號後面接這些字元就不是「代號引用」而是統計數字的一部分,不准剝也不准刪。
# 來源是敵意輸入實測:「抱20年報酬2330%」「2024年大跌40%」「報酬2330.5%」。
_UNIT_AFTER = "%％倍年元點萬億股天月季"
# 🔴 TODO(2026-09-04,不擋上線但要記):`_UNIT_AFTER` 是**黑名單,必然不完整**。
# 真實語料裡獨立四位數後面實際跟著的字元有 25 種不在表內(卻/的/報/賺/支/家…),
# 構造得出來:「2330支股票的故事」→「支股票的故事」。
# 而多重集合那道**在這裡幫不上忙,是設計上幫不上**:被刪的數字就等於代號,
# `set(_lost) - {code}` 必為空。
# 觸發條件是「hook 裡有一個獨立數字剛好等於代號」,407 筆實測命中 0,所以不擋上線。
# 更好的判準(驗證員給的,採用為後續改法):**那個數字在不在這檔股票的事實集合裡**
# —— 在,就是統計數字不是代號引用。便宜、正確,而且不必窮舉中文量詞。


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載入,直跑沒有→LLM 找不到 key)。
    與 topics_from_facts._load_env 同慣例。"""
    import os
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

import studio_common as sc          # noqa: E402
import topic_bank as tb             # noqa: E402
import fact_source_guard as fsg     # noqa: E402
import stock_checkup_facts as scf   # noqa: E402
import stock_checkup_backlog_gen as bg  # noqa: E402
import topics_from_facts as tff     # noqa: E402  重用 build_prompt/去重/誠信溯源(唯讀沿用,不改這支)


def _load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"last_run_date": None, "history": []}


def _save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_backlog():
    if not BACKLOG_FILE.exists():
        print("[stock_checkup_daily] backlog 不存在，先建一份...")
        bl = bg.build_backlog()
        BACKLOG_FILE.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
        return bl
    return json.loads(BACKLOG_FILE.read_text(encoding="utf-8"))


def _save_backlog(bl):
    BACKLOG_FILE.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_candidates(bl, limit):
    items = bl.get("items") or []
    return [it for it in items if not it.get("done") and not it.get("skip")][:limit]


# 🔴 舊 _next_ep_number()(掃題庫/output/ledger 的「個股體檢EP(\d+)」取 max+1)已於 2026-07-19 移除:
# 它在「種題」當下就把 EP 號寫死,而種題進度≠發布進度 → 跳號。EP 號改由發布端 daily_publish
# ._next_checkup_ep()按「已發布集數 max+1」在**發布時**確定性推導,種題/產製一律不寫號。


def seed_topics_for_code(code: str, name: str = "", dry_run: bool = False) -> int:
    """只對這一檔『新產生』的 checkup_ fact_key 生題(不重跑全部歷史事實，控 LLM 成本)。
    重用 topics_from_facts.py 的 prompt 組裝/去重/誠信溯源邏輯(唯讀 import，不改那支)。
    🔴 2026-07-19:標題掛「個股體檢{name}{code}:」連載前綴,**只留系列名不帶 EP 編號**——
    EP 號改由發布時按已發布集數 max+1 連號(治「種題進度≠發布進度」的跳號,見
    daily_publish._next_checkup_ep)。回傳實際新增的題目數。"""
    all_facts = tff.load_facts()
    code_facts = {k: v for k, v in all_facts.items()
                  if k.endswith(f"__{code}") or f"__{code}__" in k}
    if not code_facts:
        print(f"[stock_checkup_daily] {code} 沒有可種題的 fact_key(不應發生，請人工複查)")
        return 0
    print(f"[stock_checkup_daily] {code} 共 {len(code_facts)} 組新事實可種題：{list(code_facts.keys())}")
    if not sc.has_llm_key():
        print("[stock_checkup_daily] 無 LLM key，跳過種題(事實已存檔，之後補跑 topics_from_facts.py 仍能補上)")
        return 0

    # 🔴 2026-08-19:只送**少數幾組**事實給 LLM,不要一次丟 13 組。
    #
    # 舊碼送全部(11~13 組),要模型對每組生 2~4 題 = 一次要吐 26~52 題的 JSON。
    # 實測那個回應在 max_tokens=3200 被截在半路(只吐 217 字,停在 keywords 中間),
    # 加倍到上限 8000 仍不夠 → 解析出 0 題 → **連續十天種不出任何長片題**,
    # 而本檔封頂 MAX_TOPICS_PER_CODE=1,那 26~52 題本來就要丟掉 25~51 題。
    # 等於花三倍額度買一個必定截斷的回應。
    #
    # 挑法:固定帶三組資訊量最高的(長期報酬、與 0050 同期對決、最長套牢期),
    # 再依股票代號雜湊輪替一組其他事實——**輪替是刻意的**:1,925 檔全部用同一組
    # 事實生題會讓整個系列的敘事長得一模一樣,那正是 YouTube inauthentic content
    # 政策點名的「模板化、影片間變化極小」(memory yt-inauthentic-template-risk-2026-08)。
    # 2026-08-19 加入 industry_rank:它回答的是觀眾真正在問的「這樣到底算好還算壞」
    # (真留言:「20年才1145%也叫爆賺喔==」),而且每檔在產業裡的位置都不同,
    # 天然分岔敘事——正好緩解 memory yt-inauthentic-template-risk 的模板化風險。
    _PRIME = ("checkup_three_way__", "checkup_long_horizon__",
              "checkup_underwater__", "checkup_industry_rank__")
    _keys = list(code_facts.keys())
    _picked = [k for k in _keys if any(k.startswith(p) for p in _PRIME)]
    _rest = [k for k in _keys if k not in _picked]
    if _rest:
        _picked.append(_rest[sum(ord(c) for c in code) % len(_rest)])
    batch = [code_facts[k] for k in _picked] or list(code_facts.values())[:4]
    print(f"[stock_checkup_daily] 送 LLM 的事實:{len(batch)}/{len(code_facts)} 組 "
          f"({', '.join(k.replace('checkup_', '').replace('__' + code, '') for k in _picked)})")
    # 種題允許退到免費 Gemini(2026-08-10 實測):批量種 32 檔時,**15 檔的財報 13 組
    # 全部算好寫入了,卻卡在 LLM 生題的 groq 429**,等於白算一次(資料有留、下次重試,
    # 但批量時一半浪費)。llm.py 的 LLM_RESERVE_FALLBACK=1 是為了把 Gemini 額度留給
    # 長片產稿而把小請求鎖死在 Groq——種題一天只跑一次、量不大,值得放行。
    # 只在這個函式的作用域內暫時放行,不影響其他部門的省額度策略。
    # 🔴 2026-08-29 補完上面那道放行的另一半:放行 Gemini 只擋得住「groq 掛」,
    # **groq 與 gemini 同時 429 就整批死**,而付費且有餘額的 openrouter 被
    # LLM_BIG_FOR_SMALL=0 擋在鏈外(小請求不准用付費的)——實測當天 316 檔補種
    # 前三檔全滅,錯誤是 `groq: 429 | gemini: 429`,openrouter 從未被試,
    # 帳上還有 US$9.87。
    # 後果不對稱:這道呼叫失敗 → 題庫種不出題 → pull_topic 抽不到題 →
    # 模型自由生題(沒有事實可依據)→ 灌水 → 密度閘門擋下 → **整條長片產線停擺**。
    # (08-28 18:11 起連續 7 小時零產出就是這樣來的。)
    # 而成本這邊小到不成比例:一次 3,200 max_tokens 的小請求,一檔一次。
    # 「省額度」的理由撐不住「整條產線停擺」的代價,這一格值得付錢。
    _prev_reserve = os.environ.get("LLM_RESERVE_FALLBACK")
    _prev_bigsmall = os.environ.get("LLM_BIG_FOR_SMALL")
    os.environ["LLM_RESERVE_FALLBACK"] = "0"   # 放行免費 Gemini
    os.environ["LLM_BIG_FOR_SMALL"] = "1"      # 兩家都限流時,放行付費 openrouter 當最後一道
    try:
        cands = tff.gen_topics_for_batch(batch)
    except Exception as exc:  # noqa: BLE001
        # 🔴 2026-09-05:這裡原本是 `return 0`,而那讓「LLM 全滅」和「沒有新題」
        # 在唯一的回傳值上**完全無法分辨** —— 兩者都是 0,而 0 不會觸發任何告警。
        # 實測後果:08-21~08-29 連續九天(08-25、08-28 各 16/16 為 0,08-29 是 30/30)
        # 種出 0 題、零告警、last_run_date 照設,沒有任何人看得出來。
        # 上面那段註解自己就寫著這條路徑會讓「整條長片產線停擺」,而它被自己 catch 掉了。
        #
        # 現在改成往上丟。**這在今天之前是不安全的**(main() 沒有 try/except,
        # 丟上去會帶走整輪 —— 那多半正是當初寫成 return 0 的原因),
        # 但 main() 已經接得住了:會記成 n_new_topics=-1 + seed_error、
        # 計入熔斷、且不設 last_run_date。吞掉它現在是嚴格更差的選擇。
        print(f"[stock_checkup_daily] LLM 生題失敗：{str(exc)[:160]}", file=sys.stderr)
        raise
    finally:
        for _k, _v in (("LLM_RESERVE_FALLBACK", _prev_reserve),
                       ("LLM_BIG_FOR_SMALL", _prev_bigsmall)):
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v

    bank = tb.load_bank()
    existing_norms = {tb._norm(t.get("title", "")) for t in bank} | {tb._norm(t) for t in tb.existing_titles()}
    existing_titles_list = [t.get("title", "") for t in bank]
    new_recs = []
    rejected = {"exact_dup": 0, "skeleton_dup": 0, "unsourced": 0, "banned": 0, "bad_fact_key": 0,
                "rewrite_broke_number": 0}
    import hashlib
    # 🔴 2026-08-20 候選排序:每檔只取 1 題(MAX_TOPICS_PER_CODE),所以**排序決定一切**。
    # 實測今天產出的 7 支:旁白 6/6 都講了 0050 同期對照(誠信面 100% 落地),
    # 但標題只有 2/6 帶到——因為選的是第一個通過守門的候選,不看它是不是對照題。
    # 而觀眾的質疑正是打在標題:「20年才1145%也叫爆賺喔==」——沒有對照就無從判斷好壞。
    # ⚠️ 但**不能一律**優先對照題:1,925 檔全套同一個「vs 0050」句式,
    # 那正是 inauthentic 政策點名的「模板化、影片間變化極小」
    # (memory yt-inauthentic-template-risk-2026-08)。
    # 折衷:依股票代號雜湊,**約一半**的檔優先挑對照題,另一半保留其他角度。
    # 對照率預期從 33% 升到 ~60%,而句式仍有一半的空間分岔。
    if sum(ord(ch) for ch in code) % 2 == 0:
        cands = sorted(cands, key=lambda c: 0 if "0050" in str(c.get("title") or "") else 1)

    for c in cands:
        fact_key = str(c.get("fact_key") or "").strip()
        title = str(c.get("title") or "").strip()
        if not title:
            continue
        if fact_key not in code_facts:
            rejected["bad_fact_key"] += 1
            continue
        if sc.is_banned_skeleton(title):
            rejected["banned"] += 1
            continue
        n = tb._norm(title)
        if n in existing_norms:
            rejected["exact_dup"] += 1
            continue
        if sc.skeleton_dup_any(title, existing_titles_list):
            rejected["skeleton_dup"] += 1
            continue
        ok, bad_nums = tff.numbers_sourced_to_fact(title, code_facts[fact_key])
        if not ok:
            rejected["unsourced"] += 1
            print(f"  ✗ 溯源失敗（不該發生，人工複查）：{title}  無憑據數字={bad_nums}")
            continue
        # 🔴 連載前綴改為「個股體檢{name}{code}：{hook}」——**不帶 EP 編號**(2026-07-19)。
        # 舊法在種題當下用 _next_ep_number()寫死 EP 號(掃題庫最大號+1),但題庫每天種一檔就+1、
        # 種到 EP39,實際只發布了 EP1/EP7 → EP 號跟著「種題進度」跳號,觀眾看 EP1 下一支卻是 EP40,
        # 連載追劇/播放清單全斷。改成:種題只留系列名不留號、產製端(produce_batch._strip_checkup_ep_number)
        # 也剝號、發布時(daily_publish._apply_checkup_ep)才按「已發布集數 max+1」掛號 →「發一支進一號、
        # 永不跳」。LLM 標題若以股名/代號開頭先剝掉,避免「個股體檢南亞科2408：南亞科…」疊字。
        hook = title
        # 🔴 2026-09-04 快照抓在**剝前綴之前**。第一版抓在下面 `if code:` 那行前,
        # 而案例③(「2303 vs 2303 十年對決」)的傷害是**剝前綴那圈**造成的 ——
        # 快照時 hook 已經是「vs 2303 十年對決」,退回等於退到一個**自己就壞掉**的版本:
        # 最終仍以「：vs」開頭、仍少一個 2303。
        # **閘門③為那個案例而建,而它修不好那個案例。**
        # (對真實案例的括號傷害則是對的 —— 菱生2369 發生在快照之後,退回完全正確。
        #  所以那不是「放置點錯」而是「對一種傷害對、對另一種傷害錯」,更難看出來。)
        _hook_pre = hook          # 改寫前的版本,任一道收斂器擋下時退回這個
        for lead in (name, code):
            # 🔴 2026-09-04:代號後面**接著單位**就不是代號引用,是統計數字。
            # 敵意輸入「2024年大跌40%」被這一圈吃掉年份變成「年大跌40%」——
            # 那不是 c7a9c8e6 造成的,是 2026-07-19 這圈剝前綴的既有行為。
            if lead and hook.startswith(lead) and not (
                    lead == code and hook[len(lead):len(lead) + 1] in _UNIT_AFTER):
                hook = hook[len(lead):].lstrip("：:，,、 ")
        # 🔴 2026-09-01 上面那圈只擋「hook **開頭**就是股名/代號」,而實際的重複多半是
        # 帶括號或落在句中,擋不到。實測 63 支標題把代號印兩次(已發布 39 支):
        #     個股體檢【上海商銀 5876】**(5876)** 抱12年報酬91.5%?…
        #     個股體檢【一詮 2486】ALL IN 一詮**(2486)** 十年賺2051%…
        # 標題是**搜尋的曝光面**(搜尋佔 47.1% 觀看分鐘)而 YouTube 在搜尋結果會截斷,
        # 重複的代號等於白白吃掉約 7 個字元。
        # 前綴已經帶了代號,hook 裡再出現一次就是冗餘 —— 整段(含括號與前後空白)刪掉。
        if code:
            hook = re.sub(r"\s*[（(]\s*" + re.escape(code) + r"\s*[)）]\s*", "", hook)
            # 裸代號:前後不是數字才刪(避免咬到「20493」這種更長的數字)。
            # 🔴 2026-09-04 再加兩個條件,兩個都是敵意輸入實際打出來的:
            #   後面接單位(% 倍 年 元 點 萬 億…)→ 那是統計數字不是代號引用
            #     「抱20年報酬2330%」→ 舊碼刪成「抱20年報酬%」,**真數字被靜默刪、留懸空的 %**
            #   後面接小數點 → `(?!\d)` 擋不住,「報酬2330.5%」→「報酬.5%」
            # 曝險是真的:**51%(210/407)的真實 hook 含有非代號的四位數**,
            # 而報酬率常態 1000~4000%、台股代號多在 1101~9962,**兩個區間重疊**。
            hook = re.sub(r"(?<![\d.])" + re.escape(code) + r"(?![\d.%])(?![" + _UNIT_AFTER + r"])\s*",
                          "", hook, count=1)
            hook = re.sub(r"\s{2,}", " ", hook).lstrip("：:，,、 ").strip()
        _mk = (lambda h: (f"個股體檢{name}{code}：{h}" if name else f"個股體檢{code}：{h}"))
        title = _mk(hook)
        # 🔴 2026-09-04 改寫之後**沒有任何閘門**。is_banned_skeleton / exact_dup /
        # skeleton_dup / numbers_sourced_to_fact 全部在上面那幾行 re.sub **之前**跑完,
        # 改寫到 new_recs.append 之間唯一的動作是重算 `_norm` 指紋 ——
        # **溯源驗過的是改寫前的標題,改寫後的版本沒有任何東西看過就進了題庫。**
        #
        # 敵意輸入打出三個真缺陷,共同點都是「改寫後冒出一個溯源不到的數字形狀」:
        #     代號=真統計數字  抱20年報酬2330%  → 抱20年報酬%   真數字被靜默刪、留懸空的 %
        #     代號=小數整數部  報酬2330.5%      → 報酬.5%       (?!\d) 擋不住小數點
        #     代號出現兩次     2303 vs 2303 對決 → vs 對決       count=1 沒限制住
        #     代號=年份        2024年大跌40%    → 年大跌40%
        # 曝險是真的:**51%(210/407)的真實 hook 含有非代號的四位數**,而這個語料的
        # 報酬率常態落在 1000~4000%、台股代號多在 1101~9962,**兩個區間重疊**。
        # 407 筆真實資料經驗命中 0,但空間在 —— 而它明天 05:50 是第一次真的執行
        # (c7a9c8e6 寫了三天跑零次,`re` 從來沒被 import,直到 eed3ca25 才補上)。
        #
        # 擋下之後**退回未改寫版,不丟題**:代號印兩次只是浪費約 7 個字元,
        # 而丟掉一題是少一支片 —— 誤擋比誤放貴。種題歸零正是我們剛修好的東西。
        # ⚠️ 這道網刻意**不是**重跑 `numbers_sourced_to_fact` —— 那是我第一版的選擇,
        # 實測擋不住 4 種敵意輸入裡的 3 種,而且在 407 筆真實資料上誤擋 1 筆。
        # 根因:溯源閘門問的是「有沒有冒出溯源不到的數字」,而這裡的失敗形態是
        # **一個真數字被靜默刪掉** —— 刪掉之後標題裡沒有可疑數字,溯源當然放行。
        # **拿一道問錯問題的閘門去守,比沒有守更糟:它會給出「驗過了」的錯覺。**
        # 對症的判準是數字的**多重集合**:改寫只准拿掉代號本身,不准動到別的數字、
        # 也不准新增。「2303 vs 2303」被 count=1 刪掉一個 → 個數 2→1 → 擋下。
        if code and title != _mk(_hook_pre):
            _n_pre = collections.Counter(re.findall(r"\d+(?:\.\d+)?", _hook_pre))
            _n_post = collections.Counter(re.findall(r"\d+(?:\.\d+)?", hook))
            _lost = _n_pre - _n_post
            _gained = _n_post - _n_pre
            # 「2303 vs 2303 對決」這種:被刪掉的**就是代號本身**,值上跟真代號引用
            # 無法區分,所以上面的數字網**依設計抓不到它**。它剩下的傷害不是錯數字
            # 而是**斷句**(變成「vs 對決十年誰贏」),所以用句首的懸空連接詞接。
            # ⚠️ 不要寫 `\b?` —— 零寬斷言不能加量詞,Python re 直接丟
            # `re.error: nothing to repeat`,而它只在**這條路徑真的被走到**時才炸
            # (第一版就是這樣寫的,測試才抓到)。
            # 也刻意**不收單字「和/與/跟」**:「和碩的十年」會被誤擋,
            # 而誤擋的代價是種題少一題,比多印 7 個字元貴。
            _dangling = re.match(r"^(?:vs|VS|對決|對比)[\s，,、]", hook)
            if _gained or set(_lost) - {code} or _dangling:
                rejected["rewrite_broke_number"] += 1
                print(f"  ↩ 代號去重動壞了標題,退回未改寫版:{title}"
                      f"  少了={dict(_lost)} 多了={dict(_gained)}"
                      + ("  句首懸空連接詞" if _dangling else ""))
                hook, title = _hook_pre, _mk(_hook_pre)
        n = tb._norm(title)  # 前綴改變了標題,去重指紋要跟著重算
        angle = str(c.get("angle") or "").strip()
        category = str(c.get("category") or "").strip()
        keywords = c.get("keywords") if isinstance(c.get("keywords"), list) else []
        rec = {
            "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
            "title": title, "angle": angle, "category": category,
            "format": "long",  # 本系列固定10分鐘長片，不採用LLM自己判的short/long(見上方常數註解)
            "used": False,
            "bucket": sc.classify_topic_bucket(title, angle, category),
            "source": "stock_checkup_daily", "fact_key": fact_key,
            "keywords": [str(kw) for kw in keywords][:6],
        }
        new_recs.append(rec)
        existing_norms.add(n)
        existing_titles_list.append(title)
        if len(new_recs) >= MAX_TOPICS_PER_CODE:
            break  # 這檔候選夠了，其餘 LLM 候選不寫入(控題庫規模，見上方常數註解)

    print(f"[stock_checkup_daily] 新增 {len(new_recs)} 題（拒絕：{rejected}，"
          f"LLM原始候選 {len(cands)} 個，本檔封頂 {MAX_TOPICS_PER_CODE} 題）")
    for t in new_recs:
        print(f"  · [{t['format']}] {t['title']}")

    if new_recs and not dry_run:
        tb.save_bank(bank + new_recs)
        # 誠信驗證：拿新題實跑 fact_source_guard，證明數字都溯源得到(同 topics_from_facts.main 慣例)
        pool = fsg.fact_pool(refresh=True)
        n_bad = 0
        for t in new_recs:
            if fsg.unsourced_claims(t["title"], pool):
                n_bad += 1
        print(f"[stock_checkup_daily] fact_source_guard 覆核：{len(new_recs)} 題中 {n_bad} 題溯源失敗(應為0)")
    return len(new_recs)


# 失敗種類:決定呼叫端要不要把這一檔**永久**踢出 backlog。
FAIL_TRANSIENT = "transient"   # 上游抓取失敗 —— 可能只是這一次,不可以永久排除
FAIL_PERMANENT = "permanent"   # 這一檔結構上做不出來 —— 可以排除


def process_one(code: str, name: str) -> tuple:
    """算一檔的完整體檢(價格+基本面)。回傳 (ok: bool, reason: str, kind: str)。

    🔴 2026-09-07:第三個回傳值是新加的,因為呼叫端**必須**分得出暫時性與永久性。
    原本兩種失敗共用一條路,呼叫端一律 `skip=True` ⇒ 一次 yfinance 抖動就把一檔
    上市二十年的公司**永久**踢出體檢名單。實測代價:36 檔被誤殺,
    重測 36/36 全部抓得到,裡面有彰銀 2801、台肥 1722、和碩 4938、王品 2727。

    🔴 而原本那個理由字串「價格資料抓取失敗**或上市未滿最短年限**」後半段是**假的**:
    `build_checkup` 只在 `fetch_series` 回 None 時回 `(None, [])`,那就是純粹的抓取失敗;
    「年限不足」走的是另一條路(回 facts + skipped 明細,ok=True)。
    **是那半句不存在的原因,讓「永久排除」看起來合理。**
    """
    print(f"[stock_checkup_daily] 處理 {code}（{name}）...")
    try:
        facts, skipped = scf.build_checkup(code, name_override=name)
    except Exception as exc:  # noqa: BLE001
        return False, f"build_checkup 例外：{str(exc)[:160]}", FAIL_TRANSIENT
    if facts is None:
        return False, "價格資料抓取失敗(上游暫時性失敗也走這條)", FAIL_TRANSIENT
    if not facts.get("results"):
        return False, "抓到公司但算不出任何事實(價格+基本面皆資料不足)", FAIL_PERMANENT
    scf.merge_and_write(facts, dry=False)
    return True, f"算出 {len(facts['results'])} 組事實({len(skipped)} 組略過)", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印會選中誰，不寫檔不呼叫LLM")
    ap.add_argument("--force", action="store_true", help="忽略「今天已跑過」的冪等檢查")
    ap.add_argument("--count", type=int, default=1, help="一次做幾檔(正式cron固定1，補進度可調高)")
    args = ap.parse_args()

    today = _dt.date.today().isoformat()
    state = _load_state()
    if state.get("last_run_date") == today and not args.force and not args.dry_run:
        print(f"[stock_checkup_daily] 今天({today})已經跑過(冪等跳過)。--force 可強制重跑。")
        return 0

    bl = _load_backlog()
    done_this_run = 0
    attempts = 0
    fails = 0
    seed_fails = 0   # 連續種題失敗數(成功一檔就歸零)
    seeded_ok = 0    # 種題**沒有丟例外**的檔數(n_new_topics=0 也算成功:那是合法的「沒有新題」)
    idx = 0
    items = bl.get("items") or []

    while done_this_run < args.count and fails < MAX_FAILS:
        remaining = [it for i, it in enumerate(items) if i >= idx and not it.get("done") and not it.get("skip")]
        if not remaining:
            print("[stock_checkup_daily] backlog 已無待處理代號(全部 done 或 skip)。"
                  "請到 stock_checkup_backlog_gen.py 重新掃描(新股上市會自動補進來)。")
            break
        cand = remaining[0]
        idx = items.index(cand) + 1
        code, name = cand["code"], cand["name"]
        attempts += 1
        if args.dry_run:
            print(f"[dry-run] 會選中：{code}（{name}），rank={cand.get('rank')}")
            done_this_run += 1
            continue
        ok, reason, fail_kind = process_one(code, name)
        if not ok:
            fails += 1
            if fail_kind == FAIL_TRANSIENT:
                # 🔴 暫時性失敗**不寫 skip**,只累計次數。連續 FETCH_FAIL_LIMIT 次
                # (跨不同輪)才判定為真的抓不到 —— 一次 yfinance 抖動不可以讓一檔
                # 上市二十年的公司永久消失。2026-09-07 實測:36 檔被這樣誤殺,重測 36/36 都抓得到。
                n = int(cand.get("fetch_fail") or 0) + 1
                cand["fetch_fail"] = n
                if n >= FETCH_FAIL_LIMIT:
                    cand["skip"] = True
                    cand["skip_reason"] = f"價格連續 {n} 次抓取失敗(疑似已下市/代號無效):{reason}"
                    print(f"[stock_checkup_daily] 🔴 {code}（{name}）連續 {n} 次抓不到,"
                          f"永久排除。若是誤判,把 skip/fetch_fail 清掉即可回收。", file=sys.stderr)
                else:
                    print(f"[stock_checkup_daily] ⚠️ {code}（{name}）抓取失敗第 {n}/{FETCH_FAIL_LIMIT} 次"
                          f"(**不排除**,下輪再試):{reason}", file=sys.stderr)
            else:
                cand["skip"] = True
                cand["skip_reason"] = reason
                print(f"[stock_checkup_daily] {code}（{name}）永久略過：{reason}", file=sys.stderr)
            _save_backlog(bl)
            print(f"[stock_checkup_daily] {code}（{name}）本輪跳過（第 {fails}/{MAX_FAILS} 次），試下一檔...",
                  file=sys.stderr)
            continue
        cand["done"] = True
        cand["done_at"] = today
        _save_backlog(bl)
        # 🔴 2026-09-05:種題**必須**包 try/except,而且 history 那一列必須無論如何都寫下去。
        # 原本這裡是裸呼叫,09-02/09-03 的 NameError 直接把整個 main() 帶走,後果有兩層:
        #   (a) 這一檔 done 已落盤但 history 沒有它、題庫也沒有題 → 從此不再入列(孤兒);
        #   (b) 當天剩下的名額全部蒸發(--count 16 只做了 1 檔)。三天共 48 個名額。
        # ⚠️ 失敗時**不回滾 done**,這是刻意的:
        #   FinMind 已經付過、事實已經 merge_and_write 落盤。回滾 → 明天重跑 →
        #   merge_and_write 會先 pop 掉該 code 全部舊 key 再灌新的(stock_checkup_facts.py:581-584)、
        #   build_checkup 沒有「已算過就跳過」的分支且 as_of 取當天(:462)。
        #   而 seed_topics_for_code 是 tb.save_bank() 先、fact_source_guard 覆核後 ——
        #   若 save_bank 已成功、例外丟在覆核階段,**題已經在題庫裡了**,
        #   這時回滾 done 會讓明天的重跑把事實換掉、而標題裡的數字是綁在舊事實上的。
        #   (09-05 早上否決「清掉 8215/5464 的 done」正是這個理由。)
        # ⇒ 正確的復原路徑是 seed_checkup_backfill.py(補「有事實但題庫沒題」的 code,
        #   不打 FinMind、只花 LLM),它的判準跟這裡留下的痕跡對得上。
        try:
            n_new_topics = seed_topics_for_code(code, name=name, dry_run=False)
            seed_err = ""
            seed_fails = 0
        except Exception as exc:  # noqa: BLE001
            n_new_topics = -1     # 哨兵值:和 0(合法的「沒有新題」)必須分得開,
                                  # 而且要出現在**已經有人在讀的那個欄位**上(history[].n_new_topics),
                                  # 否則失敗只寫進沒人讀的 log = 靜默。
            seed_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            seed_fails += 1
            print(f"[stock_checkup_daily] 🔴 {code}（{name}）種題失敗:{seed_err}"
                  f"(連續第 {seed_fails}/{MAX_SEED_FAILS} 次)——事實已落盤,"
                  f"用 seed_checkup_backfill.py 補種即可,不要清 done。", file=sys.stderr)
        _h = {"date": today, "code": code, "name": name, "reason": reason, "n_new_topics": n_new_topics}
        if seed_err:
            _h["seed_error"] = seed_err
        state.setdefault("history", []).append(_h)
        _save_state(state)   # 每檔就存,不要等迴圈結束 —— 原本 _save_state 只在迴圈後,
                             # 任何未捕捉的例外都會讓整輪的 history 一起消失(09-02 就是這樣)。
        if n_new_topics >= 0:
            seeded_ok += 1
        done_this_run += 1   # 種題失敗仍計入:FinMind 已付、事實已落盤。
                             # 不計入的話,系統性錯誤會把整個 backlog 一路重抓下去。
        if seed_fails >= MAX_SEED_FAILS:
            print(f"[stock_checkup_daily] 🔴 連續 {seed_fails} 檔種題失敗,中止本輪"
                  f"(已處理 {done_this_run} 檔)。這是系統性錯誤,先修再跑。", file=sys.stderr)
            break

    if not args.dry_run:
        # 只有真的產出至少一檔才記「今天跑過」——若5檔連續因資料不足被skip(0產出)也標已跑，
        # 會白白停擺一天(驗證agent 2026-07-15抓到的邊角)。不寫marker讓當天手動重跑還能接著
        # 隊伍更後面試；被skip的檔已標skip=true不會重複打FinMind，cron一天也只觸發一次。
        # 🔴 2026-09-05:條件由 done_this_run > 0 改成 seeded_ok > 0。
        # 原註解的用意是「0 產出不要標已跑,免得白白停擺一天」,而種題全炸正是 0 產出 ——
        # 舊條件會把「16 檔全部種題失敗」標成今天跑過,當天就再也接不下去了。
        # 已 done 的檔不會被重抓(done=True),所以同日重跑只會往隊伍後面走,不浪費 FinMind。
        if seeded_ok > 0:
            state["last_run_date"] = today
        _save_state(state)

    # --dry-run 一個檔都沒碰,seeded_ok 恆為 0 而 done_this_run 照加,
    # 不排除的話 `--count 5 --dry-run` 會假報「種題失敗 5 檔」並喊人去跑 backfill(會花 LLM)。
    # 新裝的告警管道的第一發不能是假的,否則之後沒人會信它。
    _seed_bad = 0 if args.dry_run else done_this_run - seeded_ok
    print(f"[stock_checkup_daily] 本次完成 {done_this_run}/{args.count} 檔(共嘗試 {attempts} 檔"
          f"，其中種題失敗 {_seed_bad} 檔)。")
    if _seed_bad:
        print(f"[stock_checkup_daily] 🔴 有 {_seed_bad} 檔事實已落盤但沒種到題 —— "
              f"跑 seed_checkup_backfill.py 補種(不打 FinMind)。history 裡 n_new_topics=-1 的就是。",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
