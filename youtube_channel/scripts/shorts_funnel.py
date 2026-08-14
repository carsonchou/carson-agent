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
import studio_common as sc  # noqa: E402  共用地基：PERSONA、has_llm_key、evidence_block
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
BANK = STUDIO / "topic_bank.json"
SEEN = STUDIO / "funnel_seen.json"
TW = timezone(timedelta(hours=8))

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
    """找尚未切過的長片腳本：output/L_*.md，回傳 [(slug, title, content)]。

    2026-08-12 贏家優先:舊版 sorted(glob) = **字母序**,切到哪支全看檔名。跨頻道研究
    (20 頻道實抓)的結論是:同行 Shorts 成功的全是「從已成功的長片切出的結論」,獨立產
    的 Shorts 就是我們自己量到的 0.04 訂閱/支。改成:已發布且有觀看的長片按觀看數
    降冪排最前(贏家先切),未發布/查無觀看的排後(字母序維持穩定)。"""
    views = {}
    try:
        _q = json.loads((STUDIO / "quality_scores.json").read_text(encoding="utf-8"))
        for it in (_q.get("published") or []):
            if it.get("slug"):
                views[it["slug"]] = it.get("views") or 0
    except Exception:  # noqa: BLE001
        pass
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
    res.sort(key=lambda r: -views.get(r[0], 0))
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
    """請 LLM 把一份長內容/主題規劃成 per 支 Shorts 的切點＋導流文案。"""
    ev = sc.evidence_block()
    prompt = f"""{sc.PERSONA}
以上是頻道人設(含軟性新定位:照顧怕被割的小白)。你現在是這個頻道的【切片漏斗規劃師】。{GUARD}
{(ev + chr(10)) if ev else ""}
把下面這支『長片/長主題』，裂變成 {per} 支獨立 Shorts，組成一個互相導流的叢集。原則：
- 每支 Short 對齊小白：抓『一個新手最容易踩的雷 / 最常見的誤解 / 一個會害人被割的錯做法』當切點，
  用「我先幫你試、別自己送死」的口吻拆給小白聽，各自能獨立看懂。
- 也可用反直覺結論／一個數字／一個比喻當鉤子，但落點都要回到「小白怎麼避雷、怎麼不被割」。
- 優先靠向上面【本頻道實證數據】裡已驗證高完播的角度(有的話)，別憑空發想。
- 每支結尾一句『導流文案』：自然引導去看完整長片或追蹤主頻道（不誇大、不喊單、不保證收益）。
- {per} 支彼此角度不同，不要同一句話換句話說。

長片標題：{title}
長片內容/主題：
{body[:4000]}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"這支Short的標題","angle":"切哪個新手雷/誤解＋鉤子","cta":"片尾導流文案一句"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    # 🔴 2026-08-14:這支每天都被 Groq 免費層 429 打掉(08-13、08-14 連兩天「規劃失敗:
    # groq 429 rate limit」→ 切片漏斗連續產出 0 支)。而它是目前最重要的一條管線:
    # Shorts feed 每天帶進 1,200+ 次**外部**觸及(頻道最大的非訂閱者來源),而贏家切片
    # 是研究實證唯一能把那些觸及轉成訂閱的作法。
    # 它一天只打 1~2 次小呼叫,走付費(OpenRouter)的成本約 $0.0001/次——為了省這個
    # 而讓整條戰略管線每天掛掉,是明顯錯誤的取捨。故此處局部覆寫 LLM_BIG_FOR_SMALL,
    # 讓小呼叫也能用付費供應商;用完還原,不影響其他部門的省錢設定。
    _prev_small = os.environ.get("LLM_BIG_FOR_SMALL")
    os.environ["LLM_BIG_FOR_SMALL"] = "1"
    try:
        txt = llm.complete(prompt, 1800, json_mode=True)
    finally:
        if _prev_small is None:
            os.environ.pop("LLM_BIG_FOR_SMALL", None)
        else:
            os.environ["LLM_BIG_FOR_SMALL"] = _prev_small
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
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr); return 2

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
