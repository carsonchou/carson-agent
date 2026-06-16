#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_score.py — 【片庫評分官】給每支片 0–100 分＋依門檻判 pass/退件，供決策中心檢視。

評分＝規則式（不耗 AI、可無人值守）：以 audit_video 的檢查項目逐條扣分。
狀態：score < min_score → reject（建議退件重做）；否則 pass。min_score 存 boss_directives.json。
輸出 STUDIO/quality_scores.json 給 control_center『🎬 片庫評分』分頁讀。

用法：
  python scripts/quality_score.py                 # 掃全片庫、評分、寫 quality_scores.json
  python scripts/quality_score.py --set-min 75    # 設退件門檻為 75 分
  python scripts/quality_score.py --reject S_xxx  # 退件重做：隔離該片+釋放題目，下輪自動補產
  python scripts/quality_score.py --auto-reject    # 把低於門檻且『未發布』的自動退件（給排程用）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
REJECT_DIR = OUT / "_rejected"
SCORES = STUDIO / "quality_scores.json"
LEDGER = STUDIO / "uploaded_ledger.json"
BANK = STUDIO / "topic_bank.json"
DIRECTIVES = STUDIO / "boss_directives.json"
TW = timezone(timedelta(hours=8))
DEFAULT_MIN = 70

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

import audit_video

# audit reason 關鍵字 → 扣分權重
DEDUCT = [
    ("mp4 不存在", 100), ("無視訊軌", 45), ("無音軌", 45), ("片長過短", 35),
    ("檔案過小", 30), (".md 腳本不存在", 25), ("禁語", 40), ("Shorts 超過", 18),
    ("缺影片標題", 15), ("缺風險聲明", 12),
]


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def get_min():
    d = _load(DIRECTIVES, {})
    try:
        return int(d.get("min_score", DEFAULT_MIN))
    except Exception:
        return DEFAULT_MIN


def set_min(n):
    d = _load(DIRECTIVES, {})
    d["min_score"] = int(n)
    DIRECTIVES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    log_ops("片庫評分", f"退件門檻設為 {n} 分")
    print(f"[ok] 退件門檻 → {n} 分")


def title_of(slug):
    md = OUT / f"{slug}.md"
    if md.exists():
        try:
            first = md.read_text(encoding="utf-8").splitlines()[0]
            return first.replace("# 🎬", "").replace("#", "").strip()
        except Exception:
            pass
    return slug


def score_one(slug):
    ok, reasons = audit_video.audit(slug)
    total = 0
    for kw, w in DEDUCT:
        if any(kw in r for r in reasons):
            total += w
    return max(0, 100 - total), reasons


def all_slugs():
    slugs = set()
    for f in OUT.glob("S_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("L_*.mp4"):
        slugs.add(f.stem)
    return sorted(slugs)


def scan():
    ledger = _load(LEDGER, {})
    min_score = get_min()
    prev = {i["slug"]: i for i in _load(SCORES, {}).get("items", [])}
    items = []
    for slug in all_slugs():
        sc, reasons = score_one(slug)
        published = slug in ledger
        # 已被人工退件的保留 reject 狀態；否則依門檻
        was = prev.get(slug, {})
        if was.get("status") == "rejected_manual":
            status = "rejected_manual"
        else:
            status = "reject" if sc < min_score else "pass"
        items.append({
            "slug": slug, "title": title_of(slug), "score": sc,
            "status": status, "reasons": reasons,
            "published": published, "videoId": ledger.get(slug, ""),
        })
    items.sort(key=lambda x: (x["published"], x["score"]))  # 未發布+低分排前面（最需要處理）
    payload = {"updated": tw_now(), "min_score": min_score,
               "summary": {"total": len(items),
                           "pass": sum(1 for i in items if i["status"] == "pass"),
                           "reject": sum(1 for i in items if i["status"].startswith("reject")),
                           "published": sum(1 for i in items if i["published"])},
               "items": items}
    STUDIO.mkdir(parents=True, exist_ok=True)
    SCORES.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    s = payload["summary"]
    log_ops("片庫評分", f"評分 {s['total']} 支：pass {s['pass']}／退件建議 {s['reject']}（門檻{min_score}）")
    print(f"[ok] 片庫評分完成：{s['total']} 支，pass {s['pass']}／退件 {s['reject']}，門檻 {min_score} → quality_scores.json")
    return payload


def _free_topic(title):
    """把該片對應的題庫題目標回未用，讓 produce_batch 重做（找不到就算了）。"""
    bank = _load(BANK, [])
    if not isinstance(bank, list):
        return
    import re
    norm = lambda t: re.sub(r"[\s，。！？、：；…·\-—()（）]+", "", (t or "")).lower()
    nt = norm(title)
    changed = False
    for t in bank:
        if t.get("used") and (norm(t.get("title", "")) == nt or norm(t.get("title", ""))[:12] == nt[:12]):
            t["used"] = False
            changed = True
    if changed:
        BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")


def reject(slug, manual=True):
    """退件重做：把該片所有檔案隔離到 output/_rejected/，釋放題目，下輪 produce_batch 自動補產新的。"""
    if slug in _load(LEDGER, {}):
        print(f"[warn] {slug} 已發布，退件只隔離本機檔案、不會動線上影片（要下架請用 set_public.py）。")
    REJECT_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    title = title_of(slug)
    for f in OUT.glob(f"{slug}.*"):
        try:
            shutil.move(str(f), str(REJECT_DIR / f.name))
            moved += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 移動 {f.name} 失敗：{e}")
    _free_topic(title)
    # 在 scores 記一筆 rejected_manual
    data = _load(SCORES, {"items": []})
    for i in data.get("items", []):
        if i["slug"] == slug:
            i["status"] = "rejected_manual"
    SCORES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log_ops("片庫評分", f"退件重做：{title[:24]}（隔離 {moved} 檔、釋放題目待補產）")
    print(f"[ok] 已退件：{slug}（隔離 {moved} 檔，釋放題目，下輪自動補產新片）")
    return 0


def auto_reject():
    """排程用：把『未發布且低於門檻』的自動退件重做。"""
    data = scan()
    n = 0
    for i in data["items"]:
        if (not i["published"]) and i["status"] == "reject":
            reject(i["slug"], manual=False); n += 1
    log_ops("片庫評分", f"自動退件 {n} 支未發布低分片")
    print(f"[ok] 自動退件 {n} 支（未發布、低於門檻 {data['min_score']}）。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-min", type=int, default=None)
    ap.add_argument("--reject", default=None)
    ap.add_argument("--auto-reject", action="store_true")
    args = ap.parse_args()
    if args.set_min is not None:
        set_min(args.set_min); return 0
    if args.reject:
        return reject(args.reject)
    if args.auto_reject:
        return auto_reject()
    scan()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
