#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traffic_dept.py — ⑤流量部門：用「真實流量數據」訓練選題。

抓 YouTube Analytics（各影片觀看數＋看完率）→ 算出哪些題材/角度真的有流量 →
寫 STUDIO/traffic_signals.json（決策部門會讀，據此偏向高流量題材）＋ 流量洞察報告。

資料夠才給洞察；資料太少就誠實說「累積中」，不硬掰（誠信鐵則）。
需 token_analytics.json（沒有就優雅降級）。每天由 cron 在決策部門之前跑。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
LEDGER = STUDIO / "uploaded_ledger.json"
SIGNALS = STUDIO / "traffic_signals.json"
TW = timezone(timedelta(hours=8))

import yt_analytics as ya  # noqa: E402

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        pass

# 頻道利基題材關鍵字（用來從「高流量影片」反推哪些題材該多做）。
NICHE_KW = [
    "網格", "定投", "DCA", "派網", "Pionex", "過擬合", "回測", "Walk-Forward", "複利", "槓桿",
    "馬丁", "止損", "停利", "勝率", "回撤", "參數", "格數", "格距", "資金費率", "套利",
    "被動收入", "夏普", "蒙地卡羅", "區間", "幣價", "暴跌", "手續費", "風控", "微笑曲線",
]


def load_ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:
        return {}


def kw_of(text: str):
    return [k for k in NICHE_KW if k in text]


def write_report(date: str, signals: dict, note: str | None):
    REPORTS.mkdir(parents=True, exist_ok=True)
    c = signals.get("channel_28d", {})
    L = [f"# {date} 流量部門洞察（資料驅動選題）", ""]
    if note:
        L += [f"> {note}", ""]
    L += [f"近 28 天：觀看 {c.get('views', 0)}、平均看完率 {c.get('avg_pct', 0)}%、新增訂閱 {c.get('subs_gained', 0)}",
          f"曝光 {signals.get('impressions', 0)}、曝光點閱率 {signals.get('ctr', 0)}%", ""]
    win = signals.get("win_keywords", [])
    weak = signals.get("weak_keywords", [])
    L += ["## 🔥 有流量的題材（決策部門優先做、加重）",
          ("・" + "、".join(win)) if win else "（數據累積中，先保持多元測試）", ""]
    L += ["## 🧊 表現弱的題材（少做）",
          ("・" + "、".join(weak)) if weak else "（暫無明顯弱項）", ""]
    L += ["## 📈 Top 影片（觀看×看完率）"]
    for v in signals.get("top_videos", []):
        L.append(f"- {v['views']} 觀看・看完率 {v['avg_pct']}%　{v['slug'][:42]}")
    if not signals.get("top_videos"):
        L.append("（尚無足夠觀看數據，等影片累積流量後出現）")
    (REPORTS / f"{date}_流量洞察.md").write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    date = datetime.now(TW).strftime("%Y-%m-%d")
    led = load_ledger()
    vid2slug = {v: k for k, v in led.items()}

    if not ya.available():
        # 標 stale 讓下游知道這是舊資料（非 ok），並推播警報
        signals = {"generated": date, "status": "stale",
                   "win_keywords": [], "weak_keywords": [], "top_videos": []}
        SIGNALS.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")
        write_report(date, signals, "尚未連 YouTube Analytics（缺 token_analytics.json）；連上後即可資料驅動選題。")
        log_ops("流量部門", "無 analytics token，流量訊號暫空（誠實降級）")
        try:
            from notify import push
            push("流量數據斷線",
                 "traffic_signals 無法更新，token_analytics 可能過期，請跑 auth_analytics.py",
                 tag="rotating_light")
        except Exception:
            pass
        print("[流量部門] 無 analytics token，已寫空訊號（stale）。")
        return 0

    summary = ya.channel_summary(28) or {}
    perf = ya.top_by_ctr(28, 50) or []
    ic = ya.impressions_ctr(28) or {}

    rows = []
    for p in perf:
        slug = vid2slug.get(p["video_id"], "")
        if not slug:
            continue
        avg = float(p.get("avg_pct", 0) or 0)
        score = float(p.get("views", 0)) * (1 + avg / 100.0)  # 觀看為主、看完率加權
        rows.append({"slug": slug, "vid": p["video_id"], "views": p.get("views", 0),
                     "avg_pct": round(avg, 1), "score": round(score, 1)})
    rows.sort(key=lambda x: -x["score"])

    # 從贏家/輸家影片反推題材關鍵字
    seg = max(3, len(rows) // 3)
    top, bottom = rows[:seg], (rows[-seg:] if len(rows) > 6 else [])
    win_c = Counter(k for r in top for k in kw_of(r["slug"]))
    weak_c = Counter(k for r in bottom for k in kw_of(r["slug"]))
    win_keywords = [k for k, _ in win_c.most_common(8)]
    weak_keywords = [k for k, c in weak_c.most_common(6) if win_c.get(k, 0) == 0]

    enough = sum(r["views"] for r in rows) >= 30  # 觀看太少不硬給洞察
    signals = {
        "generated": date,
        "status": "ok" if enough else "data_accumulating",
        "channel_28d": {"views": summary.get("views", 0),
                        "avg_pct": round(float(summary.get("avg_pct", 0) or 0), 1),
                        "subs_gained": summary.get("subs_gained", 0)},
        "impressions": ic.get("impressions", 0), "ctr": round(float(ic.get("ctr", 0) or 0), 2),
        "win_keywords": win_keywords if enough else [],
        "weak_keywords": weak_keywords if enough else [],
        "top_videos": [{"slug": r["slug"], "views": r["views"], "avg_pct": r["avg_pct"]} for r in rows[:8]],
    }
    SIGNALS.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(date, signals, None if enough else "觀看數據仍在累積，先衝 Shorts 量、保持題材多元，數據夠了自動給選題建議。")
    log_ops("流量部門", f"分析{len(rows)}支 贏家題材{win_keywords or '累積中'} 弱{weak_keywords or '無'}")
    # 訊號注入題庫：把有流量的贏家題材推進 topic_bank（優先製作）
    if win_keywords and enough:
        try:
            from topic_bank import add_topics
            tb_items = [{"title": k, "angle": "", "category": "市場觀念",
                         "format": "short", "priority": "traffic"} for k in win_keywords]
            add_topics(tb_items, source="traffic", front=True)
        except Exception:
            pass
    print(f"[流量部門] 分析 {len(rows)} 支｜贏家題材 {win_keywords or '(累積中)'}｜弱題材 {weak_keywords or '(無)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
