#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""winner_amplifier.py — 【贏家自動放大迴路】把「什麼會紅」變成每天自動反饋。

背景(Carson 實測)：頻道同題材表現差可達 80 倍(台股單支 850 觀看 vs 幣圈同期 0 觀看)。
現況：growth_agent/weekly_winners 已經在做「關鍵字級」放大(win_keywords 回灌 evidence_block +
偏產贏家關鍵字題)，但那是**詞彙統計**、幾天才更新一次、也不會針對「某一支具體贏家片」派生
不同切角的追擊題。這支補的是**逐片級、每日**的迴路：

  掃近 72h 發布片的即時觀看(YouTube Data API，非 Analytics——Analytics 有 2-3 天延遲會漏掉
  剛發布的贏家) → 跟「同齡片」比(age-normalized velocity，不是跟全站絕對觀看比，否則新片
  天生輸舊片) → 抓出真正跑贏同齡的 top 3 → 對每支贏家抽題材要素(topic_bank 比對 fact_key，
  沒有就用 classify_topic_bucket 兜底) → LLM 生 2-3 個「同題材、不同切角」的派生題目 → 去重 +
  fact_source_guard 溯源守門 → 高優先寫回 topic_bank，隔天 produce_batch 自然抽到。

「同齡相對表現」怎麼算(誠實記在這裡，別自己騙自己)：
  YouTube Data API 只給「現在」的累積觀看數，沒有「這支片在發布後第 48 小時當下」的歷史快照
  (那要 Analytics day-dimension 查詢，且仍有延遲)。故不跟「全站歷史片的現在觀看數」比(老片
  累積時間長，天生贏)，改用 velocity = views ÷ 發布至今小時數(age-normalized)，拿「近期同一
  批次發布、可比較的片」互比——這樣新片與新片才是同齡比較，不會被「發布 20 天」的老片拉低。
  已知限制：velocity 前段(0-48h)通常因訂閱推播天生偏高，跨年齡混池比會有系統性誤差，這裡
  用「候選片年齡限制在 12-72h」+「基準池同樣限制在 12-336h(14天)內」縮小誤差，非嚴謹統計。

冪等/防洗版：
  - 同一個 videoId 72h 內只放大一次(STUDIO/winner_amplifier_state.json 記錄)。
  - 單次執行最多派生並寫入 6 題(防單一贏家洗成整批同骨架)。
  - 派生題目一律過 is_banned_skeleton + skeleton_dup_any(existing) + fact_source_guard 溯源，
    任一不過就丟棄，不強湊數。

用法：
  python scripts/winner_amplifier.py             # 真跑：掃贏家 → 派生 → 寫入 topic_bank
  python scripts/winner_amplifier.py --dry        # 只掃描+生成+驗證，不寫入 topic_bank/state
  python scripts/winner_amplifier.py --pool 150   # 候選+基準池取最近幾支已發布片(預設140)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
STATE_FILE = STUDIO / "winner_amplifier_state.json"


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        import os
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

import studio_common as sc          # noqa: E402  共用地基
import topic_bank as tb             # noqa: E402  題庫引擎(load_bank/save_bank/add_topics/_norm，唯讀沿用)
import fact_source_guard as fsg     # noqa: E402  誠信溯源守門(唯讀沿用，只呼叫公開函式)

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

try:
    from produce_batch import GUARD  # 借用同一份誠信鐵則措辭(唯讀沿用，不改該檔)
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"

FACT_FILES = ["tw_facts_computed.json", "tw_stock_facts.json"]

# ── 掃描/比較參數 ──
SCAN_WINDOW_H = 72        # 贏家候選：發布至今 72h 內
MIN_AGE_H = 12             # 太新(<12h)觀看數還沒穩定，先不判
POOL_MAX_AGE_H = 14 * 24   # 基準池：14 天內的片才拿來當「同齡比較基準」
DEFAULT_POOL = 140         # uploaded_ledger 取最近幾支去查 API(批次查，配額便宜)
TOP_N = 3                  # 最多挑幾支贏家
MIN_RELATIVE = 1.5         # 贏家門檻：velocity 要 >= 基準池中位數的 1.5 倍才算「真的跑贏同齡」
REAMPLIFY_COOLDOWN_H = 72  # 同一支片 72h 內只放大一次
DAILY_CAP = 6              # 單日(單次執行)最多寫入幾個派生題
DERIVE_PER_WINNER = 3      # 每個贏家最多生成幾個候選派生題(生成後仍會被去重/守門過濾)

ANGLE_POOL = (
    "反直覺數字（結果和直覺想的相反）", "成本揭露（紀律/擇時/手續費的隱藏代價）",
    "迷思拆穿（打破一個投資圈常見的說法）", "新手陷阱（新手最容易踩的具體錯誤）",
    "對照比較（換一組標的/換一種期間並排數據）", "情緒代入（模擬觀眾當下的心理掙扎再用數據打臉）",
    "決策框架（給觀眾一個可直接套用的判斷準則）",
)

_RX_TITLE_PCT = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*%")
_RX_TITLE_MULT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*倍")

# 標題裡常見的標的/主題代號，用來把「贏家片」跟事實庫的 fact_key 對上關係
_SYMBOL_TOKENS = ("0050", "0056", "00878", "00929", "00919", "00940", "00631L", "006208",
                   "00713", "00733", "2330", "台積電", "大盤", "加權指數", "台灣50")


def _now_utc():
    return datetime.now(timezone.utc)


def _load_json(p, default=None):
    return sc.load_json_safe(p, default)


# ────────────────────────────── 1) 抓近期片的即時觀看(Data API，非 Analytics：Analytics 2-3天延遲會漏掉剛發布贏家) ──────────────────────────────
def recent_pool(pool_n: int) -> list:
    """回傳最近 pool_n 支已上傳片的 {videoId, slug, title, published_at(dt), views, age_h, velocity}。
    slug/title 優先用本地 ledger/quality_scores(避免多打 API)，views/publishedAt 一定用即時 API(真數字)。"""
    ledger = _load_json(LEDGER, {}) or {}
    items = list(ledger.items())[-pool_n:]  # dict 插入順序＝上傳時間順序(每次上傳才 append)
    if not items:
        return []
    id2slug = {v: k for k, v in items}
    ids = [v for _, v in items]

    q = _load_json(STUDIO / "quality_scores.json", {}) or {}
    id2title = {}
    for x in (q.get("published") or []):
        if isinstance(x, dict) and x.get("videoId"):
            id2title[x["videoId"]] = x.get("title") or x.get("slug") or x["videoId"]

    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:  # noqa: BLE001
        print(f"[winner_amplifier] 無法連 YouTube Data API：{e}", file=sys.stderr)
        return []

    now = _now_utc()
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            resp = yt.videos().list(part="snippet,statistics,status", id=",".join(chunk)).execute()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] videos.list 失敗：{e}", file=sys.stderr)
            continue
        for it in resp.get("items", []):
            vid = it["id"]
            sn = it.get("snippet", {}) or {}
            st = it.get("statistics", {}) or {}
            status = it.get("status", {}) or {}
            if status.get("privacyStatus") not in (None, "public"):
                continue  # 非公開片(private/unlisted)觀看數不具比較意義，剔除
            pub_raw = sn.get("publishedAt")
            if not pub_raw:
                continue
            try:
                published_at = datetime.strptime(pub_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
            age_h = max((now - published_at).total_seconds() / 3600.0, 0.01)
            views = int(st.get("viewCount", 0) or 0)
            title = id2title.get(vid) or sn.get("title") or vid
            out.append({
                "videoId": vid,
                "slug": id2slug.get(vid, ""),
                "title": title,
                "published_at": published_at,
                "age_h": round(age_h, 2),
                "views": views,
                "velocity": round(views / age_h, 3),
            })
    return out


# ────────────────────────────── 2) 同齡相對表現：跟基準池比,不是絕對觀看數 ──────────────────────────────
def pick_winners(pool: list, top_n=TOP_N, min_relative=MIN_RELATIVE):
    """候選＝近 SCAN_WINDOW_H 小時內發布(且已過 MIN_AGE_H 穩定期)的片；
    基準＝POOL_MAX_AGE_H 天內全部片的 velocity 中位數(age-normalized，同齡比較用)。
    回傳依 relative 由高到低排序、且 relative>=min_relative 的候選(最多 top_n 支)。"""
    baseline_pool = [p for p in pool if p["age_h"] <= POOL_MAX_AGE_H]
    if not baseline_pool:
        return [], None
    base_vel = median(p["velocity"] for p in baseline_pool)
    if base_vel <= 0:
        return [], base_vel
    candidates = [p for p in pool if MIN_AGE_H <= p["age_h"] <= SCAN_WINDOW_H]
    for c in candidates:
        c["relative"] = round(c["velocity"] / base_vel, 2)
        c["baseline_velocity"] = round(base_vel, 3)
    candidates.sort(key=lambda x: x["relative"], reverse=True)
    winners = [c for c in candidates if c["relative"] >= min_relative][:top_n]
    return winners, base_vel


# ────────────────────────────── 3) 抽題材要素：topic_bank 比對 + fact_key(若有) ──────────────────────────────
def load_facts() -> dict:
    facts = {}
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        d = _load_json(p, {}) or {}
        for k, v in (d.get("results") or {}).items():
            if not isinstance(v, dict):
                continue
            v = dict(v)
            v.setdefault("key", k)
            v.setdefault("claim", v.get("summary", ""))
            facts[k] = v
    return facts


def match_topic_bank_entry(title: str, bank_by_norm: dict):
    return bank_by_norm.get(tb._norm(title))


def related_facts(fact_key: str, facts: dict, max_n=4) -> list:
    """同一個 fact_key 本身 + 家族相鄰(同前綴/同標的)的 fact，供 LLM 有更多真數據可切角。"""
    if fact_key not in facts:
        return []
    base = facts[fact_key]
    prefix = fact_key.split("__")[0]
    symbol = base.get("symbol", "")
    out = [base]
    for k, v in facts.items():
        if k == fact_key or len(out) >= max_n:
            continue
        if k.split("__")[0] == prefix or (symbol and v.get("symbol") == symbol):
            out.append(v)
    return out[:max_n]


def guess_related_facts_by_title(title: str, facts: dict, max_n=3) -> list:
    """贏家片沒有比對到 topic_bank(fact_key 缺)時的兜底：從標題文字抓標的代號，
    去 fact 庫裡找標的相符的，給 LLM 當『可用真數據』參考(找不到就回空，讓 LLM 走概念型標題)。"""
    hit_syms = [s for s in _SYMBOL_TOKENS if s in (title or "")]
    if not hit_syms:
        return []
    out = []
    for v in facts.values():
        sym = str(v.get("symbol", ""))
        if any(s in sym or s in v.get("key", "") for s in hit_syms):
            out.append(v)
        if len(out) >= max_n:
            break
    return out


# ────────────────────────────── 4) LLM 派生 2-3 個「同題材、不同切角」的新題目 ──────────────────────────────
def build_prompt(winner: dict, entry: dict | None, rel_facts: list, n: int) -> str:
    angles = "、".join(ANGLE_POOL)
    fact_lines = "\n".join(
        f'- fact_key="{f.get("key")}" | 標的={f.get("symbol") or f.get("desc","")} | '
        f'真實數據原文={f.get("claim","")}' for f in rel_facts
    ) or "(這支贏家片目前查無直接對應的事實庫條目——請只生成概念型標題,不要自己編具體百分比/倍數數字)"
    context = (
        f'贏家片標題：「{winner["title"]}」\n'
        f'表現：發布 {winner["age_h"]:.0f} 小時內觀看 {winner["views"]:,}，'
        f'是同期基準池 velocity 中位數的 {winner["relative"]}倍(同齡片相對表現,不是絕對數)。'
    )
    entry_ctx = ""
    if entry:
        entry_ctx = f'\n這支片原始題目資料：angle="{entry.get("angle","")}" category="{entry.get("category","")}"'
    return f"""{sc.PERSONA}

你是量化阿森頻道的選題總監（量化/自動交易教學，繁中）。{GUARD}

【任務：贏家自動放大——這支片剛驗證跑贏同齡片，趁熱追加同題材、不同切角的新題目】
{context}{entry_ctx}

【可用的真實回測事實(若有)】
{fact_lines}

【可選切角池(不必每個都用，混搭+輪流，別每題套同一種)】
{angles}

請生成 {n} 個跟這支贏家片**同題材(同標的/同主軸)、但切角彼此不同**的新影片題目——
不是換句話說同一支，是同一個「已驗證會紅」的主題延伸出不同的觀眾好奇點。

【誠信硬規(零妥協)】
1. 標題若出現百分比或倍數，該數字**一定要是上面「真實數據原文」裡出現過的數字**
   (可四捨五入，不可自己換算/拼湊新數字)。查無對應事實時，**寫概念型標題、不要帶自創的具體數字**。
2. 不喊單、不報明牌、不喊目標價、不保證會漲會賺；「穩賺/躺賺/保證」這類誇大詞一律不用。
3. {n} 個題目彼此切角要明顯不同。
4. 大多數給 short（Shorts），可有 1 支給 long（深度長片）。

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"fact_key":"若有對應則填,否則留空字串","title":"標題","angle":"一句話獨特切入點",
"category":"子領域關鍵字","format":"short 或 long"}}]"""


def _parse_llm_json(txt: str) -> list:
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


def derive_for_winner(winner: dict, entry: dict | None, facts: dict, n=DERIVE_PER_WINNER) -> list:
    import llm
    fact_key = (entry or {}).get("fact_key") or ""
    if fact_key and fact_key in facts:
        rel_facts = related_facts(fact_key, facts)
    else:
        rel_facts = guess_related_facts_by_title(winner["title"], facts)
    prompt = build_prompt(winner, entry, rel_facts, n)
    txt = llm.complete(prompt, 2000, json_mode=True, temperature=0.8)
    return _parse_llm_json(txt)


# ────────────────────────────── 5) 去重 + fact_source_guard 誠信溯源 → 寫回 topic_bank ──────────────────────────────
def numbers_present(title: str) -> bool:
    return bool(_RX_TITLE_PCT.search(title or "") or _RX_TITLE_MULT.search(title or ""))


def build_bank_records(cands: list, existing_norms: set, existing_titles: list, fact_pool: set, facts: dict):
    """對 LLM 產出的候選逐一過：禁用骨架 → 精確去重 → 骨架相似去重 → fact_source_guard 溯源。
    回傳 (可寫入的 record dict list, rejected dict)。不在此處實際寫檔(main 統一寫，方便 --dry 測)。"""
    keep = []
    rejected = {"banned": [], "exact_dup": [], "skeleton_dup": [], "unsourced": []}
    for c in cands:
        title = str(c.get("title") or "").strip()
        if not title:
            continue
        if sc.is_banned_skeleton(title):
            rejected["banned"].append(title)
            continue
        n = tb._norm(title)
        if n in existing_norms:
            rejected["exact_dup"].append(title)
            continue
        if sc.skeleton_dup_any(title, existing_titles):
            rejected["skeleton_dup"].append(title)
            continue
        bad = fsg.unsourced_claims(title, fact_pool)
        if bad:
            rejected["unsourced"].append((title, bad))
            continue
        angle = str(c.get("angle") or "").strip()
        category = str(c.get("category") or "").strip()
        fmt = "long" if str(c.get("format", "")).lower().startswith("l") else "short"
        rec = {
            "title": title,
            "angle": angle,
            "category": category,
            "format": fmt,
            "source": "winner_amplifier",
        }
        fk = str(c.get("fact_key") or "").strip()
        if fk and fk in facts:  # LLM 可能幻覺出一個看似合理但不存在的 fact_key，存進題庫前先驗證真的查得到
            rec["fact_key"] = fk
        keep.append(rec)
        existing_norms.add(n)
        existing_titles.append(title)
    return keep, rejected


# ────────────────────────────── main ──────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只掃描+生成+驗證，不寫入 topic_bank/state")
    ap.add_argument("--pool", type=int, default=DEFAULT_POOL, help="候選+基準池取最近幾支已發布片")
    ap.add_argument("--top", type=int, default=TOP_N, help="最多挑幾支贏家")
    ap.add_argument("--min-relative", type=float, default=MIN_RELATIVE, help="同齡相對表現門檻(倍數)")
    args = ap.parse_args()

    if not sc.has_llm_key():
        print("[winner_amplifier] 無任何 LLM 供應商 API key，無法生成派生題目。")
        return 1

    log_ops("贏家放大迴路", f"掃近{SCAN_WINDOW_H}h發布片(池{args.pool}支)找同齡跑贏的贏家…")
    pool = recent_pool(args.pool)
    if not pool:
        print("[winner_amplifier] 抓不到任何已發布片的即時數據(YouTube API 或 uploaded_ledger 問題)，中止。")
        return 1
    print(f"[pool] 取樣 {len(pool)} 支已發布片(來自 uploaded_ledger 最近 {args.pool} 支上傳)")

    winners, base_vel = pick_winners(pool, top_n=args.top, min_relative=args.min_relative)
    print(f"[baseline] 基準池(<= {POOL_MAX_AGE_H}h={POOL_MAX_AGE_H/24:.0f}天)velocity 中位數 = "
          f"{base_vel if base_vel is None else round(base_vel, 3)} views/h")

    if not winners:
        print(f"[winner_amplifier] 本輪沒有片跑贏同齡基準(門檻 {args.min_relative}x)，不派生、不放大。")
        log_ops("贏家放大迴路", "本輪無贏家(無片跑贏同齡基準)")
        return 0

    print(f"\n[winners] Top {len(winners)} 贏家(同齡相對表現)：")
    for w in winners:
        print(f"  🏆 x{w['relative']}　{w['views']:,}v／{w['age_h']:.0f}h　"
              f"velocity={w['velocity']}(基準{w['baseline_velocity']})　{w['title'][:44]}")

    # 冪等守門：72h 內已放大過的贏家跳過
    state = _load_json(STATE_FILE, {}) or {}
    amplified = state.get("amplified", {}) or {}
    now_ts = time.time()
    fresh_winners = []
    skipped_cooldown = []
    for w in winners:
        last = amplified.get(w["videoId"])
        if isinstance(last, (int, float)) and (now_ts - last) < REAMPLIFY_COOLDOWN_H * 3600:
            skipped_cooldown.append(w)
            continue
        fresh_winners.append(w)
    if skipped_cooldown:
        print(f"\n[冪等] {len(skipped_cooldown)} 支贏家 {REAMPLIFY_COOLDOWN_H}h 內已放大過，本輪跳過：")
        for w in skipped_cooldown:
            print(f"  ⏭ {w['title'][:44]}")
    if not fresh_winners:
        print("[winner_amplifier] 本輪贏家全部在冷卻期內，無新動作。")
        log_ops("贏家放大迴路", "本輪贏家全在冷卻期,無新動作(冪等生效)")
        return 0

    # 比對 topic_bank 找原始題目要素(angle/category/fact_key)
    bank = tb.load_bank()
    bank_by_norm = {tb._norm(t.get("title", "")): t for t in bank}
    facts = load_facts()
    existing_norms = {tb._norm(t.get("title", "")) for t in bank} | {tb._norm(t) for t in tb.existing_titles()}
    existing_titles_list = [t.get("title", "") for t in bank]
    fpool = fsg.fact_pool(refresh=True)

    all_new_recs = []
    per_winner_report = []
    for w in fresh_winners:
        if len(all_new_recs) >= DAILY_CAP:
            break
        entry = match_topic_bank_entry(w["title"], bank_by_norm)
        try:
            cands = derive_for_winner(w, entry, facts, n=DERIVE_PER_WINNER)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 派生失敗({str(e)[:100]})：{w['title'][:40]}", file=sys.stderr)
            continue
        remaining = DAILY_CAP - len(all_new_recs)
        keep, rejected = build_bank_records(cands, existing_norms, existing_titles_list, fpool, facts)
        keep = keep[:remaining]
        for rec in keep:
            rec["bucket"] = sc.classify_topic_bucket(rec["title"], rec.get("angle", ""), rec.get("category", ""))
        all_new_recs.extend(keep)
        per_winner_report.append({"winner": w, "entry": entry, "kept": keep, "rejected": rejected})
        # 不論這支贏家最後有沒有題目真的被寫入，只要跑過派生流程就記冷卻(避免生成失敗/全被拒絕時每輪重打 LLM)
        amplified[w["videoId"]] = now_ts

    print("\n[派生結果]")
    for r in per_winner_report:
        w = r["winner"]
        print(f"\n  🏆 贏家：{w['title'][:50]}  (videoId={w['videoId']}, x{w['relative']})")
        if r["entry"]:
            print(f"     原題材：angle=\"{r['entry'].get('angle','')}\"  "
                  f"category=\"{r['entry'].get('category','')}\"  fact_key=\"{r['entry'].get('fact_key','')}\"")
        else:
            print("     原題材：topic_bank 查無比對紀錄(可能來自其他產題引擎)，改用標題關鍵字兜底找相關事實")
        for rec in r["kept"]:
            print(f"     ✅ [{rec['bucket']}] {rec['title']}")
            print(f"        angle={rec['angle']}  fact_key={rec.get('fact_key','(無)')}  format={rec['format']}")
        rej = r["rejected"]
        n_rej = sum(len(v) for v in rej.values())
        if n_rej:
            print(f"     拒絕 {n_rej} 題：禁用骨架{len(rej['banned'])} 完全重複{len(rej['exact_dup'])} "
                  f"骨架相似{len(rej['skeleton_dup'])} 數字查無來源{len(rej['unsourced'])}")
            for t, bad in rej["unsourced"][:3]:
                print(f"        ✗ 數字查無來源：{t}  → {bad}")

    if not all_new_recs:
        print("\n[winner_amplifier] 本輪贏家全部派生後被誠信/去重守門擋光，0 題寫入(誠信優先於數量)。")
        if not args.dry:
            state["amplified"] = amplified
            sc.save_json_atomic(STATE_FILE, state)
        log_ops("贏家放大迴路", f"{len(fresh_winners)} 支贏家全被去重/守門擋下,0 題寫入")
        return 0

    before_unused = sum(1 for t in bank if not t.get("used"))
    if args.dry:
        print(f"\n[dry] 會寫入 {len(all_new_recs)} 題到 topic_bank(front 優先)，本次不實際寫入。")
        print(f"[dry] 題庫寫入前未用題數：{before_unused}（--dry 不變動）")
        return 0

    n_added = tb.add_topics(all_new_recs, source="winner_amplifier", front=True)
    bank_after = tb.load_bank()
    after_unused = sum(1 for t in bank_after if not t.get("used"))

    # 更新冪等狀態(含當日寫入計數，供之後擴充每日總量觀察)
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    daily = state.get("daily_added", {}) or {}
    daily[today] = daily.get(today, 0) + n_added
    state["amplified"] = amplified
    state["daily_added"] = daily
    sc.save_json_atomic(STATE_FILE, state)

    print(f"\n[ok] 題庫寫入前未用題數：{before_unused} → 寫入後：{after_unused}（新增 {n_added} 題，"
          f"add_topics 內建 topic_gate 可能再擋掉少量 P2 骨架週上限題）")
    log_ops("贏家放大迴路", f"{len(fresh_winners)} 支贏家 → 派生入庫 {n_added} 題(高優先)，"
                        f"未用題數 {before_unused}→{after_unused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
