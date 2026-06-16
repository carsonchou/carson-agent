#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_score.py — 【倉庫評分官】給每支片 0–100 分＋依門檻判 pass/退件，供決策中心檢視。

評分＝規則式（不耗 AI、可無人值守）：以 audit_video 的檢查項目逐條扣分。
狀態：score < min_score → reject（建議退件重做）；否則 pass。min_score 存 boss_directives.json。
輸出 STUDIO/quality_scores.json 給 control_center『🎬 倉庫評分』分頁讀。

用法：
  python scripts/quality_score.py                 # 掃全倉庫、評分、寫 quality_scores.json
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
import os
import re

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
AI_MODEL = "claude-haiku-4-5-20251001"  # 便宜，評分夠用

# audit reason 關鍵字 → 硬扣分（技術/誠信硬傷，AI 分數之上再扣）
DEDUCT = [
    ("mp4 不存在", 100), ("無視訊軌", 45), ("無音軌", 45), ("片長過短", 35),
    ("檔案過小", 30), (".md 腳本不存在", 25), ("禁語", 50), ("Shorts 超過", 18),
    ("缺影片標題", 15), ("缺風險聲明", 12),
]


def _read_script(slug):
    """讀該片的標題＋旁白逐字稿，給 AI 評分。"""
    voice = OUT / f"{slug}.voice.txt"
    txt = voice.read_text(encoding="utf-8") if voice.exists() else ""
    return title_of(slug), txt[:1400]


def ai_score(slug):
    """Claude 真讀腳本，依四面向各 0–25 評分（鉤子/標題CTR/內容/誠信），回 dict 或 None。"""
    if not API_KEY:
        return None
    import requests
    title, voice = _read_script(slug)
    if len(voice) < 40:
        return None
    prompt = (
        "你是量化阿森（量化/網格/派網/回測/風控，繁中 faceless 短影音）的品管評審。"
        "依下列四面向為這支 Shorts 腳本評分，每項 0–25，嚴格、有鑑別度（別都給高分）：\n"
        "①hook 前2秒鉤子抓不抓得住 ②title 標題點擊慾/公式 ③content 內容紮實正確清晰 "
        "④honesty 誠信合規（不誇大不喊單、有風險意識、不空泛）。\n"
        f"標題：{title}\n旁白逐字稿：{voice}\n\n"
        '只輸出 JSON（不要其他字）：{"hook":N,"title":N,"content":N,"honesty":N,"note":"一句最該改的具體建議"}'
    )
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": AI_MODEL, "max_tokens": 400,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        m = re.search(r"\{.*\}", r.json()["content"][0]["text"], re.S)
        if not m:
            return None
        d = json.loads(m.group(0))
        for k in ("hook", "title", "content", "honesty"):
            d[k] = max(0, min(25, int(d.get(k, 0))))
        d["total"] = d["hook"] + d["title"] + d["content"] + d["honesty"]
        return d
    except Exception:
        return None


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
    log_ops("倉庫評分", f"退件門檻設為 {n} 分")
    print(f"[ok] 退件門檻 → {n} 分，重新評定 pass/退件…")
    scan(rescore_ai=False)  # 用快取分數依新門檻重判 pass/退件（快、不重跑 AI）


def title_of(slug):
    md = OUT / f"{slug}.md"
    if md.exists():
        try:
            first = md.read_text(encoding="utf-8").splitlines()[0]
            return first.replace("# 🎬", "").replace("#", "").strip()
        except Exception:
            pass
    return slug


def score_one(slug, ai):
    """合成分數＝AI 內容分(0-100) 再扣 audit 硬傷；無 AI 可評時退回合規分(100-硬扣)。"""
    ok, reasons = audit_video.audit(slug)
    ded = sum(w for kw, w in DEDUCT if any(kw in r for r in reasons))
    if ai:
        score = max(0, min(100, ai["total"] - ded))
    else:
        score = max(0, 100 - ded)
    return score, reasons


def all_slugs():
    slugs = set()
    for f in OUT.glob("S_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("L_*.mp4"):
        slugs.add(f.stem)
    return sorted(slugs)


def channel_published(yt):
    """從 YouTube 頻道 uploads 播放清單抓『真實已發布』影片(videoId,title)——含 ledger 沒記到的(如手動發的長片)。"""
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        plid = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        out, tok = [], None
        while True:
            r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=plid,
                                        maxResults=50, pageToken=tok).execute()
            for it in r.get("items", []):
                out.append((it["contentDetails"]["videoId"], it["snippet"].get("title", "")))
            tok = r.get("nextPageToken")
            if not tok:
                break
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 抓頻道影片失敗（改用 ledger）：{str(e)[:80]}", file=sys.stderr)
        return []


def scan(rescore_ai=False):
    ledger = _load(LEDGER, {})
    rev = {v: k for k, v in ledger.items()}  # videoId → slug
    min_score = get_min()
    p0 = _load(SCORES, {})
    prev = {}
    for key in ("pending", "published", "items"):
        for i in (p0.get(key) or []):
            if i.get("slug"):
                prev[i["slug"]] = i
    # 1) 評分本機所有 mp4（含未發布 queue ＋ 已發布但本機還留檔的）
    scored = {}
    new_ai = 0
    for slug in all_slugs():
        was = prev.get(slug, {})
        if rescore_ai or "ai" not in was:
            ai = ai_score(slug)
            if ai:
                new_ai += 1
        else:
            ai = was.get("ai")
        sc, reasons = score_one(slug, ai)
        scored[slug] = {"slug": slug, "title": title_of(slug), "score": sc,
                        "reasons": reasons, "ai": ai, "ai_note": (ai or {}).get("note", "")}
    # 2) 未發布 queue ＝ 有 mp4 但不在 ledger（退件對象）
    pending = []
    for slug, it in scored.items():
        if slug in ledger:
            continue
        was = prev.get(slug, {})
        st = "rejected_manual" if was.get("status") == "rejected_manual" else \
             ("reject" if it["score"] < min_score else "pass")
        pending.append(dict(it, status=st, published=False, videoId=""))
    pending.sort(key=lambda x: x["score"])
    # 3) 已發布 ＝ 真實頻道 uploads（完整含長片）；抓不到才退回 ledger
    yt = None
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception:
        pass
    chan = channel_published(yt) if yt else []
    published = []
    if chan:
        for vid, title in chan:
            base = scored.get(rev.get(vid, ""))
            published.append({"slug": rev.get(vid) or vid, "title": title, "videoId": vid,
                              "score": base["score"] if base else None,
                              "ai": base["ai"] if base else None,
                              "ai_note": base.get("ai_note", "") if base else "",
                              "reasons": base["reasons"] if base else [],
                              "status": "published", "published": True})
    else:
        for slug, vid in ledger.items():
            base = scored.get(slug)
            published.append({"slug": slug, "title": (base or {}).get("title", slug), "videoId": vid,
                              "score": (base or {}).get("score"), "ai": (base or {}).get("ai"),
                              "ai_note": (base or {}).get("ai_note", ""), "reasons": (base or {}).get("reasons", []),
                              "status": "published", "published": True})
    # 4) 已發布附上真實成效（觀看／留存／CTR，YouTube Analytics；無 token 則略過）
    try:
        import yt_analytics as ya
        stats = ya.video_stats(days=180) or {}
    except Exception:
        stats = {}
    for p in published:
        st = stats.get(p["videoId"])
        if st:
            p["views"] = st.get("views")
            p["retention"] = round(st.get("retention"), 1) if st.get("retention") is not None else None
            p["ctr"] = round(st.get("ctr"), 1) if st.get("ctr") is not None else None
    if stats:  # 有成效資料就按觀看高→低排（一眼看哪支最紅）；無資料維持頻道時間序
        published.sort(key=lambda x: (x.get("views") is None, -(x.get("views") or 0)))
    payload = {"updated": tw_now(), "min_score": min_score, "has_analytics": bool(stats),
               "summary": {"pending": len(pending), "published": len(published),
                           "pass": sum(1 for i in pending if i["status"] == "pass"),
                           "reject": sum(1 for i in pending if i["status"].startswith("reject"))},
               "pending": pending, "published": published}
    STUDIO.mkdir(parents=True, exist_ok=True)
    SCORES.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    s = payload["summary"]
    log_ops("倉庫評分", f"未發布 {s['pending']}(pass{s['pass']}/退{s['reject']})、已發布 {s['published']}（門檻{min_score}、新評AI{new_ai}）")
    print(f"[ok] 倉庫評分：未發布 {s['pending']} 支(pass {s['pass']}／退件 {s['reject']})、已發布 {s['published']} 支，"
          f"門檻 {min_score}，新評 AI {new_ai} → quality_scores.json")
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
    log_ops("倉庫評分", f"退件重做：{title[:24]}（隔離 {moved} 檔、釋放題目待補產）")
    print(f"[ok] 已退件：{slug}（隔離 {moved} 檔，釋放題目，下輪自動補產新片）")
    if manual:
        scan(rescore_ai=False)  # 重掃刷新清單（該片已移走→自動從未發布消失）
    return 0


def auto_reject():
    """排程用：把『未發布且低於門檻』的自動退件重做。"""
    data = scan()
    n = 0
    for i in data["pending"]:
        if i["status"] == "reject":
            reject(i["slug"], manual=False); n += 1
    if n:
        scan(rescore_ai=False)
    log_ops("倉庫評分", f"自動退件 {n} 支未發布低分片")
    print(f"[ok] 自動退件 {n} 支（未發布、低於門檻 {data['min_score']}）。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-min", type=int, default=None)
    ap.add_argument("--reject", default=None)
    ap.add_argument("--auto-reject", action="store_true")
    ap.add_argument("--rescore-ai", action="store_true", help="強制全部重跑 AI 內容評分（平常用快取）")
    args = ap.parse_args()
    if args.set_min is not None:
        set_min(args.set_min); return 0
    if args.reject:
        return reject(args.reject)
    if args.auto_reject:
        return auto_reject()
    scan(rescore_ai=args.rescore_ai)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
