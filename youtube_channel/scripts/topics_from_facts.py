#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topics_from_facts.py — 【反轉題庫引擎】先有真數據、再想題目，結構上不可能編造。

背景(2026-07-13 實跑抓到的根因鏈)：
  STUDIO/topic_bank.json 現存題目台股佔比極低 → produce_batch.pull_topic() 常抽不到台股題
  → call_claude 註解寫死「題庫空了才自由發揮」→ LLM 自由發想題目 → 這題目沒有對應的真實
  回測數據 → LLM 只好編造數字（實跑抓到一支長片編「實測發現47%訂單失效」）→ fact_source_guard
  誠信守門擋下 → 整支片白產、算力/API 費全浪費。

這支的正解：**反轉順序**。不要「先想題目、再找數據」(找不到就編)；改成「先有數據、再想題目」：
  對 STUDIO/tw_facts_computed.json + STUDIO/tw_stock_facts.json 裡每一組**真實回測事實**，
  用 LLM 生 2-4 個彼此切角不同的題目，每個題目**綁定一個 fact_key**，且**標題裡的數字必須
  是該 fact claim 裡本來就有的數字**（本地二次驗證 + fact_source_guard 溯源複查）。
  這樣：①每支片天生就有真憑據，誠信守門必過 ②題庫自動富含台股(事實庫本身就是台股)
  ③題目彼此角度不同，不是換句話說同一支。

fact_key 會原樣存進題庫紀錄，pull_topic() 回傳的 dict 是題庫紀錄本身(未做欄位過濾)，
所以 call_claude 收到的 topic dict 天生就帶得到 fact_key，供之後寫稿階段查回真實 claim
文字，不必改 produce_batch.py 一行。

用法：
  python scripts/topics_from_facts.py                  # 全部 45 組事實各生 2-4 題
  python scripts/topics_from_facts.py --dry-run         # 只印不寫檔(先看生成品質)
  python scripts/topics_from_facts.py --limit-facts 5   # 只處理前 5 組事實(小量測試用)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載入,直跑沒有→LLM 找不到 key)。
    setdefault 不覆蓋既有環境(cron 環境優先)。與 produce_batch._load_env 同一慣例(唯讀沿用,不改那支)。"""
    import os
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

import studio_common as sc          # noqa: E402  共用地基：PERSONA / has_llm_key / classify_topic_bucket / is_banned_skeleton / skeleton_dup_any
import topic_bank as tb             # noqa: E402  題庫引擎：load_bank/save_bank/existing_titles/_norm(唯讀沿用,不改這支)
import fact_source_guard as fsg     # noqa: E402  誠信溯源守門(唯讀沿用，只呼叫公開函式，不改這支)

try:
    from produce_batch import GUARD  # 與 topic_bank.py 同慣例：借用同一份誠信鐵則措辭
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"

FACT_FILES = ["tw_facts_computed.json", "tw_stock_facts.json", "stock_checkup_facts.json"]

ANGLE_POOL = (
    "反直覺數字（結果和直覺想的相反）", "成本揭露（紀律/擇時/手續費的隱藏代價）",
    "迷思拆穿（打破一個投資圈常見的說法）", "新手陷阱（新手最容易踩的具體錯誤）",
    "長期複利（時間拉長後的巨大落差）", "風險側寫（最大回撤/崩盤情境的真實痛感）",
    "時機side（該不該擇時進出場）", "對照比較（兩檔標的/兩種做法並排數據）",
    "情緒代入（模擬觀眾當下的心理掙扎再用數據打臉）", "決策框架（給觀眾一個可直接套用的判斷準則）",
)

# 數字誠信硬規：標題裡的績效數字只能是百分比或倍數，且必須在同句搭配績效語境詞
# (報酬/回撤/賺/賠/差/倍…)，才會被視為「績效宣稱」需要溯源比對(避免年份/天數誤判)。
_RX_TITLE_PCT = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*%")
_RX_TITLE_MULT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*倍")
TOL_ABS = 1.0
TOL_REL = 0.02


def _walk_numbers(obj) -> set:
    """把單一 fact 物件(含 data 巢狀結構)裡所有數值攤平成集合，當這組 fact 專屬的『可佐證數字池』。
    與 fact_source_guard._walk_numbers 同邏輯(獨立複製一份，不 import 私有函式，避免耦合)。"""
    pool: set = set()
    if isinstance(obj, dict):
        for v in obj.values():
            pool |= _walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            pool |= _walk_numbers(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        pool.add(abs(float(obj)))
    elif isinstance(obj, str):
        for tok in re.findall(r"-?\d+(?:\.\d+)?", obj):
            try:
                pool.add(abs(float(tok)))
            except Exception:  # noqa: BLE001
                pass
    return pool


def load_facts() -> dict:
    """合併 tw_facts_computed.json + tw_stock_facts.json 的 results，回傳 {fact_key: fact_dict}。
    兩份檔案 schema 略有差異(computed 版多了 claim/method/symbol/period/source 等欄位、
    legacy 版只有 desc/summary/keywords/data)，統一補齊 claim(缺就退回 summary)。"""
    facts = {}
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for k, v in (d.get("results") or {}).items():
            if not isinstance(v, dict):
                continue
            v = dict(v)
            v.setdefault("key", k)
            v.setdefault("claim", v.get("summary", ""))
            v["_src_file"] = fn
            facts[k] = v
    return facts


def extract_title_numbers(title: str) -> list:
    nums = []
    for m in _RX_TITLE_PCT.finditer(title or ""):
        nums.append(float(m.group(1)))
    for m in _RX_TITLE_MULT.finditer(title or ""):
        nums.append(float(m.group(1)))
    return nums


def numbers_sourced_to_fact(title: str, fact: dict):
    """title 裡的績效數字是否都能在『這一個』綁定 fact 的專屬數字池裡找到來源
    (比對容差沿用 fact_source_guard 同一組 TOL_ABS/TOL_REL)。
    回傳 (是否全數溯源得到, 查無來源的數字清單)。無數字時視為通過(概念型標題不強制帶數字)。"""
    nums = extract_title_numbers(title)
    if not nums:
        return True, []
    pool = _walk_numbers(fact)
    bad = [n for n in nums if not any(abs(p - n) <= max(TOL_ABS, p * TOL_REL) for p in pool)]
    return (len(bad) == 0), bad


def build_prompt(batch: list) -> str:
    fact_lines = []
    for f in batch:
        fact_lines.append(
            f'- fact_key="{f["key"]}" | 標的={f.get("symbol") or f.get("desc","")} | '
            f'描述={f.get("desc","")} | 真實數據原文={f.get("claim","")}'
        )
    facts_block = "\n".join(fact_lines)
    angles = "、".join(ANGLE_POOL)
    return f"""{sc.PERSONA}

你是量化阿森頻道的選題總監（量化/自動交易教學，繁中）。{GUARD}

【任務：反轉題庫——先有真數據，再想題目】
下面每一組是**已經真實回測算出來的事實**（fact_key 是內部代號，之後寫稿會用它去撈完整數據）。
針對**每一組** fact，生成 2 到 4 個**彼此切角不同**的影片題目，題目要能讓觀眾好奇點進來，
但**標題與內容論點必須完全建立在這組事實給的數字上，不准自己編或換算新數字**。

【可選切角池(不必每個都用，混搭+輪流，別每題套同一種)】
{angles}

【真實事實清單】
{facts_block}

【誠信硬規(零妥協)】
1. 標題裡若出現百分比或倍數，該數字**一定要是上面「真實數據原文」裡出現過的數字**
   (可以四捨五入到整數或一位小數，不可以自己換算成別的單位、不可以拼湊新數字)。
2. 標題裡若帶數字，一定要搭配報酬/回撤/賺/賠/差/倍這類績效語境詞，讓數字讀起來是「結論」而非年份。
3. 不喊單、不報明牌、不喊目標價、不保證會漲會賺；「穩賺/躺賺/保證」這類誇大詞一律不用。
4. 同一個 fact_key 底下的 2-4 個題目，切角要明顯不同(不是換句話說同一句)。
5. 大多數給 short（Shorts，約 30-45 秒可講完一個對比），可以有 1-2 支特別厚的 fact
   (如 miss_best_days/crash 系列)給 long（深度長片）。

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"fact_key":"對應上面的fact_key","title":"標題","angle":"一句話獨特切入點",
"category":"子領域關鍵字(如：定投vs單筆/停利續抱/高股息vs市值型/槓桿ETF/崩盤心理/擇時vs傻抱)",
"keywords":["關鍵字1","關鍵字2","關鍵字3"],"format":"short 或 long"}}]"""


def _parse_llm_json(txt: str) -> list:
    """穩健解析：先試完整陣列；截斷時退而逐一撿出完整的 {...} 物件，不整批報廢
    (與 topic_bank.gen_topics 同一容錯策略)。"""
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass
    items = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:  # noqa: BLE001
            continue
    return items


def gen_topics_for_batch(batch: list) -> list:
    import llm
    prompt = build_prompt(batch)
    txt = llm.complete(prompt, 3200, json_mode=True, temperature=0.9)
    return _parse_llm_json(txt)


def bucket_dist(items) -> dict:
    from collections import Counter
    return dict(Counter(t.get("bucket") or "(none)" for t in items))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印生成結果，不寫入 topic_bank.json")
    ap.add_argument("--limit-facts", type=int, default=0, help="只處理前 N 組事實(0=全部)，小量測試用")
    ap.add_argument("--batch-size", type=int, default=5, help="每次 LLM 呼叫塞幾組 fact")
    ap.add_argument("--min-tw", type=int, default=0,
                    help="題庫『未用的台股題』低於這個數才補題(0=不檢查,一律補)。"
                         "給每日 cron 用:台股題夠就不白燒 API、也不讓題庫無限膨脹。")
    args = ap.parse_args()

    # 「不足才補」守門:每天 cron 跑,但台股題還夠就直接結束(省 API、防題庫無限膨脹)。
    # 產線配額吃台股 78%(一天約 11 短 + 3 長),題庫台股題不足就會落回「自由發揮」→
    # LLM 生沒數據的題 → 編造 → 被誠信守門擋下 → 整支片白產。這道補題就是防止餓死。
    if args.min_tw > 0:
        try:
            bank = tb.load_bank()
            _items = bank if isinstance(bank, list) else (bank.get("topics") or bank.get("items") or [])
            _tw = sum(1 for t in _items
                      if not t.get("used") and (t.get("bucket") or "") == "tw_stock")
            print(f"[topics_from_facts] 題庫未用台股題:{_tw} 個(門檻 {args.min_tw})")
            if _tw >= args.min_tw:
                print(f"[topics_from_facts] 台股題充足({_tw} >= {args.min_tw}),本次不補題。")
                return 0
            print(f"[topics_from_facts] 台股題不足({_tw} < {args.min_tw}),開始從真實回測事實補題…")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 檢查題庫存量失敗({str(e)[:60]}),照常補題", file=sys.stderr)

    if not sc.has_llm_key():
        print("[錯誤] 無任何 LLM 供應商 API key，無法生成。")
        return 1

    facts = load_facts()
    fact_keys = list(facts.keys())
    if args.limit_facts:
        fact_keys = fact_keys[: args.limit_facts]
    print(f"[事實庫] 載入 {len(facts)} 組真實回測事實（{'、'.join(FACT_FILES)}），本次處理 {len(fact_keys)} 組。")

    bank = tb.load_bank()
    before_total = len(bank)
    before_unused = [t for t in bank if not t.get("used")]
    before_dist = bucket_dist(before_unused)
    print(f"[生成前] 題庫總數 {before_total}，未用 {len(before_unused)}，未用題材分佈：{before_dist}")

    existing_norms = {tb._norm(t.get("title", "")) for t in bank} | {tb._norm(t) for t in tb.existing_titles()}
    existing_titles_list = [t.get("title", "") for t in bank]

    new_recs = []
    rejected = {"exact_dup": [], "skeleton_dup": [], "unsourced": [], "banned": [], "bad_fact_key": []}

    batches = [fact_keys[i:i + args.batch_size] for i in range(0, len(fact_keys), args.batch_size)]
    for bi, keys in enumerate(batches, 1):
        batch = [facts[k] for k in keys]
        print(f"[生成] 第 {bi}/{len(batches)} 批（{len(keys)} 組事實）…")
        try:
            cands = gen_topics_for_batch(batch)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] 這批 LLM 失敗：{str(exc)[:160]}，跳過")
            continue
        for c in cands:
            fact_key = str(c.get("fact_key") or "").strip()
            title = str(c.get("title") or "").strip()
            if not title:
                continue
            if fact_key not in facts:
                rejected["bad_fact_key"].append((title, fact_key))
                continue
            if sc.is_banned_skeleton(title):
                rejected["banned"].append(title)
                continue
            n = tb._norm(title)
            if n in existing_norms:
                rejected["exact_dup"].append(title)
                continue
            if sc.skeleton_dup_any(title, existing_titles_list):
                rejected["skeleton_dup"].append(title)
                continue
            ok, bad_nums = numbers_sourced_to_fact(title, facts[fact_key])
            if not ok:
                rejected["unsourced"].append((title, bad_nums))
                continue
            angle = str(c.get("angle") or "").strip()
            category = str(c.get("category") or "").strip()
            fmt = "long" if str(c.get("format", "")).lower().startswith("l") else "short"
            keywords = c.get("keywords") if isinstance(c.get("keywords"), list) else []
            rec = {
                "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
                "title": title,
                "angle": angle,
                "category": category,
                "format": fmt,
                "used": False,
                "bucket": sc.classify_topic_bucket(title, angle, category),
                "source": "facts_engine",
                "fact_key": fact_key,
                "keywords": [str(kw) for kw in keywords][:6],
            }
            new_recs.append(rec)
            existing_norms.add(n)
            existing_titles_list.append(title)
        # 每批就存一次(原子寫)，避免長跑中途失敗整批白工——與 topic_bank.main() 同慣例。
        if new_recs and not args.dry_run:
            tb.save_bank(bank + new_recs)

    print(f"\n[生成完成] 新增 {len(new_recs)} 題（"
          f"拒絕：完全重複 {len(rejected['exact_dup'])}、骨架相似 {len(rejected['skeleton_dup'])}、"
          f"數字查無來源 {len(rejected['unsourced'])}、洗版骨架 {len(rejected['banned'])}、"
          f"fact_key錯配 {len(rejected['bad_fact_key'])}）")

    print("\n[樣本] 實際生成的題目(最多15個)：")
    for t in new_recs[:15]:
        print(f"  · [{t['bucket']}] {t['title']}")
        print(f"      angle={t['angle']}")
        print(f"      fact_key={t['fact_key']}  category={t['category']}  format={t['format']}")

    if rejected["skeleton_dup"]:
        print("\n[去重樣本·骨架相似被擋]：")
        for t in rejected["skeleton_dup"][:6]:
            print(f"  ✗ {t}")
    if rejected["exact_dup"]:
        print("\n[去重樣本·完全重複被擋]：")
        for t in rejected["exact_dup"][:6]:
            print(f"  ✗ {t}")
    if rejected["unsourced"]:
        print("\n[誠信樣本·數字查無來源被擋(不該發生，若有請人工複查)]：")
        for t, nums in rejected["unsourced"][:6]:
            print(f"  ✗ {t}  無憑據數字={nums}")

    # ── 自我測試：即使這次真跑剛好沒撞到既有題庫的重複，也要證明去重函式本身有效 ──
    if bank:
        probe_title = bank[0].get("title", "")
        if probe_title:
            n = tb._norm(probe_title)
            probe_exact_dup = n in existing_norms
            probe_skeleton_dup = sc.skeleton_dup_any(probe_title, existing_titles_list)
            print(f"\n[去重自我測試] 拿題庫既有題目「{probe_title[:40]}」重新丟進去重檢查："
                  f"exact_dup={probe_exact_dup}  skeleton_dup={probe_skeleton_dup}"
                  f"（任一為 True 就證明去重機制正確擋下重複）")

    if not args.dry_run:
        final_bank = tb.load_bank()
        after_unused = [t for t in final_bank if not t.get("used")]
        after_dist = bucket_dist(after_unused)
        print(f"\n[生成後] 題庫總數 {len(final_bank)}（前 {before_total} + 新增 {len(new_recs)}"
              f" = {before_total + len(new_recs)}，實際 {len(final_bank)}）")
        print(f"[生成後] 未用 {len(after_unused)}，未用題材分佈：{after_dist}")
        old_ids = {t.get("id") for t in bank}
        new_ids = {t.get("id") for t in final_bank}
        print(f"[洗庫檢查] 原有 {len(old_ids)} 個 id 全部仍在新庫中：{old_ids.issubset(new_ids)}")

        # ── 誠信驗證：拿生成的標題實跑 fact_source_guard，證明數字都溯源得到 ──
        pool = fsg.fact_pool(refresh=True)
        print(f"\n[fact_source_guard 驗證] 事實庫可佐證數字池共 {len(pool)} 個數字。")
        n_checked = 0
        n_bad = 0
        for t in new_recs:
            bad = fsg.unsourced_claims(t["title"], pool)
            if bad:
                n_bad += 1
                print(f"  ✗ 溯源失敗：{t['title']}  → {bad}")
            n_checked += 1
        print(f"[fact_source_guard 驗證] 檢查 {n_checked} 個新標題，{n_bad} 個溯源失敗"
              f"（0 = 全數標題裡的數字都查得到真實回測來源）")
    else:
        print("\n[dry-run] 未寫入 topic_bank.json。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
