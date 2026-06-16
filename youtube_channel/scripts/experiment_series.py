#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""experiment_series.py — 【實驗格式招牌系列】量產本 niche 已驗證會爆的骨架題目。

格式骨架（competitor_growth_research 實證最穩）：
  「我給 [機器人/策略] [$金額] 跑 [時間]，[沒看盤/極端條件]，結果…」「[A] vs [B]，誰先賺/誰破產？」
  數字具體＋時間框架＋懸念結果＝Shorts 最穩爆款骨架。
本檔用 Claude 產一批這種題目（守誠實鐵則：用含回撤的真回測口吻、不喊單），插隊進 topic_bank。
排程每週補一批，讓產線固定有「招牌系列」在跑。
用法：python scripts/experiment_series.py [--count 6] [--dry]
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass
try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森。"


def gen(count):
    import requests
    prompt = f"""你是量化阿森（量化/網格/定投/派網Pionex/回測/風控，繁中 faceless Shorts）的招牌系列選題官。{GUARD}

請產 {count} 個『實驗格式』題目——這是本 niche 最穩的爆款骨架，務必照骨架：
- 骨架A「實測」：我給 [機器人/某策略] [具體金額] 跑 [時間框架]，[條件/限制]，結果是…（懸念）
  例：我給派網網格機器人 1 萬元跑 30 天，全程沒看盤，結果賺賠出乎意料
- 骨架B「對決」：[A] vs [B]，30 天誰先賺到 X%／誰先爆倉？
  例：網格機器人 vs 定投，同樣 1 萬本金，誰先賺 10%？
要求：金額/時間/數字要具體；結尾留懸念但不誇大、不保證、不喊單；用『含回撤的真回測』口吻；
主題涵蓋網格/定投/合約網格/資金費率/AI交易/不同參數對比等，彼此不重複。

只輸出 JSON 陣列：[{{"title":"標題","angle":"一句話：實驗設定＋要驗證什麼＋誠實揭露點","format":"short"}}]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 2000, "temperature": 0.6,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=150)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    out = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            out.append(json.loads(om.group(0)))
        except Exception:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2
    picks = [p for p in gen(args.count) if (p.get("title") or "").strip()][:args.count]
    if not picks:
        print("[experiment] 沒產出題目。"); return 0
    if args.dry:
        for p in picks:
            print(f"[dry] {p['title']}\n      {p.get('angle','')[:70]}")
        return 0
    from topic_bank import add_topics
    added = add_topics([{"title": p["title"], "angle": p.get("angle", ""),
                         "category": "工具派網", "format": "short", "priority": "series"} for p in picks],
                       source="experiment", front=True)
    log_ops("實驗系列", f"招牌實驗格式 +{added} 題進題庫")
    print(f"[ok] 實驗格式系列：{added} 個題目已插隊進題庫（優先製作）。")
    for p in picks:
        print(f"   🧪 {p['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
