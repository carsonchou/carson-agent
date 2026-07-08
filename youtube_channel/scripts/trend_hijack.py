#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trend_hijack.py — 趨勢/格式劫持引擎(D1)。

抓 outlier_scan 已產的 STUDIO/outliers.json(競品在量化/AI/交易niche的爆款),
挑最猛(ratio高=相對頻道規模爆)且沒劫持過的一支 → 用 LLM 改寫成「量化阿森」自己的
誠實角度(拆解/實測/避雷,不抄標題不喊單)→ 呼叫 produce_batch --topic 產一支過贏家公式的同型片。
騎上正在紅的題型=演算法加速器。

誠實:trending 音檔無官方 API + 版權音檔失 Shorts 分潤 → 本工具只產「內容」,並輸出
「建議在 Shorts app 手動配 trending 音檔」提醒(pre-YPP 為觸及值得),不假裝自動配音檔。

用法:python scripts/trend_hijack.py [--dry] [--max N]
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
STATE = STUDIO / "trend_hijacked.json"

import studio_common as sc


def _load_env():
    envf = ROOT / ".env"
    import os
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _adapt(outlier_title):
    """把競品爆款標題改寫成量化阿森誠實角度(拆解/實測/避雷),回 {title, angle} 或 None。"""
    prompt = f"""{sc.PERSONA}
一支競品爆款影片標題是:「{outlier_title}」
請把它改寫成「量化阿森」自己的誠實角度短片題目——**不是抄標題**,是借「這個正在紅的題型」用我們的角度(拆解/實測/回測/避雷)重做。
要求:①標題含具體數字/對比+懸念,像「我實測XX,結果...」「照著做90%會虧,問題在...」②誠信:不喊單不報明牌不保證收益、不誇大③不點名攻擊competitor。
只輸出 JSON:{{"title":"標題","angle":"一句話切入點"}}"""
    try:
        import llm
        txt = llm.complete(prompt, 400, json_mode=True)
        import re
        m = re.search(r"\{.*\}", txt or "", re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print(f"[hijack] 改寫失敗:{str(e)[:70]}", file=sys.stderr)
        return None


def main() -> int:
    _load_env()
    dry = "--dry" in sys.argv
    o = sc.load_json_safe(STUDIO / "outliers.json", {}) or {}
    outliers = o.get("outliers") or []
    if not outliers:
        print("[hijack] 無 outliers.json 資料(先跑 outlier_scan)。")
        return 0
    done = set(sc.load_json_safe(STATE, []) or [])
    recent = sc.recent_titles(80)
    # 依 ratio 排序,挑沒劫持過的最猛一支
    for cand in sorted(outliers, key=lambda x: -(x.get("ratio", 0) or 0)):
        vid = cand.get("id")
        if not vid or vid in done:
            continue
        print(f"[hijack] 目標爆款:{cand.get('title', '')[:44]}（{cand.get('views')}v ratio {cand.get('ratio')}）")
        ad = _adapt(cand.get("title", ""))
        if not ad or not ad.get("title"):
            done.add(vid); continue
        title, angle = ad["title"], ad.get("angle", "")
        if sc.topic_gate(title, recent):
            print(f"[hijack] 改寫標題卡洗版閘,跳過:{title[:30]}")
            done.add(vid); continue
        print(f"[hijack] 改寫成:{title}")
        print("  💡 手動提醒:發布時在 Shorts app 手動配一個 trending 音檔(pre-YPP 為觸及值得;版權音檔會失分潤,post-YPP 改回原創BGM)")
        if not dry:
            subprocess.run([PY, "scripts/produce_batch.py", "--topic", title, "--angle", angle], cwd=str(ROOT))
            done.add(vid)
            sc.save_json_atomic(STATE, sorted(done))
            try:
                from ops import log_ops
                log_ops("趨勢劫持", f"劫持爆款題型產片:{title[:36]}")
            except Exception:  # noqa: BLE001
                pass
        break
    else:
        print("[hijack] 所有 outlier 都劫持過了,等 outlier_scan 抓新的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
