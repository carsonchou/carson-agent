#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comment_dept.py — 【⑧ 社群留言部】抓新留言 + 草擬回覆（不自動發）。

讀頻道近期留言，用 Claude 以「理性顧問口吻、不亂承諾」草擬回覆，存成草稿給老闆過目後人工回。
誠實：自動發留言有 spam/政策風險，且違誠信鐵則的風險高 → **只草擬不自動發**。
另把觀眾問的好問題挑出來餵 ③靈感（可變內容）。
輸出：STUDIO/REPORTS/{date}_留言回覆草稿.md
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"
CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def draft_reply(comment):
    if not API_KEY:
        return "（無 ANTHROPIC_API_KEY，無法草擬）"
    import requests
    prompt = f"""你是量化阿森頻道的小編，回覆觀眾留言。誠信鐵則：理性顧問口吻、絕不保證收益、不喊單、不亂承諾、不報明牌。
觀眾留言：「{comment}」
請寫一則 1-3 句、友善、有幫助的繁中回覆草稿（若是問題就簡短解惑或引導看相關影片；若是抱怨就誠懇回應）。只輸出回覆內容。"""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        return f"（草擬失敗：{e}）"


def main() -> int:
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    comments = []
    try:
        r = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=CHANNEL_ID,
                                     maxResults=20, order="time").execute()
        for it in r.get("items", []):
            sn = it["snippet"]["topLevelComment"]["snippet"]
            comments.append({"author": sn.get("authorDisplayName", "")[:20],
                             "text": sn.get("textDisplay", "")[:300],
                             "likes": sn.get("likeCount", 0)})
    except Exception as e:
        print(f"[warn] 取留言失敗（可能尚無留言或權限）：{e}", file=sys.stderr)

    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑧ 留言回覆草稿｜{date}", "",
         "> 誠實：**只草擬不自動發**（避免 spam/違誠信鐵則風險），請過目後人工回覆。", ""]
    if not comments:
        L.append("（目前抓不到新留言——頻道剛起步留言少，或需要時再跑）")
    questions = []
    for c in comments[:15]:
        reply = draft_reply(c["text"])
        L += [f"## 💬 @{c['author']}（👍{c['likes']}）", f"> {c['text']}", f"**建議回覆：** {reply}", ""]
        if any(q in c["text"] for q in ("?", "？", "怎麼", "如何", "為什麼", "可以嗎")):
            questions.append(c["text"][:60])
    if questions:
        L += ["## 🎯 可變成內容的觀眾問題（餵 ③靈感）", *[f"- {q}" for q in questions]]
    (REPORTS / f"{date}_留言回覆草稿.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("社群留言", f"草擬 {len(comments)} 則回覆，挑出 {len(questions)} 個可用問題")
    print(f"[ok] 留言回覆草稿完成：{len(comments)} 則、{len(questions)} 個可變內容問題。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
