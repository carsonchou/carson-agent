#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_short_to_short.py — 建 STUDIO/short_to_short.json：把每支「本機已渲染、尚未上架」的
Short 對到最相關的「已發布」Short，供 daily_publish._short_link_for 做 Short→Short 同系列/同題材
連看（現只有 Short→Long，Short 之間全靠死連頻道首頁；這支補上「接下來看哪支 Short」，衝 session
watchtime——2026 演算法核心訊號）。

跟 build_short_to_long.py 的關鍵差異（這差異修正了 short_to_long 隱藏的「鍵集合」問題，順便讓
Short→Short 從第一天就真的會命中，不是重造一次同樣的坑）：
  short_to_long 的 key 取自 ledger（已發布）shorts —— 但 daily_publish 呼叫 _long_link_for 時，
  當下要寫描述的那支 Short 依定義「尚未上架」，不可能已經是 ledger key，所以 m.get(slug) 幾乎
  永遠落空。這支反過來：key＝本機已渲染但尚未上架的 short（output/S_*.mp4 減 ledger，跟
  daily_publish.find_candidates 同一批候選），value＝已發布的 short（ledger 裡有 videoId），
  確保 daily_publish 發布這支新片「當下」，查得到一支真實存在、已經可以點擊的舊 Short。

四層匹配（依序，先中先用，全部沒中就不寫，該 Short 於發布時 fallback 回既有 Short→Long／
頻道首頁，既有行為不受影響——每一層挑的都只會是 published_shorts 池裡的片，即 ledger 已有
videoId 的已發布 Short，絕不會寫出指向 pending／未發布片的死連結）：
  ①EP 實測系列（招牌 franchise，slug 含 EPn，如「EP18」「EP2」）：對到「已發布、EP 編號 <
    自己且最接近」的前一集。新集數還沒上架、連不到未來，只能連回上一集讓觀眾追系列，多次發布後
    自然疊出 EPn→EP(n-1)→…→EP1 的完整連看鏈。
  ②「回測陷阱」礦脈系列同概念（2026-07-10 新增，見 VEIN_CONCEPTS＠build_short_to_long.py）：
    候選片命中「樣本外／過擬合／前視偏差／倖存者偏差／夏普／信賴區間／Walk-Forward／滑點」任一
    概念關鍵詞時，優先在「已發布且命中同一概念」的片池裡挑 bigram 最像的一支——關鍵詞先篩池、
    bigram 只當池內排序用，避免被「回測87勝率是假的」這類共用套話 hook 誤導選到不同概念的片
    （bigram 全域比對時「前視偏差」候選片最像的常常是套話重疊度高、但概念完全不同的片）。
    這一層讓 8 支礦脈候選片彼此按「同方法論陷阱」互相連看，是這批片能串成系列 binge 鏈的關鍵。
  ③「回測陷阱」礦脈系列同家族次選：②同概念池是空的（該概念還沒有任何片發布過，例如「信賴
    區間」目前頻道零命中）時，退一步在「命中任一礦脈概念」的更大池子裡挑 bigram 最像的一支，
    門檻 VEIN_FAMILY_THRESH＝0.08（比④的一般門檻更寬，因為池子本身已用關鍵詞篩過同家族，
    弱 bigram 分數仍可信；空池或分數不到門檻就不寫，不硬湊）。
  ④同題材 bigram 相似度（一般候選片，非礦脈系列）：跟 build_short_to_long.py 同一套字元
    bigram Jaccard 演算法（直接 import 沿用，不重造一份），THRESH 沿用該檔 2026-07-10 起的
    0.10（原 0.15，人工抽驗 0.10~0.15 這段新增配對皆同題材無亂配後調降，見同檔頂部註記與
    docs/REPORTS/2026-07-10_連看與QA.md），在「已發布 shorts」池裡挑最像的一支。

任何缺檔/例外 → 產空檔或保留現狀，絕不崩。

排程：跟 build_short_to_long.py 同時機（cron 06:50 前後）跑，確保 12:30/20:30 上架時
_short_link_for 拿得到對應的已發布 Short。

用法：python scripts/build_short_to_short.py --dry-run   # 只印統計/抽樣對應，不寫檔
      python scripts/build_short_to_short.py              # 正式建檔（純本機 json，不連網）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"          # {slug: videoId}，已發布
OUTPUT = ROOT / "output"                          # 本機已渲染 mp4（含尚未上架的候選）
OUT_JSON = STUDIO / "short_to_short.json"         # {candidate_short_slug: published_short_slug}
THRESH = 0.10                                     # 沿用 build_short_to_long.py 門檻(2026-07-10 起 0.10，見該檔註記)
VEIN_FAMILY_THRESH = 0.08                         # ③礦脈同家族次選門檻，比④寬（池已用關鍵詞篩過同家族）

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

try:
    # 沿用同一套題材相似度演算法 + 礦脈概念關鍵詞表，不重造一份
    from build_short_to_long import _bigrams, _jaccard, _vein_concepts
except Exception:  # noqa: BLE001
    def _bigrams(slug: str) -> set:
        s = re.sub(r"^[SL]_+", "", slug or "")
        s = re.sub(r"[^0-9A-Za-z一-鿿]+", "", s).lower()
        if len(s) < 2:
            return {s} if s else set()
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def _jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    _VEIN_CONCEPTS_FALLBACK = {
        "walk_forward": ["walk-forward", "walkforward"],
        "oos": ["樣本外"],
        "overfit": ["過擬合"],
        "lookahead": ["前視偏差"],
        "survivorship": ["倖存者偏差", "生存者偏差", "存活者偏差"],
        "sharpe": ["夏普"],
        "ci": ["信賴區間"],
        "slippage": ["滑點", "隱形殺手"],
    }

    def _vein_concepts(slug: str) -> set:
        s = (slug or "").lower()
        out = set()
        for concept, kws in _VEIN_CONCEPTS_FALLBACK.items():
            for kw in kws:
                if kw.lower() in s:
                    out.add(concept)
                    break
        return out


_EP_RE = re.compile(r"EP\s*0*(\d{1,3})", re.IGNORECASE)


def _ep_num(slug: str):
    """抽 slug 裡的 EP 集數（招牌實測系列用），抓不到回 None。"""
    m = _EP_RE.search(slug or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:  # noqa: BLE001
        return None


def _load_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def candidate_shorts(ledger: dict) -> list:
    """本機已渲染、尚未上架的 Short slug（daily_publish 之後會拿去發布的那批候選，
    篩選條件同 daily_publish.find_candidates：不在 ledger、檔案不是壞檔）。"""
    out = []
    if not OUTPUT.exists():
        return out
    for f in OUTPUT.glob("S_*.mp4"):
        slug = f.stem
        if slug in ledger:
            continue
        if f.stat().st_size < 100 * 1024:
            continue
        out.append(slug)
    return out


def _match_one(cand: str, ep_index: dict, published_shorts: list, pub_bg: dict,
               vein_concepts_by_pub: dict = None):
    """回傳 (target_slug_or_None, how_str)。how 只供 dry-run 顯示用。
    vein_concepts_by_pub：{published_slug: set(concept)} 預先算好的礦脈概念表(避免每支候選片
    都重算全池，見 build())；未傳（如舊呼叫方式）就即時算，行為不變只是較慢。"""
    cn = _ep_num(cand)
    if cn is not None:
        prev_nums = sorted((n for n in ep_index if n < cn), reverse=True)
        if prev_nums:
            return ep_index[prev_nums[0]][0], f"EP{prev_nums[0]}接續"

    cb = _bigrams(cand)
    if vein_concepts_by_pub is None:
        vein_concepts_by_pub = {s: _vein_concepts(s) for s in published_shorts}
    cand_concepts = _vein_concepts(cand)
    if cand_concepts:
        same_pool = [s for s in published_shorts if vein_concepts_by_pub.get(s) & cand_concepts]
        if same_pool:
            best, best_sc = None, -1.0
            for s in same_pool:
                sc = _jaccard(cb, pub_bg[s])
                if sc > best_sc:
                    best_sc, best = sc, s
            if best:
                return best, f"vein同概念({','.join(sorted(cand_concepts))}){best_sc:.2f}"
        fam_pool = [s for s in published_shorts if vein_concepts_by_pub.get(s)]
        if fam_pool:
            best, best_sc = None, 0.0
            for s in fam_pool:
                sc = _jaccard(cb, pub_bg[s])
                if sc > best_sc:
                    best_sc, best = sc, s
            if best and best_sc >= VEIN_FAMILY_THRESH:
                return best, f"vein同家族{best_sc:.2f}"

    best, best_sc = None, 0.0
    for s in published_shorts:
        sc = _jaccard(cb, pub_bg[s])
        if sc > best_sc:
            best_sc, best = sc, s
    if best and best_sc >= THRESH:
        return best, f"bigram{best_sc:.2f}"
    return None, ""


def build() -> dict:
    ledger = _load_json(LEDGER)
    published_shorts = [k for k in ledger if k.startswith("S_") and ledger.get(k)]
    cands = candidate_shorts(ledger)
    mapping: dict = {}
    if published_shorts and cands:
        ep_index: dict = {}
        for s in published_shorts:
            n = _ep_num(s)
            if n is not None:
                ep_index.setdefault(n, []).append(s)
        pub_bg = {s: _bigrams(s) for s in published_shorts}
        vein_concepts_by_pub = {s: _vein_concepts(s) for s in published_shorts}
        for cand in cands:
            target, _how = _match_one(cand, ep_index, published_shorts, pub_bg, vein_concepts_by_pub)
            if target:
                mapping[cand] = target
    try:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[short_to_short] 寫檔失敗（保留現狀）：{exc}", file=sys.stderr)
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印統計/抽樣對應，不寫檔")
    args = ap.parse_args()

    ledger = _load_json(LEDGER)
    published_shorts = [k for k in ledger if k.startswith("S_") and ledger.get(k)]
    cands = candidate_shorts(ledger)

    if args.dry_run:
        print(f"[dry-run] 已發布 shorts {len(published_shorts)} 支，本機待上架候選 {len(cands)} 支。")
        ep_index: dict = {}
        for s in published_shorts:
            n = _ep_num(s)
            if n is not None:
                ep_index.setdefault(n, []).append(s)
        pub_bg = {s: _bigrams(s) for s in published_shorts}
        vein_concepts_by_pub = {s: _vein_concepts(s) for s in published_shorts}
        hit = 0
        for cand in cands[:20]:
            target, how = _match_one(cand, ep_index, published_shorts, pub_bg, vein_concepts_by_pub)
            if target:
                hit += 1
                print(f"  {cand[:40]} -> {target[:40]} ({how})")
            else:
                print(f"  {cand[:40]} -> （無匹配，fallback 既有 Short→Long／頻道首頁）")
        if len(cands) > 20:
            print(f"  ... 還有 {len(cands) - 20} 支候選未列出")
        print(f"[dry-run] 前 {min(20, len(cands))} 支候選中，{hit} 支找到 Short→Short 對應。")
        return 0

    m = build()
    print(f"[short_to_short] 已建 {len(m)} 筆 short→short 對應 -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
