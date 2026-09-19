#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_credit_watch.py — OpenRouter 餘額看板 + 低水位告警。

## 為什麼(2026-08-28 的實際事故)
長片一支都產不出來,ops_log 只寫「所有 LLM 供應商都失敗」。追了一小時才發現:
    gemini      429 限流
    groq        429 限流(長片 ~14k tokens 本來就吃不下)
    openrouter  **餘額 -0.12 USD**,儲值的 20 美元用完了
    ollama      本機模型,唯一還活著
**整條產線停擺,而且沒有任何警訊。** 儲值餘額是唯一沒有被監控的單點故障。

而且它便宜到不該用完:良率修好後每支長片約 **US$0.025**(2.3 次大呼叫 × 15k tokens),
每天 10 支 = US$0.25/天 ≈ **7 美元/月**。20 美元原本能撐 800 支。
之所以會用完,是因為前一陣良率 35%(每支燒 9 次而不是 2.3 次)——
**良率修法直接把單支成本壓到四分之一**,這也是為什麼良率不只是品質問題。

## 用法
  python scripts/llm_credit_watch.py            # 看餘額與可撐支數
  python scripts/llm_credit_watch.py --notify   # 低於門檻才推 ntfy(給 cron 用)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# 實測單價:gemini-2.5-flash 在 OpenRouter 約 $0.30/M 輸入、$2.50/M 輸出;
# 長片提示約 15k tokens、輸出約 2.5k,良率修好後平均 2.3 次大呼叫/支。
COST_PER_VIDEO = 0.0247
WARN_VIDEOS = int(os.environ.get("LLM_CREDIT_WARN_VIDEOS", "120"))   # 剩不到約 3 天量就喊


def balance():
    """回 (餘額 USD, 已用, 總儲值);拿不到回 (None, None, None)。"""
    try:
        import local_cron as lc
        os.environ.update({k: v for k, v in lc.load_env().items()
                           if k not in os.environ})
    except Exception:  # noqa: BLE001
        pass
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        return None, None, None
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/credits",
                                     headers={"Authorization": "Bearer " + k})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data", {})
        tc = float(d.get("total_credits", 0))
        tu = float(d.get("total_usage", 0))
        return tc - tu, tu, tc
    except Exception:  # noqa: BLE001
        return None, None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="低於門檻才推 ntfy")
    args = ap.parse_args()

    bal, used, total = balance()
    if bal is None:
        print("查不到餘額(缺 OPENROUTER_API_KEY 或連不上)。")
        return 0
    vids = int(bal / COST_PER_VIDEO) if bal > 0 else 0
    print(f"OpenRouter 餘額 US${bal:.2f}(已用 {used:.2f} / 儲值 {total:.2f})")
    print(f"  照每支長片 US${COST_PER_VIDEO:.4f} 估,還可產約 **{vids} 支**"
          f"(每天 10 支 ≈ {vids//10} 天)")
    if bal <= 0:
        print("  🔴 **餘額已用盡 —— 長片會完全產不出來**(免費層吃不下 14k tokens 的提示)")
    elif vids < WARN_VIDEOS:
        print(f"  ⚠️ 低於門檻({WARN_VIDEOS} 支),建議儲值")
    if args.notify and vids < WARN_VIDEOS:
        try:
            from notify import push
            push("LLM 餘額不足",
                 f"OpenRouter 剩 US${bal:.2f},約 {vids} 支長片。"
                 f"用完長片會完全產不出來(免費層吃不下)。openrouter.ai/credits")
            print("  已推 ntfy")
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 推播失敗:{str(e)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
