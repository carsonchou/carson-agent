#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retention_segments.py — 留存曲線 × 旁白句時間戳對映:「觀眾是在哪一種段落離開的」。

## 為什麼(2026-08-12)
開場碎句修復已驗證有效(訂閱轉化 2 倍),但非碎句片平均完播仍只有 24.6%——中段還在漏人。
我們有兩份可以對起來的資料:
  ①Analytics elapsedVideoTimeRatio×audienceWatchRatio(逐段留存,x 軸=片長比例)
  ②{slug}.wordtimes.json(edge-tts 句級時間戳,已發布長片 108/157 支有)
對映後能回答:「財報段掉得比回測段快嗎」「訂閱鉤前後掉多少」「最陡的懸崖是哪句話」。
這是回灌腳本結構的依據——改產線之前,先讓數據說話。

## 方法備註
- 留存天生單調下滑,直接比各段落型態的絕對斜率會被「段落出現位置」混淆
  (愈後面的段落斜率天生愈緩)。故每支片先算「該片平均斜率」,段落斜率除以它=**相對流失速度**
  (>1 = 這種段落比同片平均掉得快)。
- 只取 5%~95% 區間(開頭懸崖是 hook 問題已另案處理;片尾自然雪崩不具資訊量)。
- 觀看太少的片 Analytics 不回資料列,自動跳過。

唯讀:不改任何產線檔案。產出 STUDIO/REPORTS/retention_segments_<date>.md + .json。
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

import yt_analytics as ya  # noqa: E402

# 段落型態分類(句文字關鍵字;順序=優先序,先中先贏)
SEG_RULES = [
    ("sub_cta",      ("訂閱",)),
    ("risk",         ("不構成", "投資建議", "風險聲明", "盈虧", "不代表未來", "自行判斷")),
    ("fundamentals", ("營收", "毛利", "EPS", "每股盈餘", "財報", "配息", "殖利率", "本益比", "股利")),
    ("backtest",     ("回測", "年化", "回撤", "套牢", "崩盤", "含息", "報酬", "大跌", "腰斬")),
    ("story",        ("就像", "想像", "好比", "比喻", "電扶梯", "雲霄飛車")),
]


def classify(text: str) -> str:
    for name, kws in SEG_RULES:
        if any(k in text for k in kws):
            return name
    return "explain"


def analyze_video(svc, vid: str, slug: str, end: str):
    wt_path = OUT / f"{slug}.wordtimes.json"
    try:
        wt = json.loads(wt_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(wt, list) or len(wt) < 8:
        return None
    total = max(w["t"] + w["d"] for w in wt)
    if total < 120:  # 非長片
        return None
    try:
        r = svc.reports().query(
            ids="channel==MINE", startDate="2026-06-01", endDate=end,
            dimensions="elapsedVideoTimeRatio", metrics="audienceWatchRatio",
            filters=f"video=={vid}", sort="elapsedVideoTimeRatio",
        ).execute()
    except Exception:  # noqa: BLE001
        return None
    rows = r.get("rows", [])
    if len(rows) < 20:
        return None

    def sent_at(t: float):
        for w in wt:
            if w["t"] <= t < w["t"] + w["d"]:
                return w
        return None

    # 每個 bucket 的斜率(往下一個 bucket 掉多少),歸到該時點句子的段落型態
    slopes = []   # (type, slope, t, text)
    for i in range(len(rows) - 1):
        x, wr = rows[i]
        x2, wr2 = rows[i + 1]
        if x < 0.05 or x2 > 0.95:
            continue
        t = x * total
        w = sent_at(t)
        if not w:
            continue
        dt = (x2 - x) * total
        if dt <= 0:
            continue
        slope = (wr - wr2) / dt * 60.0   # 每分鐘流失(絕對)
        slopes.append((classify(w["text"]), slope, t, w["text"]))
    if len(slopes) < 10:
        return None
    avg = sum(s for _, s, _, _ in slopes) / len(slopes)
    if avg <= 0:
        avg = 1e-6
    # 全片最陡懸崖(單 bucket)
    cliff = max(slopes, key=lambda s: s[1])
    return {"slug": slug, "vid": vid, "avg_slope": avg,
            "slopes": [(ty, sl / avg) for ty, sl, _, _ in slopes],
            "cliff": {"t": round(cliff[2]), "rel": round(cliff[1] / avg, 2),
                      "text": cliff[3][:60]}}


def main() -> int:
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    svc = ya._service()
    if svc is None:
        print("[FATAL] analytics service 不可用")
        return 1
    end = date.today().isoformat()
    results = []
    todo = [(s, v) for s, v in led.items() if s.startswith("L_") and (OUT / f"{s}.wordtimes.json").exists()]
    print(f"候選 {len(todo)} 支(已發布長片且有 wordtimes)")
    for i, (slug, vid) in enumerate(todo):
        r = analyze_video(svc, vid, slug, end)
        if r:
            results.append(r)
        if i % 20 == 19:
            print(f"  …{i + 1}/{len(todo)},有效 {len(results)}")
        time.sleep(0.2)
    print(f"有效樣本 {len(results)} 支(其餘觀看不足或資料缺)")
    if not results:
        return 1

    # 聚合:各段落型態的相對流失速度
    agg = {}
    for r in results:
        for ty, rel in r["slopes"]:
            agg.setdefault(ty, []).append(rel)
    lines = ["# 留存 × 段落型態分析", f"樣本:{len(results)} 支已發布長片(句級時間戳對映)", "",
             "相對流失速度(1.0=同片平均;>1 掉得比平均快):", "",
             "| 段落型態 | 相對流失 | 樣本bucket數 |", "|---|---|---|"]
    for ty, vals in sorted(agg.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        lines.append(f"| {ty} | {sum(vals) / len(vals):.2f} | {len(vals)} |")
    lines += ["", "## 各片最陡懸崖(相對流失倍數,含當時那句話)", ""]
    for r in sorted(results, key=lambda r: -r["cliff"]["rel"])[:15]:
        c = r["cliff"]
        lines.append(f"- **{c['rel']}x** @{c['t']}s 「{c['text']}」— {r['slug'][:36]}")

    md = "\n".join(lines)
    day = date.today().isoformat()
    (STUDIO / "REPORTS" / f"{day}_留存段落分析.md").write_text(md, encoding="utf-8")
    (STUDIO / "retention_segments.json").write_text(
        json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
