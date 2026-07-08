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
import studio_common as sc   # 共用地基：PERSONA / has_llm_key / evidence_block
MODEL = "claude-haiku-4-5-20251001"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass
try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森。"


def gen(count):
    prompt = f"""{sc.PERSONA}

你是量化阿森（量化/網格/定投/派網Pionex/回測/風控，繁中 faceless Shorts）的招牌系列選題官。{GUARD}

{sc.evidence_block()}

請產 {count} 個『實驗格式』題目——這是本 niche 最穩的爆款骨架，務必照骨架：
- 骨架A「回測·我幫你試」：我用回測『丟 [具體金額] 給 [機器人/某策略]』跑 [時間框架]，[條件/限制]，會不會被割/虧光？結果是…（是回測、不假稱真錢；先戳恐懼再給安心的懸念）
  例：我回測『丟 1 萬給這網格機器人』跑 30 天，全程不動它，會不會被割？結果出乎意料
- 骨架B「對決」：[A] vs [B]，30 天誰先賺到 X%／誰先爆倉/被套？
  例：網格機器人 vs 定投，同樣 1 萬本金，新手該選哪個才不會送死？
- 骨架C「AI×交易實測」：我用 [Claude Code/ChatGPT/Cursor] 手搓一個交易 bot，跑 [X 天]，
  帳戶從 [具體金額] 到 [結果]；或 AI 選股 vs 人工選股回測打臉；或照抄某支瘋傳 AI 策略樣本外會怎樣。
  這是本頻道最大外部爆款池（競品「用 Vibe Coding 手搓量化」「AI 選股 30 秒」單支 6.6～30 萬觀看），
  Carson 真的用 Claude Code 寫過交易 bot＝對手抄不出的誠實護城河，角度只准數據/回測/拆穿/避雷/教學：
  例：我用 Claude Code 手搓一個量化交易 bot，$1 萬跑 30 天，帳戶從 1 萬到多少？
  例：AI 選股 30 秒 vs 人工選股一小時，誰準？回測打臉給你看
  例：照抄那支瘋傳「勝率 812%」的 AI 策略，樣本外會怎樣？
  **絕不喊單、不報明牌、不喊目標價、不保證會漲會賺**——文字要體現「我先幫你試/樣本外打臉」，不是「這樣做會賺」。
要求：金額/時間/數字要具體；用「小白怕被割→我先幫你試→這樣才安全」的情緒鉤子；
結尾留懸念但不誇大、不保證、不喊單；用『含回撤的真回測』口吻；
**優先靠向上面『本頻道實證數據』已驗證會爆的實驗題材**；
主題涵蓋網格/定投/合約網格/資金費率/AI交易/不同參數對比等，彼此不重複。

只輸出 JSON 陣列：[{{"title":"標題","angle":"一句話：實驗設定＋要驗證什麼＋誠實揭露點","format":"short"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    txt = llm.complete(prompt, 2000, json_mode=True)
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
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr); return 2
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
