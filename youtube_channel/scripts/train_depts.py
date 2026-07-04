#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_depts.py — 進修部門（每週）：用真實成效數據訓練各部門，越跑越強。

每週分析本週真實成效（流量訊號＋Analytics＋本週報告），用 Claude 產出**各部門可落地的進修洞察**，
寫成 STUDIO/training_insights.md（製作/決策部門會讀它當補充心法）＋ 部門進修報告。

安全設計：只寫「進修洞察」補充層，**不覆蓋**人工手調的 competitor_playbook.md 核心。
誠信鐵則：不編造損益、不保證收益；數據太少就說「累積中」，不硬掰。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
INSIGHTS = STUDIO / "training_insights.md"
SIGNALS = STUDIO / "traffic_signals.json"
PLAYBOOK = STUDIO / "competitor_playbook.md"
TW = timezone(timedelta(hours=8))

import requests  # noqa: E402

try:
    import yt_analytics as ya
except Exception:  # noqa: BLE001
    ya = None
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        pass

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"  # 一週一次，用較強模型成本低


def _gather() -> str:
    """蒐集本週真實成效素材。"""
    parts = []
    # 流量訊號
    try:
        if SIGNALS.exists():
            sig = json.loads(SIGNALS.read_text(encoding="utf-8"))
            tv = "；".join(f"{v['slug'][:28]}({v['views']}觀看/{v['avg_pct']}%看完)"
                           for v in sig.get("top_videos", [])[:8])
            parts.append(f"[流量訊號] 贏家題材={sig.get('win_keywords')}；弱題材={sig.get('weak_keywords')}；"
                         f"高流量影片={tv or '累積中'}；近28天 觀看{sig.get('channel_28d',{}).get('views',0)}、"
                         f"看完率{sig.get('channel_28d',{}).get('avg_pct',0)}%")
    except Exception:
        pass
    # Analytics 補充
    try:
        if ya and ya.available():
            cs = ya.channel_summary(28) or {}
            ic = ya.impressions_ctr(28) or {}
            parts.append(f"[Analytics] 觀看{cs.get('views',0)}、看完率{round(cs.get('avg_pct',0) or 0,1)}%、"
                         f"新增訂閱{cs.get('subs_gained',0)}、曝光{ic.get('impressions',0)}、CTR{round(ic.get('ctr',0) or 0,2)}%")
    except Exception:
        pass
    # 本週決策/回顧報告（摘要）
    try:
        wk = [(REPORTS / f).name for f in []]  # placeholder
        recent = sorted(REPORTS.glob("*_決策.md"), reverse=True)[:1] + sorted(REPORTS.glob("*_回顧檢討.md"), reverse=True)[:1]
        for p in recent:
            parts.append(f"[{p.stem}] " + " ".join(p.read_text(encoding="utf-8").split())[:400])
    except Exception:
        pass
    return "\n".join(parts) or "（本週數據仍在累積）"


def _ask_claude(material: str) -> dict:
    prompt = f"""你是量化阿森 YouTube 工作室的【進修部門】教練。頻道=量化/自動交易教學(網格/定投/派網Pionex/回測/風控)，繁中，主攻 Shorts 衝 YPP。
誠信鐵則：不編造損益、不保證收益、不喊單。數據太少時就給「保持多元測試、衝量累積數據」這類務實方向，不硬掰假洞察。

以下是本週真實成效數據：
{material}

請基於**真實數據**，產出各部門「下週可落地的進修重點」，只輸出 JSON（不要其他字）：
{{
 "summary":"本週成效一句話總結",
 "production":["製作/腳本進修：從高留存影片的共通鉤子/結構/比喻歸納出可複製的點(2-4條)"],
 "selection":["選題進修：哪些題材/角度該加碼、哪些該捨(2-4條,具體)"],
 "thumbnail":["縮圖CTR進修(1-3條)"],
 "seo":["標題/標籤/描述進修(1-3條)"],
 "comment":["留言互動進修(1-2條)"],
 "promo":["跨平台宣傳進修(1-2條)"]
}}"""
    body = {"model": MODEL, "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"}, json=body, timeout=120)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))


def _write(date: str, d: dict):
    def sec(title, key):
        items = d.get(key) or []
        return [f"## {title}"] + ([f"- {x}" for x in items] if items else ["-（本週數據不足，保持多元測試）"]) + [""]
    md = [f"# 部門進修洞察（每週・資料驅動）｜{date}", "",
          f"> 本週總結：{d.get('summary','')}", "",
          "（製作/決策部門製作時會自動讀本檔當補充心法；其餘部門供參考。不覆蓋人工 playbook 核心。）", ""]
    md += sec("🎬 製作/腳本進修", "production")
    md += sec("🎯 選題進修", "selection")
    md += sec("🖼 縮圖CTR進修", "thumbnail")
    md += sec("🔎 SEO進修", "seo")
    md += sec("💬 留言互動進修", "comment")
    md += sec("📣 宣傳進修", "promo")
    INSIGHTS.write_text("\n".join(md), encoding="utf-8")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{date}_部門進修.md").write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    date = datetime.now(TW).strftime("%Y-%m-%d")
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    material = _gather()
    try:
        d = _ask_claude(material)
    except Exception as exc:  # noqa: BLE001
        log_ops("進修部門", f"⚠️ 訓練失敗：{str(exc)[:80]}")
        print(f"[FATAL] 訓練失敗：{exc}", file=sys.stderr)
        return 3
    _write(date, d)
    log_ops("進修部門", f"完成每週進修：{d.get('summary','')[:40]}")
    print(f"[進修部門] 已產出各部門進修洞察 → {INSIGHTS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
