#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topic_bank.py — 【題庫引擎】先擴題庫再衝量。

由 ③創作靈感＋⑯競品 的精神，用 Claude 一次產出「跨子領域、彼此不同角度」的題目庫，
跟既有影片＋既有題庫去重，存 STUDIO/topic_bank.json。produce_batch 之後從題庫抽題產片，
保證放量時不會做出一堆重複片（避免 YouTube 懲罰重複低值內容）。

每個題目：{id, title, angle(獨特切入鉤子), category, format(short/long), used(bool)}

用法：
  python scripts/topic_bank.py                 # 補到預設 50 個未用題目
  python scripts/topic_bank.py --target 80     # 補到 80 個未用題目
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
BANK = STUDIO / "topic_bank.json"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"   # 擴題庫一次性、要創意與廣度，用較強模型

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

# 量化嚴謹標準（與 produce_batch 一致，確保題庫題目正確）
try:
    from produce_batch import QUANT_STANDARD, GUARD
except Exception:  # noqa: BLE001
    QUANT_STANDARD = ""
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"

CATEGORIES = [
    "網格交易（設定/參數/上下限/等差等比/無限網格/單邊行情/適用幣種/常見錯誤）",
    "定投 DCA（原理/微笑曲線/買在高點/分批紀律/vs一次買/標的選擇）",
    "回測與數據（過擬合/前視偏差/生存者偏差/樣本外/交易成本/夏普卡瑪MDD/勝率vs盈虧比/期望值）",
    "風控與心法（停損/部位管理/Kelly/馬丁危險/複利72法則/情緒紀律/破產風險）",
    "工具與派網 Pionex（機器人類型/手續費/安全/API/被動收入實作）",
    "市場觀念與避坑（趨勢vs震盪/被動收入迷思/新手韭菜陷阱/槓桿風險）",
]


def existing_titles():
    out = set()
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            t = first.replace("# 🎬", "").replace("#", "").strip()
            if t:
                out.add(t)
        except Exception:
            pass
    return out


def load_bank():
    if BANK.exists():
        try:
            return json.loads(BANK.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_bank(bank):
    BANK.parent.mkdir(parents=True, exist_ok=True)
    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm(t):
    return re.sub(r"[\s，。！？、：；…·\-—()（）]+", "", (t or "")).lower()


def add_topics(items, source="", front=False):
    """把外部模組（熱點/寄生/切片漏斗）產的題目併入題庫，與既有題庫＋既有影片去重。
    items: list of dict，每筆至少 {title}；可帶 angle/category/format/parent/news/priority。
    source: 標記來源（hotspot/parasite/funnel…），方便日後分析哪條漏斗有效。
    front: True＝插隊到題庫最前面（produce_batch 下批優先抽到，給『搶首發』用）。
    回傳實際新增題數。"""
    bank = load_bank()
    have = {_norm(t.get("title", "")) for t in bank} | {_norm(t) for t in existing_titles()}
    new_recs = []
    for t in items:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        n = _norm(title)
        if n in have:
            continue
        have.add(n)
        rec = {
            "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
            "title": title,
            "angle": (t.get("angle") or "").strip(),
            "category": (t.get("category") or "").strip(),
            "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
            "used": False,
        }
        if source:
            rec["source"] = source
        for k in ("parent", "news", "priority"):
            if t.get(k):
                rec[k] = t[k]
        new_recs.append(rec)
    if new_recs:
        bank = (new_recs + bank) if front else (bank + new_recs)
        save_bank(bank)
    return len(new_recs)


def gen_topics(need, avoid_titles):
    if not API_KEY:
        raise RuntimeError("無 ANTHROPIC_API_KEY")
    import requests
    cats = "\n".join(f"  - {c}" for c in CATEGORIES)
    avoid = "、".join(list(avoid_titles)[:80])
    prompt = f"""你是量化阿森頻道的選題總監（量化/自動交易教學，繁中）。{GUARD}
{QUANT_STANDARD}

請產出 {need} 個**彼此角度不同、不重複**的影片題目，平均分布在這些子領域：
{cats}

要求：
- 每題一個**獨特切入點**（反直覺結論／痛點場景／數字實測／破除迷思／比較懸念），不要同一觀念換句話說。
- 標題要有點擊慾但不誇大、不保證收益、不喊單。
- 多數給 short（Shorts），約 1/4 給 long（深度長片）。
- **避免重複以下既有題目**：{avoid}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"標題","angle":"一句話獨特切入點","category":"網格交易/定投DCA/回測數據/風控心法/工具派網/市場觀念 擇一","format":"short 或 long"}}]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 4000,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=180)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    # 先試完整陣列；截斷時退而逐一撿出完整的 {...} 物件，不整批報廢
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    items = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:
            continue
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50, help="題庫要維持的未用題目數")
    args = ap.parse_args()

    bank = load_bank()
    unused = [t for t in bank if not t.get("used")]
    have_norms = {_norm(t.get("title", "")) for t in bank} | {_norm(t) for t in existing_titles()}
    need = args.target - len(unused)
    if need <= 0:
        print(f"題庫已有 {len(unused)} 個未用題目（≥目標 {args.target}），無需補充。")
        return 0

    log_ops("題庫引擎", f"擴題庫：目標未用 {args.target}，現 {len(unused)}，需補 {need}…")
    print(f"擴題庫中：要補 {need} 個（現有未用 {len(unused)}）…")

    added = 0
    rounds = 0
    while added < need and rounds < 8:
        rounds += 1
        batch = gen_topics(min(need - added + 3, 15), have_norms | set())
        for t in batch:
            title = (t.get("title") or "").strip()
            if not title:
                continue
            n = _norm(title)
            if n in have_norms:
                continue  # 去重
            have_norms.add(n)
            bank.append({
                "id": "t" + hashlib.md5(n.encode("utf-8")).hexdigest()[:8],
                "title": title,
                "angle": (t.get("angle") or "").strip(),
                "category": (t.get("category") or "").strip(),
                "format": "long" if str(t.get("format", "")).lower().startswith("l") else "short",
                "used": False,
            })
            added += 1
            if added >= need:
                break
        save_bank(bank)

    unused_now = sum(1 for t in bank if not t.get("used"))
    by_fmt = {}
    for t in bank:
        if not t.get("used"):
            by_fmt[t["format"]] = by_fmt.get(t["format"], 0) + 1
    log_ops("題庫引擎", f"完成 新增{added} 題，現未用 {unused_now}（short {by_fmt.get('short',0)}/long {by_fmt.get('long',0)}）")
    print(f"[ok] 新增 {added} 題，題庫現有未用 {unused_now} 個"
          f"（short {by_fmt.get('short',0)} / long {by_fmt.get('long',0)}）→ {BANK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
