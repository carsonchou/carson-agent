#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parasite_titles.py — 【白帽漏洞②｜寄生標題產生器】

蹭別人的流量池：競品爆款一紅，2 小時內出一支『同主題 + 我們的誠實/反方角度』，
吃它的長尾搜尋與推薦欄寄生。本檔吃 STUDIO/intel.json（競品情報部撈的高觀看競品）
＋ competitor_analysis.md 最新拆解，用 Claude 產一批『寄生 + 好奇缺口』題目灌進題庫，
produce_batch 之後自動把它們做成片。

寄生不是抄：守誠信鐵則，用我們的回測數據/誠實護城河做出差異化反方觀點，不誤導不喊單。
用法：python scripts/parasite_titles.py [--count 8] [--dry]
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
INTEL = STUDIO / "intel.json"
ANALYSIS = ROOT / "competitor_analysis.md"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"   # 要創意＋懂寄生分寸，用較強模型

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森(網格/定投/派網/回測/風控)。"


def _top_competitors(n=15):
    """讀競品情報部最近撈到的高觀看競品標題（最新鮮的寄生標的）。"""
    try:
        d = json.loads(INTEL.read_text(encoding="utf-8"))
        return [(t.get("title", ""), t.get("channel", ""), t.get("views", 0))
                for t in d.get("top", [])][:n]
    except Exception:
        return []


def _analysis_tail(chars=2500):
    """讀 competitor_analysis.md 末段（最新自動學習的拆解），給 Claude 抓最新爆款角度。"""
    try:
        return ANALYSIS.read_text(encoding="utf-8")[-chars:]
    except Exception:
        return ""


def gen(count, comps, tail):
    import requests
    comp_lines = "\n".join(f"- 👁{v:,}｜{t}　@{c}" for t, c, v in comps) or "（暫無情報）"
    prompt = f"""你是量化阿森頻道（量化/自動交易/網格/定投/派網Pionex/風控，繁中 faceless）的【寄生流量選題官】。{GUARD}

【寄生流量心法】競品爆款影片＝現成的流量池。我們要出『同主題、但用我們的誠實/反方/回測角度』的影片，
吃它的長尾搜尋與推薦欄寄生。關鍵：
- 同題不同角：對手講「網格穩賺」→ 我們講「網格我也會虧的情況」；對手只曬贏單→我們補回測勝率真相。
- 好奇缺口（Curiosity Gap）：標題拋懸念逼點開，但片裡『真的有答案』，不准標題殺人（封面講A內容講B會被降推）。
- 可埋熱門幣種/工具名（BTC、Pionex、ETF…）蹭搜尋，但不得碰瓷造謠、不冒充對方。

以下是近期『高觀看競品影片』（你的寄生標的，挑最相關的題材切入）：
{comp_lines}

以下是competitor_analysis.md最新拆解片段（抓最新爆款角度與鉤子）：
{tail}

請產出 {count} 個『寄生 + 好奇缺口』影片題目，要求：
- 緊貼上面競品的熱門題材，但角度是我們的誠實/反方/回測差異化，不是換句話說抄。
- 標題有強點擊慾但不誇大、不保證收益、不喊單。
- 多數 short，約 1/5 可給 long（深度反方拆解）。

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"寄生標題","angle":"一句話：蹭哪個競品題材＋我們的差異化反方角度","category":"網格交易/定投DCA/回測數據/風控心法/工具派網/市場觀念 擇一","format":"short 或 long"}}]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 2500,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8, help="本輪要產幾個寄生題目")
    ap.add_argument("--dry", action="store_true", help="只產、印出，不寫題庫")
    args = ap.parse_args()
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2

    comps = _top_competitors()
    if not comps:
        print("[寄生] intel.json 無競品資料（競品情報部尚未跑？），改用 analysis 拆解產題。")
    tail = _analysis_tail()
    try:
        picks = gen(args.count, comps, tail)
    except Exception as exc:  # noqa: BLE001
        log_ops("寄生標題", f"⚠️ 產題失敗：{str(exc)[:70]}")
        print(f"[FATAL] 產題失敗：{exc}", file=sys.stderr); return 3

    picks = [p for p in picks if (p.get("title") or "").strip()][:args.count]
    if not picks:
        print("[寄生] 沒產出可用題目。"); return 0

    if args.dry:
        for p in picks:
            print(f"[dry] {p.get('title','')}\n      角度：{p.get('angle','')[:70]}　[{p.get('format','short')}]")
        return 0

    from topic_bank import add_topics
    added = add_topics(picks, source="parasite", front=False)
    log_ops("寄生標題", f"寄生競品爆款 → 題庫新增 {added} 題")
    print(f"[ok] 寄生標題：{added} 個蹭流量題目已進題庫，produce_batch 之後自動做成片。")
    for p in picks:
        print(f"   🪝 {p['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
