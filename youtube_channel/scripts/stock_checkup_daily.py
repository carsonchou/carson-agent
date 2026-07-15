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

quota/rate 紀律(Carson硬性交代)：FinMind 免費層一天只抓 1-2 檔的量，這支預設 --count 1，
絕不在單次執行內對 FinMind 連續掃很多檔。

用法：
  python scripts/stock_checkup_daily.py                # 正式跑：算下一檔 + 種題(每天限跑一次)
  python scripts/stock_checkup_daily.py --dry-run       # 只印會選中誰，不寫檔不呼叫LLM
  python scripts/stock_checkup_daily.py --force         # 忽略「今天已經跑過」的冪等檢查(測試用)
  python scripts/stock_checkup_daily.py --count 2       # 一次做2檔(補進度用，正式cron別加這個)

驗證：python -m py_compile scripts/stock_checkup_daily.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
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
MAX_ATTEMPTS = 5   # 連續試幾檔資料不足就放棄(防止一路撞到都是新股，整天卡死)
# Carson拍板：一檔股票=一集10分鐘長片(公司是誰→基本面→價格體檢→估值位置→結尾，見
# TW_STOCK_CHECKUP_RULES)，不是短片系列。LLM 用通用 prompt 生題時偶爾會判成 short(2026-07-15
# 實測：13組事實生出15題只有short，因為 topics_from_facts.build_prompt 是共用邏輯不知道這系列
# 只做長片)——這裡強制覆蓋成 long。同時只留前 N 個候選(不是全收)：規模到1900檔時，若每檔都塞
# 10幾個候選題進 topic_bank，長年累積會讓題庫嚴重膨脹(其中只有1個會被真的產出)；保留2個是為了
# 給抽題時一點選擇餘地(避免唯一候選撞到既有題被擋掉就整檔卡死)，不是要每個角度都做一集。
MAX_TOPICS_PER_CODE = 2


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


def seed_topics_for_code(code: str, dry_run: bool = False) -> int:
    """只對這一檔『新產生』的 checkup_ fact_key 生題(不重跑全部歷史事實，控 LLM 成本)。
    重用 topics_from_facts.py 的 prompt 組裝/去重/誠信溯源邏輯(唯讀 import，不改那支)。
    回傳實際新增的題目數。"""
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

    batch = list(code_facts.values())
    try:
        cands = tff.gen_topics_for_batch(batch)
    except Exception as exc:  # noqa: BLE001
        print(f"[stock_checkup_daily] LLM 生題失敗：{str(exc)[:160]}")
        return 0

    bank = tb.load_bank()
    existing_norms = {tb._norm(t.get("title", "")) for t in bank} | {tb._norm(t) for t in tb.existing_titles()}
    existing_titles_list = [t.get("title", "") for t in bank]
    new_recs = []
    rejected = {"exact_dup": 0, "skeleton_dup": 0, "unsourced": 0, "banned": 0, "bad_fact_key": 0}
    import hashlib
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


def process_one(code: str, name: str) -> tuple:
    """算一檔的完整體檢(價格+基本面)。回傳 (ok: bool, reason: str)。"""
    print(f"[stock_checkup_daily] 處理 {code}（{name}）...")
    try:
        facts, skipped = scf.build_checkup(code, name_override=name)
    except Exception as exc:  # noqa: BLE001
        return False, f"build_checkup 例外：{str(exc)[:160]}"
    if facts is None:
        return False, "價格資料抓取失敗或上市未滿最短年限"
    if not facts.get("results"):
        return False, "抓到公司但算不出任何事實(價格+基本面皆資料不足)"
    scf.merge_and_write(facts, dry=False)
    return True, f"算出 {len(facts['results'])} 組事實({len(skipped)} 組略過)"


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
    idx = 0
    items = bl.get("items") or []

    while done_this_run < args.count and attempts < MAX_ATTEMPTS:
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
        ok, reason = process_one(code, name)
        if not ok:
            cand["skip"] = True
            cand["skip_reason"] = reason
            _save_backlog(bl)
            print(f"[stock_checkup_daily] {code}（{name}）略過：{reason}，試下一檔...")
            continue
        cand["done"] = True
        cand["done_at"] = today
        _save_backlog(bl)
        n_new_topics = seed_topics_for_code(code, dry_run=False)
        state.setdefault("history", []).append({
            "date": today, "code": code, "name": name, "reason": reason, "n_new_topics": n_new_topics,
        })
        done_this_run += 1

    if not args.dry_run:
        # 只有真的產出至少一檔才記「今天跑過」——若5檔連續因資料不足被skip(0產出)也標已跑，
        # 會白白停擺一天(驗證agent 2026-07-15抓到的邊角)。不寫marker讓當天手動重跑還能接著
        # 隊伍更後面試；被skip的檔已標skip=true不會重複打FinMind，cron一天也只觸發一次。
        if done_this_run > 0:
            state["last_run_date"] = today
        _save_state(state)

    print(f"[stock_checkup_daily] 本次完成 {done_this_run}/{args.count} 檔(共嘗試 {attempts} 檔)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
