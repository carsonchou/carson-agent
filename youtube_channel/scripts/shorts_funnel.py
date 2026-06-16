#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shorts_funnel.py — 【白帽漏洞③｜Shorts 切片漏斗 SOP】

Shorts 養帳號權重 → 灌長片：一支長片自動規劃 3–5 支 Shorts 的『切點 + 導流文案』，
每支 Short 拋一個鉤子、片尾導去長片/主頻道，形成一個『同主題引流叢集』。
對 faceless 量產特別有利（一份長內容裂變成多支高曝光 Shorts，互相拉抬權重）。

輸入優先序：
  1) output/ 內『尚未切過』的長片腳本 L_*.md（真的有長片時，照逐字稿挑切點）。
  2) 沒有新長片時，退而從題庫抽一個未用的 long 題目當『叢集主題』，規劃 3–5 支 Shorts。
輸出：
  - 把規劃出的 Shorts 題目灌進 STUDIO/topic_bank.json（parent=長片slug/主題，source=funnel）。
  - 一份人看的切片 SOP：STUDIO/REPORTS/{date}_切片漏斗_{slug}.md。
誠信鐵則：導流文案不誇大、不喊單、不保證收益。
用法：python scripts/shorts_funnel.py [--max 2] [--per 4] [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
BANK = STUDIO / "topic_bank.json"
SEEN = STUDIO / "funnel_seen.json"
TW = timezone(timedelta(hours=8))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森。"


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _load_seen():
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()
    except Exception:
        return set()


def _save_seen(seen):
    try:
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _long_scripts(seen):
    """找尚未切過的長片腳本：output/L_*.md，回傳 [(slug, title, content)]。"""
    res = []
    for f in sorted(OUT.glob("L_*.md")):
        slug = f.stem
        if slug in seen:
            continue
        try:
            txt = f.read_text(encoding="utf-8")
            first = txt.splitlines()[0] if txt else ""
            title = first.replace("# 🎬", "").replace("#", "").strip()
            res.append((slug, title or slug, txt))
        except Exception:
            continue
    return res


def _pull_long_topic(consume=True):
    """退路：題庫抽一個未用 long 題目當叢集主題。consume=True 才標記已用＋寫檔（dry 模式不動資料）。
    回傳 (seed_id, title, angle) 或 None。"""
    if not BANK.exists():
        return None
    try:
        bank = json.loads(BANK.read_text(encoding="utf-8"))
    except Exception:
        return None
    for t in bank:
        if not t.get("used") and t.get("format") == "long":
            if consume:
                t["used"] = True
                try:
                    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
            return (t.get("id", ""), t.get("title", ""), t.get("angle", ""))
    return None


def plan(per, title, body):
    """請 Claude 把一份長內容/主題規劃成 per 支 Shorts 的切點＋導流文案。"""
    import requests
    prompt = f"""你是量化阿森頻道（量化/自動交易/網格/定投/派網Pionex/風控，繁中 faceless）的【切片漏斗規劃師】。{GUARD}

把下面這支『長片/長主題』，裂變成 {per} 支獨立 Shorts，組成一個互相導流的叢集。原則：
- 每支 Short 抓長內容裡『一個最有鉤子的點』（反直覺結論／一個數字／一個常見錯誤／一個比喻），各自能獨立看懂。
- 每支結尾一句『導流文案』：自然引導去看完整長片或追蹤主頻道（不誇大、不喊單、不保證收益）。
- {per} 支彼此角度不同，不要同一句話換句話說。

長片標題：{title}
長片內容/主題：
{body[:4000]}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"這支Short的標題","angle":"切哪個點＋鉤子","cta":"片尾導流文案一句"}}]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 1800,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=150)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
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


def _write_sop(slug, title, shorts):
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ✂️ 切片漏斗 SOP｜{title}", "",
         f"> 來源：`{slug}`　規劃 {len(shorts)} 支引流 Shorts（同主題叢集，互相拉抬權重 → 導去長片/主頻道）",
         f"> 產生日：{tw_today()}　誠信鐵則：導流文案不誇大、不喊單、不保證收益", ""]
    for i, s in enumerate(shorts, 1):
        L += [f"## Short {i}：{s.get('title','')}",
              f"- **切點/鉤子**：{s.get('angle','')}",
              f"- **片尾導流文案**：{s.get('cta','')}", ""]
    (REPORTS / f"{tw_today()}_切片漏斗_{slug[:24]}.md").write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2, help="本輪最多處理幾支長片/長主題")
    ap.add_argument("--per", type=int, default=4, help="每支長片裂變成幾支 Shorts")
    ap.add_argument("--dry", action="store_true", help="只規劃、印出，不寫題庫/SOP")
    args = ap.parse_args()
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2

    seen = _load_seen()
    jobs = []  # [(slug, title, body, is_real_long)]
    for slug, title, body in _long_scripts(seen)[:args.max]:
        jobs.append((slug, title, body, True))
    # 沒有新長片就退而用題庫的 long 題目當叢集主題
    if not jobs:
        for _ in range(args.max):
            seed = _pull_long_topic(consume=not args.dry)
            if not seed:
                break
            sid, st, sa = seed
            jobs.append((f"topic_{sid}", st, f"主題：{st}\n切入點：{sa}", False))
            if args.dry:
                break  # dry 不消耗題庫，同題只取一支當樣本，避免重複

    if not jobs:
        print("[切片漏斗] 無新長片、題庫也無未用 long 題目，本輪略過。")
        log_ops("切片漏斗", "無長片/長題可切，略過")
        return 0

    from topic_bank import add_topics
    total_short, total_long = 0, 0
    for slug, title, body, is_real in jobs:
        try:
            shorts = plan(args.per, title, body)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 規劃失敗 {slug}：{exc}", file=sys.stderr); continue
        shorts = [s for s in shorts if (s.get("title") or "").strip()][:args.per]
        if not shorts:
            continue
        if args.dry:
            print(f"\n=== {title} → {len(shorts)} 支 Shorts ===")
            for s in shorts:
                print(f"  ✂️ {s.get('title','')}｜導流：{s.get('cta','')[:40]}")
            continue
        items = [{"title": s["title"],
                  # 把導流文案併進 angle，produce_batch 寫腳本時會帶到片尾
                  "angle": (s.get("angle", "") + "｜片尾導流：" + s.get("cta", "")).strip("｜"),
                  "category": "市場觀念", "format": "short",
                  "parent": slug} for s in shorts]
        n = add_topics(items, source="funnel", front=False)
        total_short += n
        total_long += 1
        _write_sop(slug, title, shorts)
        if is_real:
            seen.add(slug)
        print(f"[ok] {title[:30]} → 規劃 {n} 支引流 Shorts 進題庫")
    if not args.dry:
        _save_seen(seen)
        log_ops("切片漏斗", f"{total_long} 支長片/長題 → 裂變 {total_short} 支引流 Shorts 進題庫")
        print(f"\n[ok] 切片漏斗：{total_long} 個主題裂變成 {total_short} 支引流 Shorts，已進題庫＋SOP 報告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
